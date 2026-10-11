"""실행기 — 처리 설정 번호 · 셸에 남은 스위치 지우기 · 몇 판부터 · 리허설 측정 폴더(학교 방문 준비 설계 §3.4 · §8.1 V15 · §7.1).

실행: python3 Demo/selftest/test_measure_runner.py
"""
import json
import os
import subprocess
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

_fails = []
SCRIPT = "판,행동,대상,기대,메모,누름\n1,정상,,,,B1 B2 B3 B4\n2,정상,,,,B1 B2 B3 B4\n3,정상,,,,B1 B2 B3 B4\n"


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _script_file(d):
    p = os.path.join(d, "시험대본.csv")
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write(SCRIPT)
    return p


def _runner(answers, extra_env=None):
    """실행기를 표준입력 답으로 돌린다 — 시연 대신 환경변수를 적어 두는 스크립트를 띄운다."""
    d = tempfile.mkdtemp()
    probe = os.path.join(d, "probe.sh")
    with open(probe, "w") as f:
        f.write('#!/bin/bash\nenv | grep -E "^SOP_(ORIENT|DISPLAY|INFER|PIPELINE)" | sort > "$PROBE_OUT"\n')
    env = dict(os.environ, SOP_MEASURE_BASE=os.path.join(d, "measure"), SOP_DEMO_LAUNCHER=probe,
               PROBE_OUT=os.path.join(d, "env.txt"), **(extra_env or {}))
    r = subprocess.run(["bash", os.path.join(_DEMO_DIR, "run_measure.sh")], input="\n".join(answers) + "\n\n\n",
                       capture_output=True, text=True, env=env, timeout=60)
    seen = open(env["PROBE_OUT"]).read().split() if os.path.exists(env["PROBE_OUT"]) else None
    sessions = [os.path.join(env["SOP_MEASURE_BASE"], n) for n in sorted(os.listdir(env["SOP_MEASURE_BASE"]))] \
        if os.path.isdir(env["SOP_MEASURE_BASE"]) else []
    return r, seen, sessions


def _answers(script="", from_run="", processing=""):
    # 장소 · 세션 · 손 · 사람 · 조명 · 대본 · 몇 판부터 · 펌웨어 · 안경 전원 · 처리 설정 · 측정 기록(0 = 끔 → 세기 안 함) · 음성 알림
    return ["1", "0", "1", "1", "", script, from_run, "", "", processing, "0", ""]


def test_processing_numbers():
    print("\n[실행기] 처리 설정 번호 → 스위치 · 셸에 남은 스위치는 먼저 지운다(Review Focus 1)")
    stale = {"SOP_DISPLAY_EVERY": "2", "SOP_INFER_MODEL": "1"}
    r, seen, sessions = _runner(_answers(processing=""), stale)
    check(seen == [], f"엔터(1 = 1단계) → 남은 스위치 없음 · {seen} · {r.stderr[-200:]}")
    s = json.load(open(os.path.join(sessions[0], "session.json"), encoding="utf-8"))
    check(s["설정"]["DISPLAY_EVERY"] == 1 and s["설정"]["INFER_MODEL"] is False, f"session.json 설정 {s['설정'].get('INFER_MODEL')}")
    r, seen, _ = _runner(_answers(processing="2"))
    check(seen == ["SOP_DISPLAY_PAINT=0", "SOP_ORIENT_ONE_REMAP=0"], f"2 = 종전 → {seen}")
    r, seen, _ = _runner(_answers(processing="5"))
    check(seen == ["SOP_INFER_MODEL=1", "SOP_PIPELINE2=1"], f"5 = 1단계+2a+2b → {seen}")
    r, seen, sessions = _runner(_answers(processing="9"))
    check(r.returncode != 0 and seen is None and sessions == [], f"없는 번호 → 시연 · 폴더 없이 멈춤(코드 {r.returncode})")


def test_from_run():
    print("\n[실행기] 몇 판부터 — 그 판부터의 줄만 세션에 복사 · 판 번호는 그대로 · 잘못된 값은 폴더 전에 멈춤(Review Focus 3)")
    d = tempfile.mkdtemp()
    sc = _script_file(d)
    r, seen, sessions = _runner(_answers(script=sc, from_run="2"))
    check(len(sessions) == 1, f"세션 하나 · {r.stdout[-300:]}")
    copied = open(os.path.join(sessions[0], "시험대본.csv"), encoding="utf-8-sig").read().splitlines()
    check([ln.split(",")[0] for ln in copied] == ["판", "2", "3"], f"복사된 판 {copied}")
    s = json.load(open(os.path.join(sessions[0], "session.json"), encoding="utf-8"))
    check(s["입력"].get("시작판") == 2, f"session.json 시작판 {s['입력'].get('시작판')}")
    for bad in ("4", "0", "abc"):
        r, seen, sessions = _runner(_answers(script=sc, from_run=bad))
        check(r.returncode != 0 and sessions == [], f"몇 판부터 {bad!r} → 폴더 없이 멈춤")


def test_measure_base_followed():
    print("\n[리허설 폴더] SOP_MEASURE_BASE 를 진행 도우미도 따른다(Review Focus 2)")
    env = dict(os.environ, SOP_MEASURE_BASE="/tmp/리허설시험/measure")
    r = subprocess.run([sys.executable, "-c", "import measure_guide as G, measure_session as S; "
                        "print(G.MEASURE_DIR); print(S.BASE); print(S.SCENARIO_DIR)"],
                       cwd=_DEMO_DIR, env=env, capture_output=True, text=True)
    out = r.stdout.split()
    check(out[:2] == ["/tmp/리허설시험/measure"] * 2, f"진행 도우미 · 세션 = {out[:2]}")
    check(out[2:] == [os.path.join(_DEMO_DIR, "measure", "시나리오")], f"대본 목록은 그대로 Demo/measure/시나리오 = {out[2:]}")


def test_report_processing_line():
    print("\n[세기] ④ 조건 줄에 2a · 2b")
    import measure_report as MR
    line = MR._processing({"ORIENT_ONE_REMAP": True, "DISPLAY_SCALE_IN_PAINT": True, "DISPLAY_EVERY": 1,
                           "INFER_MODEL": True, "PIPELINE2": False})
    check(line.endswith("· 2a 켬 · 2b 끔"), line)
    old = MR._processing({"ORIENT_ONE_REMAP": True, "DISPLAY_SCALE_IN_PAINT": True, "DISPLAY_EVERY": 1})
    check("2a" not in old, f"2단계 기록 전 세션은 그대로 — {old}")


if __name__ == "__main__":
    test_processing_numbers()
    test_from_run()
    test_measure_base_followed()
    test_report_processing_line()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 실행기 검증 통과")
