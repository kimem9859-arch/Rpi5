"""세기 — 측정 기록으로 값을 낸다(측정 도구 정합 1단계-나 · 순수 함수 · 파일을 읽지 않는다).

설계 = 상위 sop-project docs/superpowers/specs/2026-10-09-측정도구-정합-1단계-나-세기-design.md
    §3 공통 규칙 · §3-b 기준 · §4 값별 세는 법. 파일 읽기·대본·목표·표 = measure_report.py.

S(세션 하나) — measure_report.load_session 이 만든다:
    "kind" 세션 종류 · "info" session.json · "settings" session.json 「설정」
    "frames" [{frame, t(=t_recv_ms), seq, t_start, t_done, roi, level, decode_ms…zone_ms}] (t 순)
    "fsm"    [{t(=t_recv_ms), t_gui, roi, level, state, expected}] (t 순)
    "events" · "voice" [(t_ms, kind, data)] (t_ms 순) · "script" [{판, 행동, 대상, 기대, 메모}] 또는 None
    "says"   guide.csv 의 말 띠 [(t_ms, "say"|"said", data)] (t_ms 순 · 없으면 빈 목록 · 옛 꼴은 키가 없다)
    "emo" EMO 버튼 이름 · "rate" 마이크 표본률
🔴 판정을 다시 하지 않는다 — 시연 프로그램이 적은 상태·구역·시각을 센다(측정도구 스킬 「재구현하지 않는다」).
🔴 기준 값을 여기 따로 적지 않는다 — 시연·측정 쪽에서 읽는다(설계 §3-b). 아래 상수는 세기에만 있는 값이다.
"""
import bisect
import os
import re
import sys

_TEST = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_TEST))      # Demo/ — fps
sys.path.insert(0, _TEST)                       # Demo/test/ — hoi_metrics

import fps            # noqa: E402 — FPS 창·끊김 = 시연 화면과 같은 상수
import hoi_metrics    # noqa: E402 — 사전 감지·선행시간·구간 판정 규칙 단일 출처
import measure_script  # noqa: E402 — 대본 행동 · 판 맞춤 단일 출처(진행 도우미 설계 D3)
import voice_lib      # noqa: E402 — 호출어 떼기 단일 출처(음성비서가 질문에서 떼는 규칙 그대로 · V6)

# ── 세기에만 있는 값(설계 §3-b 마지막 행) ──────────────────────────────────
EDGE_PAIR_MS = 500.0                    # 누름 ↔ 같은 버튼 GPIO 엣지 짝 — 화면 처리 시각 앞 0.5초 안(디바운스 0.05초보다 넉넉히)
CURVE_STEPS = tuple(round(0.10 + 0.05 * i, 2) for i in range(19))    # 체류 두 곡선 문턱 0.10~1.00초
ALERT_WAIT_MS = 3000.0                  # 알림·해제 뒤 재생 시작·멈춤을 기다리는 한도 — 넘으면 「없음」
ALERT_MATCH_MS = (-100.0, 1000.0)       # 경고·차단 전이 시각 대비 알림 「상태 공개 시각」 짝 범위(앞·뒤) — 뒤는 다음 상태 바뀜에서 자른다
BYTES_PER_SAMPLE = 2                    # 마이크 업링크 = int16 · 1채널(voice_mic 형식)
GAP_MAX_SEC = 2.0                       # 28 — 이보다 긴 공백은 손을 떼고 돌아온 것(손 놓침 아님 · 갭메우기 0.3초의 몇 배)
WAKE_PAD_MS = 1000.0                    # V5 — said 뒤 여유(데몬의 호출 사건이 진행 도우미 said 보다 늦게 적힐 수 있다)
ANSWER_PLAY_MS = 3000.0                 # V7 — 답 보내기 직전(answer) → 그 답의 재생 시작을 기다리는 한도
EMERGENCY_PAD_MS = 500.0                # V8 — 차단 해제 뒤에도 비상 구간으로 보는 여유(데몬이 상태를 다시 읽기 전)
ANSWER_GROUPS = ("LLM", "즉답", "그 밖")  # V7 답 출처 묶음(_src_group) — 보고서 순서
DONE_WORDS = ("끝", "완료")              # V7 초벌 — 기대 칸의 「끝/완료」는 답에 둘 중 하나

RUN_STATES = ("PROCESS_RUN", "MONITOR", "WARNING")     # 판이 진행 중인 판정기 상태(fsm.State 이름)
ACTIONS = measure_script.ACTIONS                       # 대본 행동 — 단일 출처(진행 도우미 설계 D3)
STAGES = ("decode_ms", "orient_ms", "detect_ms", "track_ms", "hand_ms", "tool_ms", "zone_ms")
REQ_CMD = {("engage", True): "BLOCK", ("feedback", "BLOCK"): "BLOCK", ("feedback", "WARNING"): "WARN"}   # interlock_req → 그 요청이 부르는 명령(interlock._FEEDBACK_TO_CMD · set_interlock)


# ── 공통 ─────────────────────────────────────────────────────────────────
def split_runs(events):
    """판 = run_start ~ run_end(완주) · run_reset(초기화) · 닫히지 않으면 미완. 판 밖 사건은 버린다."""
    runs, cur = [], None
    for t, k, d in events:
        if k == "run_start":
            if cur is not None:
                runs.append(cur)
            cur = {"i": len(runs) + 1, "t0": t, "t1": None, "end": "미완", "ok": None, "why": None, "ev": []}
        elif cur is None:
            continue
        elif k == "run_end":
            cur.update(t1=t, end="완주", ok=bool(d.get("ok")))
            runs.append(cur)
            cur = None
        elif k == "run_reset":
            cur.update(t1=t, end="초기화", why=d.get("why"))
            runs.append(cur)
            cur = None
        else:
            cur["ev"].append((t, k, d))
    if cur is not None:
        runs.append(cur)
    return runs


def run_of(runs, t):
    for r in runs:
        if r["t0"] <= t and (r["t1"] is None or t <= r["t1"]):
            return r
    return None


def pair_presses(events):
    """누름마다 실제로 누른 시각 — 같은 버튼 GPIO 엣지(처리 시각 앞 EDGE_PAIR_MS 안)와 **들어온 순서대로** 짝.
    how = 엣지(장치 엣지 시각) · 콜백(엣지 대신 콜백 시각이 적힌 엣지) · 처리(엣지 기록 없음 → 화면 처리 시각) · 키보드."""
    edges = [(t, d) for t, k, d in events if k == "gpio_edge"]
    used, out = set(), []
    for t, k, d in events:
        if k != "press":
            continue
        b = d.get("button")
        cand = [i for i, (te, de) in enumerate(edges)
                if i not in used and de.get("button") == b and 0 <= t - te <= EDGE_PAIR_MS]
        if d.get("source") == "keyboard":
            t_at, how = t, "키보드"
        elif cand:
            used.add(cand[0])                    # 가장 먼저 들어온 엣지 — gpio_input 은 엣지를 적은 순서대로 누름을 내보낸다
            t_at = edges[cand[0]][0]
            how = "엣지" if edges[cand[0]][1].get("src") == "edge" else "콜백"
        else:
            t_at, how = t, "처리"
        out.append({"t": t, "t_at": t_at, "button": b, "source": d.get("source"),
                    "expected": d.get("expected"), "state": d.get("state"), "how": how})
    return out


