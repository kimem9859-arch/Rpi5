"""세기 보고 도구(측정 도구 정합 1단계-나 · 관문 ⑤) — 손으로 만든 세션 폴더로.

실행: python3 Demo/selftest/test_measure_report.py
"""
import csv
import json
import os
import re
import sys
import tempfile

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import measure_count as MC
import measure_report as MR

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


TABLE = """### 4.1 목표

| ID | 측정 # | 목표 | 목표값 | 무엇을 세나 | 상태 |
| --- | --- | --- | --- | --- | --- |
| KPI | 1 | 위반 사전 차단율 | **≥ 80%**(위반 눌림 60회 이상) | x | x |
| KPI | 4 | 경고 선행시간 | **중앙값 ≥ 0.25초** | x | x |
| KPI | 16 | 정상 작업 완주율 | **≥ 90%**(10판 중 9판 이상) | x | x |
| KPI | 9 | 버튼 검출 mAP50 | **≥ 0.95** | x | x |
| KPI | 17ⓐ | 틀린 공구 통과 | **0건**(시도 20회 이상) | x | x |
| **NFR-1** | 12 | 실시간 처리 | **중앙값 ≥ 15 fps** | x | x |
| **NFR-2** | 14 | 응답시간 | **모든 건 ≤ 100 ms** | x | x |
| 음성 | V1 | 음성 알림 지연 | **중앙값 ≤ 0.3초** | x | x |

- 다음 줄
"""


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def make_session(d, script="판,행동,대상,기대,메모\n1,위반,B3,,\n", truncate=False, slow=None, reason=None):
    """slow = 설정 FSM_SLOW_ENTRY_PX_S_VGA · reason = 경고 상태 사건의 reason — 둘 다 None 이면 칸이 없다(안 B 이전 옛 세션)."""
    os.makedirs(d, exist_ok=True)
    info = {"입력": {"장소": 1, "세션": "위반", "손": "맨손", "사람": 1, "조명": "", "대본": "대본.csv" if script else "",
                     "펌웨어": "glass_voice"},
            "설정": {"FSM_DWELL_THRESHOLD_SEC": 0.3, "FSM_GAP_FILL_SEC": 0.3, "PRESS_CONFIRM_GRACE_SEC": 0.5,
                     "HEF_MODEL_PATH": "/x/B.hef", "ORIENT_ONE_REMAP": False, "DISPLAY_SCALE_IN_PAINT": True,
                     "DISPLAY_EVERY": 2},
            "측정기록": True, "음성": True, "코드": {"Rpi5": "abc1234"}}
    if slow is not None:
        info["설정"]["FSM_SLOW_ENTRY_PX_S_VGA"] = slow
    warn = {"old": "PROCESS_RUN", "new": "WARNING", "expected": "B2", "dwell_roi": "B3"}
    if reason is not None:
        warn["reason"] = reason
    _write(os.path.join(d, "session.json"), json.dumps(info, ensure_ascii=False))
    _csv(os.path.join(d, "frames.csv"), ["frame", "t_recv_ms", "recv_seq", "t_start_ms", "t_done_ms", "decode_ms", "orient_ms",
                                         "detect_ms", "track_ms", "hand_ms", "tool_ms", "zone_ms", "tip_x", "tip_y", "tip_score",
                                         "roi", "level"],
         [[i + 1, 1000 + 100 * i, i + 1, 1010 + 100 * i, 1060 + 100 * i, 5, "", "", "", "", "", "", "", "", "", r, l]
          for i, (r, l) in enumerate([("", ""), ("B3", 2), ("B3", 2)])])
    _csv(os.path.join(d, "fsm.csv"), ["t_recv_ms", "t_gui_ms", "fsm_roi", "fsm_level", "state", "expected"],
         [[1000 + 100 * i, 1030 + 100 * i, r, l, "PROCESS_RUN", "B2"] for i, (r, l) in enumerate([("", ""), ("B3", 2), ("B3", 2)])])
    ev = [[900, "run_start", "{}"], [1250, "state", json.dumps(warn)],
          [1300, "press", json.dumps({"button": "B3", "source": "gpio", "expected": "B2", "state": "WARNING"})],
          [1400, "run_reset", json.dumps({"why": "작업 초기화"})], [1500, "measure_end", json.dumps({"dropped": 0, "failed": False})]]
    _csv(os.path.join(d, "events.csv"), ["t_ms", "kind", "data"], ev)
    if truncate:
        with open(os.path.join(d, "events.csv"), "a", encoding="utf-8") as f:
            f.write('1600,state,"{""old"": ""WAR')
    _csv(os.path.join(d, "voice_events.csv"), ["t_ms", "kind", "data"], [])
    if script:
        _write(os.path.join(d, "대본.csv"), "﻿" + script)
    return d


