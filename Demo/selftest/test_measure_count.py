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


def S_(events=(), frames=(), fsm=(), voice=(), script=None, kind="위반", settings=None, voice_on=True, rate=16000):
    return {"name": "t", "kind": kind, "info": {"음성": voice_on, "측정기록": True}, "steps": ["B1", "B2", "B3", "B4"],
            "settings": settings or {"FSM_GAP_FILL_SEC": 0.3, "PRESS_CONFIRM_GRACE_SEC": 0.5},
            "frames": list(frames), "fsm": list(fsm),
            "events": sorted(events, key=lambda e: e[0]), "voice": sorted(voice, key=lambda e: e[0]),
            "script": script, "emo": "EMO", "rate": rate}


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
    print("\n[누름] 같은 버튼 엣지(0.5초 안)와 들어온 순서대로 짝 · 콜백 엣지 = 콜백 · 엣지 없음 = 처리 · 키보드")
    ev = [E(1000, "gpio_edge", button="B3", src="edge"), P(1040, "B3"), P(2000, "B1"),
          P(3000, "B2", source="keyboard"), E(3500, "gpio_edge", button="B4", src="edge"), P(4100, "B4"),
          E(4990, "gpio_edge", button="B1", src="callback"), P(5000, "B1"),
          E(6000, "gpio_edge", button="B2", src="edge"), E(6050, "gpio_edge", button="B2", src="edge"),
          P(6200, "B2"), P(6210, "B2")]
    ps = MC.pair_presses(sorted(ev))
    check([(p["t_at"], p["how"]) for p in ps] == [(1000.0, "엣지"), (2000.0, "처리"), (3000.0, "키보드"), (4100.0, "처리"),
                                                  (4990.0, "콜백"), (6000.0, "엣지"), (6050.0, "엣지")],
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
          P(1000, "B3", state="WARNING"), E(1990, "gpio_edge", button="B3", src="edge"), P(2000, "B3"), P(3000, "B4"),
          P(4000, "B4")]
    fsm = [FS(1980, roi="B3", level=2), FS(2950, roi=None), FS(3950, roi="B4", level=2, t_gui=3960)]
    S = S_(ev, fsm=fsm)
    check(MC.v_prevent(S) == {"n": 4, "k": 1, "late": 1, "short": 1},
          f"1 = {MC.v_prevent(S)} — 처리 늦음 = 그 프레임을 누름보다 늦게 처리 · 체류 미달 = 먼저 처리했는데 경고 없음")
    check(MC.v_lead(S) == {"leads": [0.08]}, f"4 = {MC.v_lead(S)}")


def test_normal():
    print("\n[2·16] 정상 판 = 완주 + ok + 경고·차단 0 · 대본이 있으면 대본의 정상 판만")
    ev = [E(0, "run_start"), E(100, "run_end", ok=True), E(200, "run_start"), E(250, "state", new="WARNING"),
          E(300, "run_end", ok=True), E(400, "run_start"), E(500, "run_reset", why="작업 초기화"),
          E(600, "run_start"), E(650, "run_end", ok=False), E(700, "run_start")]
    z = {"f_alarm": 0, "f_reset": 0, "f_viol": 0, "open": 0}
    v = MC.v_normal(S_(ev, kind="정상"))
    check(v == {"n": 4, "k": 1, "alarms": [0, 1, 0, 0], "f_alarm": 1, "f_reset": 1, "f_viol": 1, "open": 1},
          f"{v} — 세션 끝에 열린 판은 세지 않는다")
    s2 = S_(ev, kind="위반", script=SCR((2, "정상", "")))
    check(MC.v_normal(s2) == {"n": 1, "k": 0, "alarms": [1], **z, "f_alarm": 1}, f"대본 = {MC.v_normal(s2)}")
    check(MC.v_normal(S_(ev, kind="위반")) == {"n": 0, "k": 0, "alarms": [], **z}, "위반 세션·대본 없음 = 정상 판 없음")


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


