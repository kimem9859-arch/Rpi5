"""음성비서 상시 가동 — run_voice.sh --forever (설계 2026-10-03 §4.6 · D1′).

실행: python3 Demo/selftest/test_voice_supervisor.py
⚠️ 진짜 음성비서를 띄우지 않는다 — SOP_VOICE_PY 로 가짜 파이썬(셸 스크립트)을 넣는다.
"""
import os
import subprocess
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(_DEMO_DIR, "run_voice.sh")
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def fake_python(d, body):
    p = os.path.join(d, "fakepy")
    with open(p, "w") as f:
        f.write("#!/bin/bash\n" + body)
    os.chmod(p, 0o755)
    return p


def test_restarts_and_stops_cleanly():
    print("\n[감시] 죽으면 다시 띄우고, 끌 때 자식도 끈다")
    d = tempfile.mkdtemp()
    cnt, pidf = os.path.join(d, "n"), os.path.join(d, "pid")
    py = fake_python(d, f'n=$(($(cat {cnt} 2>/dev/null || echo 0) + 1)); echo $n > {cnt}\n'
                        f'if [ $n -le 2 ]; then exit 1; fi\necho $$ > {pidf}; exec sleep 60\n')
    p = subprocess.Popen(["bash", RUN, "--forever"], env=dict(os.environ, SOP_VOICE_PY=py),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    end = time.time() + 15
    while time.time() < end and not os.path.exists(pidf):
        time.sleep(0.2)
    check(open(cnt).read().strip() == "3", "두 번 죽고 세 번째로 떴다")
    p.terminate()
    out, _ = p.communicate(timeout=10)
    check(p.returncode == 0, f"끌 때 코드 0 · {p.returncode}")
    check(out.count("다시 띄운다") == 2, f"다시 띄운 기록 2번 · {out.strip()}")
    child = int(open(pidf).read())
    time.sleep(0.5)
    try:
        os.kill(child, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    check(not alive, "자식(음성비서)도 끝났다")


def test_already_running_stops_supervisor():
    print("\n[감시] 이미 돌면(코드 3) 감시를 멈춘다")
    d = tempfile.mkdtemp()
    py = fake_python(d, "exit 3\n")
    r = subprocess.run(["bash", RUN, "--forever"], env=dict(os.environ, SOP_VOICE_PY=py),
                       capture_output=True, text=True, timeout=15)
    check(r.returncode == 0 and "이미" in r.stdout, f"코드 {r.returncode} · {r.stdout.strip()}")


def test_run_demo_starts_and_stops_voice():
    """run_demo.sh 가 음성비서를 함께 띄우고 끝낼 때 끈다 — 줄 단위로 확인(GUI 를 띄우지 않는다)."""
    print("\n[run_demo] 함께 켜고 함께 끈다")
    src = open(os.path.join(_DEMO_DIR, "run_demo.sh"), encoding="utf-8").read()
    check("run_voice.sh --forever" in src, "음성비서를 감시 모드로 띄운다")
    check('SOP_VOICE:-1' in src, "SOP_VOICE=0 으로 끌 수 있다")
    check("trap stop_voice EXIT" in src, "끝날 때 끈다")
    r = subprocess.run(["bash", "-n", os.path.join(_DEMO_DIR, "run_demo.sh")], capture_output=True, text=True)
    check(r.returncode == 0, f"문법 · {r.stderr.strip()}")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 음성비서 상시 가동 검증 통과")