def test_load_session():
    print("\n[읽기] session.json · CSV · 사건 정렬 · 대본(BOM) · EMO · 표본률")
    with tempfile.TemporaryDirectory() as tmp:
        S = MR.load_session(make_session(os.path.join(tmp, "s1")))
        check(len(S["frames"]) == 3 and S["frames"][0]["roi"] is None and S["frames"][1]["level"] == 2, "프레임 3 · 빈 구역 = None")
        check([k for _, k, _ in S["events"]][:3] == ["run_start", "state", "press"], "사건 시각 순")
        check(S["script"] == [{"판": 1, "행동": "위반", "대상": "B3", "기대": "", "메모": "", "누름": "", "안내": "", "낱말": []}],
              f"대본 = {S['script']} — 누름 · 안내 칸이 없으면 빈 칸 · 낱말 없음(진행 도우미 설계 §4.2 · 학교 방문 준비 설계 §5.2)")
        check(S["emo"] == MR.emo_button() and S["kind"] == "위반" and S["rate"] == MR.mic_rate(), "EMO · 종류 · 표본률")
        check(MC.v_prevent(S) == {"n": 1, "k": 1, "late": 0, "short": 0, "ring": 0, "none": 0, "other": 0}, f"1 = {MC.v_prevent(S)}")
        check(S["steps"] == MR.recipe_buttons() and len(S["steps"]) > 0, f"레시피 단계 버튼 = {S['steps']}")


def test_mic_rate_from_source():
    print("\n[기준] 마이크 표본률 = voice_assistant.RATE(파일에서 상수만)")
    src = open(os.path.join(_DEMO, "voice_assistant.py"), encoding="utf-8").read()
    m = re.search(r"^RATE\s*=\s*(\d+)", src, re.M)
    check(m is not None and MR.mic_rate() == int(m.group(1)), f"{MR.mic_rate()}")


def test_parse_targets():
    print("\n[목표] §4.1 표를 읽는다 — 부호 · 값 · 단위 · 통계 · 최소 표본")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "통합문서.md")
        _write(p, "앞\n" + TABLE)
        t = MR.load_targets(p)
    check(list(t) == ["1", "4", "16", "9", "17ⓐ", "12", "14", "V1"], f"키 = {list(t)}")
    check((t["1"]["op"], t["1"]["value"], t["1"]["unit"], t["1"]["min_n"]) == ("≥", 80.0, "%", 60), f"1 = {t['1']}")
    check((t["4"]["stat"], t["4"]["value"], t["4"]["unit"]) == ("median", 0.25, "초"), f"4 = {t['4']}")
    check(t["16"]["min_n"] == 10 and (t["17ⓐ"]["op"], t["17ⓐ"]["value"], t["17ⓐ"]["unit"], t["17ⓐ"]["min_n"]) == ("≤", 0.0, "건", 20),
          f"16·17ⓐ = {t['16']['min_n']} {t['17ⓐ']}")
    check((t["14"]["stat"], t["14"]["value"], t["14"]["unit"]) == ("max", 100.0, "ms") and t["V1"]["stat"] == "median", "14 · V1 = 중앙값")


def test_real_targets():
    print("\n[목표] 지금 통합문서 §4.1 이 8행으로 읽힌다(파일이 있을 때)")
    if not os.path.exists(MR.TARGETS_MD):
        print("  ⏭ 통합문서 없음 — 건너뜀")
        return
    t = MR.load_targets()
    check(t is not None and set(t) == {"1", "4", "16", "9", "17ⓐ", "12", "14", "V1"}, f"{None if t is None else list(t)}")


def test_targets_missing():
    print("\n[목표] 파일 없음 · 표 모양 바뀜 → None(판정 없음)")
    check(MR.load_targets("/없는/경로.md") is None, "파일 없음")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "x.md")
        _write(p, "| 아이디 | 번호 |\n| --- | --- |\n| a | b |\n")
        check(MR.load_targets(p) is None, "표 머리 다름")
        S = MR.load_session(make_session(os.path.join(tmp, "s")))
        per = [MC.count_all(S)]
        md = MR.render([S], per, MC.merge(per), None)
    check("목표 읽기 실패 — 판정 없음" in md, "표에 판정 없음")


