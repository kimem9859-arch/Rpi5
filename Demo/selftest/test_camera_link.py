"""카메라 수신 연결 검증(C12·C16·C19) — ESP32·Hailo 없이.

실행: python3 Demo/selftest/test_camera_link.py
🔴 버튼 검출기를 가짜로 바꿔 끼운다 — `camera_thread` 는 import 할 때 검출기(Hailo)를 연다.
   카메라는 127.0.0.1 의 가짜 TCP 서버(4바이트 길이 + JPEG — ESP32 와 같은 모양)로 흉내 낸다.
정본 = 상위 docs/superpowers/specs/2026-09-25-런타임-문제수정-design.md §9.2
"""
import os
import socket
import struct
import sys
import threading
import time
import types

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np


class _FakeDetector:
    backend_name = "시험용"
    NAMES = {0: "B1", 1: "B2", 2: "B3", 3: "B4", 4: "EMO"}

    def __init__(self):
        self.dets = []
        self.fail_next = 0            # 다음 N번 detect 는 예외(Hailo 일시 오류 흉내 · C12)

    def class_name(self, i):
        return self.NAMES[i]

    def detect(self, frame):
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("HAILO_TIMEOUT(시험)")
        return list(self.dets)

    def close(self):
        pass


_FAKE_DET = _FakeDetector()
_fake_mod = types.ModuleType("detector")
_fake_mod.create_detector = lambda: _FAKE_DET
sys.modules["detector"] = _fake_mod

import config
config.HAND_ENABLED = False
config.TOOL_ENABLED = False

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

import camera_thread as ct

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------------------------------------------------------- C19 연결별 수신
def test_c19_old_receiver_leaves_new_connection_alone():
    """C19 — 끝난 연결의 수신 스레드는 새 연결의 플래그를 건드리지 않는다(검토 C19 — 새 연결을 끊었다)."""
    print("\n[C19] 옛 수신 스레드")
    th = ct.CameraThread()
    a, b = socket.socketpair()
    b.close()                                        # 옛 연결 — 곧바로 끊김(recv 가 빈 값)
    th._conn_gen = 2                                 # 그 사이 새 연결(2번)이 붙었다
    th._recv_error = False
    th._raw_event.clear()
    try:
        th._recv_worker(a, 1)                        # 1번 연결의 수신 스레드가 뒤늦게 끝난다
    except TypeError as e:
        check(False, f"수신 스레드가 자기 연결(소켓·번호)을 받지 않는다 — {e}")
        return
    finally:
        a.close()
    check(th._recv_error is False, "새 연결에 「수신 오류」를 세우지 않는다")
    check(not th._raw_event.is_set(), "새 연결의 처리 루프를 깨우지 않는다")


def test_c19_close_wakes_blocked_receiver():
    """C19 — 연결을 끝내면 막혀 있던 수신이 곧바로 깬다(close 만으로는 안 깨 join 3초 뒤에도 살아남았다)."""
    print("\n[C19] 막힌 수신 깨우기")
    close = getattr(ct, "_close_sock", None)
    check(close is not None, "camera_thread._close_sock 이 있다")
    if close is None:
        return
    a, b = socket.socketpair()
    a.settimeout(5)
    woke = threading.Event()

    def rx():
        try:
            a.recv(4)
        except OSError:
            pass
        woke.set()

    threading.Thread(target=rx, daemon=True).start()
    time.sleep(0.1)                                  # recv 에 들어갈 시간
    close(a)
    check(woke.wait(1.0), "1초 안에 깬다")
    b.close()


# ---------------------------------------------------------------- C16 프레임 시각
def test_c16_roi_carries_frame_time():
    """C16 — 체류 시각은 GUI 가 신호를 받은 때가 아니라 **카메라가 프레임을 받은 때**다(검토 C16·U18)."""
    print("\n[C16] 프레임 시각")
    th = ct.CameraThread()
    got = []
    th.roi_signal.connect(lambda *a: got.append(a))
    try:
        th._process_frame(np.zeros((48, 64, 3), np.uint8), 123.5)
    except TypeError as e:
        check(False, f"프레임 시각을 받지 못한다 — {e}")
        return
    check(got == [("", 0, 123.5)], f"roi_signal = {got} — 받은 시각이 실려야 한다")


def test_c16_console_passes_frame_time():
    """C16 — 콘솔은 받은 시각을 그대로 판정기에 넘긴다(time.time() 으로 바꾸지 않는다)."""
    print("\n[C16] 콘솔 → 판정기")
    import safety_console as sc
    calls = []
    fake = types.SimpleNamespace(
        fsm=types.SimpleNamespace(update_vision=lambda roi, now, level: calls.append((roi, now, level))),
        _last_roi=None, _append_log=lambda m: None)
    try:
        sc.SafetyConsole._on_roi(fake, "B2", 2, 77.25)
    except TypeError as e:
        check(False, f"슬롯이 시각을 받지 못한다 — {e}")
        return
    check(calls == [("B2", 77.25, 2)], f"update_vision 인자 = {calls}")

# ---------------------------------------------------------------- C12 프레임 처리 오류
class _FakeCam:
    """ESP32 대역 — 붙는 손님마다 작은 JPEG 를 0.05초 간격으로 보낸다(4바이트 길이 + JPEG). 붙은 횟수를 센다."""

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.srv.settimeout(0.2)
        self.port = self.srv.getsockname()[1]
        self.conns = 0
        self._stop = False
        ok, buf = cv2.imencode(".jpg", np.zeros((48, 64, 3), np.uint8))
        self._frame = struct.pack("<I", len(buf)) + buf.tobytes()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self._stop:
            try:
                c, _ = self.srv.accept()
            except OSError:
                continue
            self.conns += 1
            threading.Thread(target=self._send, args=(c,), daemon=True).start()

    def _send(self, c):
        try:
            while not self._stop:
                c.sendall(self._frame)
                time.sleep(0.05)
        except OSError:
            pass
        finally:
            c.close()

    def close(self):
        self._stop = True
        self.srv.close()


def test_c12_frame_error_keeps_connection():
    """C12 — 프레임 처리 오류로 카메라 연결을 끊지 않는다(검토 C12 — 영상이 3초 넘게 끊기고 로그는 네트워크 탓)."""
    print("\n[C12] 프레임 처리 오류")
    cam = _FakeCam()
    ct.CAMERA_TCP_PORT = cam.port
    ct.TCP_RECONNECT_DELAY_SEC = 0.1
    th = ct.CameraThread()
    th.set_host("127.0.0.1")
    logs, frames = [], []
    th.log_signal.connect(logs.append, Qt.ConnectionType.DirectConnection)
    th.change_pixmap_signal.connect(lambda img: frames.append(1), Qt.ConnectionType.DirectConnection)
    _FAKE_DET.fail_next = 3                          # 세 프레임 연달아 처리 오류
    runner = threading.Thread(target=th.run, daemon=True)
    runner.start()
    time.sleep(1.0)
    th._running = False
    th._raw_event.set()
    runner.join(timeout=5)
    cam.close()
    _FAKE_DET.fail_next = 0
    errs = [m for m in logs if "프레임 처리 오류" in m]
    check(cam.conns == 1, "한 번만 붙는다 — 끊고 다시 붙으면 안 된다")
    check(len(frames) >= 3, "오류 뒤에도 영상이 이어진다")
    check(len(errs) == 1, "「프레임 처리 오류」 로그가 한 줄 — 이어진 오류는 묶는다")
    check(not any("수신 오류" in m for m in logs), "「수신 오류」(네트워크 탓)로 적지 않는다")

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
    print("✅ 카메라 연결 검증 통과")
