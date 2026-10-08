"""세기 값 함수(측정 도구 정합 1단계-나 · 관문 ⑤) — 손으로 만든 작은 기록으로.

실행: python3 Demo/selftest/test_measure_count.py
설계 = 상위 docs/superpowers/specs/2026-10-09-측정도구-정합-1단계-나-세기-design.md
"""
import inspect
import os
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import fps
import measure_count as MC

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_fps_criteria_shared():
    print("\n[기준] FPS 창·끊김 = fps.py 상수 하나를 시연 화면과 세기가 같이 쓴다")
    check(getattr(fps, "FPS_WINDOW", None) == 60, "fps.FPS_WINDOW = 60(시연 화면이 쓰던 값 그대로)")
    check(getattr(fps, "STALE_SEC", None) == 2.0, "fps.STALE_SEC = 2.0")
    check(inspect.signature(fps.fps_stale).parameters["stale_after"].default == getattr(fps, "STALE_SEC", None),
          "fps_stale 기본값 = STALE_SEC")
    src = open(os.path.join(_DEMO, "safety_console.py"), encoding="utf-8").read()
    check("len(self._fps_intervals) > FPS_WINDOW" in src, "safety_console 이 FPS_WINDOW 로 창을 자른다")
    check("len(self._fps_intervals) > 60" not in src, "숫자 60 이 남아 있지 않다")


def E(t, k, **d):
    return (float(t), k, d)


def S_(events=(), frames=(), fsm=(), voice=(), script=None, kind="위반", settings=None, voice_on=True):
    return {"name": "t", "kind": kind, "info": {"음성": voice_on, "측정기록": True},
            "settings": settings or {"FSM_GAP_FILL_SEC": 0.3, "PRESS_CONFIRM_GRACE_SEC": 0.5},
            "frames": list(frames), "fsm": list(fsm),
            "events": sorted(events, key=lambda e: e[0]), "voice": sorted(voice, key=lambda e: e[0]),
            "script": script, "emo": "EMO", "rate": 16000}


def FR(frame, t, roi=None, level=None, **kw):
    row = {"frame": frame, "t": float(t), "seq": kw.get("seq", frame), "t_start": kw.get("t_start"),
           "t_done": kw.get("t_done"), "roi": roi, "level": level}
    for s in MC.STAGES:
        row[s] = kw.get(s)
    return row


def FS(t, roi=None, level=None, t_gui=None, state="PROCESS_RUN", expected="B1"):
    return {"t": float(t), "t_gui": float(t + 30 if t_gui is None else t_gui), "roi": roi, "level": level,
            "state": state, "expected": expected}


def P(t, button, expected="B2", state="PROCESS_RUN", source="gpio"):
    return E(t, "press", button=button, source=source, expected=expected, state=state)


def SCR(*rows):
    return [{"판": p, "행동": a, "대상": b, "기대": "", "메모": ""} for p, a, b in rows]


def test_split_runs():
    print("\n[판] 시작 ~ 완주·초기화 · 닫히지 않은 판 = 미완 · 판 밖 사건은 버린다")
    ev = [E(100, "run_start"), E(110, "state", new="WARNING"), E(500, "run_end", ok=True), E(600, "state", new="X"),
          E(700, "run_start"), E(900, "run_reset", why="작업 초기화"), E(1000, "run_start"), E(1100, "press", button="B1")]
    r = MC.split_runs(sorted(ev))
    check([x["end"] for x in r] == ["완주", "초기화", "미완"], f"끝 = {[x['end'] for x in r]}")
    check([x["i"] for x in r] == [1, 2, 3] and r[0]["ok"] is True and r[2]["t1"] is None, "번호 1·2·3 · 완주 ok · 미완 t1 없음")
    check([k for _, k, _ in r[0]["ev"]] == ["state"] and [k for _, k, _ in r[2]["ev"]] == ["press"], "판 안 사건만")


def test_pair_presses():
    print("\n[누름] 같은 버튼 엣지(0.5초 안)와 짝 · 없으면 콜백 · 키보드는 키보드")
    ev = [E(1000, "gpio_edge", button="B3", src="edge"), P(1040, "B3"), P(2000, "B1"),
          P(3000, "B2", source="keyboard"), E(3500, "gpio_edge", button="B4", src="edge"), P(4100, "B4")]
    ps = MC.pair_presses(sorted(ev))
    check([(p["t_at"], p["how"]) for p in ps] == [(1000.0, "엣지"), (2000.0, "콜백"), (3000.0, "키보드"), (4100.0, "콜백")],
          f"{[(p['t_at'], p['how']) for p in ps]}")