def test_judge():
    print("\n[판정] 표본 부족 · 충족 · 미달 · 통계 · 통계 표시가 없는 목표 = 모든 건(엄격한 쪽 — 지금 §4.1 에는 없지만 표가 바뀌어도 판정이 느슨해지지 않게)")
    t80 = MR.parse_target("**≥ 80%**(위반 눌림 60회 이상)")
    check(MR.judge(t80, 90.0, 10).startswith("⏸") and MR.judge(t80, 90.0, 60) == "✅ 충족" and MR.judge(t80, 70.0, 60) == "❌ 미달", "1")
    tv1 = MR.parse_target("**≤ 0.3초**")
    v, how = MR.apply_stat(tv1, [0.1, 0.5])
    check(v == 0.5 and "모든 건" in how and MR.judge(tv1, v, 2) == "❌ 미달", f"V1 = {v} {how}")
    t4 = MR.parse_target("**중앙값 ≥ 0.25초**")
    check(MR.apply_stat(t4, [0.1, 0.3, 0.4])[0] == 0.3, "중앙값")
    t25 = MR.parse_target("**≥ 0.25초**")
    v, how = MR.apply_stat(t25, [0.0, 0.01, 0.02, 0.5])
    check(v == 0.0 and "최솟값" in how and MR.judge(t25, v, 4) == "❌ 미달", f"≥ 표시 없음 = 최솟값(엄격) = {v} {how}")


def test_script_errors():
    print("\n[대본] 빈 줄·BOM 은 받는다 · 행동 철자 · 판 글자 = 줄 번호와 함께 멈춘다")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "a.csv")
        _write(p, "﻿판,행동,대상,기대,메모\n1,정상,,,\n\n2,위반,B3,,\n")
        check(len(MR.load_script(p)) == 2, "빈 줄 건너뜀")
        for body, word in (("판,행동,대상,기대,메모\n1,위반,B3,,\n2,위밤,B3,,\n", "3행"),
                           ("판,행동,대상,기대,메모\n하나,위반,B3,,\n", "2행")):
            _write(p, body)
            try:
                MR.load_script(p)
                check(False, f"{word} 오류를 못 잡음")
            except ValueError as e:
                check(word in str(e), f"{e}")


def test_truncated_session():
    print("\n[끊긴 기록] 잘린 마지막 줄 건너뜀 · 끝 사건 없으면 경고")
    with tempfile.TemporaryDirectory() as tmp:
        d = make_session(os.path.join(tmp, "s"), truncate=True)
        with open(os.path.join(d, "frames.csv"), "a", encoding="utf-8") as f:
            f.write("4,1")                          # 잘린 프레임 줄 — 「1」 이 시각으로 읽히면 안 된다
        S = MR.load_session(d)
        check(S["events"][-1][1] == "measure_end" and len(S["frames"]) == 3, "잘린 사건·프레임 줄은 버림")
        lines = open(os.path.join(d, "events.csv"), encoding="utf-8").read().splitlines()
        _write(os.path.join(d, "events.csv"), "\n".join(l for l in lines if "measure_end" not in l) + "\n")
        check(any("measure_end" in w for w in MR.warnings(MR.load_session(d))), "끝 사건 없음 경고")


def test_empty_session():
    print("\n[빈 기록] 사건·프레임 0 — 끝까지 돈다")
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "e")
        os.makedirs(d)
        _write(os.path.join(d, "session.json"), json.dumps({"입력": {"세션": "정상", "대본": ""}, "설정": {}, "측정기록": False}))
        with open(os.path.join(tmp, "통합.md"), "w", encoding="utf-8") as f:
            f.write(TABLE)
        S = MR.load_session(d)
        per = [MC.count_all(S, 15.0)]
        md = MR.render([S], per, MC.merge(per), MR.load_targets(os.path.join(tmp, "통합.md")))
    check("값 없음" in md and "측정 기록 끔" in md, "값 없음 · 끔 회차 경고")


