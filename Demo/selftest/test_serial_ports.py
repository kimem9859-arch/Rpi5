"""serial_ports — pyserial 이 없는 파이썬에서도 상수·무선 오디오가 되는가 · 있을 때 포트 찾기는 그대로인가.

실행: python3 Demo/selftest/test_serial_ports.py

🔴 왜 이 시험이 있나 — 2026-10-06 실콘솔 음성 관문 G2 ❌(조사/실콘솔-20261006/README.md).
   gate_check.sh 의 PY(tts venv)에는 pyserial 이 없는데, esp32_audio.py 가 맨 위에서
   serial_ports 를 import 하고 serial_ports 가 맨 위에서 serial.tools 를 import 해서
   --tcp(무선) 경로가 시리얼을 안 쓰는데도 소리를 보내기 전에 ModuleNotFoundError 로 죽었다.
🔑 관문 파이썬은 gate_check.sh 의 PY 줄에서 읽는다 — 관문이 바꾸면 시험도 따라간다.
   그 파이썬이 없을 때만 건너뛴다(run_all 규칙과 같다 — 모듈 오류는 건너뜀이 아니다).
🔑 HW 에 닿지 않는다 — 무선 재생 상대는 127.0.0.1 의 모의 글라스(Demo/test/fake_glass.py)다.
"""
import os
import re
import subprocess
import sys
import tempfile
import types
import wave

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RPI5 = os.path.dirname(_DEMO_DIR)
_ESP32_AUDIO = os.path.join(_RPI5, "arduino", "mic_speaker_test", "esp32_audio.py")
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _gate_python():
    """gate_check.sh 가 쓰는 파이썬 경로 — 없으면 None(건너뜀). PY 줄을 못 읽으면 실패로 남긴다."""
    src = open(os.path.join(_DEMO_DIR, "voice", "gate_check.sh"), encoding="utf-8").read()
    m = re.search(r'^PY="([^"]+)"', src, re.M)
    check(m is not None, "gate_check.sh 에서 PY 줄을 읽었다")
    if not m:
        return None
    py = os.path.expandvars(m.group(1))
    if not os.path.exists(py):
        print(f"  ⏭ 관문 파이썬이 없어 건너뜀 — {py}")
        return None
    return py


def _tail(r, n=3):
    lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
    return " | ".join(lines[-n:])


def test_constant_without_pyserial():
    print("\n[관문 파이썬] serial_ports 상수 import")
    py = _gate_python()
    if not py:
        return
    r = subprocess.run([py, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                                  "import serial_ports; print(serial_ports.ESP32_S3)", _DEMO_DIR],
                       capture_output=True, text=True, timeout=30)
    check(r.returncode == 0 and r.stdout.strip() == str((0x303A, 0x1001)),
          f"ESP32_S3 를 읽는다 — 코드 {r.returncode} · {_tail(r)}")


def test_gate_g2_without_pyserial():
    """관문 G2 그대로 — 순음 wav 를 만들고 --tcp 로 보내 「ok」(적재 체크섬 일치)가 나오는가."""
    print("\n[관문 파이썬] G2 순음 생성 · 무선 재생(모의 글라스)")
    py = _gate_python()
    if not py:
        return
    wav = os.path.join(tempfile.mkdtemp(), "gate_tone.wav")
    r = subprocess.run([py, _ESP32_AUDIO, "tone", "1000", "1", wav],
                       capture_output=True, text=True, timeout=30)
    check(r.returncode == 0 and os.path.exists(wav), f"tone — 코드 {r.returncode} · {_tail(r)}")
    if not os.path.exists(wav):
        return
    with wave.open(wav) as w:
        check(w.getnframes() == 16000 and w.getframerate() == 16000, "1초 · 16kHz 순음")

    from fake_glass import FakeGlass
    g = FakeGlass([], mic_port=0, cmd_port=0, play_speed=0.01, quiet=True).start()
    try:
        r = subprocess.run([py, _ESP32_AUDIO, "--tcp", f"127.0.0.1:{g.cmd_port}", "play", wav],
                           capture_output=True, text=True, timeout=60)
    finally:
        g.stop()
    # gate_check.sh 의 G2 판정 = 출력에 "ok" 가 있는가([적재] … ok)
    check(r.returncode == 0 and "ok" in r.stdout, f"play --tcp — 코드 {r.returncode} · {_tail(r)}")
    check(("write", 16000, 16000, True) in g.events and g.count("play") == 1,
          f"모의 글라스가 체크섬 일치로 적재·재생했다 — {[e for e in g.events if e[0] != 'cmd_conn']}")


def test_resolve_describe_with_pyserial():
    """pyserial 이 있으면 포트 찾기는 그대로 — 부를 때마다 comports() 를 새로 본다(나중에 꽂아도 찾는다)."""
    print("\n[pyserial 있음] resolve · describe")
    try:
        from serial.tools import list_ports
    except ImportError:
        print("  ⏭ 이 파이썬에 pyserial 이 없어 건너뜀")
        return
    import serial_ports as sp

    def port(dev, vid, pid, sn, product):
        return types.SimpleNamespace(device=dev, vid=vid, pid=pid, serial_number=sn, product=product)

    arduino = port("/dev/ttyACM0", 0x2341, 0x1002, "A1", "UNO R4")
    esp_a = port("/dev/ttyACM1", 0x303A, 0x1001, "E1", None)
    esp_b = port("/dev/ttyACM2", 0x303A, 0x1001, "E2", "ESP32S3")
    nousb = port("/dev/ttyAMA0", None, None, None, None)
    old = list_ports.comports
    try:
        list_ports.comports = lambda: []
        check(sp.resolve(*sp.ESP32_S3) is None, "장치가 없으면 None")
        check(sp.describe() == [], "장치가 없으면 빈 목록")
        list_ports.comports = lambda: [nousb, arduino, esp_a, esp_b]
        check(sp.resolve(*sp.ESP32_S3) == "/dev/ttyACM1", "나중에 꽂힌 것도 찾는다 — 첫 ESP32-S3")
        check(sp.resolve(0x303A, serial_number="E2") == "/dev/ttyACM2", "시리얼번호로 고른다")
        check(sp.resolve(0x303A, 0x9999) is None, "pid 가 다르면 None")
        check(sp.describe() == [
            "/dev/ttyACM0  vid=2341 pid=1002  UNO R4  sn=A1",
            "/dev/ttyACM1  vid=303a pid=1001  ?  sn=E1",
            "/dev/ttyACM2  vid=303a pid=1001  ESP32S3  sn=E2",
        ], f"vid 없는 장치는 빼고 사람이 읽을 줄로 — {sp.describe()}")
    finally:
        list_ports.comports = old


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
    print("✅ serial_ports 검증 통과")
