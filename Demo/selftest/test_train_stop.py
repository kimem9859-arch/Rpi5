"""학습 멈춤 규칙(학습/stoprules.py)을 고정한다 — 포화 · 점수0 · results.csv 읽기 · 진행 없음 · 시간 상한.

실행: python3 Demo/selftest/test_train_stop.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §7
"""
import os
import sys

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import stoprules as S

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_포화():
    print("[1] 포화 — 최근 30 에폭 최고점 향상 < 0.005")
    check(S.saturated([0.1] * 31, 30, 0.005), "31 에폭 내내 같음 → 포화")
    check(not S.saturated([0.1] * 30, 30, 0.005), "30 에폭뿐 → 아직 판단 안 함")
    rising = [0.1 + 0.001 * i for i in range(31)]          # 30 에폭에 0.03 오름
    check(not S.saturated(rising, 30, 0.005), "0.03 오름 → 계속")
    slow = [0.1 + 0.0001 * i for i in range(31)]           # 30 에폭에 0.003 오름(찔끔)
    check(S.saturated(slow, 30, 0.005), "0.003 찔끔 → 포화(일찍 멈춤이 못 잡는 경우)")


def test_점수0():
    print("[2] 점수0 — 10 에폭 뒤 mAP50 < 0.05")
    check(S.zero_score(10, 0.01, 10, 0.05), "10 에폭 · 0.01 → 이상")
    check(not S.zero_score(9, 0.01, 10, 0.05), "9 에폭 → 아직")
    check(not S.zero_score(10, 0.2, 10, 0.05), "10 에폭 · 0.2 → 정상")


def test_csv():
    print("[3] results.csv 읽기 · 가장 좋은 에폭 · 최고점 이력")
    text = "epoch,time,train/box_loss,metrics/mAP50(B),metrics/mAP50-95(B)\n1,10.5,1.2,0.5,0.1\n2,21,1.1,0.6,0.3\n\n3,31.5,1.0,0.6,0.2\n"
    rows = S.csv_rows(text)
    check(len(rows) == 3 and rows[1]["time"] == 21.0, "3 행 · 빈 줄 무시 · 숫자")
    check(S.best_epoch(rows) == 2, f"가장 좋은 에폭 2 — {S.best_epoch(rows)}")
    check(S.fitness_history(rows) == [0.1, 0.3, 0.3], f"최고점 이력 — {S.fitness_history(rows)}")
    check(S.csv_rows("") == [] and S.best_epoch([]) is None, "빈 파일")


def test_시간():
    print("[4] 진행 없음 15분 · 시간 상한 = 에폭당 × 최대 × 2")
    check(S.stalled(100, 100 + 15 * 60 + 1, 15) and not S.stalled(100, 100 + 15 * 60, 15), "15분 넘으면 진행 없음")
    check(S.time_limit_s(20, 200, 2) == 8000, "20초 × 200 × 2 = 8000초")
    check(S.over_time(0, 8001, 8000) and not S.over_time(0, 8000, 8000) and not S.over_time(0, 10 ** 9, None), "상한 넘음 · 상한 없음")


if __name__ == "__main__":
    test_포화()
    test_점수0()
    test_csv()
    test_시간()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 학습 멈춤 규칙 검증 통과")