def violations(S):
    """위반 눌림 — gpio · 기대 버튼과 다름 · EMO 아님 · 판 안 · 누를 때 판이 진행 중(차단 중 누름은 시연이 버린다)."""
    runs = split_runs(S["events"])
    return [p for p in pair_presses(S["events"])
            if p["source"] == "gpio" and p["expected"] and p["button"] not in (p["expected"], S["emo"])
            and p["state"] in RUN_STATES and run_of(runs, p["t"]) is not None]


def normal_run_ids(S, runs):
    """정상 판 — 대본이 있으면 대본의 「정상」 판 · 없으면 정상·음성끔 세션의 모든 판."""
    if S["script"] is not None:
        return {int(r["판"]) for r in S["script"] if r["행동"] == "정상"}
    if S["kind"] in ("정상", "음성끔"):
        return {r["i"] for r in runs}
    return set()


def rec_spans(events):
    """녹화 구간 [(켬 ms, 끔 ms, 방식)] — 켬~끔(측정 녹화 설계 R4·R5) · 끔이 없으면 세션 끝까지(inf)."""
    out, cur = [], None
    for t, k, d in sorted(events, key=lambda e: e[0]):
        if k == "recording_on" and cur is None:
            cur = (float(t), d.get("mode"))
        elif k == "recording_off" and cur is not None:
            out.append((cur[0], float(t), cur[1]))
            cur = None
    if cur is not None:
        out.append((cur[0], float("inf"), cur[1]))
    return out


def split_recording(S):
    """(나머지, 녹화 쪽 또는 None) — 녹화 구간 안의 모든 기록(events·voice·frames·fsm)을 나머지에서 빼 녹화 쪽으로
    (측정 녹화 설계 R5 — 판째 · 녹화 부하가 판정 값까지 흔들 수 있다). 🔑 빠진 구간은 `breaks` 로 남겨 구간을 넘는
    간격을 끊김·받은 간격으로 세지 않게 한다(v_fps · v_stages)."""
    spans = rec_spans(S["events"])
    if not spans:
        return dict(S, rec_spans=[], breaks=list(S.get("breaks") or [])), None
    res_t = [t for t, k, _ in S["events"] if k == "res"]
    S = dict(S, first_res_t=res_t[0] if res_t else None)              # 세션 첫 res — 두 쪽 다 이것만 뺀다(v_res)
    inside = lambda t: any(a <= t <= b for a, b, _ in spans)             # noqa: E731
    pick = lambda rows, key, keep: [r for r in rows if inside(key(r)) != keep]   # noqa: E731
    lists = {"events": lambda e: e[0], "voice": lambda e: e[0], "frames": lambda r: r["t"], "fsm": lambda r: r["t"],
             "says": lambda e: e[0]}                                     # 말 띠(V5~V8)도 같이 — 옛 꼴은 키가 없다
    M = dict(S, rec_spans=spans, breaks=[(a, b) for a, b, _ in spans] + list(S.get("breaks") or []),
             **{k: pick(S.get(k, []), f, True) for k, f in lists.items()})
    R = dict(S, rec_spans=spans, breaks=[(spans[i][1], spans[i + 1][0]) for i in range(len(spans) - 1)],
             **{k: [r for r in pick(S.get(k, []), f, False)
                    if not (k == "events" and r[1] in ("recording_on", "recording_off"))] for k, f in lists.items()})
    return M, R



def split_guide(S, res):
    """판 맞춤(measure_script.match) → NG·대본 밖 판의 모든 기록(events·voice·frames·fsm)을 그 판째 빼고 대본을 남은 판
    차례로 다시 번호 매긴다 — 남은 판 i = 대본 판 i 라 값 함수는 그대로 쓴다(진행 도우미 설계 D12).
    🔑 빠진 판은 breaks 로 남겨 그 구간을 넘는 간격을 끊김으로 세지 않는다(split_recording 과 같은 방식)."""
    drop = [(r["t0"], r["t1"] if r["t1"] is not None else float("inf"))
            for r in res["runs"] if r["status"] in ("ng", "extra")]
    keep = [r for r in res["runs"] if r["status"] not in ("ng", "extra")]
    inside = lambda t: any(a <= t <= b for a, b in drop)           # noqa: E731
    lists = {"events": lambda e: e[0], "voice": lambda e: e[0], "frames": lambda r: r["t"], "fsm": lambda r: r["t"],
             "says": lambda e: e[0]}
    script = S["script"]
    if script is not None:
        by = {}
        for row in script:
            by.setdefault(int(row["판"]), []).append(row)
        script = [dict(row, 판=n) for n, r in enumerate(keep, 1) if r["script"] is not None for row in by.get(r["script"], [])]
    # 🔑 full = 판 맞춤 전 — 대본과 무관한 시스템 값(12·13·26·27·30·14·V1·V3·V4·V9)은 뺀 판까지 센다(설계 §3.1 「장비 NG 판도
    #    끊김(13)에는 남는다」 · D10 「V1 = 폐기 세션 알림 전체」 · 최종 리뷰 Important 1) — 고장 때문에 뺀 판에서 그 고장이 사라지지 않게
    return dict(S, script=script, guide=res, full=S, breaks=list(S.get("breaks") or []) + drop,
                **{k: [x for x in S.get(k, []) if not inside(f(x))] for k, f in lists.items()})


def _crosses(a, b, breaks):
    """간격 (a, b) 가 빠진 구간과 겹치나 — 겹치면 그 간격은 세지 않는다(끊김이 아니라 뺀 구간이다)."""
    return any(a < hi and b > lo for lo, hi in breaks)


def merge(parts):
    """세션 값 합치기 — 수는 더하고 목록은 잇고 딕셔너리는 안으로(통합값)."""
    out = {}
    for p in parts:
        for k, v in p.items():
            if isinstance(v, dict):
                out[k] = merge([out.get(k, {}), v])
            elif isinstance(v, list):
                out[k] = out.get(k, []) + v
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = out.get(k, 0) + v
            else:
                out[k] = v
    return out


# ── 1 · 4 · 2·16 · 25 · 3 ────────────────────────────────────────────────
def v_prevent(S):
    """1 위반 사전 차단율 — 누를 때 판정기 상태 = WARNING.
    진단(성공으로 세지 않는다 · 진행 도우미 설계 D13①) — 경고가 없던 눌림을 누르는 순간(GPIO 엣지)까지의 판정기 줄로 가른다:
    none = 그 버튼 구역에 손 없음 · ring = 링에만(박스 안 줄 없음) · late = 박스 안에서 체류 문턱을 넘긴 줄을 누르기 전에
    받았는데 판정기가 누름보다 늦게 처리 · other = 그 줄을 누름 전에 처리했는데도 경고 없음(판정 규칙 예외 — 방금 완료한 버튼 등
    · 최종 리뷰 Minor 8) · short = 체류 미달(문턱을 못 채움 — 문턱이 기록에 없으면 이쪽).
    🔑 안 B(느린 손끝 즉시 경고 · 설정 FSM_SLOW_ENTRY_PX_S_VGA > 0)가 켜진 세션의 short = 체류도 못 채웠고 손끝이 속도 문턱
    위(빠른 손)였거나 속도를 몰랐던 눌림 — 속도는 기록에 없어 가르지 않는다(세는 법 같음 · 보고서가 단서만 단다 · 최종 리뷰 Minor M-1)."""
    thr = (S.get("settings") or {}).get("FSM_DWELL_THRESHOLD_SEC")
    F = S["fsm"]
    ft = [r["t"] for r in F]
    out = {"n": 0, "k": 0, "late": 0, "short": 0, "ring": 0, "none": 0, "other": 0}
    for p in violations(S):
        out["n"] += 1
        if p["state"] == "WARNING":
            out["k"] += 1
            continue
        i = bisect.bisect_right(ft, p["t_at"]) - 1
        if i < 0 or F[i]["roi"] != p["button"]:
            out["none"] += 1
            continue
        j = i
        while j > 0 and F[j - 1]["roi"] == p["button"]:
            j -= 1
        stretch = F[j:i + 1]
        if not any(r["level"] == 2 for r in stretch):
            out["ring"] += 1
            continue
        hits = [r for r in stretch if thr is not None and r["level"] == 2 and r["t"] - F[j]["t"] >= thr * 1000]
        out["short" if not hits else "late" if any(r["t_gui"] > p["t"] for r in hits) else "other"] += 1
    return out


