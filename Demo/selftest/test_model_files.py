"""시연 모델 파일 — config 가 가리키는 파일이 있고 옛 이름(console_* · tool_* · best.pt)이 남지 않았다.

실행: python3 Demo/selftest/test_model_files.py
정본 설계: 상위 docs/superpowers/specs/2026-10-05-모델이름-정리-design.md §2.4 · 목록 = 통합문서 §6.4
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
    print("[m1] config 의 모델 경로 = 새 이름 · git 추적 파일은 반드시 있다 · git 밖(T_*)은 없으면 건너뜀")
    names = {os.path.basename(p) for p in (config.PT_MODEL_PATH, config.HEF_MODEL_PATH, config.TOOL_MODEL_PATH)}
    check(names == {"person_v1.pt", "B_v2.hef", "T_v3.pt"}, f"config 경로 = person_v1.pt · B_v2.hef · T_v3.pt — {sorted(names)}")
    for p in (config.PT_MODEL_PATH, config.HEF_MODEL_PATH):
        check(os.path.isfile(p), f"{os.path.basename(p)} 있음")
    if not os.path.isfile(config.TOOL_MODEL_PATH):
        print("  ⏭️  T_v3.pt 없음(git 밖) — 이 머신에 공구 모델 사본이 없거나 옛 이름이다 → 학습/이름대조표.md 머리말의 한 줄로 바꾼다")
    old = [f for f in os.listdir(os.path.join(_DEMO, "models")) if f.startswith(("console_", "tool_")) or f == "best.pt"]
    check(not old, f"옛 이름 없음 — {old}")


if __name__ == "__main__":
    test_파일()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 시연 모델 파일 검증 통과")
