"""시연영상 촬영 — 촬영 중에는 **꼭 필요한 인코딩 3개만** 돌린다.

설계 = 상위 `docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md`

🔴 **왜 이 모양인가 (2026-09-03 실측 두 번으로 정해졌다).**
   ① 1차 — GUI 안에서 `cv2.VideoWriter` 3개: FPS 13.1 → 0.5~1.9. GUI 가 멈췄다.
   ② 2차 — 인코딩을 전부 ffmpeg 로 넘김(1080p 5벌): **여전히 0.6~0.8.**
      `top` 으로 보니 ffmpeg 둘이서만 CPU 250%/400% 를 먹고 있었다(4코어).
      → 병목은 「누가 인코딩하느냐」가 아니라 **1080p 인코딩 개수** 자체였다.
   결론: **촬영 중에는 원본 그대로만 담고, 규격 맞추기는 촬영이 끝난 뒤 한다**
   (`demo_postprocess.py`). 사람이 연기하는 동안 CPU 를 아끼는 것이 전부다.

촬영 중 도는 것 (4개 프로세스):
  A. x11grab(창 영역) → GUI 화면. 「UI만」 회차면 그것이 곧 ②다
     🔴 창 영역만 잘라 **작업표시줄·제목표시줄을 뺀다.**
  B. v4l2 /dev/video0 → ④3인칭웹캠 1920×1080 15fps
     🔴 OpenCV 로 열면 MJPG 지정이 무시돼 1080p 5fps 로 떨어진다(2026-07-22 실측).
  C·D. 파이프(rawvideo) → ③-a/③-b 1인칭 **원본 480×640 그대로**(확대는 나중에)

촬영 뒤에 하는 것 (`demo_postprocess.py`):
  ③ 을 규격 캔버스에 레터박스로 얹기
  🔴 ②는 여기서 못 만든다 — 이 UI 는 모든 UI 가 영상 위에 떠 있어 영상 영역을
     덧칠하면 UI 까지 지워진다. ②는 「UI만」 회차에서 직접 찍는다(2026-09-03 실측).

🔴 시각 자막(drawtext)을 넣지 않는다 — `run_scenario.sh` 와 다른 점이다.
   저쪽은 대조용 기록이고 이쪽은 **제출 영상**이다.
"""
import os
import signal
import subprocess
import time

import config

def _screen_size(display):
    """현재 화면 크기 (w, h). 못 읽으면 (None, None)."""
    try:
        out = subprocess.run(["xdpyinfo", "-display", display],
                             capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if "dimensions:" in line:
                w, h = line.split()[1].split("x")
                return int(w), int(h)
    except Exception:
        pass
    return None, None


_X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p"]


class FfmpegSet:
    """촬영 중 도는 ffmpeg 프로세스 묶음(3개)."""

    def __init__(self):
        self._procs = []
        self.fpv_pipes = []      # [stdin(오버레이 O), stdin(오버레이 X)]

    def _spawn(self, args, pipe_stdin=False):
        return subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
            stdin=subprocess.PIPE if pipe_stdin else subprocess.DEVNULL)

    def start(self, screen_rect, fpv_size, paths):
        """screen_rect = 화면 절대 좌표 (x, y, w, h) — 창 내용 영역.
        fpv_size = 1인칭 원본 프레임 (w, h).
        paths = {'gui_full', 'webcam', 'fpv_on', 'fpv_off'}
        반환 = 문제 사유 목록.
        """
        problems = []
        fps = int(config.DEMO_CAPTURE_FPS)
        x, y, w, h = screen_rect
        w -= w % 2
        h -= h % 2                       # x264 는 짝수 크기만 받는다
        display = os.environ.get("DISPLAY", ":0")
        # 🔴 화면 밖으로 조금이라도 나가면 x11grab 이 즉시 죽는다
        #    ("Capture area ... outside the screen size"). 창 위치는 창 관리자가
        #    정하므로 우리가 기대한 자리에 없을 수 있다 — 여기서 화면 안으로 물린다.
        sw, sh = _screen_size(display)
        if sw and sh:
            x, y = max(0, min(x, sw - w)), max(0, min(y, sh - h))
            w, h = min(w, sw - x), min(h, sh - y)
            w -= w % 2
            h -= h % 2

        # A. GUI 전체 — 화면 전체가 아니라 창 영역만 잘라 작업표시줄·제목표시줄을 뺀다
        self._procs.append(self._spawn([
            "-f", "x11grab", "-framerate", str(fps),
            "-video_size", f"{w}x{h}", "-i", f"{display}+{x},{y}"] + _X264 + [paths['gui_full']]))

        # B. USB 웹캠 — 검출 없는 순수 촬영본
        if os.path.exists("/dev/video0"):
            self._procs.append(self._spawn([
                "-f", "v4l2", "-input_format", "mjpeg",
                "-video_size", "1920x1080", "-framerate", str(fps),
                "-i", "/dev/video0"] + _X264 + [paths['webcam']]))
        else:
            problems.append("USB 웹캠(/dev/video0)이 없어 3인칭 녹화를 건너뜁니다")

        # C·D. 1인칭 두 벌 — 원본 크기 그대로. 확대는 촬영이 끝난 뒤에 한다.
        fw, fh = fpv_size
        for key in ('fpv_on', 'fpv_off'):
            p = self._spawn([
                "-f", "rawvideo", "-pixel_format", "bgr24",
                "-video_size", f"{fw}x{fh}", "-framerate", str(fps),
                "-i", "-"] + _X264 + [paths[key]], pipe_stdin=True)
            self._procs.append(p)
            self.fpv_pipes.append(p.stdin)

        # 즉시 죽는 경우(장치 점유·좌표 오류)를 여기서 잡는다. 나중에 알면 촬영을 버린다.
        time.sleep(1.0)
        for p in list(self._procs):
            if p.poll() is not None:
                problems.append(f"ffmpeg 가 즉시 종료됨 (코드 {p.returncode})")
                self._procs.remove(p)
                if p.stdin in self.fpv_pipes:
                    self.fpv_pipes.remove(p.stdin)
        return problems

    def stop(self):
        # 🔴 파이프를 먼저 닫는다 — EOF 를 봐야 ffmpeg 가 스스로 마무리한다.
        #    이 덕에 GUI 가 갑자기 죽어도 1인칭 파일은 살아남는다.
        for s in self.fpv_pipes:
            try:
                s.close()
            except Exception:
                pass
        self.fpv_pipes = []
        # 🔴 SIGINT 여야 한다. kill 로 죽이면 mp4 무빙 헤더가 안 써져 파일이 깨진다.
        for p in self._procs:
            try:
                p.send_signal(signal.SIGINT)
            except Exception:
                pass
        for p in self._procs:
            try:
                p.wait(timeout=15)
            except Exception:
                p.kill()
        self._procs = []