def v_lead(S):
    """4 경고 선행시간 — 1의 성공 눌림마다 누른 시각 − 직전 WARNING 전이 시각(초)."""
    warns = [t for t, k, d in S["events"] if k == "state" and d.get("new") == "WARNING"]
    leads = []
    for p in violations(S):
        if p["state"] != "WARNING":
            continue
        prev = [t for t in warns if t <= p["t"]]
        if prev:
            leads.append(round((p["t_at"] - prev[-1]) / 1000, 3))
    return {"leads": leads}


def v_reason(S):
    """경고 이유(판정 기준 안 B · 목표 없음 · 최종 리뷰 Minor M-2) — 경고 상태 사건의 reason: slow = 속도 경고(느린 손끝 즉시)
    · dwell = 체류 경고 · none = 칸 없음·None(안 B 이전 옛 기록)."""
    out = {"slow": 0, "dwell": 0, "none": 0}
    for _, k, d in S["events"]:
        if k == "state" and d.get("new") == "WARNING":
            r = d.get("reason")
            out[r if r in ("slow", "dwell") else "none"] += 1
    return out


def v_normal(S):
    """16 정상 완주율 · 2 헛경고 — 정상 판이 완주 + ok + 경고·차단 0 이면 성공.
    실패 내역 = 경고·차단(f_alarm) · 초기화(f_reset) · 위반으로 끝남(f_viol). 세션 끝에 열린 판(open)은 세지 않는다."""
    runs = split_runs(S["events"])
    ids = normal_run_ids(S, runs)
    out = {"n": 0, "k": 0, "alarms": [], "f_alarm": 0, "f_reset": 0, "f_viol": 0, "open": 0}
    for r in runs:
        if r["i"] not in ids:
            continue
        if r["end"] == "미완":
            out["open"] += 1
            continue
        a = sum(1 for _, kk, d in r["ev"] if kk == "state" and d.get("new") in ("WARNING", "BLOCK"))
        out["n"] += 1
        out["alarms"].append(a)
        if a:
            out["f_alarm"] += 1
        elif r["end"] == "초기화":
            out["f_reset"] += 1
        elif not r["ok"]:
            out["f_viol"] += 1
        else:
            out["k"] += 1
    return out


def v_effect(S):
    """25 경고 효과 — 경고마다 그 판에서 다음 gpio 누름이 그때 기대 버튼인가."""
    runs = split_runs(S["events"])
    presses = [p for p in pair_presses(S["events"]) if p["source"] == "gpio"]
    n = k = none = 0
    for t, kk, d in S["events"]:
        if kk != "state" or d.get("new") != "WARNING":
            continue
        r = run_of(runs, t)
        if r is None:
            continue
        nxt = [p for p in presses if p["t"] > t and run_of(runs, p["t"]) is r]
        if not nxt:
            none += 1
            continue
        n += 1
        k += int(nxt[0]["button"] == d.get("expected"))
    return {"n": n, "k": k, "none": none}


def v_precision(S):
    """3 위반 판별 정밀도 — 경고(dwell_roi)마다 그 판 대본 시도(위반·머묾) 가운데 짝 없는 같은 버튼이 있으면 맞음."""
    if S["script"] is None:
        return {"script": 0}
    want = {}
    for row in S["script"]:
        lst = want.setdefault(int(row["판"]), [])
        if row["행동"] in ("위반", "머묾"):
            lst.append(row["대상"])
    n = k = 0
    for r in split_runs(S["events"]):
        if r["i"] not in want:
            continue
        left = list(want[r["i"]])
        for _, kk, d in r["ev"]:
            if kk == "state" and d.get("new") == "WARNING":
                n += 1
                if d.get("dwell_roi") in left:
                    left.remove(d.get("dwell_roi"))
                    k += 1
    return {"script": 1, "n": n, "k": k}


# ── 5·7 · 23 · 28 · 21 — 구역 ──────────────────────────────────────────────
def series(S):
    """프레임 순서의 (번호, 시각초, 갭메우기 앞 구역(frames.roi), 갭메우기 뒤 구역(fsm.fsm_roi — t_recv_ms 로 잇는다))."""
    by_t = {r["t"]: r["roi"] for r in S["fsm"]}
    F = [f["frame"] for f in S["frames"]]
    T = [f["t"] / 1000 for f in S["frames"]]
    raw = [f["roi"] for f in S["frames"]]
    filled = [by_t.get(f["t"]) for f in S["frames"]]
    return F, T, raw, filled


def _frame_at(F, T, t_sec):
    i = bisect.bisect_right(T, t_sec) - 1
    return F[i] if i >= 0 else (F[0] - 1 if F else -1)


def v_zone(S):
    """5 사전 감지율 · 7 ROI 오분류 · 창 능력 상한 — hoi_metrics.analyze_presses 그대로(EMO 빼고 · 판 안 gpio 누름).
    프레임 기록이 없는 누름(noframe)은 분모에서 뺀다."""
    F, T, raw, filled = series(S)
    runs = split_runs(S["events"])
    ps = [p for p in pair_presses(S["events"])
          if p["source"] == "gpio" and p["button"] != S["emo"] and run_of(runs, p["t"]) is not None]
    presses = [(p["t_at"] / 1000, p["button"], _frame_at(F, T, p["t_at"] / 1000)) for p in ps]
    rows = hoi_metrics.analyze_presses(presses, filled, F, T, None, raw_series=raw)
    noframe = sum(1 for r in rows if r[4] == "프레임 없음")
    rows = [r for r in rows if r[4] != "프레임 없음"]
    return {"n": len(rows), "noframe": noframe,
            "k5": sum(1 for r in rows if r[4] == "OK" and r[2] is not None and r[2] > 0),
            "k7": sum(1 for r in rows if r[4] == "ROI 불일치"),
            "kwin": sum(1 for r in rows if r[5]),
            "leads": [round(r[2], 3) for r in rows if r[4] == "OK" and r[2] is not None]}


