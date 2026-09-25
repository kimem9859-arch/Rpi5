"""인식 쪽 수정 검증(R1~R3·R5) — Hailo·카메라 없이.

실행: python3 Demo/selftest/test_recognition.py
🔴 버튼 검출기를 가짜로 바꿔 끼운다 — `camera_thread` 는 import 할 때 검출기(Hailo)를 연다.
정본 = 상위 docs/superpowers/specs/2026-09-25-런타임-문제수정-design.md §4.1
"""
import os
import sys
import types

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np


class _FakeDetector:
    backend_name = "시험용"
    NAMES = {0: "B1", 1: "B2", 2: "B3", 3: "B4", 4: "EMO"}

    def __init__(self):
        self.dets = []

    def class_name(self, i):
        return self.NAMES[i]

    def detect(self, frame):
        return list(self.dets)


_FAKE_DET = _FakeDetector()
_fake_mod = types.ModuleType("detector")
_fake_mod.create_detector = lambda: _FAKE_DET
sys.modules["detector"] = _fake_mod

import config
config.HAND_ENABLED = False
config.TOOL_ENABLED = False

from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

import camera_thread as ct

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------------------------------------------------------- R1 손 고르기
def test_r1_pick_hand_uses_same_hand():
    """R1 — 신뢰도와 좌표를 같은 손에서 가져온다(검토 C10)."""
    print("\n[R1] 손 고르기")
    from hand_tracker import pick_hand
    lm_a, lm_b = ["0번 손"], ["1번 손"]
    check(pick_hand([0.1, 0.9], [lm_a, lm_b], 0.5) is lm_b, "신뢰도 높은 1번 손의 좌표를 쓴다")
    check(pick_hand([[0.9], [0.1]], [lm_a, lm_b], 0.5) is lm_a, "flags 모양이 (N,1) 이어도")
    check(pick_hand([0.1, 0.3], [lm_a, lm_b], 0.5) is None, "둘 다 기준 미달이면 손 없음")
    check(pick_hand(None, [lm_a], 0.5) is None, "flags 없음 → 손 없음")
    check(pick_hand([0.9], [], 0.5) is None, "랜드마크 없음 → 손 없음")


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
    print("✅ 인식 검증 통과")