def test_violations():
    print("\n[위반] gpio · 기대와 다름 · EMO 아님 · 판 안 · 차단 중 아님")
    ev = [E(0, "run_start"), P(100, "B1", expected="B1"), P(200, "B3"), P(300, "B4", state="BLOCK"),
          P(400, "EMO"), P(500, "B3", source="keyboard"), E(600, "run_end", ok=False), P(700, "B3")]
    v = MC.violations(S_(ev))
    check([p["t"] for p in v] == [200.0], f"위반 = {[p['t'] for p in v]}")


def test_prevent_and_lead():
    print("\n[1·4] 누를 때 상태가 WARNING 인 비율 · 처리 늦음 후보 · 경고 선행시간")
    ev = [E(0, "run_start"), E(900, "state", new="WARNING"), E(980, "gpio_edge", button="B3", src="edge"),
          P(1000, "B3", state="WARNING"), E(1990, "gpio_edge", button="B3", src="edge"), P(2000, "B3"), P(3000, "B4")]
    fsm = [FS(1980, roi="B3", level=2), FS(2950, roi=None)]
    S = S_(ev, fsm=fsm)
    check(MC.v_prevent(S) == {"n": 3, "k": 1, "late": 1}, f"1 = {MC.v_prevent(S)}")
    check(MC.v_lead(S) == {"leads": [0.08]}, f"4 = {MC.v_lead(S)}")


def test_normal():
    print("\n[2·16] 정상 판 = 완주 + ok + 경고·차단 0 · 대본이 있으면 대본의 정상 판만")
    ev = [E(0, "run_start"), E(100, "run_end", ok=True), E(200, "run_start"), E(250, "state", new="WARNING"),
          E(300, "run_end", ok=True), E(400, "run_start"), E(500, "run_reset", why="작업 초기화")]
    check(MC.v_normal(S_(ev, kind="정상")) == {"n": 3, "k": 1, "alarms": [0, 1, 0]}, f"{MC.v_normal(S_(ev, kind='정상'))}")
    s2 = S_(ev, kind="위반", script=SCR((2, "정상", "")))
    check(MC.v_normal(s2) == {"n": 1, "k": 0, "alarms": [1]}, f"대본 = {MC.v_normal(s2)}")
    check(MC.v_normal(S_(ev, kind="위반")) == {"n": 0, "k": 0, "alarms": []}, "위반 세션·대본 없음 = 정상 판 없음")


def test_effect():
    print("\n[25] 경고 뒤 그 판 다음 누름이 기대 버튼인 비율")
    ev = [E(0, "run_start"), E(100, "state", new="WARNING", expected="B2"), P(200, "B2", state="WARNING"),
          E(300, "state", new="WARNING", expected="B3"), P(400, "B4", expected="B3", state="WARNING"),
          E(500, "state", new="WARNING", expected="B4"), E(600, "run_end", ok=False)]
    check(MC.v_effect(S_(ev)) == {"n": 2, "k": 1, "none": 1}, f"{MC.v_effect(S_(ev))}")


def test_precision():
    print("\n[3] 경고마다 그 판 대본 시도(위반·머묾)의 같은 버튼과 짝 — 남는 경고 = 헛경고")
    ev = [E(0, "run_start"), E(100, "state", new="WARNING", dwell_roi="B3"), E(200, "state", new="WARNING", dwell_roi="B4"),
          E(300, "state", new="WARNING", dwell_roi="B3"), E(400, "run_end", ok=False),
          E(500, "run_start"), E(600, "state", new="WARNING", dwell_roi="B1"), E(700, "run_end", ok=True)]
    s = S_(ev, script=SCR((1, "위반", "B3"), (1, "머묾", "B4")))
    check(MC.v_precision(s) == {"script": 1, "n": 3, "k": 2}, f"{MC.v_precision(s)}")
    check(MC.v_precision(S_(ev)) == {"script": 0}, "대본 없음")


def test_merge():
    print("\n[합치기] 수는 더하고 목록은 잇고 딕셔너리는 안으로")
    m = MC.merge([{"n": 1, "l": [1], "d": {"a": 1}}, {"n": 2, "l": [2], "d": {"a": 2, "b": 1}}])
    check(m == {"n": 3, "l": [1, 2], "d": {"a": 3, "b": 1}}, f"{m}")


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 세기 값 함수 검증 통과")