def v_graze(S):
    """23 스침 통과율 · 체류 두 곡선 재료 — fsm 구역 구간(EMO 빼고).
    그 버튼 누름이 구간 안(끝 + 갭메우기)이면 누름 구간 · 아니면 지나감 — 단 구간 시작 때 기대 버튼이면 뺀다
    (판정기가 기대 버튼에서는 경고를 내지 않는다 · 상위 설계 §2 23 = 「오답 버튼 구역」)."""
    F, T, _raw, filled = series(S)
    tmap = dict(zip(F, T))
    fms = {f["frame"]: f["t"] for f in S["frames"]}
    exp = {r["t"]: r["expected"] for r in S["fsm"]}
    gap = float(S["settings"].get("FSM_GAP_FILL_SEC") or 0)
    ps = [p for p in pair_presses(S["events"]) if p["source"] == "gpio"]
    warns = [d for _, k, d in S["events"] if k == "state" and d.get("new") == "WARNING"]
    press_dwell, pass_dur, passes = [], [], []
    for roi, f0, f1, dur in hoi_metrics.segments(filled, F, T):
        if roi == S["emo"]:
            continue
        t0, t1 = tmap[f0], tmap[f1]
        hit = [p for p in ps if p["button"] == roi and t0 <= p["t_at"] / 1000 <= t1 + gap]
        if hit:
            press_dwell.append(round(hit[0]["t_at"] / 1000 - t0, 3))
            continue
        if exp.get(fms.get(f0)) == roi:
            continue
        warned = any(w.get("dwell_roi") == roi and w.get("frame_t_ms") is not None
                     and t0 <= w["frame_t_ms"] / 1000 <= t1 for w in warns)
        pass_dur.append(round(dur, 3))
        passes.append((t0, t1, roi, warned, dur))
    out = {"pass_n": len(passes), "pass_k": sum(1 for x in passes if not x[3]),
           "press_dwell": press_dwell, "pass_dur": pass_dur, "stay_n": 0, "stay_warned": 0}
    if S["script"] is not None:
        for r in split_runs(S["events"]):
            t_end = r["t1"] if r["t1"] is not None else float("inf")
            cand = [x for x in passes if r["t0"] / 1000 <= x[0] <= t_end / 1000]
            for row in S["script"]:
                if int(row["판"]) != r["i"] or row["행동"] != "머묾":
                    continue
                mine = [x for x in cand if x[2] == row["대상"]]
                if not mine:
                    continue
                # 의도한 머묾 = 그 버튼 경고가 든 구간 · 없으면 가장 긴 구간(앞선 짧은 스침·놓침 조각과 짝짓지 않게)
                m = next((x for x in mine if x[3]), None) or max(mine, key=lambda x: x[4])
                cand.remove(m)
                out["stay_n"] += 1
                out["stay_warned"] += int(m[3])
    return out


def curve(press_dwell, pass_dur, steps=CURVE_STEPS):
    """문턱 t 마다 (t, 잡음 = 누름 구간 체류 > t 비율, 거름 = 지나감 구간 길이 < t 비율) — 표본 없으면 None."""
    out = []
    for t in steps:
        a = sum(1 for x in press_dwell if x > t) / len(press_dwell) if press_dwell else None
        b = sum(1 for x in pass_dur if x < t) / len(pass_dur) if pass_dur else None
        out.append((t, a, b))
    return out


def fit_range(cv, catch, filt):
    """잡음 ≥ catch 이고 거름 ≥ filt 인 문턱 범위(최소, 최대) — 없으면 None."""
    ok = [t for t, a, b in cv if a is not None and b is not None and a >= catch and b >= filt]
    return (min(ok), max(ok)) if ok else None


def v_gap(S):
    """28 손 놓침 공백 — 갭메우기 앞 구역(frames.roi)에서 같은 버튼 구간 사이 빈 구간 길이(초).
    GAP_MAX_SEC 넘는 공백은 손을 떼고 돌아온 것이라 뺀다(long) · le_fill = 그 세션 갭메우기 값 이하 수."""
    F, T, raw, _filled = series(S)
    tmap = dict(zip(F, T))
    segs = hoi_metrics.segments(raw, F, T)
    allg = [round(tmap[b[1]] - tmap[a[2]], 3) for a, b in zip(segs, segs[1:]) if a[0] == b[0]]
    gaps = [g for g in allg if g <= GAP_MAX_SEC]
    fill = float(S["settings"].get("FSM_GAP_FILL_SEC") or 0)
    return {"gaps": gaps, "long": len(allg) - len(gaps), "le_fill": sum(1 for g in gaps if g <= fill)}


def v_confirm(S):
    """21 누름 카메라 확인 — confirm 사건 · 가짜 미확인 = 미확인인데 누른 뒤 여유(session.json) 안 프레임 구역이 그 버튼."""
    grace = float(S["settings"].get("PRESS_CONFIRM_GRACE_SEC") or 0) * 1000
    ps = pair_presses(S["events"])
    out = {"n": 0, "k": 0, "before": [], "why": {}, "fake": 0}
    for t, k, d in S["events"]:
        if k != "confirm":
            continue
        out["n"] += 1
        out["k"] += int(bool(d.get("verdict")))
        if d.get("before_ms") is not None:
            out["before"].append(d["before_ms"])
        w = d.get("why") or "?"
        out["why"][w] = out["why"].get(w, 0) + 1
        if d.get("verdict"):
            continue
        prev = [p for p in ps if p["button"] == d.get("button") and p["t"] <= t]
        if prev and any(f["roi"] == d.get("button") and prev[-1]["t_at"] <= f["t"] <= prev[-1]["t_at"] + grace
                        for f in S["frames"]):
            out["fake"] += 1
    return out


# ── 12·13 · 26·27 · 14 · 30 — 속도 · 인터락 · 자원 ───────────────────────────
def v_fps(S, below=None):
    """12 FPS 중앙값 재료 · 13 끊김 — 화면이 받은 간격(fsm t_gui). STALE_SEC 이상 = 끊김(빼고 창 비움 · stalls 에 남김)
    · 창 = FPS_WINDOW · low_n = 목표(below) 미만으로 내려간 횟수 · 창이 한 번도 안 찼으면 최저·최장을 내지 않는다."""
    ts = sorted(r["t_gui"] for r in S["fsm"])
    breaks = S.get("breaks", ())
    keep, win, mins, stalls = [], [], [], []
    low_start, longest, low_n = None, 0.0, 0
    for a, b in zip(ts, ts[1:]):
        if _crosses(a, b, breaks):
            win, low_start = [], None                     # 뺀 녹화 구간을 넘는다 — 끊김이 아니다(창만 비운다)
            continue
        x = (b - a) / 1000
        if x >= fps.STALE_SEC:
            stalls.append(round(x, 3))
        if x >= fps.STALE_SEC or x <= 0:
            win, low_start = [], None
            continue
        keep.append(round(x, 4))
        win.append(x)
        if len(win) > fps.FPS_WINDOW:
            win.pop(0)
        if len(win) < fps.FPS_WINDOW:
            continue
        f = fps.fps_from_intervals(win)
        mins.append(f)
        if below is not None and f < below:
            if low_start is None:
                low_start, low_n = b, low_n + 1
            longest = max(longest, (b - low_start) / 1000)
        else:
            low_start = None
    return {"iv": keep, "roll_min": [round(min(mins), 2)] if mins else [],
            "low_longest": [round(longest, 3)] if below is not None and mins else [],   # 창이 안 찼으면 잰 적이 없다
            "low_n": low_n, "stalls": stalls,
            "fps_ev": [d["fps"] for _, k, d in S["events"] if k == "fps" and d.get("fps") is not None]}


def v_stages(S):
    """26 단계별 ms · 27 받기↔처리 — frames.csv. 한 프레임 = decode + (done − start)(README)."""
    fr = S["frames"]
    breaks = S.get("breaks", ())
    out = {s: [f[s] for f in fr if f[s] is not None] for s in STAGES}
    out["total_ms"] = [round(f["decode_ms"] + f["t_done"] - f["t_start"], 3) for f in fr
                       if None not in (f["decode_ms"], f["t_done"], f["t_start"])]
    tr = [f["t"] for f in fr]
    td = [f["t_done"] for f in fr if f["t_done"] is not None]
    out["recv_iv"] = [round(b - a, 3) for a, b in zip(tr, tr[1:]) if not _crosses(a, b, breaks)]
    out["done_iv"] = [round(b - a, 3) for a, b in zip(td, td[1:]) if not _crosses(a, b, breaks)]
    # 받은 수 = 이어진 덩어리마다(뺀 녹화 구간을 넘으면 새 덩어리) 첫·끝 수신 번호 차 — 넘어서 세면 구간 안 수신까지 들어간다
    recv_n, seg = 0, []
    for f in fr:
        if seg and _crosses(seg[-1]["t"], f["t"], breaks):
            recv_n += _seg_recv(seg)
            seg = []
        seg.append(f)
    out["recv_n"] = recv_n + _seg_recv(seg)
    out["proc_n"] = len(fr)
    return out