def test_zone():
    print("\n[5·7] analyze_presses — 갭메우기 뒤(fsm) 구역 · 앞(frames) = 창 · 누른 시각 = 엣지")
    fr = [FR(i + 1, 1000 + 100 * i, roi=r) for i, r in enumerate([None, "B2", "B2", None, "B2", "B2"])]
    fs = [FS(1000 + 100 * i, roi=r) for i, r in enumerate([None, "B2", "B2", "B2", "B2", "B2"])]
    ev = [E(900, "run_start"), E(1450, "gpio_edge", button="B2", src="edge"), P(1460, "B2"), P(1250, "B4"),
          P(1300, "EMO")]
    z = MC.v_zone(S_(ev, frames=fr, fsm=fs))
    check((z["n"], z["k5"], z["k7"], z["kwin"], z["leads"]) == (2, 1, 1, 1, [0.35]), f"{z}")


def test_graze():
    print("\n[23] 지나감 구간(눌리지 않음 · EMO 빼고) 가운데 경고 없이 끝난 비율 · 누름 구간 체류 · 대본 머묾")
    rois = ["B3", "B3", None, None, "B2", "B2", "B2", None, "EMO", "EMO"]
    fr = [FR(i + 1, 1000 + 100 * i, roi=r) for i, r in enumerate(rois)]
    fs = [FS(1000 + 100 * i, roi=r) for i, r in enumerate(rois)]
    ev = [E(900, "run_start"), E(1150, "state", new="WARNING", dwell_roi="B3", frame_t_ms=1100.0),
          P(1650, "B2"), E(2000, "run_end", ok=False)]
    g = MC.v_graze(S_(ev, frames=fr, fsm=fs))
    check((g["pass_n"], g["pass_k"], g["press_dwell"], g["pass_dur"]) == (1, 0, [0.25], [0.1]), f"{g}")
    g2 = MC.v_graze(S_(ev, frames=fr, fsm=fs, script=SCR((1, "머묾", "B3"))))
    check((g2["stay_n"], g2["stay_warned"]) == (1, 1), f"머묾 = {(g2['stay_n'], g2['stay_warned'])}")


def test_curve():
    print("\n[23-곡선] 문턱 t 에서 잡음 = 체류 > t 비율 · 거름 = 길이 < t 비율 · 참고 범위")
    cv = MC.curve([0.2, 0.4, 0.6, 0.8], [0.05, 0.1, 0.15, 0.5])
    check(len(cv) == 19 and cv[0][0] == 0.1 and cv[-1][0] == 1.0, "문턱 0.10~1.00 · 19개")
    row = {t: (a, b) for t, a, b in cv}
    check(row[0.15] == (1.0, 0.5) and row[0.2] == (0.75, 0.75) and row[0.4] == (0.5, 0.75), f"{row[0.15]} {row[0.2]} {row[0.4]}")
    check(MC.fit_range(cv, 0.75, 0.75) == (0.2, 0.35), f"범위 = {MC.fit_range(cv, 0.75, 0.75)}")
    check(MC.curve([], [])[0][1:] == (None, None), "표본 없으면 None")


def test_gap():
    print("\n[28] 갭메우기 앞 구역에서 같은 버튼 구간 사이 빈 구간 길이")
    rois = ["B1", "B1", None, None, "B1", "B2", None, "B2"]
    fr = [FR(i + 1, 1000 + 100 * i, roi=r) for i, r in enumerate(rois)]
    g = MC.v_gap(S_(frames=fr))
    check([round(x, 3) for x in g["gaps"]] == [0.3, 0.2] and g["le_fill"] == 2 and g["long"] == 0, f"{g}")
    fr2 = fr + [FR(9, 1800, roi=None)] + [FR(10 + i, 4800 + 100 * i, roi="B2") for i in range(2)]   # 빈 프레임 뒤 3.1초 만에 돌아옴
    g2 = MC.v_gap(S_(frames=fr2))
    check(g2["long"] == 1 and len(g2["gaps"]) == 2, f"3초 넘게 떠났다 돌아온 공백은 놓침에서 뺀다 = {g2}")