def test_per_session():
    print("\n[표] 여러 세션 = 통합값(분모 합) + 세션별 값(편차 확인)")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "통합.md")
        _write(p, TABLE)
        Ss = [MR.load_session(make_session(os.path.join(tmp, n))) for n in ("a1", "a2")]
        per = [MC.count_all(S, 15.0) for S in Ss]
        md = MR.render(Ss, per, MC.merge(per), MR.load_targets(p))
    check("### 세션별 값" in md and "| a1 |" in md and "| a2 |" in md and "단일 세션" not in md, "세션별 행 · 단일 경고 없음")
    check(MC.merge(per)["1"]["n"] == 2 and "⏸ 표본 부족(2 < 60)" in md, "통합 = 분모 합")


def test_render_and_main():
    print("\n[표] 단일 세션 경고 · 목표 행 · 곡선 · 조건 · main 이 report.md·json 을 쓴다")
    with tempfile.TemporaryDirectory() as tmp:
        d = make_session(os.path.join(tmp, "s1"))
        p = os.path.join(tmp, "통합.md")
        _write(p, TABLE)
        S = MR.load_session(d)
        per = [MC.count_all(S, 15.0)]
        md = MR.render([S], per, MC.merge(per), MR.load_targets(p), curve=(0.8, 0.9))
        check("단일 세션 — 인용 금지" in md and "| 1 | 위반 사전 차단율 |" in md and "⏸ 표본 부족(1 < 60)" in md, "목표 행")
        check("세기 밖" in md and "체류 두 곡선" in md and "판정용으로 쓰지 않는다" in md and "B.hef" in md, "9 · 곡선 · 조건")
        check("처리 안2 끔 · 안1 켬 · 화면 2장에 1장" in md, "④ 조건에 처리 흐름 1단계 스위치(A·B·C 섞어 세지 않게 · 리뷰 Minor 5)")
        check(MR.main([d]) == 0 and os.path.exists(os.path.join(d, "report.md")) and os.path.exists(os.path.join(d, "report.json")),
              "main → report.md · report.json")


def test_no_verdict_for_test_session():
    print("\n[판정] 시험 세션이 끼면 판정하지 않는다 · 12 는 음성 끔 세션을 뺀다(모든 기능을 켠 상태)")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "통합.md")
        _write(p, TABLE)
        d = make_session(os.path.join(tmp, "t0"))
        info = json.load(open(os.path.join(d, "session.json"), encoding="utf-8"))
        info["입력"]["세션"] = "시험"
        _write(os.path.join(d, "session.json"), json.dumps(info, ensure_ascii=False))
        S = MR.load_session(d)
        per = [MC.count_all(S, 15.0)]
        md = MR.render([S], per, MC.merge(per), MR.load_targets(p))
        check("판정 안 함 — 시험 세션" in md and "❌ 미달" not in md and "✅ 충족" not in md, "시험 = 판정 없음")
        d2 = make_session(os.path.join(tmp, "v0"))
        info["입력"]["세션"] = "음성끔"
        info["음성"] = False
        _write(os.path.join(d2, "session.json"), json.dumps(info, ensure_ascii=False))
        _csv(os.path.join(d2, "fsm.csv"), ["t_recv_ms", "t_gui_ms", "fsm_roi", "fsm_level", "state", "expected"],
             [[1000 + 50 * i, 1030 + 50 * i, "", "", "PROCESS_RUN", "B2"] for i in range(3)])
        d1 = make_session(os.path.join(tmp, "v1"))
        Ss = [MR.load_session(x) for x in (d1, d2)]
        per = [MC.count_all(x, 15.0) for x in Ss]
        md2 = MR.render(Ss, per, MC.merge(per), MR.load_targets(p))
    row12 = next(l for l in md2.splitlines() if l.startswith("| 12 |"))
    check("10.0 fps" in row12 and "음성 끔 세션 1 뺌" in row12, row12)


def test_target_value_failures_count():
    print("\n[판정] 재생 없는 알림·ACK 없는 명령은 ∞ 로 넣는다 · 14 넘은 수·미연결 · 4 의 0 이하 수")
    M = {"V1": {"delays": [0.1, 0.2], "missing": 1},
         "14": {"n": 3, "total": [40.0, 150.0], "unsent": 1, "timeout": 0, "noreq": 0},
         "4": {"leads": [-0.02, 0.3, 0.4]}}
    tv = MR.target_value("V1", M)
    check(tv["raw"].count(float("inf")) == 1
          and MR.apply_stat(MR.parse_target("**중앙값 ≤ 0.3초**"), tv["raw"])[0] == 0.2, f"V1 = {tv}")
    tv14 = MR.target_value("14", M, MR.parse_target("**모든 건 ≤ 100 ms**"))
    check(tv14["raw"].count(float("inf")) == 1 and "100 넘음 1" in tv14["note"] and "미연결 1" in tv14["note"], f"14 = {tv14}")
    check("0 이하 1" in MR.target_value("4", M)["note"], f"4 = {MR.target_value('4', M)}")


