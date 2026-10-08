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


def make_session(d, script="판,행동,대상,기대,메모\n1,위반,B3,,\n", truncate=False):
    os.makedirs(d, exist_ok=True)
    info = {"입력": {"장소": 1, "세션": "위반", "손": "맨손", "사람": 1, "조명": "", "대본": "대본.csv" if script else "",
                     "펌웨어": "glass_voice"},
            "설정": {"FSM_DWELL_THRESHOLD_SEC": 0.3, "FSM_GAP_FILL_SEC": 0.3, "PRESS_CONFIRM_GRACE_SEC": 0.5,
                     "HEF_MODEL_PATH": "/x/B.hef"},
            "측정기록": True, "음성": True, "코드": {"Rpi5": "abc1234"}}
    _write(os.path.join(d, "session.json"), json.dumps(info, ensure_ascii=False))
    _csv(os.path.join(d, "frames.csv"), ["frame", "t_recv_ms", "recv_seq", "t_start_ms", "t_done_ms", "decode_ms", "orient_ms",
                                         "detect_ms", "track_ms", "hand_ms", "tool_ms", "zone_ms", "tip_x", "tip_y", "tip_score",
                                         "roi", "level"],
         [[i + 1, 1000 + 100 * i, i + 1, 1010 + 100 * i, 1060 + 100 * i, 5, "", "", "", "", "", "", "", "", "", r, l]
          for i, (r, l) in enumerate([("", ""), ("B3", 2), ("B3", 2)])])
    _csv(os.path.join(d, "fsm.csv"), ["t_recv_ms", "t_gui_ms", "fsm_roi", "fsm_level", "state", "expected"],
         [[1000 + 100 * i, 1030 + 100 * i, r, l, "PROCESS_RUN", "B2"] for i, (r, l) in enumerate([("", ""), ("B3", 2), ("B3", 2)])])
    ev = [[900, "run_start", "{}"], [1250, "state", json.dumps({"old": "PROCESS_RUN", "new": "WARNING", "expected": "B2", "dwell_roi": "B3"})],
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
        check(S["script"] == [{"판": 1, "행동": "위반", "대상": "B3", "기대": "", "메모": ""}], f"대본 = {S['script']}")
        check(S["emo"] == MR.emo_button() and S["kind"] == "위반" and S["rate"] == MR.mic_rate(), "EMO · 종류 · 표본률")
        check(MC.v_prevent(S) == {"n": 1, "k": 1, "late": 0}, f"1 = {MC.v_prevent(S)}")


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
        check(MR.main([d]) == 0 and os.path.exists(os.path.join(d, "report.md")) and os.path.exists(os.path.join(d, "report.json")),
              "main → report.md · report.json")


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 세기 보고 도구 검증 통과")