def test_confirm():
    print("\n[21] 확인 비율 · 누르기 전 · 경로 · 가짜 미확인(미확인인데 여유 안 프레임에 그 버튼)")
    ev = [P(1000, "B2"), E(3500, "confirm", button="B2", order=2, verdict=False, before_ms=None, why="프레임"),
          P(4000, "B1", expected="B1"), E(5000, "confirm", button="B1", order=1, verdict=True, before_ms=120.0, why="프레임")]
    fr = [FR(1, 1200, roi="B2")]
    c = MC.v_confirm(S_(ev, frames=fr))
    check(c == {"n": 2, "k": 1, "before": [120.0], "why": {"프레임": 2}, "fake": 1}, f"{c}")


def test_fps():
    print("\n[12·13] 화면이 받은 간격(2초 이상 = 끊김 · 뺀다) · 최근 60간격 FPS 최저 · 15 미만 최장")
    ts = [50 * i for i in range(70)] + [69 * 50 + 3000 + 100 * i for i in range(70)]
    fs = [FS(t, t_gui=t) for t in ts]
    ev = [E(10, "fps", fps=12.5)]
    f = MC.v_fps(S_(ev, fsm=fs), below=15.0)
    check(len(f["iv"]) == 138 and abs(fps.fps_from_intervals(f["iv"]) - 1 / 0.075) < 1e-6, "간격 138개 · 중앙값 FPS")
    check(f["roll_min"] == [10.0] and f["low_longest"] == [0.9] and f["fps_ev"] == [12.5], f"{f['roll_min']} {f['low_longest']}")
    check(f["stalls"] == [3.0] and f["low_n"] == 1, f"끊김(2초 이상) = {f['stalls']} · 목표 미만 진입 = {f['low_n']}")



def test_recording_split():
    print("\n[녹화 구간] 켬~끔 구간만 모든 기록에서 빼고(판째) 따로 모은다 · 구간을 넘는 간격은 끊김이 아니다(측정 녹화 설계 R5)")
    fs = [FS(t, t_gui=t) for t in range(0, 10001, 100)]
    fr = [FR(i + 1, t, seq=(2 * i if t < 3000 or t > 6000 else 2 * i + 3), t_start=t, t_done=t + 50, decode_ms=10.0)
          for i, t in enumerate(range(0, 10001, 100))]
    ev = [E(100, "run_start"), E(2500, "run_end", ok=True), E(1000, "res", cpu_avg=1.0), E(2000, "res", cpu_avg=40.0),
          E(2990, "recording_on", mode="raw"), E(3100, "run_start"), E(4000, "res", cpu_avg=80.0), E(5900, "run_end", ok=True),
          E(6010, "recording_off", mode="raw", written=29, dropped=0), E(6100, "run_start"), E(7000, "res", cpu_avg=42.0)]
    S = S_(ev, frames=fr, fsm=fs)
    M, R = MC.split_recording(S)
    check(M["rec_spans"] == [(2990.0, 6010.0, "raw")] and R is not None, f"구간 {M['rec_spans']}")
    check(not any(2990 <= t <= 6010 for t, _, _ in M["events"]) and not any(2990 <= f["t"] <= 6010 for f in M["frames"]),
          "나머지에는 구간 안 기록이 없다(녹화한 판 통째로)")
    check([k for _, k, _ in M["events"]].count("run_start") == 2, "녹화한 판의 run_start 도 빠진다")
    check(all(2990 <= f["t"] <= 6010 for f in R["frames"]) and len(R["frames"]) == 31, f"녹화 쪽 프레임 {len(R['frames'])}(3000~6000ms · 100ms 간격)")
    f = MC.v_fps(M, below=15.0)
    check(f["stalls"] == [] and all(abs(x - 0.1) < 1e-9 for x in f["iv"]), f"구간을 넘는 간격은 끊김이 아니다 · 끊김 {f['stalls']}")
    st = MC.v_stages(M)
    check(st["proc_n"] == len(M["frames"]) and max(st["recv_iv"]) <= 100.0, f"받은 간격도 구간을 넘지 않는다 · {max(st['recv_iv'])}")
    check(MC.v_res(R)["cpu_avg"] == [80.0], f"녹화 쪽 자원 = 구간 안 res 만 {MC.v_res(R)}")

    S2 = S_(ev[:5] + [E(3100, "run_start")], frames=fr, fsm=fs)        # 끔 사건 없음 — 세션 끝까지
    M2, R2 = MC.split_recording(S2)
    check(M2["rec_spans"][0][1] == float("inf") and not any(f["t"] >= 2990 for f in M2["frames"]), "끔 없으면 끝까지 뺀다")

    M3, R3 = MC.split_recording(S_(ev[:4], frames=fr, fsm=fs))
    check(R3 is None and M3["rec_spans"] == [] and len(M3["frames"]) == len(fr), "구간 없으면 그대로")