def test_script_targets():
    print("\n[대본] 위반·머묾 대상은 레시피 버튼이어야 한다(줄 번호) · 기록에 없는 판 번호는 경고")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "a.csv")
        _write(p, "판,행동,대상,기대,메모\n1,위반,b3,,\n")
        try:
            MR.load_script(p, buttons=["B1", "B2", "B3", "B4"])
            check(False, "대상 오타를 못 잡음")
        except ValueError as e:
            check("2행" in str(e) and "b3" in str(e), f"{e}")
        d = make_session(os.path.join(tmp, "s"), script="판,행동,대상,기대,메모\n1,위반,B3,,\n5,정상,,,\n")
        check(any("판 5" in w for w in MR.warnings(MR.load_session(d))), "판 5 경고")


def test_hand_gate_warning():
    print("\n[경고] 공구를 든 동안 손 판정을 끈 구간이 있으면 알린다(공구 구간 설계 D4 · 최종 리뷰 Minor 5)")
    with tempfile.TemporaryDirectory() as tmp:
        d = make_session(os.path.join(tmp, "s"))
        check(not any("손-버튼 판정" in w for w in MR.warnings(MR.load_session(d))), "끈 적 없으면 경고 없음")
        p = os.path.join(d, "events.csv")
        rows = list(csv.reader(open(p, encoding="utf-8")))
        rows.insert(2, ["1100", "hand_gate", json.dumps({"t": 1.1, "off": True})])
        rows.insert(3, ["1200", "hand_gate", json.dumps({"t": 1.2, "off": False})])
        _csv(p, rows[0], rows[1:])
        check(any("손-버튼 판정" in w and "1번" in w for w in MR.warnings(MR.load_session(d))), "끈 구간 1번 경고")


def test_recording_compare():
    print("\n[녹화] 녹화 구간은 값에서 빼고 「⑤ 녹화 비교」 · 경고 · 끔 없으면 끝까지(측정 녹화 설계 R5)")
    with tempfile.TemporaryDirectory() as tmp:
        d = make_session(os.path.join(tmp, "s"))
        S0 = MR.load_session(d)
        check(S0.get("rec") is None and "⑤ 녹화 비교" not in MR.render([S0], [MC.count_all(S0)], MC.count_all(S0), {}),
              "녹화 없으면 ⑤ 없음")
        p = os.path.join(d, "events.csv")
        rows = list(csv.reader(open(p, encoding="utf-8")))
        rows += [["1050", "recording_on", json.dumps({"mode": "raw"})],
                 ["1150", "recording_off", json.dumps({"mode": "raw", "written": 1, "dropped": 0})]]
        _csv(p, rows[0], rows[1:])
        S = MR.load_session(d)
        check(S["rec"] is not None and all(not (1050 <= f["t"] <= 1150) for f in S["frames"])
              and [f["t"] for f in S["rec"]["frames"]] == [1100.0], f"나눔 — 나머지 {[f['t'] for f in S['frames']]}")
        w = MR.warnings(S)
        check(any("녹화 구간 1개" in x for x in w) and not any("속도 값(12" in x for x in w), f"경고 {w}")
        md = MR.render([S], [MC.count_all(S)], MC.count_all(S), {})
        check("## ⑤ 녹화 비교" in md and "| 12 FPS 중앙값 |" in md, "⑤ 표")
        rows = [r for r in rows if r[1] != "recording_off"]
        _csv(p, rows[0], rows[1:])
        S2 = MR.load_session(d)
        check(any("끔 사건이 없다" in x for x in MR.warnings(S2)), "끔 없으면 경고")


