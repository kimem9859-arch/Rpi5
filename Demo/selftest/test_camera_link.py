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
        _last_roi=None, _append_log=lambda m: None, _press_pending=None,   # 누름 확인 기억(프레임마다 판정 · 2026-10-07)
        _measure=__import__("measure_log").NullLog(), _last_frame_t=None,   # 측정 기록 자리(꺼짐)
        _hand_gate_off=lambda t: False, _hand_gate_was=False)                # 공구를 든 동안 손 판정 끔(공구 구간 설계 D4) — 여기선 꺼지지 않음
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


# ---------------------------------------------------------------- 측정 녹화(설계 2026-10-09 R1·R3)
class _CapLog:
    """측정 기록 흉내 — 줄을 모은다."""
    enabled = True

    def __init__(self):
        self.rows, self.events = [], []

    def row(self, name, values):
        self.rows.append((name, list(values)))

    def event(self, kind, t=None, **data):
        self.events.append((kind, data))


def test_raw_sink_clean_numbered():
    print("\n[원본 녹화] 오버레이 전 사본이 번호·받은 시각과 함께 온다 — 화면 오버레이와 무관(R1)")
    import measure_log
    th = ct.CameraThread()
    th.set_draw_boxes(True)
    _FAKE_DET.dets = [(0, 0.9, 5, 5, 30, 30)]
    got = []
    th.set_raw_sink(lambda img, fid, tms: got.append((img.copy(), fid, tms)))
    try:
        th._process_frame(np.zeros((48, 64, 3), np.uint8), 10.0)
        out = th._process_frame(np.zeros((48, 64, 3), np.uint8), 10.1)
    finally:
        _FAKE_DET.dets = []
    check(len(got) == 2 and [g[1] for g in got] == [1, 2], f"측정 끔이면 처리 순번 1·2 — {[g[1] for g in got]}")
    check(got[0][2] == measure_log.now_ms(10.0), f"받은 시각 ms = 측정 기록과 같은 시계 — {got[0][2]}")
    check(int(out.sum()) > 0 and int(got[1][0].sum()) == 0, "화면 프레임에는 상자가 그려졌고 원본에는 없다")
    th.set_raw_sink(None)
    th._process_frame(np.zeros((48, 64, 3), np.uint8), 10.2)
    check(len(got) == 2, "떼면 더 안 온다")

    th2 = ct.CameraThread()
    log = _CapLog()
    th2.set_measure(log)
    got2 = []
    th2.set_raw_sink(lambda img, fid, tms: got2.append(fid))
    for k in range(2):
        th2._measure_begin(20.0 + k, 1.0)
        th2._process_frame(np.zeros((48, 64, 3), np.uint8), 20.0 + k)
        th2._measure_end()
    frames = [v[0] for n, v in log.rows if n == "frames"]
    check(got2 == frames == [1, 2], f"측정 켬이면 측정 프레임 번호 그대로 — 녹화 {got2} · frames.csv {frames}")


def test_tool_boxes_logged():
    print("\n[공구 상자] 공구 결과가 온 프레임의 boxes 에 kind=tool 줄(좌표) — 버튼 상자 줄은 그대로(R3)")
    th = ct.CameraThread()
    log = _CapLog()
    th.set_measure(log)

    class _Gate:
        def __init__(self):
            self.n = 0

        def request(self, frame, tip):
            self.n += 1

        def poll(self):
            if self.n == 1:
                self.n += 1
                return [("wrench", 0.81, 10.0, 12.0, 30.0, 40.0)], None
            return None
    th._tool_gate = _Gate()
    th._tool_scan = True
    th._tool_last = 0.0
    _FAKE_DET.dets = [(1, 0.9, 5, 5, 30, 30)]
    try:
        th._measure_begin(30.0, 1.0)
        th._process_frame(np.zeros((48, 64, 3), np.uint8), 30.0)
        th._measure_end()
    finally:
        _FAKE_DET.dets = []
    boxes = [v for n, v in log.rows if n == "boxes"]
    tool = [b for b in boxes if b[2] == "tool"]
    check(len(tool) == 1 and tool[0][3] == "wrench" and tool[0][5:9] == [10, 12, 30, 40], f"공구 줄 {tool}")
    check(any(b[2] == "raw" and b[3] == "B2" for b in boxes), "버튼 상자 줄(raw)은 그대로")

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
