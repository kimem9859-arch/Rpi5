"""시연 녹화 1인칭 파이프 검증 — 한쪽이 죽어도 다른 쪽은 계속 민다(G12).

실행: python3 Demo/selftest/test_demo_recorder.py
⚠️ ffmpeg 를 띄우지 않는다 — FfmpegSet 을 가짜로 바꾼다.
"""
import os
import sys
import tempfile
import threading
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import numpy as np

import config
from demo_recorder import DemoRecorder

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _Good:
    def __init__(self):
        self.writes = 0

    def write(self, b):
        self.writes += 1


class _Broken:
    def write(self, b):
        raise BrokenPipeError("ffmpeg 가 죽었다")


class _FakeFf:
    """FfmpegSet 대역 — start 는 주어진 파이프 목록을 그대로 쓴다."""

    def __init__(self, pipes):
        self.fpv_pipes = pipes

    def start(self, screen_rect, fpv_size, paths):
        return []

    def stop(self):
        pass


def _recorder(pipes, tmp):
    rec = DemoRecorder(tmp, "20260925_000000", "시험", "켬")
    rec._ff = _FakeFf(pipes)
    img = np.zeros((8, 6, 3), np.uint8)
    rec.submit_camera(img, img)
    return rec


def test_one_pipe_dies_other_continues():
    """G12 — 오버레이 켬 쪽이 죽어도 끔 쪽은 계속 받는다."""
    print("\n[G12] 한쪽이 죽어도 다른 쪽은 계속")
    old_fps = config.DEMO_CAPTURE_FPS
    config.DEMO_CAPTURE_FPS = 100                    # 짧게 돌린다
    try:
        with tempfile.TemporaryDirectory() as tmp:
            good = _Good()
            rec = _recorder([_Broken(), good], tmp)
            rec._fpv_size = (6, 8)
            rec._running = True
            t = threading.Thread(target=rec._feed, daemon=True)
            t.start(); time.sleep(0.2); rec._running = False; t.join(timeout=2)
            check(good.writes > 3, f"끔 쪽이 계속 받는다 — {good.writes}회")
            check(getattr(rec, "take_dead", lambda: None)() == ["오버레이 켬"],
                  "멈춘 쪽이 알림 대상에 오른다")
            check(getattr(rec, "take_dead", lambda: None)() == [], "한 번 가져가면 비워진다")
    finally:
        config.DEMO_CAPTURE_FPS = old_fps


def test_immediate_death_is_reported():
    """G12 — 시작하자마자 죽은 쪽(None 자리)도 알림 대상에 오른다."""
    print("\n[G12] 즉시 종료도 알림")
    old = config.demo_wants
    config.demo_wants = lambda what: False           # 피더 스레드를 띄우지 않는다
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rec = _recorder([None, _Good()], tmp)
            rec.start((0, 0, 100, 100), (0, 0, 10, 10))
            check(getattr(rec, "take_dead", lambda: None)() == ["오버레이 켬"],
                  "시작 때 죽은 쪽이 오른다")
            rec.stop()
    finally:
        config.demo_wants = old


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
    print("✅ 시연 녹화 파이프 검증 통과")
