"""세기 — 측정 기록으로 값을 낸다(측정 도구 정합 1단계-나 · 순수 함수 · 파일을 읽지 않는다).

설계 = 상위 sop-project docs/superpowers/specs/2026-10-09-측정도구-정합-1단계-나-세기-design.md
    §3 공통 규칙 · §3-b 기준 · §4 값별 세는 법. 파일 읽기·대본·목표·표 = measure_report.py.

S(세션 하나) — measure_report.load_session 이 만든다:
    "kind" 세션 종류 · "info" session.json · "settings" session.json 「설정」
    "frames" [{frame, t(=t_recv_ms), seq, t_start, t_done, roi, level, decode_ms…zone_ms}] (t 순)
    "fsm"    [{t(=t_recv_ms), t_gui, roi, level, state, expected}] (t 순)
    "events" · "voice" [(t_ms, kind, data)] (t_ms 순) · "script" [{판, 행동, 대상, 기대, 메모}] 또는 None
    "emo" EMO 버튼 이름 · "rate" 마이크 표본률
🔴 판정을 다시 하지 않는다 — 시연 프로그램이 적은 상태·구역·시각을 센다(측정도구 스킬 「재구현하지 않는다」).
🔴 기준 값을 여기 따로 적지 않는다 — 시연·측정 쪽에서 읽는다(설계 §3-b). 아래 상수는 세기에만 있는 값이다.
"""
import bisect
import os
import sys

_TEST = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_TEST))      # Demo/ — fps
sys.path.insert(0, _TEST)                       # Demo/test/ — hoi_metrics

import fps            # noqa: E402 — FPS 창·끊김 = 시연 화면과 같은 상수
import hoi_metrics    # noqa: E402 — 사전 감지·선행시간·구간 판정 규칙 단일 출처

# ── 세기에만 있는 값(설계 §3-b 마지막 행) ──────────────────────────────────
EDGE_PAIR_MS = 500.0                    # 누름 ↔ 같은 버튼 GPIO 엣지 짝 — 화면 처리 시각 앞 0.5초 안(디바운스 0.05초보다 넉넉히)
CURVE_STEPS = tuple(round(0.10 + 0.05 * i, 2) for i in range(19))    # 체류 두 곡선 문턱 0.10~1.00초
ALERT_WAIT_MS = 3000.0                  # 알림·해제 뒤 재생 시작·멈춤을 기다리는 한도 — 넘으면 「없음」
ALERT_MATCH_MS = (-100.0, 1000.0)       # 경고·차단 전이 시각 대비 알림 「상태 공개 시각」 짝 범위(앞·뒤)
BYTES_PER_SAMPLE = 2                    # 마이크 업링크 = int16 · 1채널(voice_mic 형식)
GAP_MAX_SEC = 2.0                       # 28 — 이보다 긴 공백은 손을 떼고 돌아온 것(손 놓침 아님 · 갭메우기 0.3초의 몇 배)

RUN_STATES = ("PROCESS_RUN", "MONITOR", "WARNING")     # 판이 진행 중인 판정기 상태(fsm.State 이름)
ACTIONS = ("정상", "위반", "머묾", "틀린공구", "호출", "질문", "비상질문")   # 대본 행동(설계 §5)
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


