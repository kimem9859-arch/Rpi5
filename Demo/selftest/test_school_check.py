"""학교 사전 점검 — 항목 판정 · ❌ 면 대처 번호와 명령 · 집 모드 · 비밀값을 열지 않는다(학교 방문 준비 설계 §8.2).

실행: python3 Demo/selftest/test_school_check.py
"""
import builtins
import contextlib
import io
import os
import socket
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import cv2
import numpy as np

import school_check as SC
from fake_camera import FakeCamera

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_ip_band():
    print("\n[안경] IP 대역 — 공유기(192.168.1.x)가 아니면 폰 핫스팟으로 샌 것(V1)")
    check(SC.ip_band("192.168.1.9").ok is True, "192.168.1.9 → ✅")
    c = SC.ip_band("10.47.16.235")
    check(c.ok is False and "V1" in c.fix, f"10.47.16.235 → ❌ · {c.fix}")


def test_stray_env():
    print("\n[코드] 셸에 남은 SOP_* 변수 — 처리 설정 · 주소가 다르게 잴 수 있다(V9)")
    c = SC.stray_env({"SOP_DISPLAY_EVERY": "2", "PATH": "/bin"})
    check(c.ok is False and "SOP_DISPLAY_EVERY" in c.detail and "V9" in c.fix, f"{c}")
    check(SC.stray_env({"PATH": "/bin"}).ok is True, "없으면 ✅")


def test_hailo_holders():
    print("\n[Hailo] 장치를 쥔 프로세스 — 번호와 끄는 명령만 보인다(자동으로 끄지 않는다 · V5)")
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "123", "fd"))
    os.symlink("/dev/hailo0", os.path.join(root, "123", "fd", "7"))
    with open(os.path.join(root, "123", "cmdline"), "wb") as f:
        f.write(b"python3\0main.py\0")
    os.makedirs(os.path.join(root, "456", "fd"))
    os.symlink("/dev/null", os.path.join(root, "456", "fd", "1"))
    c = SC.hailo_holders(proc_root=root)
    check(c.ok is False and "123" in c.detail and "main.py" in c.detail and "kill 123" in c.fix, f"{c}")
    empty = tempfile.mkdtemp()
    check(SC.hailo_holders(proc_root=empty).ok is True, "아무도 안 쥠 → ✅")


def test_recv_probe():
    print("\n[안경] 5초 받기 — 받은 fps · 장 크기 · 풀림 · 연결 안 되면 V2")
    img = cv2.imencode(".jpg", np.full((120, 160, 3), 90, np.uint8))[1].tobytes()
    cam = FakeCamera([img], port=0, fps=40).start()
    try:
        c = SC.recv_probe("127.0.0.1", cam.port, sec=1.5)
        check(c.ok is True and "fps" in c.detail, f"{c}")
    finally:
        cam.stop()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    c = SC.recv_probe("127.0.0.1", port, sec=0.5)
    check(c.ok is False and "V2" in c.fix, f"닫힌 포트 → {c}")
    slow = FakeCamera([img], port=0, fps=5).start()
    try:
        c = SC.recv_probe("127.0.0.1", slow.port, sec=1.5)
        check(c.ok is False and "V4" in c.fix, f"느림(5장/초) → {c}")
    finally:
        slow.stop()


def test_run_home_and_no_secret():
    print("\n[전체] 집 모드 — 예외 없이 끝 · 「집 · 건너뜀」 항목 · .env 를 열지 않는다")
    real_open = builtins.open
    opened = []

    def guard(path, *a, **k):
        if str(path).endswith(".env"):
            opened.append(str(path))
            raise AssertionError(".env 를 열었다")
        return real_open(path, *a, **k)
    builtins.open = guard
    # 🔑 실제 로컬 포트(8888 · 8889 · 8890)에 붙지 않는다 — 돌고 있는 시연 · 리허설의 연결을 끊을 수 있다(안경은 손님 하나)
    keep = SC.recv_probe, SC.glass_ports
    SC.recv_probe = lambda host, port=None, sec=5.0: SC._c("안경", "연결 · 받기", True, "시험 대역")
    SC.glass_ports = lambda host: SC._c("음성", "안경 마이크 · 명령 포트", True, "시험 대역")
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = SC.run(home=True)
            SC.report(res)
    finally:
        builtins.open = real_open
        SC.recv_probe, SC.glass_ports = keep
    check(not opened, f".env 를 열지 않았다 {opened}")
    check(any(c.ok is None for c in res), "집 · 건너뜀 항목이 있다")
    check("키 파일" in buf.getvalue(), "키 파일 항목은 있다(있는지만)")


def test_demo_running_skips_glass():
    print("\n[시연 중] 안경 받기 · 포트 · 인터락 · Hailo 쥔 프로세스는 건너뛴다 — 안경은 손님 하나라 시연 연결을 끊는다(리뷰 Minor 2)")
    def boom(*a, **k):
        raise AssertionError("시연 중에 불렀다")
    keep = SC._demo_running, SC.recv_probe, SC.glass_ports, SC.interlock_ack, SC.hailo_holders
    SC._demo_running = lambda: True
    SC.recv_probe = SC.glass_ports = SC.interlock_ack = SC.hailo_holders = boom
    try:
        res = SC.run(home=False)
    except AssertionError as e:
        res = None
        check(False, str(e))
    finally:
        SC._demo_running, SC.recv_probe, SC.glass_ports, SC.interlock_ack, SC.hailo_holders = keep
    if res is not None:
        sk = {c.name for c in res if c.ok is None and "시연" in c.detail}
        check({"연결 · 받기", "안경 마이크 · 명령 포트", "RUN 응답", "장치를 쥔 프로세스"} <= sk, f"건너뜀 {sk}")


def test_free_space_threshold():
    print("\n[파이] 남은 공간 문턱 = 실행기 경고와 같은 1GB · 모자라면 V8(지우지 않고 사용자 확인)")
    import inspect
    check(inspect.signature(SC.free_space).parameters["min_gb"].default == 1.0, "기본 문턱 1GB")
    c = SC.free_space(tempfile.gettempdir(), min_gb=10 ** 6)
    check(c.ok is False and "V8" in c.fix and "사용자" in c.fix, f"{c}")


if __name__ == "__main__":
    test_ip_band()
    test_stray_env()
    test_hailo_holders()
    test_recv_probe()
    test_run_home_and_no_secret()
    test_demo_running_skips_glass()
    test_free_space_threshold()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 사전 점검 검증 통과")
