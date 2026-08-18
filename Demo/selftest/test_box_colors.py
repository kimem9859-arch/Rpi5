"""탐지 박스 색표 검증.

실행: python3 Demo/selftest/test_box_colors.py

정본: 상위 docs/superpowers/specs/2026-08-19-자동진행-결과창-design.md §5

🔴 cv2 는 BGR 이다. 16진수를 뒤집는 곳이 두 군데가 되면 반드시 한쪽이 틀린다 —
   변환은 box_bgr() 한 곳에서만 한다. 이 테스트가 그것을 지킨다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import config
from camera_thread import box_bgr

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_hex_to_bgr():
    """16진수 → BGR 튜플. RGB 로 뒤집히면 여기서 잡힌다."""
    print("\n[1] BGR 변환")
    check(box_bgr("B1") == (0, 212, 255), f"B1 노랑 #FFD400 → BGR {box_bgr('B1')}")
    check(box_bgr("B4") == (255, 125, 46), f"B4 파랑 #2E7DFF → BGR {box_bgr('B4')}")
    check(box_bgr("B2") == (255, 255, 255), "B2 흰 → (255,255,255)")


def test_every_button_class_has_color():
    """모델이 내는 5클래스가 전부 표에 있는가."""
    print("\n[2] 버튼 5클래스")
    for name in ("B1", "B2", "B3", "B4", "EMO"):
        check(name in config.DETECT_BOX_COLORS, f"{name} 색 있음")


def test_every_recipe_tool_has_color():
    """레시피가 쓰는 공구가 전부 표에 있는가."""
    print("\n[3] 공구")
    from recipe import load_recipe
    for s in load_recipe().get("steps", []):
        for key in (s.get("sub") or {}).get("tools", []):
            check(key in config.TOOL_BOX_COLORS, f"{key} 색 있음")


def test_unknown_falls_back():
    """표에 없는 이름은 죽지 않고 폴백색을 쓴다."""
    print("\n[4] 폴백")
    check(box_bgr("B9") == box_bgr_of_hex(config.DETECT_BOX_FALLBACK),
          "모르는 클래스 → 폴백색")


def box_bgr_of_hex(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


if __name__ == "__main__":
    test_hex_to_bgr()
    test_every_button_class_has_color()
    test_every_recipe_tool_has_color()
    test_unknown_falls_back()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 박스 색표 검증 통과")
