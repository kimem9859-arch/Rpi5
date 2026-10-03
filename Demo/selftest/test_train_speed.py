"""첫 속도 측정(학습/speedprobe.py)의 판단을 고정한다 — 에폭당 시간 · 동시 개수(메모리 안 · 처리량 10% 이상).

실행: python3 Demo/selftest/test_train_speed.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §7
"""
import os
import sys

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import speedprobe as SPD

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def m(ok, s, g):
    return {"ok": ok, "s_per_epoch": s, "gpu_peak_mb": g}


def test_에폭당_시간():
    print("[1] 에폭당 시간 — 첫 에폭(준비·캐시) 빼고")
    check(SPD.s_per_epoch([{"time": 10}, {"time": 30}, {"time": 50}]) == 20, "(50 − 10) / 2 = 20")
    check(SPD.s_per_epoch([{"time": 12}]) == 12 and SPD.s_per_epoch([]) is None, "한 행 · 빈 것")


def test_동시_개수():
    print("[2] 동시 개수 — 메모리 안 · 처리량 10% 이상 늘 때만")
    check(SPD.choose_concurrency({1: m(True, 20, 2000), 2: m(True, 30, 4000), 3: m(True, 40, 6000)}, 8192) == 3, "셋 다 이득 → 3")
    check(SPD.choose_concurrency({1: m(True, 20, 2000), 2: m(True, 38, 4000)}, 8192) == 1, "2개 처리량 +5% → 1")
    check(SPD.choose_concurrency({1: m(True, 20, 2000), 2: m(True, 30, 4000), 3: m(False, None, 8000)}, 8192) == 2, "3개 실패 → 2")
    check(SPD.choose_concurrency({1: m(True, 20, 2000), 2: m(True, 30, 7500)}, 8192) == 1, "2개 GPU 최고치가 여유(1GB) 침범 → 1")


if __name__ == "__main__":
    test_에폭당_시간()
    test_동시_개수()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for x in _fails:
            print(f"   - {x}")
        sys.exit(1)
    print("✅ 속도 측정 판단 검증 통과")