def test_stages():
    print("\n[26·27] 단계별 ms · 한 프레임 = decode + (done − start) · 받은 수 = recv_seq 증가")
    fr = [FR(i + 1, 1000 + 100 * i, seq=s, t_start=1010 + 100 * i, t_done=1060 + 100 * i, decode_ms=5.0, detect_ms=20.0)
          for i, s in enumerate([1, 3, 4])]
    st = MC.v_stages(S_(frames=fr))
    check(st["total_ms"] == [55.0, 55.0, 55.0] and st["detect_ms"] == [20.0] * 3 and st["orient_ms"] == [], "단계 시간")
    check(st["recv_iv"] == [100.0, 100.0] and (st["recv_n"], st["proc_n"]) == (4, 3), f"{st['recv_iv']} {st['recv_n']} {st['proc_n']}")


def test_interlock():
    print("\n[14] 경고·차단 전이 → 보낸 시각 → ACK · 정상 복귀 명령은 세지 않는다 · ACK 실패")
    ev = [E(1000, "interlock_req", what="feedback", value="WARNING"),
          E(1003, "interlock", cmd="WARN", t_send_ms=1003.0, t_ack_ms=1030.0, ack=True), E(1005, "state", new="WARNING"),
          E(2000, "interlock_req", what="engage", value=True), E(2001, "interlock_req", what="feedback", value="BLOCK"),
          E(2002, "interlock", cmd="BLOCK", t_send_ms=2002.0, t_ack_ms=2040.0, ack=True), E(2004, "state", new="BLOCK"),
          E(3000, "interlock_req", what="feedback", value="NONE"), E(3001, "interlock_req", what="engage", value=False),
          E(3002, "interlock", cmd="RUN", t_send_ms=3002.0, t_ack_ms=3010.0, ack=True), E(3004, "state", new="PROCESS_RUN"),
          E(4000, "interlock_req", what="feedback", value="WARNING"),
          E(4001, "interlock", cmd="WARN", t_send_ms=4001.0, t_ack_ms=None, ack=False, tries=0), E(4003, "state", new="WARNING"),
          E(5000, "interlock_req", what="engage", value=True), E(5001, "interlock_req", what="feedback", value="BLOCK"),
          E(5002, "interlock", cmd="BLOCK", t_send_ms=5002.0, t_ack_ms=5500.0, ack=False, tries=3), E(5003, "state", new="BLOCK"),
          E(6000, "interlock", cmd="WARN", t_send_ms=6000.0, t_ack_ms=6010.0, ack=True)]
    i = MC.v_interlock(S_(ev))
    check(i == {"n": 4, "noreq": 1, "unsent": 1, "timeout": 1, "total": [30.0, 40.0], "send": [3.0, 2.0], "ack": [27.0, 38.0]},
          f"{i} — 판정기는 명령 요청을 먼저 하고 상태 사건을 맨 끝에 적는다(fsm._goto)")


def test_res():
    print("\n[30] 자원 — 첫 값은 버린다")
    ev = [E(0, "res", cpu_avg=99.0, cpu_max=99.0, temp=99.0), E(10, "res", cpu_avg=30.0, cpu_max=50.0, temp=60.0),
          E(20, "res", cpu_avg=40.0, cpu_max=70.0, temp=None)]
    check(MC.v_res(S_(ev)) == {"cpu_avg": [30.0, 40.0], "cpu_max": [50.0, 70.0], "temp": [60.0]}, f"{MC.v_res(S_(ev))}")


