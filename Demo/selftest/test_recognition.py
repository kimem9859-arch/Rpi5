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


# ---------------------------------------------------------------- R2 두 프레임 확정
def _det(cls, score, box):
    return (cls, score, *box)


def test_r2_single_frame_fake_not_used():
    """R2 — 한 프레임짜리 오분류(B3 자리에 가짜 EMO)는 판정 박스가 되지 않는다(검토 C11ⓐ)."""
    print("\n[R2] 한 프레임 가짜")
    tr = []
    box = (100, 100, 140, 140)
    for _ in range(2):
        ct._update_tracks(tr, [_det(2, 0.9, box)])                       # B3 확정
    ct._update_tracks(tr, [_det(2, 0.9, box), _det(4, 0.71, (105, 105, 130, 130))])
    labels = [b[0] for b in ct._labeled_boxes(tr)]
    check(labels == ["B3"], f"판정 박스 = {labels}")
    roi, _level = ct.zone_at_point(115, 115, tr, ring=0)
    check(roi == "B3", f"손끝 ROI = {roi} — 가짜 EMO 가 끼어들면 안 된다")


def test_r2_established_not_displaced():
    """R2 — 자리 잡은 트랙은 한 프레임짜리 같은 클래스 가짜에 밀려나지 않는다(검토 C11ⓑ)."""
    print("\n[R2] 자리 잡은 트랙 유지")
    tr = []
    real = (200, 200, 240, 240)
    for _ in range(2):
        ct._update_tracks(tr, [_det(3, 0.9, real)])
    ct._update_tracks(tr, [_det(3, 0.55, real), _det(3, 0.66, (400, 50, 440, 90))])
    boxes = [b[1:] for b in ct._labeled_boxes(tr)]
    check(boxes == [real], f"B4 박스 = {boxes} — 손에 가려 점수가 낮아진 진짜 자리여야 한다")


def test_r2_established_beats_persistent_fake():
    """R2 — 둘 다 보이면 먼저 자리 잡은 트랙이 남는다 — 여러 프레임 이어진 가짜도 점수로 못 이긴다(설계 R2)."""
    print("\n[R2] 오래된 트랙 우선")
    tr = []
    real = (200, 200, 240, 240)
    for _ in range(3):
        ct._update_tracks(tr, [_det(3, 0.9, real)])
    for _ in range(3):
        ct._update_tracks(tr, [_det(3, 0.55, real), _det(3, 0.9, (400, 50, 440, 90))])
    boxes = [b[1:] for b in ct._labeled_boxes(tr)]
    check(boxes == [real], f"B4 박스 = {boxes} — 세 프레임 이어진 점수 높은 가짜에도 진짜 자리가 남는다")


def test_r2_new_track_confirmed_after_two_frames():
    """R2 — 새 버튼은 두 프레임 연속 보이면 판정에 들어간다(한 프레임 늦음 · Review Focus 3)."""
    print("\n[R2] 두 프레임 확정")
    tr = []
    box = (10, 10, 50, 50)
    ct._update_tracks(tr, [_det(0, 0.9, box)])
    check(ct._labeled_boxes(tr) == [], "첫 프레임 — 아직 판정에 안 쓴다")
    ct._update_tracks(tr, [_det(0, 0.9, box)])
    check([b[0] for b in ct._labeled_boxes(tr)] == ["B1"], "두 번째 프레임 — 판정에 쓴다")


def test_r2_moved_box_follows_after_two_frames():
    """R2 — 박스가 크게 튀면 두 번째 프레임부터 새 자리를 쓴다(그 전엔 옛 자리)."""
    print("\n[R2] 튄 박스")
    tr = []
    a, b = (10, 10, 50, 50), (300, 300, 340, 340)
    for _ in range(2):
        ct._update_tracks(tr, [_det(0, 0.9, a)])
    ct._update_tracks(tr, [_det(0, 0.9, b)])
    check([x[1:] for x in ct._labeled_boxes(tr)] == [a], "튄 첫 프레임 — 아직 옛 자리")
    ct._update_tracks(tr, [_det(0, 0.9, b)])
    check([x[1:] for x in ct._labeled_boxes(tr)] == [b], "두 번째 프레임 — 새 자리")

# ---------------------------------------------------------------- R3 손 검출 입력
class _RecordingHand:
    """손 검출 대역 — 받은 프레임을 복사해 둔다."""
    available = True
    reason = ""

    def __init__(self):
        self.seen = []

    def detect(self, frame, draw_on=None):
        self.seen.append(frame.copy())
        return None


def _thread():
    th = ct.CameraThread()
    th._hand = _RecordingHand()
    return th


def test_r3_hand_sees_frame_before_boxes():
    """R3 — 손 모델 입력에 버튼 박스 선이 없다(함수목록 §4.1-1 — 표시 설정이 손 입력을 바꾸던 것)."""
    print("\n[R3] 손 검출 입력")
    th = _thread()
    th.set_draw_boxes(True)
    _FAKE_DET.dets = [(0, 0.9, 20, 20, 60, 60)]
    img = np.zeros((120, 160, 3), np.uint8)
    for _ in range(2):                                   # 두 번째 프레임에 B1 확정 → 그림
        th._process_frame(img.copy())
    seen = th._hand.seen[-1]
    check(int(seen.max()) == 0, f"손 모델 입력에 박스 선이 없다 — 최댓값 {int(seen.max())}")
    _FAKE_DET.dets = []

# ---------------------------------------------------------------- R5 재연결
def test_r5_reconnect_clears_tracks_and_signals():
    """R5 — (재)연결되면 끊기기 전 트랙을 버리고 GUI 에 알린다(검토 C4 — 옛 트랙이 남았다)."""
    print("\n[R5] 재연결")
    th = _thread()
    th._tracks = [{'cls': 2, 'box': (1, 1, 5, 5), 'score': 0.9, 'miss': 3, 'hits': 5, 'confirmed': True}]
    got = []
    th.stream_reset_signal.connect(lambda: got.append(1))
    th._on_connected()
    check(th._tracks == [], "옛 트랙이 비워진다")
    check(got == [1], "재연결 신호가 나간다")

class _PaintingHand(_RecordingHand):
    """손 검출 대역 — 그릴 곳에 손 표시 한 점을 찍는다."""

    def detect(self, frame, draw_on=None):
        super().detect(frame, draw_on)
        if draw_on is not None:
            draw_on[20, 40] = (1, 2, 3)                  # B1 박스 윗변(y=20) 위의 한 점
        return None


def test_r3_landmarks_drawn_over_boxes():
    """R3 — 화면 모습은 종전 그대로: 손 랜드마크가 버튼 박스 선 **위에** 그려진다(최종 리뷰 M-7)."""
    print("\n[R3] 그리는 순서")
    th = ct.CameraThread()
    th._hand = _PaintingHand()
    th.set_draw_boxes(True)
    _FAKE_DET.dets = [(0, 0.9, 20, 20, 60, 60)]
    img = np.zeros((120, 160, 3), np.uint8)
    for _ in range(2):                                   # 두 번째 프레임에 B1 확정 → 그림
        out = th._process_frame(img.copy())
    px = tuple(int(v) for v in out[20, 40])
    check(px == (1, 2, 3), f"박스 선 위 한 점 = {px} — 랜드마크가 박스 위에 있어야 한다")
    check(int(th._hand.seen[-1].max()) == 0, "손 모델 입력에는 여전히 박스 선이 없다")
    _FAKE_DET.dets = []

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
