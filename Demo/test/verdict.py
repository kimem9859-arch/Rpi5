"""가장 최근 벤치 세션의 중단 규칙 판정을 출력한다.

왜 있나: 클린룸처럼 현장에서 바로 판단해야 하는 상황에서, bench_detector의 요약을 눈으로
훑는 대신 합의된 규칙을 기계가 적용해 통과/중단을 한 줄로 알려주기 위함.

판정 규칙 (2026-07-20 설계 승인분):
    1. 5클래스(B1~B4·EMO) 중 raw 검출 0회인 클래스가 있으면  → 중단
    2. 어떤 클래스의 평균 신뢰도 < CONF_WARN(0.70)이면         → 중단
    둘 다 아니면 통과 → 다음 조건 진행.

판정에는 rawdet(트래킹 이전, >=YOLO_CONF_LOW)을 쓴다. confirmed 트랙만 보면 저신뢰 B4가
사각지대에 숨는다 — v1에서 실제로 그랬다.

    python3 test/verdict.py                      # 최신 세션
    python3 test/verdict.py --condition cleanroom # 해당 조건의 최신 세션
"""

import argparse
import csv
import glob
import os
import statistics
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(_TEST_DIR, "logs")

CLASSES = ["B1", "B2", "B3", "B4", "EMO"]
CONF_WARN = 0.70          # bench_detector.CONF_WARN 과 같은 값 (판정선)


def main():
    ap = argparse.ArgumentParser(description="최근 벤치 세션 중단규칙 판정")
    ap.add_argument("--condition", default=None, help="조건 슬러그로 세션 한정")
    args = ap.parse_args()

    pattern = f"*_{args.condition}_*_rawdet_log.csv" if args.condition else "*_rawdet_log.csv"
    files = sorted(glob.glob(os.path.join(LOGS_DIR, pattern)), key=os.path.getmtime)
    if not files:
        print("판정할 rawdet 로그를 찾지 못했습니다.")
        return 2

    path = files[-1]
    print(f"세션: {os.path.basename(path)[:-len('_rawdet_log.csv')]}\n")

    scores, frames = {}, {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            scores.setdefault(r["cls_name"], []).append(float(r["score"]))
            frames.setdefault(r["cls_name"], set()).add(r["frame"])

    fails = []
    print(f"{'클래스':<6}{'검출':>7}{'프레임':>8}{'평균conf':>10}{'최저':>8}   판정")
    for c in CLASSES:
        s = scores.get(c)
        if not s:
            print(f"{c:<6}{0:>7}{0:>8}{'-':>10}{'-':>8}   ❌ 미검출 0회")
            fails.append(f"{c} 미검출(0회)")
            continue
        avg = statistics.fmean(s)
        bad = avg < CONF_WARN
        mark = f"❌ 평균 conf < {CONF_WARN}" if bad else "✅"
        if bad:
            fails.append(f"{c} 평균 conf {avg:.3f}")
        print(f"{c:<6}{len(s):>7}{len(frames[c]):>8}{avg:>10.3f}{min(s):>8.3f}   {mark}")

    print()
    if fails:
        print("🔴 중단 — " + " / ".join(fails))
        print("   다음 조건으로 넘어가지 말고 원인 분석이 필요합니다.")
        return 1
    print("🟢 통과 — 다음 조건으로 진행 가능합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