def test_tools():
    print("\n[17ⓐⓑ] 대본 틀린공구 판에서 공구 단계 통과 = 실패 · 단계 시작 → 맞는 공구 첫 쥠")
    ev = [E(0, "run_start"), E(100, "sub", what="start", button="B2"), E(200, "tool_scan", tool=None, want="렌치"),
          E(300, "wrong_tool", want="렌치", got="드라이버"), E(900, "sub", what="finish", button="B2"),
          E(950, "run_end", ok=True),
          E(1000, "run_start"), E(1100, "sub", what="start", button="B2"), E(1200, "tool_scan", tool=None, want="렌치"),
          E(1300, "wrong_tool", want="렌치", got="드라이버"), E(2000, "run_reset", why="작업 초기화"),
          E(3000, "run_start"), E(3100, "sub", what="start", button="B2"), E(3200, "tool_scan", tool=None, want="렌치"),
          E(3600, "tool_scan", tool="렌치", want="렌치"), E(3700, "sub", what="finish", button="B2"), E(4000, "run_end", ok=True),
          E(5000, "run_start"), E(5100, "run_reset", why="작업 초기화")]
    s = S_(ev, script=SCR((1, "틀린공구", "드라이버"), (2, "틀린공구", "드라이버"), (4, "틀린공구", "드라이버")))
    check(MC.v_wrong_tool(s) == {"script": 1, "n": 2, "k": 1, "det": 2, "skip": 1}, f"{MC.v_wrong_tool(s)}")
    check(MC.v_wrong_tool(S_(ev)) == {"script": 0}, "대본 없음")
    check(MC.v_tool_time(S_(ev)) == {"times": [0.5]}, f"{MC.v_tool_time(S_(ev))}")


def test_voice():
    print("\n[V1~V4] 알림 지연 · 전이마다 알림 수 · 해제 → 멈춤 · 알림 길이")
    voice = [E(1000, "alert", key="경고", t_pub_ms=990.0), E(1200, "play_start"), E(2700, "play_end", what="완료"),
             E(5000, "alert", key="경고", t_pub_ms=4990.0), E(9000, "play_start"), E(9200, "stop_sent"),
             E(9300, "play_end", what="중단")]
    ev = [E(985, "state", new="WARNING"), E(4985, "state", new="BLOCK"), E(7000, "state", new="WARNING"),
          E(9150, "release", what="warning", ok=True), E(9500, "release", what="block", ok=True)]
    s = S_(ev, voice=voice)
    check(MC.v_alert_delay(s) == {"delays": [0.21], "missing": 1}, f"V1 = {MC.v_alert_delay(s)}")
    check(MC.v_alert_count(s) == {"trans": 3, "one": 2, "zero": 1, "multi": 0, "normal": 0}, f"V2 = {MC.v_alert_count(s)}")
    check(MC.v_alert_stop(s) == {"delays": [0.05], "missing": 0}, f"V3 = {MC.v_alert_stop(s)}")
    check(MC.v_alert_len(s) == {"lens": [1.5], "cut": 0}, f"V4 = {MC.v_alert_len(s)} — 3초 넘어 시작한 재생은 짝짓지 않는다")
    s4 = S_(voice=[E(100, "alert", key="경고", t_pub_ms=90.0), E(200, "play_start"), E(400, "play_end", what="중단")])
    check(MC.v_alert_len(s4) == {"lens": [], "cut": 1}, f"V4 중단 = {MC.v_alert_len(s4)}")
    check(MC.v_alert_count(S_(ev)) == {"off": 1}, "음성 기록이 없으면 V2 = 끔")


def test_uplink():
    print("\n[V9] 10초 칸 받은/기대 바이트 — 데몬이 다시 떠 누적이 줄면 그 칸은 버린다")
    voice = [E(0, "uplink", bytes=0, connected=True), E(10000, "uplink", bytes=320000, connected=True),
             E(20000, "uplink", bytes=160000, connected=True), E(30000, "uplink", bytes=480000, connected=True),
             E(40000, "uplink", bytes=480000, connected=False)]
    check(MC.v_uplink(S_(voice=voice)) == {"ratios": [1.0, 1.0]}, f"{MC.v_uplink(S_(voice=voice))}")


