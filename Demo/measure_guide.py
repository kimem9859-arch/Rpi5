#!/usr/bin/env python3
"""측정 진행 도우미 — 노트북 SSH 창에서 대본을 한 줄씩 보이고, 안경으로 짧은 안내 소리를 내고, NG 를 잡는다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-11-측정진행도우미-안내소리-design.md §3.1 · §4.4
실행: bash Demo/run_guide.sh — 가장 최근 측정 세션을 따라간다(끝나면 다음 세션을 기다린다)
      python3 measure_guide.py --replay <세션 폴더> — 기록을 다시 돌려 안내·NG 결정을 본다(소리·파일 쓰기 없음)
키: N = NG(엔터 없이 · 이어서 1 사람 · 2 장비 · 3초 안에 안 고르면 사람) · U = 마지막 수동 NG 취소 · Q = 끝
🔴 N 은 사람·장비 탓일 때만 — 모델·판정 이상은 결과다(누르면 그 결과가 사라진다 · 설계 D4).
🔴 결과(사전 경고 여부 등)는 보이지 않는다 — 측정하는 사람이 결과를 보고 손 동작을 바꾸지 않게.
🔑 시연 프로그램을 건드리지 않는다 — 측정 기록(events.csv)을 읽기만 하고, 쓰는 것은 guide.csv · /dev/shm/sop_cue 뿐.
"""
import argparse
import csv
import io
import json
import os
import select
import signal
import sys
import time

_DEMO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import config                 # noqa: E402
import measure_check          # noqa: E402
import measure_log            # noqa: E402
import measure_report as MR   # noqa: E402 — 레시피 버튼 · EMO(세기와 같은 기준)
import measure_script as MS   # noqa: E402

MEASURE_DIR = os.path.join(_DEMO, "measure")
SKIP_DIRS = {"폐기", "시나리오"}
GAP_MS = 1000.0          # 직전 행동·안내에서 이만큼 지나야 다음 안내(설계 D8)
HOVER_WAIT_MS = 4000.0   # 머묾 안내 뒤 경고 해제가 없으면 이만큼 뒤 다음으로
REASON_MS = 3000.0       # N 뒤 이유(1 사람 · 2 장비)를 기다리는 시간
ACK_WAIT_MS = 3000.0     # 안내 요청 뒤 이만큼 응답이 없으면 「응답 없음」
TICK_SEC = 0.1
SWITCH_CHECK_MS = 1000.0  # 더 새 측정 세션이 생겼나 보는 간격(최종 리뷰 Important 2)
LOCK_FILE = "/tmp/sop_measure_guide.lock"   # 한 대만(최종 리뷰 Important 3)
RUN_STATES = ("PROCESS_RUN", "MONITOR")
RED, YEL, GRN, DIM, BOLD, RST = "\033[41;97m", "\033[43;30m", "\033[32m", "\033[2m", "\033[1m", "\033[0m"


def tool_waits(path=None):
    """레시피의 공구 대기 → {버튼: ms} — 「초기화」 안내 때를 정한다(설계 D17 · 값을 여기 따로 적지 않는다)."""
    with open(path or MR.RECIPE, encoding="utf-8") as f:
        steps = json.load(f).get("steps") or ()
    return {s["button"]: float(s["sub"]["sec"]) * 1000 for s in steps
            if (s.get("sub") or {}).get("type") == "wait_tool"}


def cue_key(tok):
    """낱말 → 고정 wav 키(make_answers.CUES)."""
    if tok.kind == "reset":
        return "cue_reset"
    if tok.kind == "press":
        return f"cue_{tok.name}"
    if tok.kind == "hover":
        return f"cue_hover_{tok.name}"
    return f"cue_tool_{MS.TOOLS[tok.name]}"


