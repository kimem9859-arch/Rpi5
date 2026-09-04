"""홀드아웃 채점 규칙 검증 — 관문 3의 수치를 만드는 로직이라 고정해 둔다.

실행: python3 Demo/selftest/test_holdout_score.py

정본: ../../docs/superpowers/specs/2026-09-03-공구-쥔상태-검출-design.md §4 관문 3

⚠️ 모델·이미지가 필요 없다 — 박스와 클래스명을 **인자로 주입**한다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

from holdout_score import base_name, condition_of, iou, match

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


BOX = (100, 100, 200, 200)
SHIFT = (110, 110, 210, 210)      # IoU ≈ 0.68 — 같은 것으로 본다
FAR = (400, 400, 500, 500)


def test_접미어_제거():
    print("[1] 클래스명 접미어를 벗긴다 (판정 로직과 같은 규칙)")
    check(base_name("wrench-in-hand") == "wrench", "wrench-in-hand → wrench")
    check(base_name("wrench") == "wrench", "평이름은 그대로")
    check(base_name("driver-in-hand") == "driver", "driver-in-hand → driver")


def test_조건_파싱():
    print("[2] 파일명에서 조건을 읽는다")
    check(condition_of("/x/20260904_wrench_grip_0007.png") == "grip", "grip")
    check(condition_of("/x/20260904_pliers_place_0031.png") == "place", "place")
    check(condition_of("/x/이상한이름.png") == "unknown", "모르면 unknown (조용히 섞지 않는다)")


def test_iou():
    print("[3] IoU")
    check(iou(BOX, BOX) == 1.0, "같은 박스 = 1.0")
    check(iou(BOX, FAR) == 0.0, "안 겹치면 0")
    check(0.6 < iou(BOX, SHIFT) < 0.8, "조금 밀린 박스는 0.6~0.8")


def test_v3_호환_규칙():
    """🔑 v3 는 in-hand 를 모른다 — 평이름으로 맞히면 정답이어야 두 모델을 같은
    잣대로 비교할 수 있다. 이게 깨지면 v3 기준선이 부당하게 0 이 된다."""
    print("[4] 🔑 쥔 상태 정답을 평이름 검출로 맞히면 정답")
    gt = [("wrench-in-hand", BOX)]
    hit, fp = match(gt, [("wrench", SHIFT)])
    check(hit == {0}, "wrench 검출이 wrench-in-hand 정답을 맞힌다")
    check(fp == 0, "오검출로 세지 않는다")


def test_다른_공구는_오검출():
    print("[5] 다른 공구를 잡으면 미적중 + 오검출")
    gt = [("wrench-in-hand", BOX)]
    hit, fp = match(gt, [("pliers", BOX)])
    check(hit == set(), "적중 없음")
    check(fp == 1, "오검출 1")


def test_위치가_틀리면_미적중():
    print("[6] 클래스가 맞아도 위치가 다르면 미적중")
    gt = [("driver", BOX)]
    hit, fp = match(gt, [("driver", FAR)])
    check(hit == set(), "적중 없음")
    check(fp == 1, "오검출 1")


def test_검출_하나가_정답_둘을_맞히지_못한다():
    """🔴 하나의 검출이 여러 정답을 먹으면 재현율이 부풀려진다."""
    print("[7] 🔴 검출 1개가 정답 2개를 동시에 맞히지 않는다")
    gt = [("pliers", BOX), ("pliers", SHIFT)]
    hit, fp = match(gt, [("pliers", BOX)])
    check(len(hit) == 1, "정답 하나만 적중")
    check(fp == 0, "쓰인 검출은 오검출이 아니다")


def test_정답이_없으면_전부_오검출():
    print("[8] 정답이 없는 화면의 검출은 전부 오검출")
    hit, fp = match([], [("driver", BOX), ("wrench", FAR)])
    check(hit == set(), "적중 없음")
    check(fp == 2, "오검출 2")


if __name__ == "__main__":
    test_접미어_제거()
    test_조건_파싱()
    test_iou()
    test_v3_호환_규칙()
    test_다른_공구는_오검출()
    test_위치가_틀리면_미적중()
    test_검출_하나가_정답_둘을_맞히지_못한다()
    test_정답이_없으면_전부_오검출()

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 홀드아웃 채점 규칙 검증 통과")
