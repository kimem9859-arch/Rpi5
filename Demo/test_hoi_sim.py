"""HOI→FSM 통합 시뮬레이션 — 버튼 검출 모델(B1~B4)이 있다고 가정.

GUI/카메라 라이브러리(PyQt6·cv2·numpy·mediapipe)를 스텁으로 막고,
camera_thread.roi_at_point(검출 박스 기반 ROI 판정)이 SafetyFSM과 맞물려
'손끝이 어느 버튼 박스에 있는가 → 상태 전이'가 실제로 도는지 확인한다.

실행: python Demo/test_hoi_sim.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(__file__))


# --- 무거운 라이브러리 스텁 (camera_thread import만 통과시키면 됨) ---
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


_stub("cv2")
_stub("numpy")
_stub("mediapipe")
qtcore = _stub("PyQt6.QtCore", QThread=type("QThread", (), {}),
               pyqtSignal=lambda *a, **k: None)
_stub("PyQt6.QtGui", QImage=object)
_stub("PyQt6", QtCore=qtcore)

import camera_thread
from fsm import SafetyFSM, State


# --- 버튼 4개를 검출하는 모델이 있다고 가정 (라벨 B1~B4) ---
class FakeDetector:
    backend_name = "fake"
    _names = {1: "B1", 2: "B2", 3: "B3", 4: "B4"}

    def class_name(self, cls_id):
        return self._names.get(cls_id, str(cls_id))


camera_thread._detector = FakeDetector()

# 화면에 검출된 버튼 박스 4개 (검출 모델이 매 프레임 준다고 가정한 좌표)
TRACKS = [
    {"cls": 1, "box": (50, 400, 150, 500)},    # B1
    {"cls": 2, "box": (200, 400, 300, 500)},   # B2
    {"cls": 3, "box": (350, 400, 450, 500)},   # B3
    {"cls": 4, "box": (500, 400, 600, 500)},   # B4
]

CENTER = {  # 각 버튼 박스 중심 (손끝을 여기 두면 그 ROI)
    "B1": (100, 450), "B2": (250, 450), "B3": (400, 450), "B4": (550, 450),
}
OUTSIDE = (700, 100)  # 어떤 박스에도 없는 좌표


def roi(label_or_outside):
    pt = CENTER.get(label_or_outside, OUTSIDE)
    return camera_thread.roi_at_point(pt[0], pt[1], TRACKS)


# --------------------------------------------------------------------- 검증
def test_roi_at_point_maps_box_to_label():
    assert roi("B1") == "B1"
    assert roi("B3") == "B3"
    assert roi("nowhere") is None
    print("  PASS  roi_at_point: 손끝 위치 → 검출 박스 라벨")


def test_perception_to_fsm_correct_path():
    """B1 박스에 손 → 누름 → 단계 진행 (정상 루프)."""
    fsm = SafetyFSM()
    fsm.load_recipe()
    fsm.update_vision(roi("B1"), now=0.0)     # 손끝 B1 박스 안
    assert fsm.state == State.MONITOR
    fsm.press_button("B1")
    assert fsm.expected_step == 2
    print("  PASS  인식→판정: B1 박스 진입 + 눌림 → 단계 2")


def test_perception_to_fsm_violation_path():
    """기대=1인데 B3 박스에 손 체류 → WARNING (순서 위반 감지)."""
    fsm = SafetyFSM(dwell_threshold=1.0)
    fsm.load_recipe()
    fsm.update_vision(roi("B3"), now=0.0)     # B3 = 오답 ROI
    fsm.update_vision(roi("B3"), now=1.0)     # 체류 1.0초 → 위반
    assert fsm.state == State.WARNING
    print("  PASS  인식→판정: 오답 박스 체류 → WARNING")


def test_hand_leaves_all_boxes():
    """손이 모든 박스 밖 → roi None → 오답 스침 시 정상 복귀."""
    fsm = SafetyFSM(dwell_threshold=1.0)
    fsm.load_recipe()
    fsm.update_vision(roi("B2"), now=0.0)     # 오답 체류 시작
    assert fsm.state == State.MONITOR
    fsm.update_vision(roi("nowhere"), now=0.5)  # 손 이탈(스침)
    assert fsm.state == State.PROCESS_RUN
    print("  PASS  인식→판정: 박스 이탈(스침) → 정상 복귀")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} passed")
