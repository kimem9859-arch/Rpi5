"""측정 도구로 재학습 모델(HEF)을 돌린다 — 버튼 모델 바꿔 끼우기(--hef) · 공구도 NPU 로(--tool-hef).

실행: python3 Demo/selftest/test_bench_tool_hef.py
계기: 2026-10-06 사용자 「재학습한 버튼, 공구 모델(hef)을 파이1에 올려서 버튼, 공구, 손 모델을 한번에 돌려
      성능 확인」 — 시연 프로그램은 그대로 두고(사용자 「측정 도구에서만」) 측정 도구에서만 세 모델을 함께 돌린다.
      NPU 장치는 없어도 되는 시험만 둔다(모델 로드는 실HW 측정에서 본다).
"""
import inspect
import os
import subprocess
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import detector  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_검출기_인자():
    print("[t1] NPU 검출기가 모델 파일·클래스 이름을 받는다 — 기본값은 지금 시연 그대로(설정 파일 · B1~EMO)")
    sig = inspect.signature(detector.HailoDetector.__init__)
    for name in ("hef_path", "names"):
        p = sig.parameters.get(name)
        check(p is not None and p.default is None, f"{name} 인자 · 기본값 None")


def test_모델_이름표():
    print("[t2] 파일 이름표 — 학습 실험 폴더의 model.hef 는 폴더 이름으로 · 소문자·밑줄만(산출물 파일명 규약)")
    import bench_detector as bd
    check(bd._hef_label("/x/학습실험/E0b-button-s0/model.hef") == "e0b_button_s0", "model.hef → 폴더 이름")
    check(bd._hef_label("/x/models/console_v2.hef") == "console_v2", "보통 파일은 파일 이름")
    check(bd._hef_label("/x/E0c-tool-f120/model.hef") == "e0c_tool_f120", "공구 실험 폴더")


def test_옵션():
    print("[t3] 측정 도구가 --hef · --tool-hef 를 받는다")
    out = subprocess.run([sys.executable, os.path.join(_DEMO, "test", "bench_detector.py"), "--help"],
                         capture_output=True, text=True, timeout=60).stdout
    check("--hef" in out and "--tool-hef" in out, "도움말에 두 옵션")
    check("--tool-interval" in out, "공구 간격 옵션(시연은 1초에 한 번 — config.TOOL_SCAN_INTERVAL_SEC)")


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
    print("✅ 측정 도구 재학습 모델 옵션 통과")
