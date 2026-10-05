"""score_hef --names — 버튼(기본 5종) 말고 공구 HEF(driver·wrench·pliers)도 같은 채점 배관으로 잰다.

실행: python3 Demo/selftest/test_score_hef_names.py
계기: 학습 파라미터 체계 1-2단계 Task 15 Step 3 — 공구 변환 모델을 292장으로 채점하려니 클래스 이름이 버튼 5종으로 고정돼 있었다.
"""
import os
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO, "test"))
sys.path.insert(0, _DEMO)

import score_hef as S  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_이름():
    print("[1] --names — 쉼표 목록 · 기본 = 버튼 5종 · 빈 값·겹침은 멈춤")
    check(S.parse_names("driver,wrench,pliers") == ["driver", "wrench", "pliers"], "공구 3종")
    check(S.parse_names(" B1, B2 ,B3,B4,EMO ") == S.CLASS_NAMES, "공백 무시 · 버튼 5종 = 기본")
    for bad in ("", "driver,,pliers", "driver,driver"):
        try:
            S.parse_names(bad); ok = False
        except ValueError:
            ok = True
        check(ok, f"{bad!r} → ValueError")


if __name__ == "__main__":
    test_이름()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 채점 이름 목록 검증 통과")
