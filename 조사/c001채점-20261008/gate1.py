"""Task 3 — 관문 ① .pt 재현: 장소1 채점 292장에서 이 스크립트 값 = 학습 체계 채점.json(종류별 tp·fp·fn 각 ±1) · 설계 §4.7.

실행(python3): python3 gate1.py   · 종료 코드 0 = 통과
"""
import sys

import common as C

IDS = ["E15-button-base", "E13-tool-base", "E1c-tool-f120in1024"]     # 버튼 640 · 공구 640 · 원본 입력


def compare(ours, theirs, names):
    rows, worst = [], 0
    for n in names:
        d = {k: ours["클래스"][n][k] - theirs["클래스"][n][k] for k in ("tp", "fp", "fn")}
        worst = max(worst, *map(abs, d.values()))
        rows.append(f"  {n:<7} 이 스크립트 {ours['클래스'][n]['tp']}·{ours['클래스'][n]['fp']}·{ours['클래스'][n]['fn']}"
                    f"  ↔ 채점.json {theirs['클래스'][n]['tp']}·{theirs['클래스'][n]['fp']}·{theirs['클래스'][n]['fn']}  차이 {d}")
    return rows, worst


def main():
    bad = []
    for rid in IDS:
        names = C.NAMES[C.group_of_id(rid)]
        ours = C.load_json(C.W / "out" / "pt" / "place1_292" / f"{rid}.json")["요약"]
        theirs = C.load_json(C.RESULTS / rid / "채점.json")
        if (ours["사진"], ours["정답박스"]) != (theirs["사진"], theirs["정답박스"]):
            bad.append(f"{rid} 사진·정답 수 다름 {ours['사진']}/{ours['정답박스']} ↔ {theirs['사진']}/{theirs['정답박스']}")
            continue
        rows, worst = compare(ours, theirs, names)
        print(f"{rid} (사진 {ours['사진']} · 정답 {ours['정답박스']}) — 가장 큰 차이 {worst}")
        print("\n".join(rows))
        print(f"  오분류 {ours['오분류']} ↔ {theirs['오분류']} · 오검출 {ours['오검출']} ↔ {theirs['오검출']}")
        if worst > 1:
            bad.append(f"{rid} 차이 {worst} > 1")
    print("관문 ① " + ("✅" if not bad else "❌ " + " · ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
