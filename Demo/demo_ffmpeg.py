"""시연영상 촬영 — ffmpeg 가 맡는 2개(①GUI 전체 · ④USB 3인칭).

설계 = 상위 `docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md`

🔴 **웹캠은 ffmpeg 가 직접 v4l2 로 연다.** OpenCV 는 기본 GStreamer 백엔드로 열려
   MJPG 지정이 무시되고 1080p 5fps 로 떨어진다(2026-07-22 실측).
   같은 이유로 GUI 의 `UsbCameraThread` 는 촬영 모드에서 띄우지 않는다
   (`SOP_USB_CAMERA=0`) — `/dev/video0` 은 하나뿐이라 둘이 못 연다.
🔴 **시각 자막(drawtext)을 넣지 않는다.** `run_scenario.sh` 와 다른 점이다 —
   저쪽은 대조용 기록이고 이쪽은 **제출 영상**이다.
🔴 **화면 전체가 아니라 창 영역만 잘라 찍는다** — 작업표시줄·제목표시줄을 뺀다.
"""
import os
import signal
import subprocess
import time

import config


class FfmpegPair:
    """①GUI 전체·④USB 3인칭을 별도 프로세스로 찍는다. GUI 스레드 부담이 없다."""

    def __init__(self):
        self._procs = []

    def _spawn(self, args, path):
        return subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args + [path],
            stdin=subprocess.DEVNULL)

    def start(self, screen_rect, screen_path, webcam_path):
        """screen_rect = 화면 절대 좌표의 (x, y, w, h). 반환 = 문제 사유 목록."""
        problems = []
        tw, th = config.DEMO_CAPTURE_SIZE
        x, y, w, h = screen_rect
        w -= w % 2
        h -= h % 2                       # x264 는 짝수 크기만 받는다
        display = os.environ.get("DISPLAY", ":0")
        self._procs.append(self._spawn([
            "-f", "x11grab",
            "-framerate", str(int(config.DEMO_CAPTURE_FPS)),
            "-video_size", f"{w}x{h}",
            "-i", f"{display}+{x},{y}",
            "-vf", f"scale={tw}:{th}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p",
        ], screen_path))

        if os.path.exists("/dev/video0"):
            self._procs.append(self._spawn([
                "-f", "v4l2", "-input_format", "mjpeg",
                "-video_size", "1920x1080", "-framerate", "30",
                "-i", "/dev/video0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p",
            ], webcam_path))
        else:
            problems.append("USB 웹캠(/dev/video0)이 없어 3인칭 녹화를 건너뜁니다")

        # 즉시 죽는 경우(장치 점유·좌표 오류)를 여기서 잡는다. 나중에 알면 촬영을 버린다.
        time.sleep(1.0)
        for p in list(self._procs):
            if p.poll() is not None:
                problems.append(f"ffmpeg 가 즉시 종료됨 (코드 {p.returncode})")
                self._procs.remove(p)
        return problems

    def stop(self):
        # 🔴 SIGINT 여야 한다. kill 로 죽이면 mp4 무빙 헤더가 안 써져 파일이 깨진다.
        for p in self._procs:
            try:
                p.send_signal(signal.SIGINT)
            except Exception:
                pass
        for p in self._procs:
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
        self._procs = []