def test_voice_warnings():
    print("\n[경고] 음성 켬인데 음성 기록이 없음 · 음성 사건 버림 · 마이크 표본률 못 읽음")
    with tempfile.TemporaryDirectory() as tmp:
        d = make_session(os.path.join(tmp, "s"))
        check(any("음성 기록이 없다" in w for w in MR.warnings(MR.load_session(d))), "음성 기록 없음")
        _csv(os.path.join(d, "voice_events.csv"), ["t_ms", "kind", "data"],
             [[2000, "measure_end", json.dumps({"dropped": 2, "failed": False})]])
        check(any("음성 사건 2건" in w for w in MR.warnings(MR.load_session(d))), "음성 버림")
        keep = MR.VOICE_SRC
        MR.VOICE_SRC = os.path.join(tmp, "없음.py")
        try:
            S = MR.load_session(d)
        finally:
            MR.VOICE_SRC = keep
        check(S["rate"] is None and any("마이크 표본률" in w for w in MR.warnings(S)), "표본률 못 읽어도 보고는 돈다")


def test_targets_unreadable_row():
    print("\n[목표] 목표값 칸을 못 읽은 행은 사라지지 않고 「목표값 못 읽음」 · 12 를 못 읽으면 13 기준 없음")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "x.md")
        _write(p, TABLE.replace("**중앙값 ≥ 15 fps**", "**빠르게**"))
        t = MR.load_targets(p)
        S = MR.load_session(make_session(os.path.join(tmp, "s")))
        per = [MC.count_all(S, MR.fps_floor(t))]
        md = MR.render([S], per, MC.merge(per), t)
    row12 = next(l for l in md.splitlines() if l.startswith("| 12 |"))
    check(t["12"].get("unreadable") and "목표값 못 읽음" in row12 and MR.fps_floor(t) is None, row12)


def test_curve_arg_error():
    print("\n[명령] --curve 형식이 틀리면 트레이스백 대신 사용법 오류(종료 코드 2)")
    with tempfile.TemporaryDirectory() as tmp:
        d = make_session(os.path.join(tmp, "s"))
        try:
            MR.main([d, "--curve", "팔십"])
            check(False, "통과해 버림")
        except SystemExit as e:
            check(e.code == 2, f"종료 코드 {e.code}")



def test_guide_session():
    print("\n[판 맞춤] 대본 누름 칸 → NG 판은 그 판째 빼고 ⓪ 절에 적는다 · guide.csv 수동 N · 옛 대본은 그대로(진행 도우미 설계 D12)")
    with tempfile.TemporaryDirectory() as tmp:
        S = MR.load_session(make_session(os.path.join(tmp, "ok"), script="판,행동,대상,기대,메모,누름\n1,위반,B3,,,B3@B2\n"))
        check(S["guide"]["runs"][0]["status"] == "ok" and MC.v_prevent(S)["n"] == 1, "대본대로 = 남긴다")
        S = MR.load_session(make_session(os.path.join(tmp, "ng"), script="판,행동,대상,기대,메모,누름\n1,위반,B4,,,B4@B2\n"))
        check(S["guide"]["runs"][0]["status"] == "ng" and MC.v_prevent(S)["n"] == 0, "안내와 다른 누름 = 그 판째 뺀다")
        L = "\n".join(MR.guide_lines(S))
        check("⓪" in L and "자동 NG 1(1)" in L, L)
        d = make_session(os.path.join(tmp, "man"), script="판,행동,대상,기대,메모,누름\n1,위반,B3,,,B3@B2\n")
        _csv(os.path.join(d, "guide.csv"), ["t_ms", "kind", "data"], [[1350, "ng", json.dumps({"why": "장비"}, ensure_ascii=False)]])
        L = "\n".join(MR.guide_lines(MR.load_session(d)))
        check("수동 장비 1(1)" in L, L)
        check(MR.guide_lines(MR.load_session(make_session(os.path.join(tmp, "old")))) == [], "누름 칸 없는 옛 대본 = ⓪ 절 없음")
        # 최종 리뷰 Important 5(b) — 누름 칸 없는 대본·대본 없는 세션도 N 표시는 뺀다
        for name, sc in (("nocol", "판,행동,대상,기대,메모\n1,위반,B3,,\n"), ("noscript", "")):
            d = make_session(os.path.join(tmp, name), script=sc)
            _csv(os.path.join(d, "guide.csv"), ["t_ms", "kind", "data"], [[1350, "ng", json.dumps({"why": "사람"}, ensure_ascii=False)]])
            S = MR.load_session(d)
            check(S.get("guide") and S["guide"]["runs"][0]["status"] == "ng" and MC.v_prevent(S)["n"] == 0,
                  f"{name} — N 표시 판을 뺀다")
            check("수동 사람 1(1)" in "\n".join(MR.guide_lines(S)), f"{name} ⓪ 절")
        # 최종 리뷰 Minor 1 — 미완 판의 못 한 누름 · 대본에 없던 경고(머묾 낱말 없는 판의 경고)
        S = MR.load_session(make_session(os.path.join(tmp, "part"), script="판,행동,대상,기대,메모,누름\n1,위반,B3,,,B3@B2 B2\n"))
        L = "\n".join(MR.guide_lines(S))
        check("미완 1(1번째 판 · 못 한 누름 1)" in L and "머묾 낱말 없는 판의 경고 1번" in L, L)


