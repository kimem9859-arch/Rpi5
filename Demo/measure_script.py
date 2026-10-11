"""대본 「누름」 칸 · 판 맞춤 — 진행 도우미(실시간)와 세기(나중)가 같이 쓰는 단일 출처.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-11-측정진행도우미-안내소리-design.md §3.1 · §4.2 · §4.3
🔴 순수 모듈이다(Qt · 장치 없음) — 사건 목록과 대본 줄만 받는다. 판정을 다시 하지 않고 시연이 적은 사건을 대조한다.

누름 칸 낱말: B2(맞는 누름) · B3@B1(B1 차례에 B3) · EMO@B4 · ~B4@B3(머묾 — 안내만) · #렌치(공구 — 안내만)
             · 초기화(「작업 초기화」 — 안내만 · 공구 대기가 끝난 뒤 · 설계 D17)
             · 끝의 ? = 그 낱말부터는 판이 먼저 끝나도 된다.
판 상태: ok 대본대로 · ng 자동(안내와 다른 버튼) 또는 수동(N 키) · partial 일찍 끝남(결과로 남김 · D16)
        · extra 대본을 다 끝낸 뒤 · open 아직 안 끝남(진행 도우미).
🔴 자동 NG 는 「안내와 다른 버튼이 실제로 눌림」 하나뿐 — 모델·판정 이상은 NG 가 아니다(D4).
"""
import csv
import os
import re
from collections import namedtuple

ACTIONS = ("정상", "위반", "머묾", "틀린공구", "호출", "질문", "비상질문")   # 대본 행동(세기 설계 §5)
TOOLS = {"렌치": "wrench", "드라이버": "driver", "플라이어": "pliers"}
RESET = "초기화"
Token = namedtuple("Token", "kind name expected optional row")              # kind = press · hover · tool · reset
_TOK = re.compile(r"^(?P<hover>~)?(?P<tool>#)?(?P<name>[^@?~#\s]+)(?:@(?P<exp>[^@?~#\s]+))?(?P<opt>\?)?$")


def parse_tokens(text, buttons, emo="EMO", row=None):
    """누름 칸 → [Token] · 틀린 낱말은 ValueError(무엇이 틀렸는지)."""
    out = []
    for w in (text or "").split():
        m = _TOK.match(w)
        if not m:
            raise ValueError(f"낱말 「{w}」 을(를) 읽을 수 없다")
        name, exp, opt = m.group("name"), m.group("exp"), bool(m.group("opt"))
        if name == RESET:
            if w != RESET:
                raise ValueError(f"초기화 낱말 「{w}」 — 꾸밈 없이 「{RESET}」 만")
            out.append(Token("reset", name, None, False, row))
            continue
        if m.group("tool"):
            if name not in TOOLS or exp or m.group("hover"):
                raise ValueError(f"공구 낱말 「{w}」 — #{' · #'.join(TOOLS)} 가운데 하나")
            out.append(Token("tool", name, None, opt, row))
            continue
        if name not in buttons and name != emo:
            raise ValueError(f"「{w}」 의 버튼 {name} 은(는) {'·'.join(buttons)}·{emo} 가운데 하나여야 한다")
        if exp is not None and exp not in buttons:
            raise ValueError(f"「{w}」 의 차례 {exp} 은(는) {'·'.join(buttons)} 가운데 하나여야 한다")
        if m.group("hover"):
            if exp is None or name == emo:
                raise ValueError(f"머묾 낱말 「{w}」 은(는) ~버튼@차례 꼴이다")
            out.append(Token("hover", name, exp, opt, row))
        else:
            out.append(Token("press", name, exp if exp is not None else (None if name == emo else name), opt, row))
    return out