def test_count_all_keys():
    print("\n[모두] 한 세션의 값 키")
    keys = set(MC.count_all(S_()).keys())
    check(keys == {"1", "4", "16", "3", "25", "5", "23", "28", "21", "12", "26", "14", "30", "17a", "17b", "18",
                   "V1", "V2", "V3", "V4", "V9"}, f"{sorted(keys)}")


def test_fps_short_session():
    print("\n[13] 창(60간격)이 한 번도 안 찼으면 최저·최장을 내지 않는다 — 「0초」로 읽히지 않게")
    fs = [FS(100 * i, t_gui=100 * i) for i in range(10)]
    f = MC.v_fps(S_(fsm=fs), below=15.0)
    check(f["roll_min"] == [] and f["low_longest"] == [] and len(f["iv"]) == 9, f"{f['roll_min']} {f['low_longest']}")


def test_graze_skips_expected():
    print("\n[23] 기대 버튼 위 구간은 지나감으로 세지 않는다 — 판정기가 거기서는 경고를 내지 않는다")
    rois = ["B1", "B1", "B1", None, "B3", "B3"]
    fr = [FR(i + 1, 1000 + 100 * i, roi=r) for i, r in enumerate(rois)]
    fs = [FS(1000 + 100 * i, roi=r, expected="B1") for i, r in enumerate(rois)]
    g = MC.v_graze(S_([E(900, "run_start")], frames=fr, fsm=fs))
    check((g["pass_n"], g["pass_dur"]) == (1, [0.1]), f"{g}")


def test_stay_prefers_warned():
    print("\n[23] 대본 머묾은 그 버튼 경고가 든 구간(없으면 가장 긴 구간)과 짝 — 앞선 짧은 스침과 짝짓지 않는다")
    rois = ["B3", None, None, "B3", "B3", "B3", "B3", "B3", None]
    fr = [FR(i + 1, 1000 + 100 * i, roi=r) for i, r in enumerate(rois)]
    fs = [FS(1000 + 100 * i, roi=r) for i, r in enumerate(rois)]
    ev = [E(900, "run_start"), E(1550, "state", new="WARNING", dwell_roi="B3", frame_t_ms=1500.0), E(2000, "run_end", ok=False)]
    g = MC.v_graze(S_(ev, frames=fr, fsm=fs, script=SCR((1, "머묾", "B3"))))
    check((g["stay_n"], g["stay_warned"]) == (1, 1), f"{(g['stay_n'], g['stay_warned'])}")


def test_input():
    print("\n[18] 표본만 — 완주한 정상 판의 기대 누름(레시피 단계 수) ↔ 기록된 gpio 누름")
    ev = [E(0, "run_start"), P(100, "B1", expected="B1"), P(200, "B2", expected="B2"), P(300, "B3", expected="B3"),
          E(400, "run_end", ok=True), E(500, "run_start"), P(600, "B1", expected="B1"), E(700, "run_reset", why="작업 초기화")]
    check(MC.v_input(S_(ev, kind="정상")) == {"runs": 1, "expect": 4, "got": 3}, f"{MC.v_input(S_(ev, kind='정상'))}")


def test_uplink_restart_boundary():
    print("\n[V9] 두 표본 사이에 음성 measure_end(데몬 재시작)가 있으면 그 칸은 버린다 · 표본률을 못 읽으면 내지 않는다")
    voice = [E(0, "uplink", bytes=0, connected=True), E(10000, "uplink", bytes=320000, connected=True),
             E(15000, "measure_end", dropped=0), E(20000, "uplink", bytes=640000, connected=True)]
    check(MC.v_uplink(S_(voice=voice)) == {"ratios": [1.0]}, f"{MC.v_uplink(S_(voice=voice))}")
    check(MC.v_uplink(S_(voice=voice, rate=None)) == {"ratios": [], "norate": 1}, "표본률 없음")


def test_zone_noframe():
    print("\n[5] 프레임 기록이 없는 누름은 분모에서 뺀다(따로 센다)")
    z = MC.v_zone(S_([E(0, "run_start"), P(100, "B2")]))
    check((z["n"], z["noframe"]) == (0, 1), f"{z}")


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 세기 값 함수 검증 통과")