def live_state(run, waits=None):
    """열린 판 → 지금 판정기 상태 · 기대 버튼 · 마지막 행동 시각 · 경고 해제 시각들(설계 D8)
    · 공구 대기가 끝나는 시각(waits = tool_waits() · 설계 D17 — 틀린 공구를 쥐고 있으면 대기가 끝나도 서브가 안 끝난다)."""
    st = {"state": None, "expected": None, "last": run["t0"], "released": [], "tool_end": None}
    for t, k, d in run["ev"]:
        if k == "sub" and d.get("what") == "start" and d.get("button") in (waits or {}):
            st["tool_end"] = t + waits[d["button"]]
        if k == "state":
            st["state"], st["expected"] = d.get("new"), d.get("expected")
        if k in ("press", "release", "step_done", "sub"):
            st["last"] = t
        if k == "release" and d.get("what") == "warning" and d.get("ok"):
            st["released"].append(t)
    return st


def next_cue(toks, consumed, cued, st, now_ms):
    """지금 낼 안내 → (낱말 자리, 소리 키) 또는 None(설계 D8).
    toks = 그 대본 판의 낱말 전부 · consumed = 쓴 누름 낱말 수 · cued = {낱말 자리: 요청 시각 ms}."""
    presses = [n for n, x in enumerate(toks) if x.kind == "press"]
    start = presses[consumed - 1] + 1 if consumed else 0
    for n in range(start, len(toks)):
        x = toks[n]
        if n in cued:
            if x.kind == "press":
                return None                              # 낸 누름이 아직 안 눌렸다 — 기다린다
            if x.kind == "hover" and not (any(t >= cued[n] for t in st["released"])
                                          or now_ms - cued[n] >= HOVER_WAIT_MS):
                return None                              # 머묾 중 — 경고 해제 또는 4초까지
            continue
        if st["state"] not in RUN_STATES:
            return None
        if x.kind in ("press", "hover") and x.expected is not None and st["expected"] != x.expected:
            return None
        if now_ms - max([st["last"]] + list(cued.values())) < GAP_MS:
            return None
        if x.kind == "reset" and (st.get("tool_end") is None or now_ms < st["tool_end"] + GAP_MS):
            return None                                  # 공구 대기가 끝나고 1초 뒤(설계 D17)
        return n, cue_key(x)
    return None


class Guide:
    """한 세션을 따라간다 — 판 맞춤 · 안내 결정 · NG 기록(소리·파일 쓰기는 sink 로 · 시험은 sink 를 바꾼다)."""

    def __init__(self, rows, emo, cue_sink=None, log_sink=None, waits=None):
        self.rows, self.emo = rows or [], emo
        self.waits = tool_waits() if waits is None else waits
        self.auto = MS.has_tokens(self.rows)   # 누름 칸 없는 대본 = 안내·자동 NG 없이 N 만(최종 리뷰 Important 5a)
        self.marks = []          # [(t, "ng"|"undo", 이유)]
        self.cued = {}           # {(실제 판 번호, 낱말 자리): 요청 시각}
        self.ng_cued = set()     # 「다시」를 낸 판
        self.cue_sink = cue_sink or (lambda key, t: None)
        self.log_sink = log_sink or (lambda t, kind, data: None)
        self.view = {"res": None, "run": None, "cur": None}
        self._n = -1
        self._res = None
        self._runs = []

    def restore(self, guide_rows):
        """guide.csv 를 다시 읽어 이어간다 — 낸 안내 · N/U(Review Focus 1)."""
        for t, k, d in guide_rows:
            if k == "cue" and d.get("tok") is not None:
                self.cued[(d.get("run"), d["tok"])] = t
            elif k == "cue" and d.get("key") == "cue_ng":
                self.ng_cued.add(d.get("run"))
            elif k in ("ng", "undo"):
                self.marks.append((t, k, d.get("why")))

    def mark(self, now_ms, kind, why=None):
        self.marks.append((now_ms, kind, why))
        self._n = -1                                     # 다시 맞춘다
        self.log_sink(now_ms, kind, {"why": why} if why else {})

    def step(self, events, now_ms):
        """→ ("cue", 키) · ("ng", "cue_ng") · None."""
        if not self.rows:
            self.view = {"res": None, "run": None, "cur": None}
            return None
        if len(events) != self._n:                       # 새 사건이 있을 때만 다시 맞춘다(CPU)
            self._res = MS.match(events, self.rows, self.marks, ahead=0, emo=self.emo, auto=self.auto)
            self._runs = MS.runs_of(events)
            self._n = len(events)
        res, runs = self._res, self._runs
        cur = runs[-1] if runs and runs[-1]["end"] == "open" else None
        r = res["runs"][-1] if cur is not None else None
        self.view = {"res": res, "run": r, "cur": cur}
        if r is None or r["script"] is None or not self.auto:
            return None
        if r["status"] == "ng" or r["live_ng"]:
            if r["i"] not in self.ng_cued and r["live_ng"]:
                self.ng_cued.add(r["i"])
                self.cue_sink("cue_ng", now_ms)
                self.log_sink(now_ms, "cue", {"run": r["i"], "script": r["script"], "key": "cue_ng"})
                return ("ng", "cue_ng")
            return None
        toks = res["order"][r["script"]]
        mine = {n: t for (i, n), t in self.cued.items() if i == r["i"]}
        c = next_cue(toks, r["consumed"], mine, live_state(cur, self.waits), now_ms)
        if c is None:
            return None
        self.cued[(r["i"], c[0])] = now_ms
        self.cue_sink(c[1], now_ms)
        self.log_sink(now_ms, "cue", {"run": r["i"], "script": r["script"], "tok": c[0], "key": c[1]})
        return ("cue", c[1])


