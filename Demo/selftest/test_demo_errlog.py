"""시연 런처 — 파이썬 오류 출력(트레이스백)을 파일에도 남긴다(최종 정리 2026-10-15).

시연 프로그램이 오류로 꺼지면 트레이스백은 터미널 창에만 찍히고, Enter 를 누르거나 창을 닫으면 사라진다
(GUI 로그 `logs/*_log.txt` 에는 남지 않는다). 런처가 오류 출력을 `logs/demo_err_<시각>.log` 에도 복사하는지,
그러면서 종료 코드 · 「오류일 때만 창을 붙잡는」 동작이 그대로인지 본다. main.py 는 가짜(GUI 를 띄우지 않는다).

실행: python3 Demo/selftest/test_demo_errlog.py
"""
import glob
import os
import shutil
import signal
import subprocess
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _copy(main_src):
    """진짜 run_demo.sh · run_voice.sh 를 임시 폴더에 복사하고 가짜 main.py 를 둔다 → 폴더."""
    d = tempfile.mkdtemp()
    for n in ("run_demo.sh", "run_voice.sh"):
        shutil.copy(os.path.join(_DEMO_DIR, n), d)
    with open(os.path.join(d, "main.py"), "w", encoding="utf-8") as f:
        f.write(main_src)
    return d


def _errlogs(d):
    return sorted(glob.glob(os.path.join(d, "logs", "demo_err_*.log")))


def _run(main_src, merged=False):
    """음성비서를 끈 채 돌린다 — (결과, 오류 기록 파일 목록). merged = 표준 출력 · 오류를 한 줄기로(순서 검사)."""
    d = _copy(main_src)
    r = subprocess.run(["bash", os.path.join(d, "run_demo.sh")], env=dict(os.environ, SOP_VOICE="0"),
                       input="\n", stdout=subprocess.PIPE, text=True, timeout=30,
                       stderr=subprocess.STDOUT if merged else subprocess.PIPE)
    return r, _errlogs(d)


def _read(logs):
    return open(logs[0], encoding="utf-8").read() if logs else ""


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


