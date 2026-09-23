"""camera_thread — 프레임 크기가 바뀌면 보정·링을 다시 정한다 (spec 2026-09-23 D1).

GUI 를 켠 채 ESP32 를 VGA↔XGA 로 다시 구우면 자동 재연결 뒤 프레임 크기가 바뀐다.
옛 맵을 그대로 쓰면 cv2.remap 이 예외 없이 잘리거나 검게 채운 프레임을 낸다(조용히 틀림).

실행: python3 Demo/selftest/test_camera_calib.py   (offscreen · HW 불필요)
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import camera_thread as ct  # noqa: E402


class _Sig:
    def __init__(self):
        self.msgs = []

    def emit(self, m):
        self.msgs.append(m)


class _Fake:
    """CameraThread 의 보정 관련 상태만 흉내낸다 — 생성자는 Hailo·손 모델을 끌어온다."""
    def __init__(self):
        self.log_signal = _Sig()
        self._undistort_map = None
        self._ring_px = 0
        self._calib_wh = None

    def _init_calibration(self, w, h):
        ct.CameraThread._init_calibration(self, w, h)


def test_reinit_on_size_change():
    f = _Fake()
    ct.CameraThread._ensure_calibration(f, 640, 480)
    assert f._ring_px == 25 and f._undistort_map is not None
    ct.CameraThread._ensure_calibration(f, 1024, 768)        # 재연결 뒤 XGA
    assert f._ring_px == 40, f._ring_px
    assert f._undistort_map[0].shape[:2] == (768, 1024), f._undistort_map[0].shape
    assert len(f.log_signal.msgs) == 2


def test_same_size_is_noop():
    f = _Fake()
    ct.CameraThread._ensure_calibration(f, 1024, 768)
    ct.CameraThread._ensure_calibration(f, 1024, 768)
    assert len(f.log_signal.msgs) == 1                       # 매 프레임 다시 읽지 않는다


if __name__ == "__main__":
    try:
        for n, fn in list(globals().items()):
            if n.startswith("test_"):
                fn(); print("ok", n)
        print("ALL OK")
    finally:
        # 🔴 닫지 않으면 종료 중 세그폴트가 나서 통과/실패가 exit code 로 안 드러난다(test_imports 와 같은 처리).
        ct.close_detector()
