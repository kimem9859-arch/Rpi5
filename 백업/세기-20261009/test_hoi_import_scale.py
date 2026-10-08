"""hoi_import — y 좌표를 VGA 기준으로 환산해 담는다 (spec 2026-09-23-XGA-런타임전환 §2.5).

hoi.db 의 절벽(CLIFF_Y_VGA 337)·권장 버튼 y(120~280)·y 구간 집계는 전부 VGA 좌표다.
XGA 세션(768×1024)의 button_y 를 그대로 담으면 fsm_sim --exclude-cliff 가 조용히 틀린다.

실행: python3 Demo/selftest/test_hoi_import_scale.py   (HW 불필요)
"""
import os
import sys
import tempfile

import cv2
import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))
import hoi_import  # noqa: E402


def _session(d, name, w, h):
    os.makedirs(os.path.join(d, name))
    cv2.imwrite(os.path.join(d, name, "f00001.png"), np.zeros((h, w, 3), np.uint8))


def test_scale_from_first_png():
    with tempfile.TemporaryDirectory() as d:
        _session(d, "vga", 480, 640)          # 회전 후 세로
        _session(d, "xga", 768, 1024)
        old = hoi_import.RAW_DIR
        hoi_import.RAW_DIR = d
        try:
            assert hoi_import._px_scale("vga") == 1.0
            assert hoi_import._px_scale("xga") == 1.6
            assert hoi_import._px_scale("없는세션") == 1.0   # raw 가 없으면 VGA 로 본다
        finally:
            hoi_import.RAW_DIR = old


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("ALL OK")
