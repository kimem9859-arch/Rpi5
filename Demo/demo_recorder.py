"""시연영상 촬영 — 한 번 실행에 5개 파일. 인코딩은 전부 ffmpeg 가 한다.

설계 = 상위 `docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md`

이 모듈이 하는 일은 **프레임을 파이프에 밀어 넣는 것뿐**이다.
🔴 GUI 스레드에서 인코딩하지 않는다 — 1차 구현이 그렇게 했다가 FPS 13.1 → 0.5 로
   GUI 가 멈췄다(2026-09-03 실측). 미는 일은 **전용 스레드**가 한다.

🔴 15fps 로 「지금 최신 프레임」을 민다 — 새 프레임이 안 왔으면 직전 것을 한 번 더.
   ESP32 프레임 간격이 일정하지 않아, 오는 대로 밀면 **영상 길이가 실제 시간과
   어긋난다**(1분 촬영이 40초짜리 영상이 된다).
"""
import json
import os
import subprocess
import threading
import time

import cv2

import config
from demo_ffmpeg import FfmpegSet


def keep_screen_awake():
    """촬영 중 화면이 꺼지지 않게 `xscreensaver` 의 활동 타이머를 되돌린다.

    🔴 **설정을 바꾸지 않는다.** `~/.xscreensaver` 는 timeout 5분·lock True 인데,
       이것을 고쳐 놓으면 촬영이 비정상 종료됐을 때 **잠금이 풀린 채 남는다.**
       타이머만 되돌리면 촬영이 끝나는 순간 저절로 원래대로 돌아간다.
    ⚠️ 2026-09-04 에 실제로 물렸다 — 5분 잠금이 걸려 화면 캡처가 **통째로 검정**으로
       찍혔다. 1인칭·3인칭은 멀쩡해서 촬영 기능 결함으로 오인하기 쉽다.
    """
    try:
        subprocess.run(["xscreensaver-command", "-deactivate"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass          # xscreensaver 가 없는 환경이면 아무것도 안 한다


class DemoRecorder:
    """촬영 한 세트(5개 파일)의 수명을 쥔다."""

    def __init__(self, out_dir, stamp, scenario, overlay):
        self._dir = out_dir
        self._base = f"{stamp}_{scenario}"
        self._overlay = overlay
        self._lock = threading.Lock()
        self._latest = None          # (annotated_bgr, clean_bgr)
        self._ff = FfmpegSet()
        self._feeder = None
        self._running = False
        self._started = 0.0
        self._pushed = 0
        self._awake_at = 0.0

    # -- 파일 -----------------------------------------------------------------
    def path_for(self, kind, overlay=None):
        """세트 폴더 안의 파일 경로. overlay=None 이면 오버레이 꼬리표를 안 붙인다."""
        tail = f"_오버레이{overlay}" if overlay else ""
        return os.path.join(self._dir, f"{self._base}_{kind}{tail}.mp4")

    # -- 프레임 수집 ----------------------------------------------------------
    def submit_camera(self, annotated_bgr, clean_bgr):
        """🔴 **카메라 스레드가 부른다.** 보관만 하고 바로 돌아간다 —
        여기서 파이프에 쓰면 느린 프레임 하나가 카메라 수신을 막는다."""
        with self._lock:
            self._latest = (annotated_bgr, clean_bgr)

    # -- 수명 -----------------------------------------------------------------
    def start(self, screen_rect, camera_rect):
        """screen_rect = 화면 절대 좌표 (x,y,w,h) · camera_rect = 창 안 (x,y,w,h)."""
        os.makedirs(self._dir, exist_ok=True)
        with self._lock:
            latest = self._latest
        # 첫 프레임이 있으면 그 크기, 없으면(10초 폴백 경로) 기본값.
        fpv_size = ((latest[0].shape[1], latest[0].shape[0]) if latest is not None
                    else config.DEMO_FPV_SIZE)
        self._fpv_size = fpv_size
        problems = self._ff.start(screen_rect, fpv_size, {
            # 「UI만」 회차는 화면 자체가 검정 배경 + UI 라 그것이 곧 ②다.
            'gui_full': (self.path_for('GUI화면만') if config.DEMO_HIDE_VIDEO
                         else self.path_for('GUI전체', self._overlay)),
            'webcam':   self.path_for('3인칭웹캠'),
            'fpv_on':   self.path_for('1인칭풀', '켬'),
            'fpv_off':  self.path_for('1인칭풀', '끔'),
        })
        # 🔴 촬영 뒤 마무리(demo_postprocess)가 읽는다 — ②를 만들 때 어디를 검게
        #    칠할지, ③을 어느 규격으로 얹을지가 여기 있다. 지우지 말 것.
        with open(os.path.join(self._dir, '촬영메타.json'), 'w') as fp:
            json.dump({'camera_rect': list(camera_rect),
                       'screen_rect': list(screen_rect),
                       'fpv_size': list(fpv_size),
                       'overlay': self._overlay,
                       'target': list(config.DEMO_CAPTURE_SIZE)}, fp, ensure_ascii=False)
        self._started = time.time()
        self._running = True
        # 🔴 1인칭을 안 찍는 회차(3인칭만)는 밀어넣을 파이프가 없다 — 스레드도 안 돈다.
        if config.demo_wants("fpv"):
            self._feeder = threading.Thread(target=self._feed, daemon=True, name="demo-feeder")
            self._feeder.start()
        return problems

    def _feed(self):
        """15fps 로 최신 프레임을 두 파이프에 민다. 🔴 GUI 스레드가 아니다."""
        interval = 1.0 / config.DEMO_CAPTURE_FPS
        pipes = self._ff.fpv_pipes
        next_t = time.time()
        while self._running:
            next_t += interval
            # 🔴 화면이 잠기면 GUI 화면 녹화가 검정으로 찍힌다(2026-09-04 실측).
            if time.time() - self._awake_at >= 60:
                self._awake_at = time.time()
                keep_screen_awake()
            with self._lock:
                latest = self._latest
            if latest is not None and len(pipes) == 2:
                for stream, img in zip(pipes, latest):
                    try:
                        if (img.shape[1], img.shape[0]) != self._fpv_size:
                            img = cv2.resize(img, self._fpv_size)
                        stream.write(img.tobytes())
                    except (BrokenPipeError, ValueError, OSError):
                        self._running = False
                        break
                self._pushed += 1
            sleep = next_t - time.time()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.time()      # 밀렸으면 따라잡지 않고 현재로 맞춘다

    def stop(self):
        self._running = False
        if self._feeder is not None:
            self._feeder.join(timeout=3)
            self._feeder = None
        self._ff.stop()
        seconds = time.time() - self._started if self._started else 0.0
        return {'seconds': seconds, 'pushed': self._pushed,
                'expected': int(seconds * config.DEMO_CAPTURE_FPS)}

    def write_info(self, extra_lines=()):
        """촬영정보.txt — 회차 설정·길이·파일 크기."""
        info = {'seconds': time.time() - self._started if self._started else 0.0}
        lines = [f"시나리오: {self._base.split('_')[-1]}",
                 f"촬영 대상: {config.DEMO_TARGETS}",
                 f"오버레이: {self._overlay}",
                 f"길이: {info['seconds']:.1f}초",
                 f"1인칭 프레임 밀어넣기: {self._pushed}장 "
                 f"(기대 {int(info['seconds'] * config.DEMO_CAPTURE_FPS)}장)", ""]
        lines.extend(extra_lines)
        for name in sorted(os.listdir(self._dir)):
            path = os.path.join(self._dir, name)
            if name.endswith('.mp4') and os.path.isfile(path):
                lines.append(f"{name}  {os.path.getsize(path) / 1024 / 1024:.1f} MB")
        with open(os.path.join(self._dir, '촬영정보.txt'), 'w') as fp:
            fp.write("\n".join(lines) + "\n")
