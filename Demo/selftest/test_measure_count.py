"""세기 값 함수(측정 도구 정합 1단계-나 · 관문 ⑤) — 손으로 만든 작은 기록으로.

실행: python3 Demo/selftest/test_measure_count.py
설계 = 상위 docs/superpowers/specs/2026-10-09-측정도구-정합-1단계-나-세기-design.md
"""
import inspect
import os
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import fps

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_fps_criteria_shared():
    print("\n[기준] FPS 창·끊김 = fps.py 상수 하나를 시연 화면과 세기가 같이 쓴다")
    check(getattr(fps, "FPS_WINDOW", None) == 60, "fps.FPS_WINDOW = 60(시연 화면이 쓰던 값 그대로)")
    check(getattr(fps, "STALE_SEC", None) == 2.0, "fps.STALE_SEC = 2.0")
    check(inspect.signature(fps.fps_stale).parameters["stale_after"].default == getattr(fps, "STALE_SEC", None),
          "fps_stale 기본값 = STALE_SEC")
    src = open(os.path.join(_DEMO, "safety_console.py"), encoding="utf-8").read()
    check("len(self._fps_intervals) > FPS_WINDOW" in src, "safety_console 이 FPS_WINDOW 로 창을 자른다")
    check("len(self._fps_intervals) > 60" not in src, "숫자 60 이 남아 있지 않다")


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 세기 값 함수 검증 통과")