def test_slow_entry_report():
    print("\n[안 B] ② 경고 이유별 수 · ④ 속도 문턱 · ① 체류 미달 단서 · ③ 곡선 단서 — 옛 세션은 그대로(최종 리뷰 Minor M-1·M-2·M-3)")
    QUAL = "(속도 문턱 위 = 빠른 손 · 속도 모름 포함)"
    NOTE3 = "⚠️ 안 B(느린 손 즉시 경고)가 켜진 세션"
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "통합.md")
        _write(p, TABLE)
        t = MR.load_targets(p)

        def md_of(*dirs):
            Ss = [MR.load_session(d) for d in dirs]
            per = [MC.count_all(S, 15.0) for S in Ss]
            return MR.render(Ss, per, MC.merge(per), t)
        old = make_session(os.path.join(tmp, "old"))
        on = make_session(os.path.join(tmp, "on"), slow=437.5, reason="slow")
        off = make_session(os.path.join(tmp, "off"), slow=0, reason="dwell")
        m_old, m_on, m_off, m_mix = md_of(old), md_of(on), md_of(off), md_of(old, on)
    row1 = lambda md: next(l for l in md.splitlines() if l.startswith("| 1 |"))              # noqa: E731
    cond = lambda md, n: next(l for l in md.splitlines() if l.startswith(f"- {n} — 장소"))   # noqa: E731
    print("  — 옛 세션(이유 · 문턱 칸 없음)")
    check("- 경고 이유 — 속도 0 · 체류 0 · 이유 없음(옛 기록) 1" in m_old, "② 이유 없는 경고 = 옛 기록으로 센다")
    check("· 갭메우기 0.3초 · 속도 경고 없음(옛 규칙) · 버튼 모델" in cond(m_old, "old"), cond(m_old, "old"))
    check(row1(m_old).endswith("| 체류 미달 0 · 처리 늦음 0 · 링에만 0 · 손 없음 0 · 기타(규칙 예외) 0 |"), f"① 덧붙임 그대로 {row1(m_old)}")
    check(QUAL not in m_old and NOTE3 not in m_old, "옛 세션에는 ①·③ 단서가 없다")
    print("  — 안 B 켬(문턱 437.5)")
    check("- 경고 이유 — 속도 1 · 체류 0 · 이유 없음(옛 기록) 0" in m_on, "② 속도 경고 1")
    check("· 갭메우기 0.3초 · 속도 문턱 VGA 437.5(XGA 700)px/s · 버튼 모델" in cond(m_on, "on"), cond(m_on, "on"))
    check(f"체류 미달 0{QUAL} · 처리 늦음 0" in row1(m_on), f"① 체류 미달 단서 {row1(m_on)}")
    L = m_on.splitlines()
    i3 = next((i for i, l in enumerate(L) if l.startswith(NOTE3)), None)
    check(i3 is not None and "실제로 걸러지는 비율이 아니다" in L[i3]
          and next(i for i, l in enumerate(L) if l.startswith("| 1.00 |")) < i3
          < next(i for i, l in enumerate(L) if l.startswith("🔴 이 곡선으로")),
          f"③ 곡선 표 바로 아래 단서 {L[i3] if i3 is not None else None}")
    print("  — 안 B 끔(문턱 0) · 섞인 통합값")
    check("· 속도 경고 끔 ·" in cond(m_off, "off") and "- 경고 이유 — 속도 0 · 체류 1 · 이유 없음(옛 기록) 0" in m_off
          and QUAL not in m_off and NOTE3 not in m_off, f"끔 = 종전 규칙 {cond(m_off, 'off')}")
    check(f"체류 미달 0{QUAL}" in row1(m_mix) and f"{NOTE3} 1/2 —" in m_mix
          and "- 경고 이유 — 속도 1 · 체류 0 · 이유 없음(옛 기록) 1" in m_mix, "섞이면 켠 세션 수를 단다 · 이유는 합친다")


