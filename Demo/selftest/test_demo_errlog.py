"""시연 런처 — 파이썬 오류 출력(트레이스백)을 파일에도 남긴다(캡스톤 대회 준비 2026-10-15).

시연 프로그램이 오류로 꺼지면 트레이스백은 터미널 창에만 찍히고, Enter 를 누르거나 창을 닫으면 사라진다
(GUI 로그 `logs/*_log.txt` 에는 남지 않는다). 런처가 오류 출력을 `logs/demo_err_<시각>.log` 에도 복사하는지,
그러면서 종료 코드 · 「오류일 때만 창을 붙잡는」 동작이 그대로인지 본다. main.py 는 가짜(GUI 를 띄우지 않는다).

실행: python3 Demo/selftest/test_demo_errlog.py
"""
import glob
import os
import shutil
import subprocess
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _run(main_src):
    """진짜 run_demo.sh 를 임시 폴더에 복사하고 가짜 main.py 로 돌린다 — (결과, 오류 기록 파일 목록)."""
    d = tempfile.mkdtemp()
    shutil.copy(os.path.join(_DEMO_DIR, "run_demo.sh"), d)
    with open(os.path.join(d, "main.py"), "w", encoding="utf-8") as f:
        f.write(main_src)
    r = subprocess.run(["bash", os.path.join(d, "run_demo.sh")], env=dict(os.environ, SOP_VOICE="0"),
                       input="\n", capture_output=True, text=True, timeout=30)
    return r, sorted(glob.glob(os.path.join(d, "logs", "demo_err_*.log")))


def test_traceback_saved():
    print("\n[시연 런처] 오류로 꺼지면 트레이스백이 파일에도 남는다 · 터미널에도 그대로 · 종료 코드 그대로")
    r, logs = _run('raise RuntimeError("가짜 화면 오류 12345")\n')
    check(len(logs) == 1, f"오류 기록 파일 1개 · {logs}")
    body = open(logs[0], encoding="utf-8").read() if logs else ""
    check("Traceback" in body and "가짜 화면 오류 12345" in body, f"파일에 트레이스백 · {body[-200:]!r}")
    check("가짜 화면 오류 12345" in r.stderr, "터미널(표준 오류)에도 그대로 보인다")
    check(r.returncode == 1, f"종료 코드 = 파이썬 코드(1) · {r.returncode}")
    check("창을 닫으려면 Enter" in r.stdout, "오류일 때 창을 붙잡는다")


def test_abort_code_kept():
    print("\n[시연 런처] PyQt6 처럼 abort 로 끝나도 종료 코드(134)와 그 전 출력이 남는다")
    r, logs = _run('import os, sys\nsys.stderr.write("슬롯 예외 흉내 67890\\n")\nsys.stderr.flush()\nos.abort()\n')
    check(r.returncode == 134, f"종료 코드 134 · {r.returncode}")
    body = open(logs[0], encoding="utf-8").read() if logs else ""
    check("슬롯 예외 흉내 67890" in body, f"abort 전 출력이 파일에 · {logs}")


def test_clean_run_leaves_nothing():
    print("\n[시연 런처] 오류 출력이 없는 정상 종료는 빈 파일을 남기지 않는다 · 창을 붙잡지 않는다")
    r, logs = _run('print("정상")\n')
    check(r.returncode == 0, f"종료 코드 0 · {r.returncode}")
    check(logs == [], f"오류 기록 파일 없음 · {logs}")
    check("창을 닫으려면 Enter" not in r.stdout, "정상이면 창을 붙잡지 않는다")


def test_warning_kept_on_clean_exit():
    print("\n[시연 런처] 정상 종료여도 오류 출력(경고)이 있었으면 남긴다")
    r, logs = _run('import sys\nsys.stderr.write("경고 한 줄 24680\\n")\n')
    check(r.returncode == 0 and len(logs) == 1, f"코드 {r.returncode} · {logs}")
    body = open(logs[0], encoding="utf-8").read() if logs else ""
    check("경고 한 줄 24680" in body, "경고가 파일에")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("  -", m)
        raise SystemExit(1)
    print("✅ 전부 통과")
