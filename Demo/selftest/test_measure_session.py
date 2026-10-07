"""측정 세션 정보(측정 도구 정합 §4.3 세션 정보·용량) — 폴더 이름 · session.json · 남은 공간.

실행: python3 Demo/selftest/test_measure_session.py
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import measure_session as MS

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_dir_name():
    print("\n[세션] 폴더 이름 = 날짜_시각_장소_세션")
    n = MS.session_dir_name(1, 2, now=datetime.datetime(2026, 10, 7, 9, 5, 3))
    check(n == "20261007_090503_장소1_위반", n)


def test_session_json():
    print("\n[세션] session.json — 입력 · 시작 시각 둘 · 코드 버전 · 설정값")
    d = tempfile.mkdtemp()
    rec = MS.write_session(d, {"장소": 1, "세션": 1, "손": 1, "사람": 2, "조명": "형광등"}, measure_on=True)
    with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    check(on_disk == rec, "파일과 반환이 같다")
    for k in ("입력", "시작_벽시계", "시작_단조_ms", "코드", "설정", "측정기록"):
        check(k in rec, f"칸 {k}")
    missing = [k for k in MS.SETTINGS if rec["설정"][k] is None]
    check(not missing, f"config 에 없는 설정 이름 {missing} — 이름이 틀렸거나 config 에서 사라졌다")


def test_cli_prints_dir():
    print("\n[세션] CLI 가 폴더를 만들고 경로를 한 줄 출력 · 대본은 원래 이름으로 복사 · 펌웨어 기본값")
    base = tempfile.mkdtemp()
    script = os.path.join(tempfile.mkdtemp(), "대본_시험.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write("1판 B1 B2 B3 B4\n")
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base,
                        "--place", "2", "--kind", "0", "--hand", "1", "--person", "1", "--on", "1",
                        "--script", script],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    check(r.returncode == 0 and os.path.isfile(os.path.join(out, "session.json")) and out.endswith("_장소2_시험"),
          f"{r.returncode} {out} {r.stderr[-200:]}")
    check(os.path.isfile(os.path.join(out, "대본_시험.txt")), "대본 복사")
    with open(os.path.join(out, "session.json"), encoding="utf-8") as f:
        check(json.load(f)["입력"]["펌웨어"] == "glass_voice", "펌웨어 기본값")


def test_voice_off_recorded():
    print("\n[세션] 음성 끔 세션이면 session.json 에 음성 끔 — 실행기가 SOP_VOICE 를 먼저 내보낸다")
    base = tempfile.mkdtemp()
    env = dict(os.environ, SOP_VOICE="0")
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base,
                        "--place", "1", "--kind", "4", "--hand", "1", "--person", "1", "--on", "1"],
                       capture_output=True, text=True, env=env)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    with open(os.path.join(out, "session.json"), encoding="utf-8") as f:
        check(json.load(f)["음성"] is False, "음성 False")
    with open(os.path.join(_DEMO_DIR, "run_measure.sh"), encoding="utf-8") as f:
        sh = f.read()
    check(sh.index("SOP_VOICE=0") < sh.index("measure_session.py"),
          "run_measure.sh 가 SOP_VOICE=0 을 세션 정보 쓰기 **앞에** 내보낸다")


if __name__ == "__main__":
    test_dir_name()
    test_session_json()
    test_cli_prints_dir()
    test_voice_off_recorded()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 측정 세션 정보 검증 통과")