def v_interlock(S):
    """14 응답시간 — 경고·차단 명령(WARN·BLOCK)마다 그 명령을 부른 판정의 첫 요청(interlock_req) → 보낸 시각 → ACK(ms).
    🔑 기준은 state 사건이 아니다 — 판정기(fsm._goto)는 인터락·피드백 요청을 먼저 하고 상태 전이를 맨 끝에 알린다.
    한 판정의 요청 묶음 = 직전 state 사건 뒤의 같은 명령 요청들(BLOCK = 차단 요청 → 피드백 · 명령은 중복 제거로 하나).
    unsent = 미연결·보내기 실패(ACK 시각 없음) · timeout = 응답 기다림 시간 초과 · noreq = 짝 요청 없음(재연결 첫 명령 등)."""
    states = [t for t, k, _ in S["events"] if k == "state"]
    reqs = [[t, REQ_CMD.get((d.get("what"), d.get("value"))), False]
            for t, k, d in S["events"] if k == "interlock_req"]
    out = {"n": 0, "noreq": 0, "unsent": 0, "timeout": 0, "total": [], "send": [], "ack": []}
    for t, k, d in S["events"]:
        if k != "interlock" or d.get("cmd") not in ("WARN", "BLOCK"):
            continue
        ts = d.get("t_send_ms", t)
        mine = [r for r in reqs if r[1] == d["cmd"] and not r[2] and r[0] <= ts]
        if not mine:
            out["noreq"] += 1
            continue
        start = max([s for s in states if s < mine[-1][0]], default=float("-inf"))
        t0 = min(r[0] for r in mine if r[0] > start)
        for r in mine:
            r[2] = True
        out["n"] += 1
        if d.get("t_ack_ms") is None:
            out["unsent"] += 1
        elif not d.get("ack"):
            out["timeout"] += 1
        else:
            out["total"].append(round(d["t_ack_ms"] - t0, 3))
            out["send"].append(round(ts - t0, 3))
            out["ack"].append(round(d["t_ack_ms"] - ts, 3))
    return out


def _seg_recv(seg):
    seqs = [f["seq"] for f in seg if f["seq"] is not None]
    return (seqs[-1] - seqs[0] + 1) if seqs else 0


def v_res(S):
    """30 자원 — res 사건(**세션** 첫 값은 의미 없다 · safety_console._pi_resources 머리말). 녹화로 나눈 쪽(split_recording)은
    세션 첫 값의 시각(first_res_t)만 뺀다 — 녹화 쪽 구간 안 첫 값까지 버리면 안 된다.
    🔑 직전 res 이후 처리한 프레임이 하나도 없는 값(안경 꺼짐·끊김 — 처리를 안 하던 동안)은 뺀다 — 실측 2026-10-09 시험
    세션에서 안경을 끈 뒤 4분이 「⑤ 녹화 비교」 나머지 쪽 CPU 중앙값을 40%대 → 3% 로 끌어내렸다."""
    ts = sorted(t for t, k, _ in S["events"] if k == "res")
    first = S.get("first_res_t", ts[0] if ts else None)
    done = sorted(f["t"] for f in S["frames"])
    keep, prev = set(), first
    for t in ts:
        if t != first:
            lo = prev if prev is not None and prev < t else float("-inf")
            if bisect.bisect_right(done, t) > bisect.bisect_right(done, lo):     # (lo, t] 에 처리한 프레임이 있다
                keep.add(t)
        prev = t
    rs = [d for t, k, d in S["events"] if k == "res" and t in keep]
    return {key: [d[key] for d in rs if d.get(key) is not None] for key in ("cpu_avg", "cpu_max", "temp")}


# ── 17ⓐⓑ — 공구 ────────────────────────────────────────────────────────────
def tool_steps(runs):
    """판마다 공구 단계 = 그 판 첫 tool_scan 직전의 서브 작업 시작 → [(판, 시작 시각, 버튼)]."""
    out = []
    for r in runs:
        scans = [t for t, k, _ in r["ev"] if k == "tool_scan"]
        if not scans:
            continue
        starts = [(t, d.get("button")) for t, k, d in r["ev"]
                  if k == "sub" and d.get("what") == "start" and t <= scans[0]]
        if starts:
            out.append((r, starts[-1][0], starts[-1][1]))
    return out


def v_wrong_tool(S):
    """17ⓐ 틀린 공구 통과 — 대본 「틀린공구」 판(틀린 공구만 쥐고 기다린 뒤 초기화)에서 공구 단계가 끝나면 통과(실패)."""
    if S["script"] is None:
        return {"script": 0}
    runs = split_runs(S["events"])
    ids = {int(row["판"]) for row in S["script"] if row["행동"] == "틀린공구"}
    steps = {r["i"]: b for r, _t0, b in tool_steps(runs)}
    out = {"script": 1, "n": 0, "k": 0, "det": 0, "skip": 0}
    for r in runs:
        if r["i"] not in ids:
            continue
        if r["i"] not in steps or any(k == "tool_sim" for _, k, _ in r["ev"]):
            out["skip"] += 1          # 공구 단계에 닿지 않았거나 키보드 공구 — 시도로 세지 않는다
            continue
        out["n"] += 1
        if any(k == "sub" and d.get("what") == "finish" and d.get("button") == steps[r["i"]] for _, k, d in r["ev"]):
            out["k"] += 1
        out["det"] += sum(1 for _, k, _ in r["ev"] if k == "wrong_tool")
    return out


def v_tool_time(S):
    """17ⓑ 공구 확인 소요 — 공구 단계 시작 → 처음 tool_scan 의 tool = want(초) · 키보드 공구 판은 뺀다.

    🔑 tool = want 는 **쥠이 확정된** 스캔이다 — 2026-10-09 부터 확인(`TOOL_GRASP_CONFIRM_SCANS` 번 · 놓침은
       `TOOL_GRASP_MISS_ALLOWED` 번까지 봐줌 · 그 사이 스캔은 phase="checking" · tool=None)이 들어가 첫 근거보다
       **적어도** (N−1)×스캔 간격 늦다(놓침을 봐준 만큼 더). 두 값은 세션 `session.json` 「설정」에 있다 —
       다른 값끼리 섞어 인용하지 않는다.
    """
    out = []
    for r, t0, _b in tool_steps(split_runs(S["events"])):
        if any(k == "tool_sim" for _, k, _ in r["ev"]):
            continue
        hit = next((t for t, k, d in r["ev"]
                    if k == "tool_scan" and t >= t0 and d.get("tool") and d.get("tool") == d.get("want")), None)
        if hit is not None:
            out.append(round((hit - t0) / 1000, 3))
    return {"times": out}


# ── V1~V4 · V9 — 음성 ──────────────────────────────────────────────────────
def _alert_plays(S):
    """알림 재생 사건만 — 안내(cue_) 재생은 뺀다 · 옛 기록은 key 가 없다(None = 그대로 쓴다)."""
    return [(t, k, d) for t, k, d in S["voice"]
            if k in ("play_start", "play_end") and not str(d.get("key") or "").startswith("cue_")]


