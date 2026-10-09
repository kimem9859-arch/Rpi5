"""1인칭 원본 녹화기 — 오버레이 없는 카메라 프레임을 **처리한 순서·번호 그대로** 영상과 대응표로 남긴다.

설계 = 상위 `docs/superpowers/specs/2026-10-09-측정녹화-보관판-design.md` R1
(사용자 2026-10-09 「1인칭 영상(오버레이 미포함)만 있어도 … 로그 데이터에 바탕으로 오버레이를 그리거나」).

왜 따로 만드나:
    시연영상 촬영(`demo_recorder`)은 「최신 프레임을 초당 15장」으로 민다 — 처리한 프레임과 1:1 이 아니라
    측정 기록(`frames.csv`·`boxes.csv`)의 프레임 번호로 맞출 수 없다. 여기서는 처리한 프레임을 **하나씩 번호와
    함께** 넘기고, 넘치면 버리되 **버린 번호도 대응표에 남긴다** — 영상 n번째 = 측정 프레임 몇 번인지 늘 안다.

🔴 카메라 스레드는 넣기만 한다(`submit`) — 인코딩·파일 쓰기는 따로 도는 쓰기 스레드가 한다. 카메라 스레드에서
   인코딩하면 처리가 멈췄다(`demo_ffmpeg` 머리 · 2026-09-03 실측). 인코딩 설정은 시연영상 촬영과 같다(`_X264`).
🔑 영상의 프레임률은 이름표일 뿐이다(고정 `fps`) — 실제 시각은 대응표의 `t_recv_ms`(측정 기록과 같은 단조 시계 ms).
⚠️ Qt 에 의존하지 않는다 — 시험은 가짜 ffmpeg(`spawn`)로 돈다.
"""
import collections
import csv
import signal
import subprocess
import threading

import cv2

from demo_ffmpeg import _X264

CSV_HEAD = ["video_frame", "frame", "t_recv_ms", "dropped"]


def _spawn_ffmpeg(args):
    return subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                            stdin=subprocess.PIPE)


class RawRecorder:
    """한 번의 녹화 — `start(size)` → 카메라 스레드가 `submit(...)` → `stop()`."""

    def __init__(self, out_mp4, out_csv, fps=12, queue_max=60, spawn=None):
        self.out_mp4, self.out_csv = out_mp4, out_csv
        self._fps, self._max = fps, max(1, int(queue_max))
        self._spawn = spawn or _spawn_ffmpeg
        self._cv = threading.Condition()
        self._items = collections.deque()      # ("img", 그림, 번호, 시각) · ("drop", None, 번호, 시각) — 넣은 순서 그대로
        self._n_img = 0                        # 대기 중인 그림 수(이것만 queue_max 로 묶는다 — 버림 표시는 늘 들어간다)
        self._closing = False
        self._proc = self._thread = None
        self._size = None
        self.written = self.dropped = 0
        self.active = False

    # -- 수명 -----------------------------------------------------------------
    def start(self, size):
        """size = (w, h) — 첫 프레임 크기. 반환 = 문제 목록(비면 녹화 중)."""
        w, h = size
        self._size = (w - w % 2, h - h % 2)        # x264 는 짝수 크기만 받는다
        try:
            self._proc = self._spawn(["-f", "rawvideo", "-pixel_format", "bgr24",
                                      "-video_size", f"{self._size[0]}x{self._size[1]}",
                                      "-framerate", str(self._fps), "-i", "-"] + _X264 + [self.out_mp4])
        except (OSError, ValueError) as e:
            return [f"ffmpeg 를 띄우지 못했다({e})"]
        if self._proc.poll() is not None:
            return [f"ffmpeg 가 바로 끝났다(코드 {self._proc.poll()})"]
        self._csv_f = open(self.out_csv, "w", encoding="utf-8", newline="")
        self._csv = csv.writer(self._csv_f)
        self._csv.writerow(CSV_HEAD)
        self.active = True
        self._thread = threading.Thread(target=self._run, name="raw_recorder", daemon=True)
        self._thread.start()
        return []

    def submit(self, clean_bgr, frame_id, t_recv_ms):
        """🔴 **카메라 스레드가 부른다** — 넣기만 하고 바로 돌아간다. 넘치면 그 번호를 「버림」으로 남긴다."""
        if not self.active:
            return
        with self._cv:
            if self._closing:
                return
            if self._n_img < self._max:
                self._items.append(("img", clean_bgr, frame_id, t_recv_ms))
                self._n_img += 1
            else:
                self._items.append(("drop", None, frame_id, t_recv_ms))
            self._cv.notify()

    def stop(self):
        """남은 것을 다 쓰고 파이프를 닫아 ffmpeg 가 스스로 마무리하게 한다 → {written, dropped, path}."""
        if self.active:
            with self._cv:
                self._closing = True
                self._cv.notify()
            self._thread.join(30)
            self._finish_ffmpeg()
            self._csv_f.close()
            self.active = False
        return {"written": self.written, "dropped": self.dropped, "path": self.out_mp4}

    # -- 쓰기 스레드 ------------------------------------------------------------
    def _run(self):
        while True:
            with self._cv:
                while not self._items and not self._closing:
                    self._cv.wait(0.5)
                if not self._items and self._closing:
                    return
                kind, img, fid, t = self._items.popleft()
                if kind == "img":
                    self._n_img -= 1
            if kind == "drop":
                self._row("", fid, t, 1)
                self.dropped += 1
                continue
            if (img.shape[1], img.shape[0]) != self._size:
                img = cv2.resize(img, self._size)
            try:
                self._proc.stdin.write(img.tobytes())
            except (BrokenPipeError, OSError, ValueError):
                self._row("", fid, t, 1)               # ffmpeg 가 죽었다 — 나머지도 버림으로 남긴다
                self.dropped += 1
                continue
            self._row(self.written, fid, t, 0)
            self.written += 1

    def _row(self, video_frame, fid, t, dropped):
        self._csv.writerow([video_frame, fid, round(float(t), 3), dropped])

    def _finish_ffmpeg(self):
        # 🔴 파이프를 먼저 닫는다 — EOF 를 봐야 ffmpeg 가 mp4 를 마무리한다(demo_ffmpeg.FfmpegSet.stop 과 같은 순서).
        try:
            self._proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.send_signal(signal.SIGINT)   # kill 이면 mp4 헤더가 안 써져 파일이 깨진다
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