class Tail:
    """CSV 사건 파일 꼬리 읽기 — 새로 쓰인 완전한 줄만(기록기는 0.5초마다 내보낸다 · 처음부터 다시 읽지 않아 CPU 를 아낀다)."""

    def __init__(self, path):
        self.path, self.pos, self.rows, self._head = path, 0, [], False

    def poll(self):
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                chunk = f.read()
        except OSError:
            return False
        end = chunk.rfind(b"\n")
        if end < 0:
            return False
        self.pos += end + 1
        new = False
        for line in csv.reader(io.StringIO(chunk[:end + 1].decode("utf-8"))):
            if not self._head:
                self._head = True
                continue
            if len(line) < 3:
                continue
            try:
                self.rows.append((float(line[0]), line[1], json.loads(line[2] or "{}")))
                new = True
            except ValueError:
                continue
        return new


def write_req(key, t, d=None):
    """안내 요청 — 음성비서 CueWatcher 가 읽는다(번호 = 요청 시각 ms · 다시 켜도 겹치지 않는다)."""
    d = d or config.CUE_SHM_DIR
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "req.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"seq": int(t), "key": key, "t_req_ms": t}, f)
    os.replace(tmp, os.path.join(d, "req.json"))


def ack_status(last_req, d=None, now_ms=None):
    """마지막 요청 (번호, 시각) 에 음성비서가 답했나 — 화면 한 줄(Review Focus 2)."""
    if last_req is None:
        return "🔈 안내 전"
    try:
        with open(os.path.join(d or config.CUE_SHM_DIR, "ack.json"), encoding="utf-8") as f:
            ack = json.load(f)
    except (OSError, ValueError):
        ack = {}
    now_ms = measure_log.now_ms() if now_ms is None else now_ms
    if ack.get("seq") == last_req[0]:
        return "🔊 응답" if ack.get("ok") else "🔇 재생 확인 안 됨(안경 스피커 확인)"
    if now_ms - last_req[1] > ACK_WAIT_MS:
        return "🔇 응답 없음 — 음성비서 확인(화면 안내로 계속)"
    return "🔈 보내는 중"


