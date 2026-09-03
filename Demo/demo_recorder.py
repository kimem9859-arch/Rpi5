"""시연영상 촬영 — GUI 안에서 찍는 3개(②UI만 · ③-a/③-b 1인칭).

①GUI 전체·④USB 3인칭은 ffmpeg 가 맡는다(`demo_ffmpeg.py`).
설계 = 상위 `docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md`

🔴 **평소 실행과 무관한 경로다.** `config.DEMO_CAPTURE` 가 켜졌을 때만 만들어진다.
🔴 **버벅임 대책을 넣지 않았다**(2026-09-03 사용자 지시) — 프레임 버리기·워커
   스레드 없이 그대로 만들고, 실제 부하를 먼저 잰 뒤에 필요 여부를 정한다.
"""
import os
import threading
import time

import cv2
import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSlot
from PyQt6.QtGui import QImage

import config


def letterbox(frame, size):
    """비율을 지켜 size 캔버스 가운데 놓고 남는 곳은 검정.

    🔴 화면 표시(`safety_console._fit_to_label`)와 다르다 — 그쪽은 채우고 넘치는
       만큼 잘라내지만(FILL), 촬영본은 **시야를 하나도 버리지 않아야** 하므로
       레터박스다. ESP32 프레임은 회전 뒤 480×640 세로라 좌우에 검은 띠가 생긴다.
    """
    tw, th = size
    h, w = frame.shape[:2]
    s = min(tw / w, th / h)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    canvas = np.zeros((th, tw, 3), dtype=np.uint8)
    x, y = (tw - nw) // 2, (th - nh) // 2
    canvas[y:y + nh, x:x + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    return canvas


def qimage_to_bgr(qt_image):
    """QImage → OpenCV BGR ndarray."""
    img = qt_image.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.bits()
    ptr.setsize(h * w * 3)
    arr = np.array(ptr).reshape(h, w, 3)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


class DemoRecorder(QObject):
    """15fps 타이머 하나가 3개 파일을 쓴다.

    🔴 타이머가 「지금 최신 프레임」을 가져다 쓴다 — 새 프레임이 안 왔으면 직전
       것을 한 번 더 쓴다. ESP32 프레임 간격이 일정하지 않아, 오는 대로 쓰면
       **영상 길이가 실제 시간과 어긋난다**(1분 촬영이 40초짜리 영상이 된다).
    """

    def __init__(self, out_dir, stamp, scenario, overlay, parent=None):
        super().__init__(parent)
        self._dir = out_dir
        self._base = f"{stamp}_{scenario}"
        self._overlay = overlay
        self._lock = threading.Lock()
        self._latest = None          # (annotated_bgr, clean_bgr)
        self._writers = {}           # key -> (VideoWriter, path)
        self._grab = None
        self._camera_rect = None
        self._started = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / config.DEMO_CAPTURE_FPS))
        self._timer.timeout.connect(self._tick)

    # -- 파일 -----------------------------------------------------------------
    def path_for(self, kind, overlay=None):
        """세트 폴더 안의 파일 경로. overlay=None 이면 오버레이 꼬리표를 안 붙인다."""
        tail = f"_오버레이{overlay}" if overlay else ""
        return os.path.join(self._dir, f"{self._base}_{kind}{tail}.mp4")

    def _open(self, key, path):
        fourcc = cv2.VideoWriter_fourcc(*config.RECORDING_CODEC)
        w = cv2.VideoWriter(path, fourcc, config.DEMO_CAPTURE_FPS, config.DEMO_CAPTURE_SIZE)
        if not w.isOpened():
            raise RuntimeError(f"VideoWriter 생성 실패 ({config.RECORDING_CODEC}): {path}")
        self._writers[key] = (w, path)

    # -- 수명 -----------------------------------------------------------------
    def start(self, grab_fn, camera_rect):
        """grab_fn() -> QImage(창 전체) · camera_rect = 창 좌표계의 QRect."""
        os.makedirs(self._dir, exist_ok=True)
        self._grab = grab_fn
        self._camera_rect = camera_rect
        self._open('화면만', self.path_for('GUI화면만', self._overlay))
        self._open('1인칭O', self.path_for('1인칭풀', '켬'))
        self._open('1인칭X', self.path_for('1인칭풀', '끔'))
        self._started = time.time()
        self._timer.start()

    def submit_camera(self, annotated_bgr, clean_bgr):
        """🔴 **카메라 스레드가 부른다.** 최신 프레임만 보관하고 바로 돌아간다 —
        여기서 인코딩하면 카메라 스레드가 프레임을 놓친다."""
        with self._lock:
            self._latest = (annotated_bgr, clean_bgr)

    @pyqtSlot()
    def _tick(self):
        if not self._writers:
            return
        # ② GUI UI만 — 창을 떠서 카메라 영역만 검정으로 덧칠한다
        try:
            frame = qimage_to_bgr(self._grab())
            r = self._camera_rect
            y1, y2 = max(0, r.y()), min(frame.shape[0], r.y() + r.height())
            x1, x2 = max(0, r.x()), min(frame.shape[1], r.x() + r.width())
            frame[y1:y2, x1:x2] = 0
            self._writers['화면만'][0].write(
                cv2.resize(frame, config.DEMO_CAPTURE_SIZE))
        except Exception as e:
            print(f"[시연촬영] GUI화면만 프레임 오류: {e}")
        # ③ 1인칭 두 벌
        with self._lock:
            latest = self._latest
        if latest is None:
            return
        annotated, clean = latest
        for key, img in (('1인칭O', annotated), ('1인칭X', clean)):
            try:
                self._writers[key][0].write(letterbox(img, config.DEMO_CAPTURE_SIZE))
            except Exception as e:
                print(f"[시연촬영] {key} 프레임 오류: {e}")

    def stop(self):
        self._timer.stop()
        files = []
        for w, path in self._writers.values():
            w.release()
            files.append(path)
        self._writers = {}
        return {'files': files,
                'seconds': time.time() - self._started if self._started else 0.0}