def test_voice_on_launcher_returns():
    print("\n[시연 런처] 음성비서를 켠 기본 설정 — 시연이 끝나면 런처도 끝나고 음성비서도 꺼진다(코드 리뷰 Critical 1)")
    d = _copy('print("정상")\n')
    fake = os.path.join(d, "fake_voice_py")
    with open(fake, "w") as f:      # 끝나지 않는 음성 데몬 흉내 — 코드 3(「이미 돈다」)으로 물러나지 않는다
        f.write("#!/bin/bash\nexec sleep 61.234\n")     # exec = 진짜 데몬처럼 프로세스 하나
    os.chmod(fake, 0o755)
    p = subprocess.Popen(["bash", os.path.join(d, "run_demo.sh")], env=dict(os.environ, SOP_VOICE="1", SOP_VOICE_PY=fake),
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    try:
        out, _ = p.communicate(timeout=10)
        returned = True
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        returned = False
    check(returned and p.returncode == 0, f"10초 안에 끝남 · 코드 {p.returncode}")
    check("=== 종료 (exit code: 0)" in out, f"종료 줄 · {out[-200:]!r}")
    time.sleep(0.5)
    left = subprocess.run(["pgrep", "-f", "[s]leep 61.234"], capture_output=True, text=True).stdout.split()
    check(left == [], f"음성 데몬이 남지 않음 · {left}")
    for pid in left:
        os.kill(int(pid), signal.SIGKILL)


def test_traceback_before_end_line():
    print("\n[시연 런처] 트레이스백이 「=== 종료」 · 「Enter」 안내보다 먼저 나온다(복사가 끝난 뒤에 끝낸다)")
    r, logs = _run('raise RuntimeError("순서 시험 11223")\n', merged=True)
    out = r.stdout
    i, j = out.find("순서 시험 11223"), out.find("=== 종료")
    check(0 <= i < j, f"트레이스백 {i} < 종료 줄 {j}")
    check("순서 시험 11223" in _read(logs), "파일에도")


def test_native_crash_leaves_record():
    print("\n[시연 런처] 파이썬 바깥 오류(세그폴트)로 죽어도 기록이 남는다 — 종료 코드 · 파이썬 위치(코드 리뷰 Important 3)")
    r, logs = _run('import os, signal\nos.kill(os.getpid(), signal.SIGSEGV)\n')
    check(r.returncode == 139, f"종료 코드 139 · {r.returncode}")
    body = _read(logs)
    check("exit code 139" in body, f"파일에 종료 코드 · {body[-200:]!r}")
    check("Segmentation fault" in body, "파일에 파이썬 위치(faulthandler)")


def test_ctrl_c_keeps_traceback():
    print("\n[시연 런처] Ctrl+C 로 끝나도 트레이스백이 터미널 · 파일에 남는다(코드 리뷰 Important 2)")
    d = _copy('import sys, time\nprint("준비", flush=True)\ntime.sleep(30)\n')
    p = subprocess.Popen(["bash", os.path.join(d, "run_demo.sh")], env=dict(os.environ, SOP_VOICE="0"),
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    out = p.stdout
    assert out is not None
    for _ in range(10):
        if "준비" in out.readline():
            break
    os.killpg(p.pid, signal.SIGINT)     # 터미널의 Ctrl+C 처럼 무리 전체에
    try:
        _, err = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        _, err = p.communicate()
    check("KeyboardInterrupt" in err, f"터미널에 트레이스백 · {err[-200:]!r}")
    check("KeyboardInterrupt" in _read(_errlogs(d)), f"파일에도 · {_errlogs(d)}")


def test_signal_end_leaves_no_empty_file():
    print("\n[시연 런처] 창 닫기 · 종료 신호로 끝나도 빈 오류 기록 파일을 남기지 않는다(코드 리뷰 Minor 4)")
    d = _copy('import time\nprint("준비", flush=True)\ntime.sleep(30)\n')
    p = subprocess.Popen(["bash", os.path.join(d, "run_demo.sh")], env=dict(os.environ, SOP_VOICE="0"),
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    out = p.stdout
    assert out is not None
    for _ in range(10):
        if "준비" in out.readline():
            break
    os.killpg(p.pid, signal.SIGHUP)     # 터미널 창을 닫으면 무리 전체가 받는다
    try:
        p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
    time.sleep(0.3)
    check(_errlogs(d) == [], f"빈 파일 없음 · {_errlogs(d)}")


def test_warning_kept_on_clean_exit():
    print("\n[시연 런처] 정상 종료여도 오류 출력(경고)이 있었으면 남긴다")
    r, logs = _run('import sys\nsys.stderr.write("경고 한 줄 24680\\n")\n')
    check(r.returncode == 0 and len(logs) == 1, f"코드 {r.returncode} · {logs}")
    body = open(logs[0], encoding="utf-8").read() if logs else ""
    check("경고 한 줄 24680" in body, "경고가 파일에")


def test_guide_started_and_stopped():
    print("\n[시연 런처] 시연 안내 프로그램을 늘 함께 띄우고(음성비서를 꺼도) · 시연이 끝나면 끈다(시연 안내 2026-10-18 §6.1)")
    d = _copy('import time\ntime.sleep(1)\nprint("정상")\n')
    mark = os.path.join(d, "guide_started")
    fake = os.path.join(d, "fake_guide_py")
    with open(fake, "w") as f:      # 끝나지 않는 안내 프로그램 흉내 — 받은 인자를 적고 sleep 으로 바뀐다
        f.write(f'#!/bin/bash\necho "$@" > {mark}\nexec sleep 62.345\n')
    os.chmod(fake, 0o755)
    r = subprocess.run(["bash", os.path.join(d, "run_demo.sh")], env=dict(os.environ, SOP_VOICE="0", SOP_GUIDE_PY=fake),
                       input="\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
    check(r.returncode == 0, f"종료 코드 0 · {r.returncode}")
    started = open(mark, encoding="utf-8").read() if os.path.exists(mark) else ""
    check("demo_guide.py" in started, f"안내 프로그램을 띄웠다 · {started!r}")
    time.sleep(0.5)
    left = subprocess.run(["pgrep", "-f", "[s]leep 62.345"], capture_output=True, text=True).stdout.split()
    check(left == [], f"시연이 끝나면 안내 프로그램이 남지 않는다 · {left}")
    for pid in left:
        os.kill(int(pid), signal.SIGKILL)
    check(not glob.glob(os.path.join(d, "logs", "guide_err_*.log")), "오류가 없으면 안내 오류 기록 파일을 남기지 않는다")


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