class GuideLog:
    """세션 폴더 guide.csv — t_ms,kind,data(측정 기록과 같은 꼴 · 세기가 measure_check.load_events 로 읽는다)."""

    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(["t_ms", "kind", "data"])

    def write(self, t, kind, data):
        with open(self.path, "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([round(t, 3), kind, json.dumps(data, ensure_ascii=False)])


def session_rows(d):
    """세션 폴더 → (session.json, 대본 줄 또는 None)."""
    with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
        info = json.load(f)
    name = (info.get("입력") or {}).get("대본")
    if not name:
        return info, None
    return info, MS.load_script(os.path.join(d, name), MR.recipe_buttons(), MR.emo_button())


def _ended(d):
    return any(k == "measure_end" for _, k, _ in measure_check.load_events(os.path.join(d, "events.csv")))


def pick_session(base=MEASURE_DIR, done=()):
    """따라갈 세션 — 가장 새 「기록 켬」 세션 하나만 · 끝났거나 이미 따라갔으면 None(기다린다).
    🔴 오래된 세션으로 돌아가지 않는다 — 비정상 종료로 끝 사건이 없는 옛 세션을 따라가면 안내가 엉뚱해진다(최종 리뷰 Important 2)."""
    for n in sorted(os.listdir(base), reverse=True):
        d = os.path.join(base, n)
        if n in SKIP_DIRS or not os.path.isfile(os.path.join(d, "session.json")):
            continue
        try:
            with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
                if json.load(f).get("측정기록") is False:
                    continue                             # 기록 끔 회차 — events.csv 가 없다
        except (OSError, ValueError):
            continue
        return None if d in done or _ended(d) else d
    return None


def take_lock(path=LOCK_FILE, wait_sec=3.0):
    """한 대만 돈다 — 이미 도는 진행 도우미(SSH 가 반쯤 끊겨 남은 옛 것)를 끄고 잠금을 넘겨받는다 → 잠금 파일(쥐고 있어야 한다) · 못 받으면 None.
    🔴 둘이 돌면 같은 안내가 두 번 나고 31 에 잡음이 섞인다(최종 리뷰 Important 3)."""
    import fcntl
    f = open(path, "a+", encoding="utf-8")
    end, asked = time.time() + wait_sec, False
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if not asked:
                f.seek(0)
                old = f.read().strip()
                if old.isdigit() and int(old) != os.getpid():
                    try:
                        os.kill(int(old), signal.SIGTERM)
                    except OSError:
                        pass
                asked = True
            if time.time() > end:
                f.close()
                return None
            time.sleep(0.1)
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def handle_keys(chars, pending, now_ms):
    """키 → (기다리는 N 시각 또는 None, [(일, 시각, 이유)]) — N 뒤 1 사람 · 2 장비 · 3초면 사람 · 기다리는 중 U = 그 N 취소
    · U = 마지막 수동 NG 취소 · Q = 끝(기다리던 N 은 사람으로 남긴다)(최종 리뷰 Minor 5·6)."""
    acts = []
    for c in chars:
        if pending is not None and c in "12":
            acts.append(("ng", pending, "장비" if c == "2" else "사람"))
            pending = None
        elif pending is not None and c in "uU":
            pending = None
        elif c in "nN":
            pending = now_ms
        elif c in "uU":
            acts.append(("undo", now_ms, None))
        elif c in "qQ":
            if pending is not None:
                acts.append(("ng", pending, "사람"))
                pending = None
            acts.append(("quit", now_ms, None))
    if pending is not None and now_ms - pending >= REASON_MS:
        acts.append(("ng", pending, "사람"))
        pending = None
    return pending, acts


def summary(res, name):
    """세션 끝 요약 — 다음 세션을 기다리는 동안 보인다(설계 §4.4)."""
    if not res:
        return f"{name} — 세션이 끝났다"
    runs = res["runs"]
    ng = [r for r in runs if r["status"] == "ng"]
    return (f"{name} — 세션이 끝났다 · 판 {len(runs)} · NG {len(ng)}"
            f"({' · '.join(str(r['i']) + '번째' for r in ng) or '없음'}) · 미완 {sum(1 for r in runs if r['status'] == 'partial')}")


def render(view, rows, ack, pending, name):
    """화면 글 — 바뀔 때만 다시 그린다."""
    res, r, cur = view["res"], view["run"], view["cur"]
    L = [f"{BOLD}SOP 가디언 측정 진행 — {name}{RST}    {ack}", ""]
    if not rows:
        L += ["대본 없음 — 안내 소리 없이 N 키만 쓴다", ""]
    elif not MS.has_tokens(rows):
        L += ["누름 칸 없는 대본 — 안내 소리·자동 NG 없이 N 키만 쓴다(대본 줄은 아래)", ""]
    if rows and res is not None:
        total = len(res["order"])
        ng = [x for x in res["runs"] if x["status"] == "ng"]
        k = r["script"] if r is not None else res["next"]
        L.append(f"{BOLD}대본 {k or '끝'}판 / 전체 {total}{RST} · 실제 {len(res['runs'])}번째 판 · NG {len(ng)}")
        if r is None:
            L.append(f"{GRN}▶ 「작업 시작」 → 대본 {k}판{RST}" if k else f"{GRN}대본을 다 했다 — ESC 로 시연 종료{RST}")
        done = r["consumed"] if r is not None else 0
        presses_done = 0
        for row in [x for x in rows if x["판"] == k]:
            ws = []
            for tk in row.get("낱말") or ():
                mark = ""
                if tk.kind == "press":
                    mark = "✔" if presses_done < done else ""
                    presses_done += 1
                pre = "~" if tk.kind == "hover" else "#" if tk.kind == "tool" else ""
                exp = f"@{tk.expected}" if tk.expected and tk.kind != "tool" and tk.expected != tk.name else ""
                ws.append(f"{mark}{pre}{tk.name}{exp}")
            L.append(f"  {row['행동']} {row.get('대상', '')} — {row['메모']}")
            if ws:
                L.append(f"    {DIM}{' · '.join(ws)}{RST}")
        if r is not None and (r["live_ng"] or r["status"] == "ng"):
            L += ["", f"{RED}  NG — 「작업 초기화」 뒤 대본 {r['script']}판 다시  {RST}", f"  {r['why']}"]
        if cur is not None:
            last = [e for e in cur["ev"] if e[1] in ("press", "release", "state", "sub")]
            if last:
                _, k2, d = last[-1]
                L.append(f"\n  마지막: {k2} {d.get('button') or d.get('new') or d.get('what') or ''}")
            if any(k3 == "state" and d3.get("new") == "WARNING" for _, k3, d3 in cur["ev"][-3:]):
                L.append(f"  {YEL} 경고 — 대본에 없으면 결과로 기록된다(NG 아님) {RST}")
    if pending is not None:
        L += ["", f"{YEL} NG 이유: 1 사람 · 2 장비 (3초 · 안 고르면 사람) {RST}"]
    L += ["", f"{DIM}N = NG(사람·장비 때만 · 모델 이상은 누르지 않는다) · U = 취소 · Q = 끝{RST}"]
    return "\n".join(L)


def read_keys(timeout):
    """한 번에 들어온 글자를 모두 — os.read 로 직접(버퍼에 글자가 묻히지 않게 · 최종 리뷰 Minor 5)."""
    fd = sys.stdin.fileno()
    r, _, _ = select.select([fd], [], [], timeout)
    return os.read(fd, 32).decode("utf-8", "ignore") if r else ""


def follow(d):
    """한 세션을 끝(measure_end)까지 따라간다 → ("q" | "next", 요약). 더 새 기록 세션이 생기면 그쪽으로 넘어간다(Important 2)."""
    _, rows = session_rows(d)
    gpath = os.path.join(d, "guide.csv")
    old = measure_check.load_events(gpath)
    glog = GuideLog(gpath)
    last_req = [None]

    def sink(key, t):
        write_req(key, t)
        last_req[0] = (int(t), t)
    g = Guide(rows, MR.emo_button(), cue_sink=sink, log_sink=glog.write)
    g.restore(old)
    tail = Tail(os.path.join(d, "events.csv"))
    pending, screen, checked = None, None, 0.0
    name = os.path.basename(d)
    while True:
        tail.poll()
        now = measure_log.now_ms()
        g.step(tail.rows, now)
        pending, acts = handle_keys(read_keys(TICK_SEC), pending, measure_log.now_ms())
        for kind, t, why in acts:
            if kind == "quit":
                return "q", ""
            g.mark(t, kind, why)
        s = render(g.view, rows, ack_status(last_req[0]), pending, name)
        if s != screen:
            sys.stdout.write("\033[2J\033[H" + s + "\n")
            sys.stdout.flush()
            screen = s
        if any(k == "measure_end" for _, k, _ in tail.rows[-3:]):
            return "next", summary(g.view["res"], name)
        if now - checked >= SWITCH_CHECK_MS:
            checked = now
            newer = pick_session()
            if newer is not None and newer != d and os.path.basename(newer) > name:
                return "next", f"{name} — 더 새 측정 세션이 열려 그쪽으로 넘어갔다(이 세션은 끝 사건이 없다)"


def run_live():
    import termios
    import tty
    lock = take_lock()
    if lock is None:
        print("🔴 다른 진행 도우미를 끄지 못했다 — 그 창에서 Q 로 끄고 다시 켜라")
        return 1
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    # 🔑 SIGTERM(새로 켠 진행 도우미가 끈다) · SIGHUP(SSH 끊김)도 터미널을 되돌리고 끝낸다(최종 리뷰 Minor 11)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))
    tty.setcbreak(fd)
    try:
        done, last, screen = set(), "", None
        while True:
            d = pick_session(done=done)
            if d is None:
                s = (last + "\n\n" if last else "") + "측정 세션을 기다린다 — 실행기(SOP 가디언 측정)를 켜면 따라간다 · Q = 끝"
                if s != screen:
                    sys.stdout.write("\033[2J\033[H" + s + "\n")
                    sys.stdout.flush()
                    screen = s
                if any(c in "qQ" for c in read_keys(1.0)):
                    return 0
                continue
            how, last = follow(d)
            screen = None
            if how == "q":
                return 0
            done.add(d)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def replay(d, dump=True):
    """기록을 시간 순서로 다시 넣어 안내·NG 결정을 본다 — 소리·파일 쓰기 없음(설계 §6.3)."""
    _, rows = session_rows(d)
    ev = sorted(measure_check.load_events(os.path.join(d, "events.csv")), key=lambda e: e[0])
    g = Guide(rows, MR.emo_button())
    g.restore(measure_check.load_events(os.path.join(d, "guide.csv")))
    out, i, t = [], 0, ev[0][0] if ev else 0.0
    while i < len(ev):
        t += TICK_SEC * 1000
        while i < len(ev) and ev[i][0] <= t:
            i += 1
        c = g.step(ev[:i], t)
        if c:
            r = g.view["run"]
            out.append((round(t), r["i"], r["script"], c[1]))
            if dump:
                print(f"{t:14.1f} · {r['i']:2d}번째 판 · 대본 {r['script']} · {c[0]} {c[1]}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="측정 진행 도우미(측정 진행 도우미 설계 2026-10-11)")
    ap.add_argument("--replay", default="", help="세션 폴더 — 기록을 다시 돌려 안내·NG 결정을 본다(소리·파일 쓰기 없음)")
    a = ap.parse_args(argv)
    if a.replay:
        replay(a.replay, dump=True)
        return 0
    return run_live()


if __name__ == "__main__":
    sys.exit(main())