def _alert_windows(S):
    """알림마다 (시각, 데이터, 다음 알림 시각) — 키 없는 옛 기록은 그 알림의 재생을 이 창 안에서만 찾는다."""
    al = [(t, d) for t, k, d in S["voice"] if k == "alert"]
    return [(t, d, al[n + 1][0] if n + 1 < len(al) else float("inf")) for n, (t, d) in enumerate(al)]


def _first_play(plays, t, t_next, key):
    """그 알림의 재생 시작 — 재생에 소리 키가 있으면 같은 키의 첫 재생(새 기록 · 뒤 알림이 먼저 와도 제 재생을 찾는다)
    · 키가 없으면 다음 알림 전의 첫 재생(옛 기록)."""
    return next(((x, dd) for x, k, dd in plays if k == "play_start" and x >= t
                 and (dd.get("key") == key if dd.get("key") is not None else x < t_next)), None)


def v_alert_delay(S):
    """V1 알림 지연 — alert 의 상태 공개 시각(t_pub_ms) → 그 알림의 재생 시작(ALERT_WAIT_MS 안 · 초).
    알림 끈 세션(VOICE_ALERTS False)은 세지 않는다(진행 도우미 설계 D10)."""
    if (S.get("settings") or {}).get("VOICE_ALERTS") is False:
        return {"delays": [], "missing": 0, "off": 1}
    plays = _alert_plays(S)
    out = {"delays": [], "missing": 0}
    for t, d, t_next in _alert_windows(S):
        if d.get("t_pub_ms") is None:
            continue
        hit = _first_play(plays, t, t_next, d.get("key"))
        if hit is None or hit[0] - t > ALERT_WAIT_MS:
            out["missing"] += 1
        else:
            out["delays"].append(round((hit[0] - d["t_pub_ms"]) / 1000, 3))
    return out


def v_alert_count(S):
    """V2 알림 정확도 — 경고·차단 전이마다 그 시각 근처(ALERT_MATCH_MS) 알림 수 · 정상 판 안의 알림(헛알림).
    🔑 창의 끝은 다음 상태 바뀜(어느 state 사건이든)에서 자른다 — 경고 0.12~0.32초 뒤 차단이 오면 차단 알림까지 경고 쪽에
    세어 「여러 번」이 됐다(10/10 위반 3건 · 음성비서 빠른 해결 설계 §2.4). 바뀜이 하나뿐인 전이는 종전과 같다."""
    if not S["voice"]:
        return {"off": 1}
    pubs = [d["t_pub_ms"] for _, k, d in S["voice"] if k == "alert" and d.get("t_pub_ms") is not None]
    lo, hi = ALERT_MATCH_MS
    st = [t for t, k, _ in S["events"] if k == "state"]
    out = {"trans": 0, "one": 0, "zero": 0, "multi": 0, "normal": 0}
    for t, k, d in S["events"]:
        if k == "state" and d.get("new") in ("WARNING", "BLOCK"):
            i = bisect.bisect_right(st, t)
            end = st[i] if i < len(st) else float("inf")
            c = sum(1 for a in pubs if lo <= a - t <= hi and a < end)
            out["trans"] += 1
            out["one" if c == 1 else ("zero" if c == 0 else "multi")] += 1
    runs = split_runs(S["events"])
    ids = normal_run_ids(S, runs)
    for r in runs:
        if r["i"] in ids:
            t1 = r["t1"] if r["t1"] is not None else float("inf")
            out["normal"] += sum(1 for a in pubs if r["t0"] <= a <= t1)
    return out


def v_alert_stop(S):
    """V3 알림 끊기 — 알림 재생 중에 해제(release ok)되면 → 다음 stop_sent(초). 재생 중이 아니었으면 세지 않는다."""
    plays = _alert_plays(S)
    starts = [t for t, k, _ in plays if k == "play_start"]
    ends = [t for t, k, _ in plays if k == "play_end"]
    stops = [t for t, k, _ in S["voice"] if k == "stop_sent"]
    out = {"delays": [], "missing": 0}
    for t, k, d in S["events"]:
        if k != "release" or not d.get("ok"):
            continue
        s = [x for x in starts if x <= t]
        if not s or any(s[-1] <= e <= t for e in ends):
            continue
        nxt = next((x for x in stops if x >= t), None)
        if nxt is None or nxt - t > ALERT_WAIT_MS:
            out["missing"] += 1
        else:
            out["delays"].append(round((nxt - t) / 1000, 3))
    return out


def v_alert_len(S):
    """V4 알림 길이 — 그 알림의 재생 시작 → 그 뒤 첫 재생 끝(초). 「중단」으로 끝난 재생은 길이가 아니라 cut."""
    plays = _alert_plays(S)
    out = {"lens": [], "cut": 0}
    for t, d, t_next in _alert_windows(S):
        hit = _first_play(plays, t, t_next, d.get("key"))
        if hit is None or hit[0] - t > ALERT_WAIT_MS:
            continue
        pe = next(((x, dd) for x, k, dd in plays if k == "play_end" and x >= hit[0]), None)
        if pe is None:
            continue
        if pe[1].get("what") == "중단":
            out["cut"] += 1
        else:
            out["lens"].append(round((pe[0] - hit[0]) / 1000, 3))
    return out


def v_cue(S):
    """31 안내 → 누름(진행 도우미 설계 D14 · 목표 없음) — 버튼 안내 재생 시작(cue_B1~B4·EMO) → 그 버튼 GPIO 엣지(다음 안내 전) ·
    나눔 = 그 사이 판정기가 그 버튼 구역(링 포함)을 처음 본 수신 시각 → reach(안내 → 구역) · stay(구역 → 누름 = 머묾)."""
    btns = set(S.get("steps") or ()) | {S["emo"]}
    cues = [(t, str(d.get("key"))[4:]) for t, k, d in S["voice"]
            if k == "play_start" and str(d.get("key") or "").startswith("cue_") and str(d.get("key"))[4:] in btns]
    ps = [p for p in pair_presses(S["events"]) if p["source"] == "gpio"]
    out = {"total": [], "viol": [], "ok": [], "reach": [], "stay": [], "nopress": 0}
    for n, (t, b) in enumerate(cues):
        t_next = cues[n + 1][0] if n + 1 < len(cues) else float("inf")
        hit = next((p for p in ps if p["button"] == b and t <= p["t_at"] < t_next), None)
        if hit is None:
            out["nopress"] += 1
            continue
        dt = round((hit["t_at"] - t) / 1000, 3)
        out["total"].append(dt)
        out["ok" if (hit["expected"] == b or b == S["emo"]) else "viol"].append(dt)
        enter = next((r["t"] for r in S["fsm"] if t <= r["t"] <= hit["t_at"] and r["roi"] == b), None)
        if enter is not None:
            out["reach"].append(round((enter - t) / 1000, 3))
            out["stay"].append(round((hit["t_at"] - enter) / 1000, 3))
    return out