def load_script(path, buttons=None, emo="EMO"):
    """대본 CSV(세기 설계 §5 + 진행 도우미 설계 §4.2 「누름」 칸) — 빈 줄·BOM 은 받는다 · 행동 철자·판 숫자·
    위반/머묾 대상·누름 낱말 오류는 줄 번호와 함께 멈춘다. buttons 를 주면 「낱말」 칸에 [Token] 을 둔다."""
    name, rows = os.path.basename(path), []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            n = rd.line_num                         # 빈 줄이 있어도 파일의 실제 줄 번호
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not any(r.values()):
                continue
            if r.get("행동") not in ACTIONS:
                raise ValueError(f"대본 {name} {n}행 — 행동 「{r.get('행동')}」 은(는) {'·'.join(ACTIONS)} 가운데 하나여야 한다")
            try:
                r["판"] = int(r.get("판", ""))
            except ValueError:
                raise ValueError(f"대본 {name} {n}행 — 판 「{r.get('판')}」 은(는) 1부터의 숫자여야 한다") from None
            for k in ("대상", "기대", "메모", "누름"):
                r.setdefault(k, "")
            if buttons and r["행동"] in ("위반", "머묾") and r["대상"] not in buttons:
                raise ValueError(f"대본 {name} {n}행 — {r['행동']} 대상 「{r['대상']}」 은(는) 레시피 버튼({'·'.join(buttons)}) 가운데 하나여야 한다")
            if buttons:
                try:
                    r["낱말"] = parse_tokens(r["누름"], buttons, emo, row=len(rows))
                except ValueError as e:
                    raise ValueError(f"대본 {name} {n}행 — 누름 칸: {e}") from None
            rows.append(r)
    return rows


def has_tokens(rows):
    """누름 칸이 하나라도 채워져 있나 — 없으면 세기는 판 맞춤을 건너뛰고 지금처럼 센다(되돌리기 · 설계 §9)."""
    return any(r.get("낱말") for r in rows or ())


def script_order(rows):
    """{대본 판: 그 판 낱말 전부(줄 차례대로)} — 판 번호 작은 것부터."""
    out = {}
    for r in rows or ():
        out.setdefault(int(r["판"]), []).extend(r.get("낱말") or ())
    return dict(sorted(out.items()))


def runs_of(events):
    """판 = run_start ~ run_end · run_reset — measure_count.split_runs 와 같은 규칙.
    끝 사건 없이 다음 run_start 가 오면 그 앞에서 닫는다(「끊김」) · 마지막 열린 판 = open."""
    out, cur = [], None
    for t, k, d in events:
        if k == "run_start":
            if cur is not None:
                cur.update(t1=t - 0.001, end="끊김")
                out.append(cur)
            cur = {"t0": t, "t1": None, "end": "open", "ev": []}
        elif cur is None:
            continue
        elif k in ("run_end", "run_reset"):
            cur.update(t1=t, end="완주" if k == "run_end" else "초기화")
            out.append(cur)
            cur = None
        else:
            cur["ev"].append((t, k, d))
    if cur is not None:
        out.append(cur)
    return out


def run_presses(ev, emo="EMO"):
    """판 안 누름 가운데 시연이 받은 것만 → [(t, 버튼, 기대)].
    무시 = 차단 중 EMO 아닌 버튼 · 진행 중 서브 작업 버튼 재입력(경고 중 정답 포함 — 단계를 올리지 않는다 · 설계 D4)."""
    sub, emo_on, out = None, False, []
    for t, k, d in ev:
        if k == "sub":
            w = d.get("what")
            if w == "start":
                sub = d.get("button")
            elif w in ("finish", "cancel"):
                sub = None
        elif k == "release" and d.get("what") == "block" and d.get("ok"):
            emo_on = False
        elif k == "press":
            b = d.get("button")
            if d.get("state") == "BLOCK" and b != emo:
                continue
            if b == emo:
                if emo_on and d.get("state") == "BLOCK":
                    continue                  # EMO 차단 중 EMO 재입력 — 시연은 아무 일도 안 한다(최종 리뷰 Minor 7)
                emo_on = True
            if sub is not None and b == sub:
                continue
            out.append((t, b, d.get("expected")))
    return out


def _simulate(presses, toks):
    """누름 → 그 대본 판의 누름 낱말에 차례대로 대 본다."""
    req = [x for x in toks if x.kind == "press"]
    first_opt = next((n for n, x in enumerate(req) if x.optional), len(req))
    i = 0
    for n, (_, b, e) in enumerate(presses):
        if i < len(req) and req[i].name == b and (req[i].expected is None or req[i].expected == e):
            i += 1
            continue
        return {"ok": False, "at": n, "got": (b, e), "want": req[i] if i < len(req) else None, "consumed": i}
    return {"ok": True, "consumed": i, "missing": max(0, first_opt - i)}


def _ng_why(s):
    b, e = s["got"]
    want = s["want"]
    w = "대본에 없는 누름" if want is None else f"안내 {want.name}@{want.expected or '아무 차례'}"
    return f"{s['at'] + 1}번째 누름 {b}@{e} · {w}"


