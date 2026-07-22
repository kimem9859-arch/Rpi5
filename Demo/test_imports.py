"""시연 경로 스모크 테스트 — GUI 진입점이 import 되는가.

왜 있나 (2026-07-22):
    손 검출 통합(0953294)이 `camera_thread.MEDIAPIPE_AVAILABLE` 을 지웠는데
    `safety_console.py` 가 그걸 계속 import 하고 있었다. **시연 경로가 통째로
    죽어 있었고**(`./run_demo.sh` → ImportError), 카메라를 연결하고서야 발견했다.

    놓친 이유가 분명하다: 당시 검증은 `camera_thread` 를 **직접** import 하고
    `test_fsm`·`test_hoi_sim` 을 돌린 게 전부였는데, **그 어느 것도 `safety_console`·
    `main` 을 import 하지 않는다.** 모듈 하나의 최상위 이름이 사라져도 소비자 쪽은
    아무도 안 건드려 보는 사각지대였다.

    이 테스트는 그 사각지대만 막는다 — GUI를 띄우지 않고 **import 만** 해 본다.
    실행에 수 초 걸린다(Hailo 백엔드가 실제로 로드된다).

⚠️ `camera_thread` 는 import 시점에 Hailo 디텍터를 만든다. 닫지 않고 인터프리터를
   끝내면 종료 중 해제가 세그폴트를 낸다(실측). 그래서 마지막에 반드시 닫는다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# GUI 위젯을 만들지 않아도 PyQt6 import 자체는 디스플레이가 없어도 된다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_gui_entrypoints_import():
    """safety_console·main 이 import 되는가 = 시연 경로가 살아 있는가."""
    import main                     # noqa: F401  (main 이 safety_console 을 끌어온다)
    import safety_console           # noqa: F401
    print("  PASS  시연 경로 import: main · safety_console")


def test_camera_thread_exports():
    """safety_console 이 camera_thread 에서 가져다 쓰는 이름이 실제로 있는가."""
    import ast

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safety_console.py")
    with open(src) as f:
        tree = ast.parse(f.read())

    wanted = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "camera_thread":
            wanted += [a.name for a in node.names]
    assert wanted, "safety_console 이 camera_thread 에서 아무것도 안 가져온다 — 배선이 끊겼다"

    import camera_thread
    missing = [n for n in wanted if not hasattr(camera_thread, n)]
    assert not missing, f"camera_thread 에 없는 이름을 import 하고 있다: {missing}"
    print(f"  PASS  camera_thread 공개 이름 {len(wanted)}개 일치: {', '.join(wanted)}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    try:
        for t in tests:
            t()
        print(f"\n{len(tests)}/{len(tests)} passed")
    finally:
        # 🔴 닫지 않으면 종료 중 세그폴트가 나서 통과/실패가 exit code로 안 드러난다.
        try:
            import camera_thread
            camera_thread.close_detector()
        except Exception:
            pass