def v_uplink(S):
    """V9 마이크 손실 — 업링크 누적 바이트의 이웃 칸 차이 ÷ (rate × BYTES_PER_SAMPLE × 경과 초).
    데몬 재시작 = 두 표본 사이 음성 measure_end 또는 누적이 줄어든 칸 → 버린다 · 표본률을 못 읽었으면 내지 않는다."""
    if not S.get("rate"):
        return {"ratios": [], "norate": 1}
    ends = [t for t, k, _ in S["voice"] if k == "measure_end"]
    ups = [(t, d) for t, k, d in S["voice"] if k == "uplink"]
    out = []
    for (t0, d0), (t1, d1) in zip(ups, ups[1:]):
        if not (d0.get("connected") and d1.get("connected")) or t1 <= t0 or any(t0 < e < t1 for e in ends):
            continue
        db = d1["bytes"] - d0["bytes"]
        if db < 0:
            continue
        out.append(round(db / (S["rate"] * BYTES_PER_SAMPLE * (t1 - t0) / 1000), 4))
    return {"ratios": out}


# ── V5~V8 — 호출 · 받아쓰기 · 답 · 비상 중 무반응(음성비서 빠른 해결 설계 §2.4) ──────────────────
def _hangul(text):
    return re.sub(r"[^가-힣]", "", text or "")


def _norm(text):
    """글자 견주기용 — 공백·문장부호를 빼고(글자·숫자만) 영문은 대문자로."""
    return "".join(c for c in (text or "").upper() if c.isalnum())


