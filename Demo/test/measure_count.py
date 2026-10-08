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