def _owner(runs, t):
    """그 시각의 판 자리 — 판 안이면 그 판 · 판 사이면 막 끝난 판 · 첫 판 전이면 None."""
    last = None
    for i, r in enumerate(runs):
        if r["t0"] <= t and (r["t1"] is None or t <= r["t1"]):
            return i
        if r["t1"] is not None and r["t1"] < t:
            last = i
    return last


def match(events, rows, marks=(), ahead=0, emo="EMO", auto=True, final=False):
    """사건 → 판마다 결과 + 다음 대본 판.

    marks = [(t_ms, "ng"|"undo", 이유)] — 시각 차례로 쌓고 undo 는 마지막 ng 를 지운다 · ng 는 그 시각의 판에.
    ahead = 끝난 판을 지금 대본 판 → 다음 ahead 판까지 대 본다(세기 2 · 진행 도우미 0 — 설계 §4.3 「앞 찾기」).
    🔴 뒤 대본 판으로 건너뛰는 것은 그 판과 **끝까지 맞을 때만**(ok) — 앞부분만 같은 NG 시도를 건너뜀으로 읽지 않게.
       지금 대본 판은 미완(partial)도 받는다(D16).
    auto = False → 누름 칸 없는 대본·대본 없는 세션(rows None) — 자동 NG 없이 수동 N 만 · 판마다 다음 대본 판(최종 리뷰
           Important 5 · 설계 §4.3 「대본 없는 세션 = 수동 NG 만」) · 대본이 없으면 대본 밖도 없다.
    final = True → 세기 — 세션 끝에 열린 판도 닫힌 판처럼 판정한다(최종 리뷰 Minor 3).
    """
    order = script_order(rows)
    keys = list(order)
    ng = []
    for t, kind, why in sorted(marks, key=lambda m: m[0]):
        if kind == "ng":
            ng.append((t, why or "사람"))
        elif kind == "undo" and ng:
            ng.pop()
    runs = runs_of(events)
    manual = {}
    for t, why in ng:
        i = _owner(runs, t)
        if i is not None:
            manual[i] = why
    out, k = [], 0
    for i, r in enumerate(runs):
        res = {"i": i + 1, "t0": r["t0"], "t1": r["t1"], "end": r["end"], "script": None, "status": "", "why": "",
               "skipped": [], "missing": 0, "consumed": 0, "live_ng": False,
               "warn": sum(1 for _, kk, d in r["ev"] if kk == "state" and d.get("new") == "WARNING")}
        ps = run_presses(r["ev"], emo)
        is_open = r["end"] == "open" and not final
        if not auto:
            if keys and k >= len(keys):
                res.update(status="extra", why="대본을 다 끝낸 뒤의 판")
            else:
                res.update(script=keys[k] if keys else None, status="open" if is_open else "ok")
                if keys and not is_open:
                    k += 1
        elif k >= len(keys):
            res.update(status="extra", why="대본을 다 끝낸 뒤의 판")
        elif is_open:
            s = _simulate(ps, order[keys[k]])
            res.update(script=keys[k], status="open", consumed=s["consumed"])
            if not s["ok"]:
                res.update(live_ng=True, why="자동 — " + _ng_why(s))
        else:
            chosen = None
            for j in range(k, min(k + ahead, len(keys) - 1) + 1):
                s = _simulate(ps, order[keys[j]])
                if s["ok"] and (j == k or not s["missing"]):
                    chosen = (j, s)
                    break
            if chosen is None:
                s = _simulate(ps, order[keys[k]])
                res.update(script=keys[k], status="ng", why="자동 — " + _ng_why(s), consumed=s["consumed"])
            else:
                j, s = chosen
                res.update(script=keys[j], status="partial" if s["missing"] else "ok", skipped=keys[k:j],
                           missing=s["missing"], consumed=s["consumed"])
                k = j + 1
        if i in manual and res["status"] != "extra":
            if res["status"] == "ng":                  # 이미 자동 NG — 자동으로 센다(최종 리뷰 Minor 2)
                res["why"] += f" · 수동 — {manual[i]} 도 표시"
            else:
                if res["status"] in ("ok", "partial") and res["script"] is not None:
                    k = keys.index(res["script"])      # 다시 할 대본 판으로 되돌린다
                res.update(status="ng", why=f"수동 — {manual[i]}" + (f" · {res['why']}" if res["why"] else ""))
        out.append(res)
    return {"runs": out, "next": keys[k] if k < len(keys) else None, "order": order}
