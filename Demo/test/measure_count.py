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

RUN_STATES = ("PROCESS_RUN", "MONITOR", "WARNING")     # 판이 진행 중인 판정기 상태(fsm.State 이름)
ACTIONS = ("정상", "위반", "머묾", "틀린공구", "호출", "질문", "비상질문")   # 대본 행동(설계 §5)
STAGES = ("decode_ms", "orient_ms", "detect_ms", "track_ms", "hand_ms", "tool_ms", "zone_ms")


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
    """누름마다 실제로 누른 시각 — 같은 버튼 GPIO 엣지(src=edge · 처리 시각 앞 EDGE_PAIR_MS 안) · 없으면 처리 시각."""
    edges = [(t, d) for t, k, d in events if k == "gpio_edge" and d.get("src") == "edge"]
    used, out = set(), []
    for t, k, d in events:
        if k != "press":
            continue
        b = d.get("button")
        cand = [i for i, (te, de) in enumerate(edges)
                if i not in used and de.get("button") == b and 0 <= t - te <= EDGE_PAIR_MS]
        if cand:
            used.add(cand[-1])
            t_at, how = edges[cand[-1]][0], "엣지"
        else:
            t_at, how = t, ("키보드" if d.get("source") == "keyboard" else "콜백")
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
    """1 위반 사전 차단율 — 누를 때 판정기 상태 = WARNING. 진단 = 아니었지만 누르기 직전 프레임에 그 버튼 안쪽 상자."""
    ft = [r["t"] for r in S["fsm"]]
    viol, k, late = violations(S), 0, 0
    for p in viol:
        if p["state"] == "WARNING":
            k += 1
            continue
        i = bisect.bisect_right(ft, p["t_at"]) - 1
        if i >= 0 and S["fsm"][i]["roi"] == p["button"] and S["fsm"][i]["level"] == 2:
            late += 1
    return {"n": len(viol), "k": k, "late": late}


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
    """16 정상 완주율 · 2 헛경고 — 정상 판이 완주 + ok + 경고·차단 0 이면 성공."""
    runs = split_runs(S["events"])
    ids = normal_run_ids(S, runs)
    n = k = 0
    alarms = []
    for r in runs:
        if r["i"] not in ids:
            continue
        a = sum(1 for _, kk, d in r["ev"] if kk == "state" and d.get("new") in ("WARNING", "BLOCK"))
        n += 1
        alarms.append(a)
        if r["end"] == "완주" and r["ok"] and a == 0:
            k += 1
    return {"n": n, "k": k, "alarms": alarms}


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
    """5 사전 감지율 · 7 ROI 오분류 · 창 능력 상한 — hoi_metrics.analyze_presses 그대로(EMO 빼고 · 판 안 gpio 누름)."""
    F, T, raw, filled = series(S)
    runs = split_runs(S["events"])
    ps = [p for p in pair_presses(S["events"])
          if p["source"] == "gpio" and p["button"] != S["emo"] and run_of(runs, p["t"]) is not None]
    presses = [(p["t_at"] / 1000, p["button"], _frame_at(F, T, p["t_at"] / 1000)) for p in ps]
    rows = hoi_metrics.analyze_presses(presses, filled, F, T, None, raw_series=raw)
    return {"n": len(rows),
            "k5": sum(1 for r in rows if r[4] == "OK" and r[2] is not None and r[2] > 0),
            "k7": sum(1 for r in rows if r[4] == "ROI 불일치"),
            "kwin": sum(1 for r in rows if r[5]),
            "leads": [round(r[2], 3) for r in rows if r[4] == "OK" and r[2] is not None]}


def v_graze(S):
    """23 스침 통과율 · 체류 두 곡선 재료 — fsm 구역 구간(EMO 빼고). 그 버튼 누름이 구간 안(끝 + 갭메우기)이면 누름 구간."""
    F, T, _raw, filled = series(S)
    tmap = dict(zip(F, T))
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
        warned = any(w.get("dwell_roi") == roi and w.get("frame_t_ms") is not None
                     and t0 <= w["frame_t_ms"] / 1000 <= t1 for w in warns)
        pass_dur.append(round(dur, 3))
        passes.append((t0, t1, roi, warned))
    out = {"pass_n": len(passes), "pass_k": sum(1 for x in passes if not x[3]),
           "press_dwell": press_dwell, "pass_dur": pass_dur, "stay_n": 0, "stay_warned": 0}
    if S["script"] is not None:
        for r in split_runs(S["events"]):
            t_end = r["t1"] if r["t1"] is not None else float("inf")
            cand = [x for x in passes if r["t0"] / 1000 <= x[0] <= t_end / 1000]
            for row in S["script"]:
                if int(row["판"]) != r["i"] or row["행동"] != "머묾":
                    continue
                m = next((x for x in cand if x[2] == row["대상"]), None)
                if m is None:
                    continue
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
    """28 손 놓침 공백 — 갭메우기 앞 구역(frames.roi)에서 같은 버튼 구간 사이 빈 구간 길이(초)."""
    F, T, raw, _filled = series(S)
    tmap = dict(zip(F, T))
    segs = hoi_metrics.segments(raw, F, T)
    return {"gaps": [round(tmap[b[1]] - tmap[a[2]], 3) for a, b in zip(segs, segs[1:]) if a[0] == b[0]]}


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