def edit_distance(a, b):
    """글자 편집거리(넣기·빼기·바꾸기 각 1)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _says(S):
    """진행 도우미 말 띠 → [{t, d(say), t1 = said 시각, why = said 이유, next = 다음 say 시각}] (say 순).
    said 가 없으면(세션이 그 전에 끝남) t1 = 다음 say 시각 · why = None."""
    rows = S.get("says") or []
    said = {(d.get("run"), d.get("tok")): (t, d) for t, k, d in rows if k == "said"}
    says = [(t, d) for t, k, d in rows if k == "say"]
    out = []
    for n, (t, d) in enumerate(says):
        nxt = says[n + 1][0] if n + 1 < len(says) else float("inf")
        sd = said.get((d.get("run"), d.get("tok")))
        out.append({"t": t, "d": d, "t1": sd[0] if sd else nxt, "why": sd[1].get("why") if sd else None, "next": nxt})
    return out


def _wakes(S):
    """호출 시각 — wake 사건 · 비상 중 무시된 말 가운데 호출어가 든 것(emergency_ignored wake=true · 비상 중엔 wake 를 안 적는다)."""
    return [t for t, k, d in S["voice"] if k == "wake" or (k == "emergency_ignored" and d.get("wake"))]


def v_wake(S):
    """V5 호출 인식 — 진행 도우미 말 띠(say) 가운데 「넘어감」(질문 전에 다음 누름·판)이 아닌 것마다 창
    [say, said + WAKE_PAD_MS] 안에 호출(_wakes)이 있었나. calls = 전체 호출 · outside = 어느 말 띠 창(넘어감 포함)에도
    없는 호출(헛호출 후보) · skip = 넘어감 · open = said 없이 세션이 끝난 띠(시도 전에 멈춤 — 분모에서 뺀다).
    음성 기록이 없으면 off · 말 띠 기록이 없으면(진행 도우미 3판 전 · 시연) 호출 수만."""
    if not S["voice"]:
        return {"off": 1}
    wakes, says = _wakes(S), _says(S)
    if not says:
        return {"say": 0, "calls": len(wakes)}
    win = [(s["t"], s["t1"] + WAKE_PAD_MS) for s in says]
    out = {"say": 1, "n": 0, "k": 0, "skip": 0, "open": 0, "calls": len(wakes),
           "outside": sum(1 for w in wakes if not any(a <= w <= b for a, b in win))}
    for s, (a, b) in zip(says, win):
        if s["why"] in ("넘어감", None):
            out["skip" if s["why"] else "open"] += 1
            continue
        out["n"] += 1
        out["k"] += int(any(a <= w <= b for w in wakes))
    return out


def _chunks(V):
    """받아쓴 조각(한글이 든 stt — 발화 하나에 하나) → [[시각, 글, 호출 조각인가]]. 데몬은 받아쓴 뒤 판단을 적는다 — 다음 조각
    전에 wake(보통) 또는 emergency_ignored wake=true(비상 중)가 오면 그 stt 가 호출 조각.
    🔑 비상 중에도 stt 는 적힌다 — emergency_ignored 를 조각으로 또 넣으면 한 발화를 두 번 잇는다(실측 2026-10-12 세션 1)."""
    out = []
    for t, k, d in V:
        if k == "stt" and _hangul(d.get("text")):
            out.append([t, d.get("text") or "", False])
        elif out and (k == "wake" or (k == "emergency_ignored" and d.get("wake"))):
            out[-1][2] = True
    return out


def v_stt(S):
    """V6 받아쓰기 글자 오류율 — 질문까지 간 말 띠(said 이유 「질문」 · 비상 포함)마다 띠 문장(say.text) ↔ 받아쓴 질문.
    받아쓴 질문 = 창 [say, said] 의 마지막 호출 조각 뒤 한글 조각들을 이은 것 — 호출어와 한 조각이면 호출어를 뗀 나머지
    (voice_lib.strip_wake)부터. 둘 다 공백·부호를 빼고 견준다 · 오류율 = dist(편집거리 합) ÷ ref(참조 글자 수 합).
    noq = 호출어만 받아씀(질문 못 받음 — 오류율에서 뺀다) · nowake = 창에 호출 조각이 없음 · rows = [띠 문장, 받아쓴 질문, 거리]."""
    if not S["voice"]:
        return {"off": 1}
    says = _says(S)
    if not says:
        return {"say": 0}
    chunks = _chunks(S["voice"])
    out = {"say": 1, "n": 0, "dist": 0, "ref": 0, "noq": 0, "nowake": 0, "rows": []}
    for s in says:
        if s["why"] != "질문":
            continue
        mine = [c for c in chunks if s["t"] <= c[0] <= s["t1"]]
        w = max((i for i, c in enumerate(mine) if c[2]), default=None)
        if w is None:
            out["nowake"] += 1
            continue
        hyp = _norm(voice_lib.strip_wake(mine[w][1])) + "".join(_norm(c[1]) for c in mine[w + 1:])
        if not _hangul(hyp):
            out["noq"] += 1
            continue
        ref = _norm(s["d"].get("text"))
        dist = edit_distance(ref, hyp)
        out["n"] += 1
        out["dist"] += dist
        out["ref"] += len(ref)
        out["rows"].append([s["d"].get("text"), hyp, dist])
    return out


def _src_group(src):
    """답 출처 묶음 — 즉답(「즉답-<종류>」 · 설계 §2.1) · LLM · 그 밖(고정-… · 대체-… · 검산 버림)."""
    s = str(src or "")
    return "즉답" if s.startswith("즉답") else ("LLM" if s == "LLM" else "그 밖")


def core_words(expect):
    """대본 기대 칸 → 답에 있어야 할 핵심 낱말 묶음 [(낱말, …)](묶음 안 하나면 됨) — 괄호 안 · 「—」 뒤 조건은 뺀다(사람 판정 몫).
    버튼(B1~B4 · EMO) · N단계 · 공구 이름(measure_script.TOOLS) · 끝/완료(DONE_WORDS)."""
    x = re.sub(r"\([^)]*\)", "", (expect or "").split("—")[0])
    out = [(w,) for w in re.findall(r"B[1-4]|EMO", x)] + [(w,) for w in re.findall(r"\d+단계", x)]
    out += [(w,) for w in measure_script.TOOLS if w in x]
    if any(w in x for w in DONE_WORDS):
        out.append(DONE_WORDS)
    return out


def v_answer(S, script=None):
    """V7 답 지연 · 초벌 정확도 — 질문까지 간 말 띠(비상 아님 · said 이유 「질문」)마다 그 띠 뒤 다음 띠 전의 첫 답(answer).
    지연 = 그 답의 질문 받아쓰기(answer 직전 한글 stt — 데몬은 발화를 하나씩 처리한다 · stt 시각 = 발화 끝) → answer(보내기
    직전) · → 그 답의 재생 시작(play_start — 고정 답은 같은 키 · 문장 답은 키 없음 · ANSWER_PLAY_MS 안).
    초벌(판정 아님) = 대본(script — 판 맞춤 전 원래 판 번호)에서 같은 판 · 같은 문장 질문 줄의 기대 칸 핵심 낱말(core_words)이
    답 문장에 다 있으면 ok(맞음 후보) · 빠지면 bad(틀림 후보) · 핵심 낱말이 없거나 문장 없는 답 = human · 검산 버림 = drop.
    bad · human 은 review(사람 판정 목록). 묶음 = _src_group. 띠와 짝짓지 못한 답(같은 띠의 두 번째 답 · 띠 없는 세션) = extra."""
    if not S["voice"]:
        return {"off": 1}
    V = S["voice"]
    qt = [t for t, k, d in V if k == "stt" and _hangul(d.get("text"))]
    answers = [(t, d) for t, k, d in V if k == "answer"]
    plays = [(t, d) for t, k, d in V if k == "play_start"]

    def since_q(t):
        i = bisect.bisect_left(qt, t) - 1
        return round((t - qt[i]) / 1000, 3) if i >= 0 else None

    expect = {}
    for r in script or ():
        if r.get("행동") == "질문":
            expect.setdefault((int(r["판"]), r.get("대상")), r.get("기대") or "")
    says = _says(S)
    out = {"say": int(bool(says)), "n": 0, "noans": 0, "noplay": 0, "ans": {}, "play": {}, "extra": {}, "judge": {},
           "review": []}
    used = set()
    for s in says:
        if s["d"].get("emergency") or s["why"] != "질문":
            continue
        out["n"] += 1
        hit = next(((t, d) for t, d in answers if s["t"] < t < s["next"]), None)
        if hit is None:
            out["noans"] += 1
            continue
        used.add(hit[0])
        ta, da = hit
        g = _src_group(da.get("src"))
        dq = since_q(ta)
        if dq is not None:
            out["ans"].setdefault(g, []).append(dq)
        pl = next((x for x, d in plays if ta <= x <= ta + ANSWER_PLAY_MS and d.get("key") == da.get("key")), None)
        if pl is None or dq is None:
            out["noplay"] += 1
        else:
            out["play"].setdefault(g, []).append(round(dq + (pl - ta) / 1000, 3))
        exp = expect.get((s["d"].get("script"), s["d"].get("text")), "")
        words, text = core_words(exp), da.get("text")
        if da.get("src") == "고정-검산불일치":
            v = "drop"
        elif not words or not text:
            v = "human"
        else:
            got = re.sub(r"\s", "", text).upper()
            v = "ok" if all(any(w.upper() in got for w in grp) for grp in words) else "bad"
        out["judge"].setdefault(g, {"ok": 0, "bad": 0, "human": 0, "drop": 0})[v] += 1
        if v in ("bad", "human"):
            out["review"].append({"세션": S.get("name"), "판": s["d"].get("script"), "질문": s["d"].get("text"), "기대": exp,
                                  "답": text or da.get("key"), "src": da.get("src"),
                                  "판정": "틀림 후보" if v == "bad" else "사람 판정"})
    for t, d in answers:
        if t not in used and since_q(t) is not None:
            out["extra"].setdefault(_src_group(d.get("src")), []).append(since_q(t))
    return out


def v_emergency(S):
    """V8 비상 중 무반응 — 비상 구간 = EMO 로 든 차단(BLOCK 직전 누름이 EMO · EDGE_PAIR_MS 안) ~ 차단을 벗어난 다음 상태
    바뀜 + EMERGENCY_PAD_MS. n = 비상 중 호출(emergency_ignored wake=true)이 든 구간 · k = 그 가운데 호출(wake) · 답(answer)
    · 응답 소리(play_start — 안내 cue_ · 알림 alert_ 는 빼고 · 키 칸이 없는 옛 기록은 알림과 못 갈라 세지 않는다)가 없는 구간.
    spans = 비상 구간 수."""
    if not S["voice"]:
        return {"off": 1}
    presses = [(t, d) for t, k, d in S["events"] if k == "press"]
    states = [(t, d) for t, k, d in S["events"] if k == "state"]
    spans = []
    for n, (t, d) in enumerate(states):
        if d.get("new") != "BLOCK":
            continue
        prev = [p for p in presses if p[0] <= t]
        if not prev or prev[-1][1].get("button") != S["emo"] or t - prev[-1][0] > EDGE_PAIR_MS:
            continue
        spans.append((t, (states[n + 1][0] if n + 1 < len(states) else float("inf")) + EMERGENCY_PAD_MS))
    calls = [t for t, k, d in S["voice"] if k == "emergency_ignored" and d.get("wake")]
    resp = [t for t, k, d in S["voice"] if k in ("wake", "answer")
            or (k == "play_start" and "key" in d and not str(d.get("key") or "").startswith(("cue_", "alert_")))]
    out = {"spans": len(spans), "n": 0, "k": 0}
    for a, b in spans:
        if any(a <= c <= b for c in calls):
            out["n"] += 1
            out["k"] += int(not any(a <= r <= b for r in resp))
    return out


def v_input(S):
    """18 입력 누락(첫 판 = 표본만) — 완주한 정상 판마다 기대 누름(레시피 단계 수) ↔ 기록된 단계 버튼 gpio 누름."""
    runs = split_runs(S["events"])
    ids = normal_run_ids(S, runs)
    steps = set(S.get("steps") or ())
    out = {"runs": 0, "expect": 0, "got": 0}
    for r in runs:
        if r["i"] not in ids or r["end"] != "완주":
            continue
        out["runs"] += 1
        out["expect"] += len(S.get("steps") or ())
        out["got"] += sum(1 for _, k, d in r["ev"] if k == "press" and d.get("source") == "gpio" and d.get("button") in steps)
    return out


def count_all(S, below=None):
    """세션 하나의 값 전부 — 키 = 측정 설계 §2 번호(17ⓐ = 17a · reason = 경고 이유 — 번호 없음). below = NFR-1 FPS 목표(통합문서 §4.1).
    🔑 시스템 값은 판 맞춤 전 기록(S["full"] — 없으면 S)으로 · 대본을 따라 세는 값은 NG·대본 밖을 뺀 S 로(split_guide)."""
    F = S.get("full") or S
    return {"1": v_prevent(S), "4": v_lead(S), "16": v_normal(S), "3": v_precision(S), "25": v_effect(S),
            "5": v_zone(S), "23": v_graze(S), "28": v_gap(S), "21": v_confirm(S),
            "12": v_fps(F, below), "26": v_stages(F), "14": v_interlock(F), "30": v_res(F),
            "17a": v_wrong_tool(S), "17b": v_tool_time(S), "18": v_input(S),
            "V1": v_alert_delay(F), "V2": v_alert_count(S), "V3": v_alert_stop(F), "V4": v_alert_len(F),
            "V5": v_wake(S), "V6": v_stt(S), "V7": v_answer(S, F.get("script")), "V8": v_emergency(S),
            "V9": v_uplink(F), "31": v_cue(S), "reason": v_reason(S)}