def test_voice_values():
    print("\n[V5~V8] guide.csv 의 말 띠(say · said)를 읽어 세고 ②에 적는다 · V7 사람 판정 목록(음성비서 빠른 해결 설계 §2.4)")
    J = lambda **d: json.dumps(d, ensure_ascii=False)     # noqa: E731
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "통합.md")
        _write(p, TABLE)
        d = make_session(os.path.join(tmp, "v"), script="판,행동,대상,기대,메모\n1,위반,B3,,\n1,질문,지금 몇 단계야?,1단계(클린·가스차단),\n")
        _csv(os.path.join(d, "guide.csv"), ["t_ms", "kind", "data"],
             [[950, "cue", J(run=1, script=1, tok=0, key="cue_B1")],
              [1000, "say", J(run=1, script=1, tok=1, text="지금 몇 단계야?", emergency=False)],
              [1200, "said", J(run=1, tok=1, why="질문", attempts=1)]])
        _csv(os.path.join(d, "voice_events.csv"), ["t_ms", "kind", "data"],
             [[1100, "stt", J(text="가디언 지금 몇 단계야", stt_ms=40, utter_sec=1.0)], [1150, "wake", "{}"],
              [1300, "answer", J(src="LLM", text="지금 2단계입니다.")], [1350, "play_start", J(key=None)]])
        S = MR.load_session(d)
        check([k for _, k, _ in S["says"]] == ["say", "said"], f"말 띠 = say · said 만 · {S['says']}")
        per = [MC.count_all(S, 15.0)]
        md = MR.render([S], per, MC.merge(per), MR.load_targets(p))
        check("V5 호출 인식 — 말 띠 1개" in md and "호출 1(100.0%)" in md, "V5 줄")
        check("V6 받아쓰기 — 글자 오류율 0.0%" in md, "V6 줄")
        check("V7 답 지연 — 질문 받아쓰기 → 답 보내기 중앙 0.200초" in md and "LLM 0.200초(1)" in md, "V7 지연 줄")
        check("틀림 후보 1" in md and "V7 사람 판정 목록" in md and "「지금 2단계입니다.」" in md, "V7 초벌 · 사람 판정 목록")
        check("V8 비상 중 무반응 — 해당 없음" in md, "V8 — 비상질문 띠 없음")
        check("V6 도메인 낱말 — 해당 없음" in md, "V6 도메인 낱말 — 띠 문장에 없음")
        print("  — 음성 기록 · guide.csv 가 없는 세션(알림 끔 · 음성 끔 · 옛 세션)은 죽지 않고 해당 없음")
        S = MR.load_session(make_session(os.path.join(tmp, "old")))
        per = [MC.count_all(S, 15.0)]
        md = MR.render([S], per, MC.merge(per), MR.load_targets(p))
        check(S["says"] == [] and all(f"{v} — 음성 기록 없음" in md for v in ("V5 호출 인식", "V6 받아쓰기", "V7 답", "V8 비상 중 무반응")),
              "V5~V8 = 음성 기록 없음")


def test_alert_drop_lines():
    print("\n[V1 · V2] 밀린 알림은 V1 덧붙임 · V2 「밀림」으로 따로 · 알림 끈 세션의 V2 = 해당 없음(최종 리뷰 I-2 · b)")
    tv = MR.target_value("V1", {"V1": {"delays": [0.1], "missing": 1, "dropped": 2}})
    check(tv["n"] == 2 and "밀림 2" in tv["note"], f"V1 = {tv}")
    line = MR._v2_line({"trans": 3, "one": 1, "zero": 1, "multi": 0, "dropped": 1, "normal": 0})
    check("전이 3 가운데 알림 한 번 1 · 없음 1 · 여러 번 0 · 밀림 1" in line, line)
    check("해당 없음(알림 끈 세션" in MR._v2_line({"alerts_off": 1}) and "음성 기록 없음" in MR._v2_line({"off": 1}),
          f"{MR._v2_line({'alerts_off': 1})} · {MR._v2_line({'off': 1})}")
    line = MR._v2_line({"trans": 2, "one": 2, "zero": 0, "multi": 0, "dropped": 0, "normal": 0, "alerts_off": 1})
    check("알림 끈 세션 1 뺌" in line, line)


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 세기 보고 도구 검증 통과")
