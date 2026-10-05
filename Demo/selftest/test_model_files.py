"""시연 모델 파일 — config 가 가리키는 파일이 있고, 이름이 흔해 겹치던 옛 best.pt 가 person_v1.pt 로 바뀌었다.

실행: python3 Demo/selftest/test_model_files.py
계기: 2026-10-05 옛 Demo/models/best.pt 가 버튼 모델이 아니라 사람 1종(person_v1)으로 드러나 이름을 바꿨다(사용자 「바꿔줘」).
      console_v1·console_v2·tool_v* 는 이름 그대로다(사용자 범위 결정 · 통합문서 §6.4).
"""
import os
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import config  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_파일():
    print("[m1] config 의 PT 경로 = person_v1.pt(있음) · HEF 경로 파일 있음 · models/ 에 옛 best.pt 없음")
    check(os.path.basename(config.PT_MODEL_PATH) == "person_v1.pt" and os.path.isfile(config.PT_MODEL_PATH), f"PT = person_v1.pt — {config.PT_MODEL_PATH}")
    check(os.path.isfile(config.HEF_MODEL_PATH), f"HEF 있음 — {os.path.basename(config.HEF_MODEL_PATH)}")
    check(not os.path.exists(os.path.join(_DEMO, "models", "best.pt")), "옛 best.pt 없음")


if __name__ == "__main__":
    test_파일()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 시연 모델 파일 검증 통과")