def recording(S):
    return any(k == "recording_on" for _, k, _ in S["events"])


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
    진단(성공으로 세지 않는다) — 누르기 직전 프레임에 그 버튼 안쪽 상자였는데 경고가 없던 눌림을 둘로 가른다:
    late = 그 프레임을 판정기가 누름보다 늦게 처리(처리 늦음) · short = 먼저 처리했는데 경고 전(체류 미달)."""
    ft = [r["t"] for r in S["fsm"]]
    viol, k, late, short = violations(S), 0, 0, 0
    for p in viol:
        if p["state"] == "WARNING":
            k += 1
            continue
        i = bisect.bisect_right(ft, p["t_at"]) - 1
        if i >= 0 and S["fsm"][i]["roi"] == p["button"] and S["fsm"][i]["level"] == 2:
            if S["fsm"][i]["t_gui"] > p["t"]:
                late += 1
            else:
                short += 1
    return {"n": len(viol), "k": k, "late": late, "short": short}


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
    if recording(S):
        return {"excluded": 1}
    ts = sorted(r["t_gui"] for r in S["fsm"])
    keep, win, mins, stalls = [], [], [], []
    low_start, longest, low_n = None, 0.0, 0
    for a, b in zip(ts, ts[1:]):
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
    if recording(S):
        return {"excluded": 1}
    fr = S["frames"]
    out = {s: [f[s] for f in fr if f[s] is not None] for s in STAGES}
    out["total_ms"] = [round(f["decode_ms"] + f["t_done"] - f["t_start"], 3) for f in fr
                       if None not in (f["decode_ms"], f["t_done"], f["t_start"])]
    tr = [f["t"] for f in fr]
    td = [f["t_done"] for f in fr if f["t_done"] is not None]
    out["recv_iv"] = [round(b - a, 3) for a, b in zip(tr, tr[1:])]
    out["done_iv"] = [round(b - a, 3) for a, b in zip(td, td[1:])]
    seqs = [f["seq"] for f in fr if f["seq"] is not None]
    out["recv_n"] = (seqs[-1] - seqs[0] + 1) if seqs else 0
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


def v_res(S):
    """30 자원 — res 사건(첫 값은 의미 없다 · safety_console._pi_resources 머리말)."""
    rs = [d for _, k, d in S["events"] if k == "res"][1:]
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
def v_alert_delay(S):
    """V1 알림 지연 — alert 의 상태 공개 시각(t_pub_ms) → 다음 play_start(ALERT_WAIT_MS 안 · 초)."""
    plays = [t for t, k, _ in S["voice"] if k == "play_start"]
    out = {"delays": [], "missing": 0}
    for t, k, d in S["voice"]:
        if k != "alert" or d.get("t_pub_ms") is None:
            continue
        nxt = next((p for p in plays if p >= t), None)
        if nxt is None or nxt - t > ALERT_WAIT_MS:
            out["missing"] += 1
        else:
            out["delays"].append(round((nxt - d["t_pub_ms"]) / 1000, 3))
    return out


def v_alert_count(S):
    """V2 알림 정확도 — 경고·차단 전이마다 그 시각 근처(ALERT_MATCH_MS) 알림 수 · 정상 판 안의 알림(헛알림)."""
    if not S["voice"]:
        return {"off": 1}
    pubs = [d["t_pub_ms"] for _, k, d in S["voice"] if k == "alert" and d.get("t_pub_ms") is not None]
    lo, hi = ALERT_MATCH_MS
    out = {"trans": 0, "one": 0, "zero": 0, "multi": 0, "normal": 0}
    for t, k, d in S["events"]:
        if k == "state" and d.get("new") in ("WARNING", "BLOCK"):
            c = sum(1 for a in pubs if lo <= a - t <= hi)
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
    """V3 알림 끊기 — 재생 중에 해제(release ok)되면 → 다음 stop_sent(초). 재생 중이 아니었으면 세지 않는다."""
    starts = [t for t, k, _ in S["voice"] if k == "play_start"]
    ends = [t for t, k, _ in S["voice"] if k == "play_end"]
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
    """V4 알림 길이 — 알림 뒤 ALERT_WAIT_MS 안 첫 play_start → 그 뒤 첫 play_end(초). 「중단」으로 끝난 재생은 길이가 아니라 cut."""
    out = {"lens": [], "cut": 0}
    for t, k, _ in S["voice"]:
        if k != "alert":
            continue
        ps = next((x for x, kk, _ in S["voice"] if kk == "play_start" and x >= t), None)
        if ps is None or ps - t > ALERT_WAIT_MS:
            continue
        pe = next(((x, dd) for x, kk, dd in S["voice"] if kk == "play_end" and x >= ps), None)
        if pe is None:
            continue
        if pe[1].get("what") == "중단":
            out["cut"] += 1
        else:
            out["lens"].append(round((pe[0] - ps) / 1000, 3))
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
    """세션 하나의 값 전부 — 키 = 측정 설계 §2 번호(17ⓐ = 17a). below = NFR-1 FPS 목표(통합문서 §4.1)."""
    return {"1": v_prevent(S), "4": v_lead(S), "16": v_normal(S), "3": v_precision(S), "25": v_effect(S),
            "5": v_zone(S), "23": v_graze(S), "28": v_gap(S), "21": v_confirm(S),
            "12": v_fps(S, below), "26": v_stages(S), "14": v_interlock(S), "30": v_res(S),
            "17a": v_wrong_tool(S), "17b": v_tool_time(S), "18": v_input(S),
            "V1": v_alert_delay(S), "V2": v_alert_count(S), "V3": v_alert_stop(S), "V4": v_alert_len(S),
            "V9": v_uplink(S)}
