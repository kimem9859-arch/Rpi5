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


def S_(events=(), frames=(), fsm=(), voice=(), script=None, kind="위반", settings=None, voice_on=True, rate=16000, says=()):
    return {"name": "t", "kind": kind, "info": {"음성": voice_on, "측정기록": True}, "steps": ["B1", "B2", "B3", "B4"],
            "settings": settings or {"FSM_GAP_FILL_SEC": 0.3, "PRESS_CONFIRM_GRACE_SEC": 0.5},
            "frames": list(frames), "fsm": list(fsm),
            "events": sorted(events, key=lambda e: e[0]), "voice": sorted(voice, key=lambda e: e[0]),
            "says": sorted(says, key=lambda e: e[0]),
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
    check(MC.v_prevent(S) == {"n": 4, "k": 1, "late": 0, "short": 2, "ring": 0, "none": 1, "other": 0},
          f"1 = {MC.v_prevent(S)} — 문턱 없는 설정 = 체류로 가를 수 없어 체류 미달로")
    S2 = S_([E(0, "run_start"), E(1500, "gpio_edge", button="B3", src="edge"), P(1510, "B3"),
             E(2500, "gpio_edge", button="B4", src="edge"), P(2510, "B4"),
             E(3500, "gpio_edge", button="B1", src="edge"), P(3510, "B1")],
            fsm=[FS(1000, roi="B3", level=1), FS(1100, roi="B3", level=2), FS(1400, roi="B3", level=2, t_gui=1600),
                 FS(2400, roi="B4", level=1), FS(3400, roi="B3", level=2)],
            settings={"FSM_GAP_FILL_SEC": 0.3, "FSM_DWELL_THRESHOLD_SEC": 0.3})
    check(MC.v_prevent(S2) == {"n": 3, "k": 0, "late": 1, "short": 0, "ring": 1, "none": 1, "other": 0},
          f"1 = {MC.v_prevent(S2)} — 체류 0.4초(링부터)·박스 안 = 처리 늦음 · 링에만 · 다른 버튼 = 손 없음")
    S3 = S_([E(0, "run_start"), E(1500, "gpio_edge", button="B3", src="edge"), P(1510, "B3")],
            fsm=[FS(1000, roi="B3", level=2, t_gui=1030), FS(1400, roi="B3", level=2, t_gui=1430)],
            settings={"FSM_GAP_FILL_SEC": 0.3, "FSM_DWELL_THRESHOLD_SEC": 0.3})
    check(MC.v_prevent(S3)["other"] == 1 and MC.v_prevent(S3)["late"] == 0,
          f"1 = {MC.v_prevent(S3)} — 체류는 찼고 누름 전에 처리됐는데 경고 없음 = 기타(판정 규칙 예외 · 최종 리뷰 Minor 8)")
    check(MC.v_lead(S) == {"leads": [0.08]}, f"4 = {MC.v_lead(S)}")
    S4 = dict(S2, settings={"FSM_GAP_FILL_SEC": 0.3, "FSM_DWELL_THRESHOLD_SEC": 0.3, "FSM_SLOW_ENTRY_PX_S_VGA": 437.5})
    check(MC.v_prevent(S4) == MC.v_prevent(S2), "속도 문턱(안 B)이 켜져도 세는 법은 같다(진단 문구만 다르다 · 최종 리뷰 Minor M-1)")


def test_warn_reason():
    print("\n[경고 이유] 경고 상태 사건의 reason — 속도(slow) · 체류(dwell) · 이유 없음(옛 기록 · 판정 기준 안 B · 최종 리뷰 Minor M-2)")
    ev = [E(0, "run_start"), E(100, "state", new="WARNING", reason="slow"), E(200, "state", new="PROCESS_RUN"),
          E(300, "state", new="WARNING", reason="dwell"), E(400, "state", new="BLOCK"), E(500, "state", new="WARNING"),
          E(600, "state", new="WARNING", reason=None), E(700, "run_end", ok=False)]
    check(MC.v_reason(S_(ev)) == {"slow": 1, "dwell": 1, "none": 2}, f"{MC.v_reason(S_(ev))} — 경고 상태 사건만 · 칸 없음·None = 이유 없음")
    check(MC.v_reason(S_()) == {"slow": 0, "dwell": 0, "none": 0}, "경고 없음 = 모두 0")


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
    print("\n[30] 자원 — 첫 값은 버린다 · 직전 값 이후 처리한 프레임이 없는 값(안경 꺼짐·끊김)도 뺀다")
    ev = [E(0, "res", cpu_avg=99.0, cpu_max=99.0, temp=99.0), E(10, "res", cpu_avg=30.0, cpu_max=50.0, temp=60.0),
          E(20, "res", cpu_avg=40.0, cpu_max=70.0, temp=None), E(30, "res", cpu_avg=2.0, cpu_max=3.0, temp=45.0)]
    fr = [FR(i + 1, t) for i, t in enumerate([2, 9, 15, 20])]           # 20 뒤로 프레임 없음 = 안경 꺼짐
    check(MC.v_res(S_(ev, frames=fr)) == {"cpu_avg": [30.0, 40.0], "cpu_max": [50.0, 70.0], "temp": [60.0]},
          f"{MC.v_res(S_(ev, frames=fr))} — 30 의 값(프레임 없음)은 빠진다")


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
    check(MC.v_alert_delay(s) == {"delays": [0.21], "missing": 1, "dropped": 0}, f"V1 = {MC.v_alert_delay(s)}")
    # 🔑 V2 「한 번」 = 그 알림이 실제로 재생됐다(3초 안) — 4초 뒤에야 재생된 차단 알림은 V1 처럼 「없음」(최종 리뷰 I-2)
    check(MC.v_alert_count(s) == {"trans": 3, "one": 1, "zero": 2, "multi": 0, "dropped": 0, "normal": 0},
          f"V2 = {MC.v_alert_count(s)}")
    check(MC.v_alert_stop(s) == {"delays": [0.05], "missing": 0}, f"V3 = {MC.v_alert_stop(s)}")
    check(MC.v_alert_len(s) == {"lens": [1.5], "cut": 0}, f"V4 = {MC.v_alert_len(s)} — 3초 넘어 시작한 재생은 짝짓지 않는다")
    s4 = S_(voice=[E(100, "alert", key="경고", t_pub_ms=90.0), E(200, "play_start"), E(400, "play_end", what="중단")])
    check(MC.v_alert_len(s4) == {"lens": [], "cut": 1}, f"V4 중단 = {MC.v_alert_len(s4)}")
    check(MC.v_alert_count(S_(ev)) == {"off": 1}, "음성 기록이 없으면 V2 = 끔")
    print("  — 알림 둘이 붙어 와도 재생 하나를 나눠 쓰지 않는다 · 안내(cue_) 재생은 뺀다 · 알림 끈 세션")
    v2 = [E(1000, "alert", key="alert_warn_B2", t_pub_ms=990.0), E(1100, "alert", key="alert_block_B2", t_pub_ms=1090.0),
          E(1150, "play_start", key="alert_warn_B2"), E(1160, "play_end", what="중단", key="alert_warn_B2"),
          E(1900, "play_start", key="alert_block_B2"), E(3900, "play_end", what="완료", key="alert_block_B2"),
          E(5000, "play_start", key="cue_B1"), E(5400, "play_end", what="완료", key="cue_B1")]
    s5 = S_(voice=v2)
    # 경고 제 재생(1150)보다 차단 알림(1100)이 먼저 왔다 = 밀림(뺀다) — 10ms 만에 끊긴 소리
    check(MC.v_alert_delay(s5) == {"delays": [0.81], "missing": 0, "dropped": 1}, f"V1 = {MC.v_alert_delay(s5)}")
    check(MC.v_alert_len(s5) == {"lens": [2.0], "cut": 1}, f"V4 = {MC.v_alert_len(s5)}")
    s6 = S_(voice=[], settings={"FSM_GAP_FILL_SEC": 0.3, "VOICE_ALERTS": False})
    check(MC.v_alert_delay(s6) == {"delays": [], "missing": 0, "off": 1}, f"V1 끔 = {MC.v_alert_delay(s6)}")
    s7 = S_(ev, voice=voice, settings={"FSM_GAP_FILL_SEC": 0.3, "VOICE_ALERTS": False})
    check(MC.v_alert_count(s7) == {"alerts_off": 1}, f"V2 알림 끈 세션 = 해당 없음(V1 과 같다 · 최종 리뷰 b) = {MC.v_alert_count(s7)}")


def test_alert_count_cut():
    print("\n[V2] 짝 창의 끝 = 다음 상태 바뀜(음성비서 빠른 해결 설계 §2.4) — 경고 0.2초 뒤 차단 = 경고 한 번 · 차단 한 번")
    ev = [E(1000, "state", new="WARNING"), E(1200, "state", new="BLOCK"), E(5000, "state", new="IDLE")]
    voice = [E(1003, "alert", key="alert_warn_B2", t_pub_ms=1002.0), E(1100, "play_start", key="alert_warn_B2"),
             E(1203, "alert", key="alert_block_B2", t_pub_ms=1202.0), E(1400, "play_start", key="alert_block_B2")]
    v = MC.v_alert_count(S_(ev, voice=voice))
    check(v == {"trans": 2, "one": 2, "zero": 0, "multi": 0, "dropped": 0, "normal": 0}, f"경고 → 0.2초 뒤 차단 = {v}")
    print("  — 경고가 46ms 만에 차단으로 바뀌어 경고 제 알림이 없으면 경고는 「밀림」(알림이 나갈 틈 없이 바뀜 · 최종 리뷰 I-2)")
    v = MC.v_alert_count(S_([E(1000, "state", new="WARNING"), E(1046, "state", new="BLOCK")],
                            voice=[E(1050, "alert", key="alert_block_B2", t_pub_ms=1049.0),
                                   E(1250, "play_start", key="alert_block_B2")]))
    check(v == {"trans": 2, "one": 1, "zero": 0, "multi": 0, "dropped": 1, "normal": 0}, f"{v}")
    print("  — 바뀜이 하나뿐이면 지금과 같다(창 끝 +1.0초 그대로) · 알림 없이 1초 넘게 머문 상태 = 없음(누락)")
    v = MC.v_alert_count(S_([E(1000, "state", new="WARNING")], voice=[E(2001, "alert", key="alert_warn_B2", t_pub_ms=2000.0),
                                                                     E(2100, "play_start", key="alert_warn_B2")]))
    check(v == {"trans": 1, "one": 1, "zero": 0, "multi": 0, "dropped": 0, "normal": 0}, f"{v}")
    v = MC.v_alert_count(S_([E(1000, "state", new="WARNING"), E(3000, "state", new="MONITOR")], voice=[E(500, "uplink")]))
    check(v == {"trans": 1, "one": 0, "zero": 1, "multi": 0, "dropped": 0, "normal": 0}, f"{v}")


def test_alert_dropped():
    print("\n[V1 · V2] 밀린 알림(뒤 알림·풀림이 제 재생보다 먼저 · dropped=true)은 누락이 아니라 「밀림」으로 따로(최종 리뷰 I-2)")
    voice = [E(1000, "alert", key="alert_warn_B2", t_pub_ms=990.0), E(1100, "alert", key="alert_block_B2", t_pub_ms=1090.0),
             E(1105, "alert_played", key="alert_warn_B2", ok=False, dropped=True),
             E(1300, "play_start", key="alert_block_B2"), E(3300, "play_end", what="완료", key="alert_block_B2"),
             E(3301, "alert_played", key="alert_block_B2", ok=True, dropped=False),
             E(5000, "alert", key="alert_warn_B3", t_pub_ms=4990.0), E(5050, "alert_clear"),
             E(5060, "alert_played", key="alert_warn_B3", ok=False, dropped=True),
             E(8000, "alert", key="alert_warn_B1", t_pub_ms=7990.0),                         # 재생도 밀어낸 것도 없음 = 누락
             E(12000, "alert", key="alert_block_B4", t_pub_ms=11990.0),                      # _want 를 덮어써 alert_played 도 없음
             E(12050, "alert", key="alert_emo", t_pub_ms=12040.0), E(12300, "play_start", key="alert_emo"),
             E(15000, "play_end", what="완료", key="alert_emo"), E(15001, "alert_played", key="alert_emo", ok=True, dropped=False)]
    ev = [E(985, "state", new="WARNING"), E(1085, "state", new="BLOCK"), E(4000, "state", new="IDLE"),
          E(4985, "state", new="WARNING"), E(5045, "state", new="MONITOR"),
          E(7985, "state", new="WARNING"), E(9500, "state", new="MONITOR"),
          E(11985, "state", new="BLOCK"), E(16000, "state", new="IDLE")]
    s = S_(ev, voice=voice)
    check(MC.v_alert_delay(s) == {"delays": [0.21, 0.26], "missing": 1, "dropped": 3}, f"V1 = {MC.v_alert_delay(s)}")
    check(MC.v_alert_count(s) == {"trans": 5, "one": 2, "zero": 1, "multi": 0, "dropped": 2, "normal": 0},
          f"V2 = {MC.v_alert_count(s)}")
    print("  — 옛 기록(재생 키 · dropped 없음 · 10/10 꼴): 경고 재생이 차단 알림 뒤 「[재생]」 즉시 중단(0샘플) = 밀림 ·"
          " 차단 알림의 재생은 제 alert_played 직전 재생")
    old = [E(87, "alert", key="alert_warn_B1", t_pub_ms=2.0), E(87, "stop_sent"),
           E(187, "alert", key="alert_block_B1", t_pub_ms=125.0), E(402, "stop_sent"),
           E(657, "play_start"), E(657, "play_end", what="중단"), E(657, "alert_played", key="alert_warn_B1", ok=True),
           E(1344, "play_start"), E(2610, "stop_sent"), E(2611, "alert_clear"), E(2631, "play_end", what="중단"),
           E(2631, "alert_played", key="alert_block_B1", ok=True)]
    s = S_([E(0, "state", new="WARNING"), E(123, "state", new="BLOCK"), E(2610, "state", new="IDLE")], voice=old)
    check(MC.v_alert_delay(s) == {"delays": [1.219], "missing": 0, "dropped": 1}, f"V1 = {MC.v_alert_delay(s)}")
    check(MC.v_alert_count(s) == {"trans": 2, "one": 1, "zero": 0, "multi": 0, "dropped": 1, "normal": 0},
          f"V2 = {MC.v_alert_count(s)}")


def SAY(t, run, tok, text, emergency=False, script=None):
    return E(t, "say", run=run, script=run if script is None else script, tok=tok, text=text, emergency=emergency)


def SAID(t, run, tok, why="질문", attempts=1):
    return E(t, "said", run=run, tok=tok, why=why, attempts=attempts)


def STT(t, text):
    return E(t, "stt", text=text, stt_ms=500, utter_sec=1.0)


def test_wake():
    print("\n[V5] 호출 인식 — 말 띠(say) 가운데 「넘어감」 아닌 것마다 창 [say, said + 1초] 안에 호출(wake · 비상 중 호출)")
    says = [SAY(10000, 1, 1, "지금 몇 단계야?"), SAID(20000, 1, 1),
            SAY(30000, 1, 4, "작업 결과 어때?"), SAID(31000, 1, 4, why="넘어감", attempts=0),
            SAY(40000, 1, 5, "지금 상태 어때?"), SAID(70000, 1, 5, why="시간", attempts=2),
            SAY(80000, 2, 1, "왜 멈췄어?", emergency=True), SAID(90000, 2, 1),
            SAY(95000, 3, 1, "작업 결과 어때?")]                                # said 없이 세션이 끝남 — 분모에서 뺀다(open)
    voice = [STT(19000, "가디언 지금 몇 단계야"), E(20500, "wake"),          # said 뒤 0.5초 — 창 안(+1초)
             E(25000, "wake"),                                             # 어느 창에도 없다 — 헛호출 후보
             STT(45000, "아"), STT(50000, "어디야"),                       # 호출 못 함
             E(85000, "emergency_ignored", text="가디야.", wake=True), E(88000, "emergency_ignored", text="왜멈췄어", wake=False)]
    v = MC.v_wake(S_(voice=voice, says=says))
    check(v == {"say": 1, "n": 3, "k": 2, "skip": 1, "open": 1, "calls": 3, "outside": 1}, f"V5 = {v}")
    check(MC.v_wake(S_(says=says)) == {"off": 1}, "음성 기록이 없으면 끔")
    check(MC.v_wake(S_(voice=voice)) == {"say": 0, "calls": 3}, f"말 띠 기록이 없으면 대본 값 없음 · 호출 수만 = {MC.v_wake(S_(voice=voice))}")


def test_stt_error():
    print("\n[V6] 받아쓰기 글자 오류율 — 호출 뒤 첫 한글 조각부터 said 까지 ↔ 띠 문장(공백·부호 빼고) · 호출어만이면 「질문 못 받음」")
    says = [SAY(10000, 1, 1, "지금 몇 단계야?"), SAID(18000, 1, 1),
            SAY(30000, 1, 4, "지금 눌러야 하는 버튼이 뭐야?"), SAID(33000, 1, 4),
            SAY(40000, 1, 5, "작업 결과 어때?"), SAID(42000, 1, 5),
            SAY(50000, 1, 7, "다음에 뭐 눌러야 돼?"), SAID(51000, 1, 7, why="넘어감", attempts=0),
            SAY(80000, 2, 1, "왜 멈췄어?", emergency=True), SAID(90000, 2, 1)]
    voice = [STT(12000, "응"), STT(15000, "가디언"), E(15800, "wake"), STT(17000, "지금몇단게야."),   # 호출 앞 조각은 빼고 · 1자 틀림
             STT(32000, "가디언 지금 눌러야 하는 버튼이 뭐야?"), E(32800, "wake"),               # 호출어와 한 조각 = 호출어를 뗀다
             STT(41000, "가디언가디언"), E(41800, "wake"),                                     # 호출어만 = 질문 못 받음
             # 비상 중에도 데몬은 받아쓴 조각을 stt 로 적고 판단에서 emergency_ignored 를 또 적는다 — 한 발화를 두 번 잇지 않는다
             STT(84000, "가디야."), E(85000, "emergency_ignored", text="가디야.", wake=True),
             STT(87000, "왜멈췄어"), E(88000, "emergency_ignored", text="왜멈췄어", wake=False)]
    v = MC.v_stt(S_(voice=voice, says=says))
    check((v["say"], v["n"], v["dist"], v["ref"], v["noq"]) == (1, 3, 1, 22, 1), f"V6 = {v}")
    check(["지금몇단게야" in r[1] for r in v["rows"]] == [True, False, False], f"조각 = {v['rows']}")
    check(MC.v_stt(S_(says=says)) == {"off": 1} and MC.v_stt(S_(voice=voice)) == {"say": 0}, "음성 기록 · 말 띠가 없으면 해당 없음")
    check(MC.edit_distance("가나다", "가다라") == 2 and MC.edit_distance("", "가나") == 2, "편집거리")


def test_answer():
    print("\n[V7] 답 지연(질문 받아쓰기 → answer · → 답 재생) · 초벌 정확도(기대 칸 핵심 낱말) — src 별(LLM · 즉답 · 그 밖)")
    script = [{"판": 1, "행동": "질문", "대상": "지금 몇 단계야?", "기대": "1단계(클린·가스차단)"},
              {"판": 1, "행동": "질문", "대상": "다음에 뭐 눌러야 돼?", "기대": "B2(펌프/퍼지) — 대기가 끝난 뒤"},
              {"판": 1, "행동": "질문", "대상": "앞에 보이는 공구가 뭐야?", "기대": "렌치"},
              {"판": 1, "행동": "질문", "대상": "작업 결과 어때?", "기대": "완료 · 위반 없음"},
              {"판": 1, "행동": "질문", "대상": "지금 상태 어때?", "기대": ""}]
    says = [SAY(10000, 1, 1, "지금 몇 단계야?"), SAID(12000, 1, 1),
            SAY(30000, 1, 2, "다음에 뭐 눌러야 돼?"), SAID(32000, 1, 2),
            SAY(50000, 1, 3, "앞에 보이는 공구가 뭐야?"), SAID(52000, 1, 3),
            SAY(70000, 1, 4, "작업 결과 어때?"), SAID(72000, 1, 4),
            SAY(90000, 1, 5, "지금 상태 어때?"), SAID(92000, 1, 5),
            SAY(100000, 1, 6, "작업 결과 어때?"), SAID(101000, 1, 6, why="넘어감", attempts=0)]
    voice = [STT(11000, "지금몇단계야"), E(13000, "answer", src="즉답-단계", text="지금 1단계 클린·가스차단입니다."),
             E(13300, "play_start", key=None),
             STT(31000, "다음뭐눌러야돼"), E(32000, "play_start", key="checking"), E(40000, "answer", src="LLM", text="지금은 B3 버튼을 누르세요."),
             E(40500, "play_start", key=None),
             STT(51000, "앞에보이는공구가뭐야"), E(60000, "answer", src="고정-검산불일치", key="changed"),
             E(60100, "play_start", key="cue_B3"), E(60200, "play_start", key="changed"),
             STT(71000, "작업결과어때"), E(75000, "answer", src="LLM", text="작업이 끝났습니다."), E(75400, "play_start", key=None),
             STT(78000, "다시 말해줘"), E(85000, "answer", src="LLM", text="확인할 수 없습니다."),     # 같은 띠의 두 번째 답 = 대본 밖
             STT(91000, "지금상태어때")]                                                            # 답 없음
    v = MC.v_answer(S_(voice=voice, says=says), script)
    check(v["ans"] == {"즉답": [2.0], "LLM": [9.0, 4.0], "그 밖": [9.0]}, f"질문 → answer = {v['ans']}")
    check(v["play"] == {"즉답": [2.3], "LLM": [9.5, 4.4], "그 밖": [9.2]}, f"질문 → 답 재생 = {v['play']}")
    check(v["extra"] == {"LLM": [7.0]} and v["n"] == 5 and v["noans"] == 1, f"대본 밖 답 · 짝 수 · 답 없음 = {v['extra']} {v['n']} {v['noans']}")
    check(v["judge"] == {"즉답": {"ok": 1, "bad": 0, "human": 0, "drop": 0}, "LLM": {"ok": 1, "bad": 1, "human": 0, "drop": 0},
                         "그 밖": {"ok": 0, "bad": 0, "human": 0, "drop": 1}}, f"초벌 = {v['judge']}")
    check([(r["질문"], r["판정"]) for r in v["review"]] == [("다음에 뭐 눌러야 돼?", "틀림 후보")], f"사람 판정 목록 = {v['review']}")
    check(MC.core_words("B2(펌프/퍼지) — 대기가 끝난 뒤") == [("B2",)] and MC.core_words("완료 · 위반 없음") == [("끝", "완료")]
          and MC.core_words("4단계(챔버 벤트) 차례") == [("4단계",)] and MC.core_words("") == [], "핵심 낱말 — 괄호 · 「—」 뒤 조건은 뺀다")
    check(MC.v_answer(S_(says=says), script) == {"off": 1}, "음성 기록이 없으면 끔")
    w = MC.v_answer(S_(voice=voice), None)
    check(w["n"] == 0 and w["extra"] == {"즉답": [2.0], "LLM": [9.0, 4.0, 7.0], "그 밖": [9.0]}, f"말 띠가 없으면 모든 답이 대본 밖 = {w['extra']}")


def test_emergency_silence():
    print("\n[V8] 비상 중 무반응 — 질문 단위(측정 설계 V8 · 최종 리뷰 M-5): 비상 구간 안의 비상질문 띠(질문까지 감)마다"
          " 띠부터 해제 + 0.5초까지 호출·답·응답 소리가 없었나 · 비상 구간 = EMO 누름(위반 차단 중에 누른 EMO 도) ~ 차단을 벗어난 바뀜")
    ev = [P(1000, "EMO", expected="B1", state="MONITOR"), E(1001, "state", old="MONITOR", new="BLOCK"),
          E(9000, "state", old="BLOCK", new="IDLE"),
          P(20000, "EMO", expected="B1", state="MONITOR"), E(20001, "state", old="MONITOR", new="BLOCK"),
          E(29000, "state", old="BLOCK", new="IDLE"),
          P(40000, "B3", expected="B2", state="MONITOR"), E(40001, "state", old="MONITOR", new="BLOCK"),   # 위반 차단
          P(42000, "EMO", expected="B2", state="BLOCK"),                                                    # 차단 중 EMO — 새 BLOCK 없음
          E(50000, "state", old="BLOCK", new="IDLE"),
          P(59000, "EMO", expected="B1", state="MONITOR"), E(59001, "state", old="MONITOR", new="BLOCK"),
          E(65000, "state", old="BLOCK", new="IDLE"),
          P(70000, "EMO", expected="B1", state="IDLE")]                                                      # 차단이 안 됨 = 비상 아님
    says = [SAY(2000, 1, 1, "지금 B1 눌러도 돼?", emergency=True), SAID(3000, 1, 1),
            SAY(21000, 2, 1, "다음에 뭐 해야 돼?", emergency=True), SAID(22000, 2, 1),
            SAY(43000, 3, 1, "지금 상태 어때?", emergency=True), SAID(44000, 3, 1),
            SAY(60000, 4, 1, "작업 계속해도 돼?", emergency=True), SAID(64000, 4, 1, why="시간", attempts=0),
            SAY(70500, 5, 1, "왜 멈췄어?", emergency=True), SAID(71000, 5, 1),
            SAY(80000, 6, 1, "지금 몇 단계야?"), SAID(81000, 6, 1)]                                       # 비상 아닌 띠는 V8 밖
    voice = [E(2500, "emergency_ignored", text="가디야.", wake=True),
             E(21500, "emergency_ignored", text="가디언", wake=True), E(29300, "answer", src="LLM", text="네"),   # 해제 + 0.3초 = 창 안
             E(42100, "play_start", key="alert_emo"), E(43500, "emergency_ignored", text="가디언", wake=True),
             E(43600, "play_start", key="cue_B1"),                                                                 # 알림 · 안내는 응답 아님
             E(80500, "wake")]
    v = MC.v_emergency(S_(ev, voice=voice, says=says))
    check(v == {"say": 1, "spans": 4, "n": 3, "k": 2, "skip": 1, "outside": 1}, f"V8 = {v}")
    check(MC.v_emergency(S_(ev, says=says)) == {"off": 1}, "음성 기록이 없으면 끔")
    check(MC.v_emergency(S_(ev, voice=voice)) == {"say": 0, "spans": 4}, f"말 띠가 없으면 해당 없음 = {MC.v_emergency(S_(ev, voice=voice))}")


def test_stt_domain():
    print("\n[V6] 도메인 낱말(B1~B4 · EMO · 공구 이름 — 측정 설계 V6 「따로」 · 최종 리뷰 M-5) — 띠 문장의 낱말이 받아쓴 글에 있나"
          " · 「비원」 같은 한글 읽기(voice_tts.read_out)도 맞음")
    says = [SAY(10000, 1, 1, "지금 B1 눌러도 돼?"), SAID(12000, 1, 1),
            SAY(20000, 1, 2, "렌치 보여?"), SAID(22000, 1, 2),
            SAY(30000, 1, 3, "B2 다음에 B3 눌러?"), SAID(32000, 1, 3)]
    voice = [STT(11000, "가디언 지금 비원 눌러도 돼"), E(11500, "wake"),
             STT(21000, "가디언 랜치 보여"), E(21500, "wake"),
             STT(31000, "가디언 B2 다음에 비상 눌러"), E(31500, "wake")]
    v = MC.v_stt(S_(voice=voice, says=says))
    check((v["dom"], v["dom_miss"]) == (4, 2), f"도메인 낱말 4 · 빠짐 2(렌치 · B3) = {v.get('dom')} · {v.get('dom_miss')}")


def test_voice_absent():
    print("\n[V5~V8] 음성 기록 · 말 띠가 없는 세션(알림 끔 · 음성 끔 · 옛 세션)에서 죽지 않고 해당 없음")
    S = S_([E(0, "run_start"), E(100, "run_end", ok=True)])
    S.pop("says")                                   # 옛 세션 꼴 — 말 띠 키가 아예 없다
    c = MC.count_all(S)
    check(all(c[k] == {"off": 1} for k in ("V5", "V6", "V7", "V8")), f"{[c[k] for k in ('V5', 'V6', 'V7', 'V8')]}")


def test_says_follow_splits():
    print("\n[말 띠] 녹화 구간 · 뺀 판의 말 띠도 다른 기록과 같이 뺀다")
    S = S_([E(0, "recording_on", mode="x"), E(500, "recording_off")], says=[SAY(100, 1, 1, "가"), SAY(900, 1, 2, "나")])
    M, R = MC.split_recording(S)
    check([t for t, _, _ in M["says"]] == [900.0] and [t for t, _, _ in R["says"]] == [100.0], f"{M['says']} {R['says']}")
    old = S_()
    old.pop("says")
    M, _R = MC.split_recording(old)
    check(M.get("says", []) == [], "말 띠 키 없는 옛 꼴도 돈다")


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
                   "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "31", "reason"}, f"{sorted(keys)}")


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


def test_split_guide():
    print("\n[판 맞춤] NG·대본 밖 판의 기록을 그 판째 빼고 대본을 남은 판 순서로 다시 번호 매긴다")
    import measure_script as MS
    B = ["B1", "B2", "B3", "B4"]
    rows = [{"판": 1, "행동": "위반", "대상": "B2", "기대": "", "메모": "", "누름": "B2@B1", "낱말": MS.parse_tokens("B2@B1", B)},
            {"판": 2, "행동": "위반", "대상": "B3", "기대": "", "메모": "", "누름": "B3@B1", "낱말": MS.parse_tokens("B3@B1", B)}]
    ev = [E(0, "run_start"), P(10, "B4", expected="B1"), E(90, "run_reset", why="작업 초기화"),
          E(100, "run_start"), P(110, "B2", expected="B1"), E(190, "run_reset", why="작업 초기화"),
          E(200, "run_start"), P(210, "B3", expected="B1"), E(290, "run_reset", why="작업 초기화")]
    S = S_(ev, frames=[FR(1, 50), FR(2, 150)], fsm=[FS(50), FS(150)], script=rows)
    res = MS.match(S["events"], rows, ahead=2)
    G = MC.split_guide(S, res)
    check([e[0] for e in G["events"]] == [100.0, 110.0, 190.0, 200.0, 210.0, 290.0], f"{[e[0] for e in G['events']]}")
    check([f["t"] for f in G["frames"]] == [150.0] and [f["t"] for f in G["fsm"]] == [150.0], "프레임·판정기 줄도 판째")
    check([(r["판"], r["대상"]) for r in G["script"]] == [(1, "B2"), (2, "B3")], f"{[(r['판'], r['대상']) for r in G['script']]}")
    check(G["breaks"] == [(0.0, 90.0)] and G["guide"] is res, f"breaks = {G['breaks']}")


def test_system_values_keep_ng_runs():
    print("\n[시스템 값] 뺀 판(장비 NG 등)도 FPS·끊김·단계·자원·인터락·V1·V3·V4·V9 에는 남는다(설계 §3.1 · 최종 리뷰 Important 1)")
    import measure_script as MS
    B = ["B1", "B2", "B3", "B4"]
    rows = [{"판": 1, "행동": "위반", "대상": "B2", "기대": "", "메모": "", "누름": "B2@B1", "낱말": MS.parse_tokens("B2@B1", B)}]
    ev = [E(0, "run_start"), P(10, "B2", expected="B1"), E(4000, "run_reset", why="작업 초기화"),
          E(5000, "run_start"), P(5010, "B2", expected="B1"), E(6000, "run_reset", why="작업 초기화")]
    fsm = [FS(100), FS(200), FS(3300), FS(3400), FS(5100), FS(5200)]
    S = S_(ev, fsm=fsm, script=rows)
    res = MS.match(S["events"], rows, marks=[(2000.0, "ng", "장비")], ahead=2, final=True)
    G = MC.split_guide(S, res)
    check([r["status"] for r in res["runs"]] == ["ng", "ok"], f"{[r['status'] for r in res['runs']]}")
    st = MC.count_all(G)["12"].get("stalls", [])
    check(any(abs(x - 3.1) < 0.05 for x in st), f"장비 NG 판 안의 3.1초 끊김이 남는다 = {st}")
    check(G["full"]["fsm"] == S["fsm"] and [f["t"] for f in G["fsm"]] == [5100.0, 5200.0], "대본 값은 뺀 S · 시스템 값은 판 맞춤 전 S")


def test_cue():
    print("\n[31] 안내 재생 시작 → 그 버튼 GPIO 엣지 · 구역 첫 관측으로 나눔 · 안내 뒤 누름 없음")
    ev = [E(0, "run_start"), E(1700, "gpio_edge", button="B2", src="edge"), P(1710, "B2", expected="B1"),
          E(4600, "gpio_edge", button="B1", src="edge"), P(4610, "B1", expected="B1")]
    voice = [E(1000, "play_start", key="cue_B2"), E(4000, "play_start", key="cue_B1"),
             E(6000, "play_start", key="cue_hover_B3"), E(8000, "play_start", key="cue_B3")]
    fsm = [FS(1400, roi="B2", level=1), FS(4300, roi="B1", level=2)]
    v = MC.v_cue(S_(ev, fsm=fsm, voice=voice))
    check(v == {"total": [0.7, 0.6], "viol": [0.7], "ok": [0.6], "reach": [0.4, 0.3], "stay": [0.3, 0.3], "nopress": 1},
          f"31 = {v}")


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 세기 값 함수 검증 통과")
