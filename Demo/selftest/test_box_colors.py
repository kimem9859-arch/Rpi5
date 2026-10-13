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
    check(box_bgr("B4") == (255, 182, 107), f"B4 밝은 파랑 #6BB6FF → BGR {box_bgr('B4')}")
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


def test_role_colors():
    """② 단계 뜻 색(설계 2026-10-13 §3 ②) — 지금 노랑 · 끝남 초록 · 남은 회색 · EMO 빨강 · 경고 주황 · 차단 빨강."""
    print("\n[역할] 단계 뜻 색")
    from camera_thread import role_bgr
    check(role_bgr("current") == (92, 215, 255), f"current {role_bgr('current')}")
    check(role_bgr("warn") == (69, 157, 255), f"warn {role_bgr('warn')}")
    for r in ("current", "done", "todo", "emo", "warn", "block"):
        check(r in config.BOX_ROLE_COLORS, f"{r} 표에 있음")


def test_label_draws_inside_frame_and_glyphs():
    """② 이름표 — 위쪽 끝 상자도 화면 안 · ✓ ✕ 자물쇠 선 그리기가 죽지 않는다."""
    print("\n[역할] 이름표 그리기")
    import numpy as np
    from camera_thread import draw_box_label
    f = np.zeros((480, 640, 3), np.uint8)
    for role in ("current", "done", "todo", "emo", "warn", "block"):
        draw_box_label(f, (10, 2, 120, 90), "B1", role, score=0.94)
    check(bool(f.any()), "무언가 그려짐")
    g = np.zeros((480, 640, 3), np.uint8)
    draw_box_label(g, (10, 2, 120, 90), "B1", "current")
    check(bool(g[4:30, 12:60].any()), "이름표가 상자 안쪽 위로 내려옴(화면 밖으로 안 나감)")
    h = np.zeros((480, 640, 3), np.uint8)
    draw_box_label(h, (100, 100, 200, 180), "B2", "done")
    check(tuple(int(v) for v in h[100, 105]) == (168, 255, 125), f"꺾쇠 = 끝남 초록 {tuple(h[100, 105])}")
    check(not h[140, 150].any(), "상자 가운데는 비어 있음(꺾쇠만)")


def test_unknown_falls_back():
    """표에 없는 이름은 죽지 않고 폴백색을 쓴다."""
    print("\n[4] 폴백")
    check(box_bgr("B9") == box_bgr_of_hex(config.DETECT_BOX_FALLBACK),
          "모르는 클래스 → 폴백색")


def box_bgr_of_hex(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


if __name__ == "__main__":
    try:
        test_hex_to_bgr()
        test_every_button_class_has_color()
        test_every_recipe_tool_has_color()
        test_unknown_falls_back()
        test_role_colors()
        test_label_draws_inside_frame_and_glyphs()
        print()
        if _fails:
            print(f"❌ 실패 {len(_fails)}건")
            for m in _fails:
                print(f"   - {m}")
            sys.exit(1)
        print("✅ 박스 색표 검증 통과")
    finally:
        # 🔴 camera_thread 를 import 하면 Hailo 탐지기가 열린다 — 닫지 않으면 종료 중
        #    세그폴트가 나서 통과/실패가 exit code 로 안 드러난다(test_camera_calib 와 같은 처리).
        import camera_thread
        camera_thread.close_detector()
