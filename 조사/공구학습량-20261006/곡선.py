"""공구 학습량 곡선 — 절반 · 지금 · +b010 의 채점(292장 · conf 0.65 · IoU 0.5)을 시드별·평균으로 한 표에.

설계 = 상위 docs/superpowers/specs/2026-10-06-공구학습량곡선-design.md §6.
실행(Rpi5 에서): python3 조사/공구학습량-20261006/곡선.py — 결과 = 학습/결과/<id>/채점.json(받기 뒤).
지금 = T-full-base-albu(결과 폴더 E13-tool-base · …s1 · …s2).
"""
import json
from pathlib import Path

RES = Path(__file__).resolve().parents[2] / "학습" / "결과"
ROWS = [("절반", 286, ["T-full-half-s0", "T-full-half-s1", "T-full-half-s2"]),
        ("지금", 571, ["E13-tool-base", "E13-tool-bases1", "E13-tool-bases2"]),
        ("+b010", 733, ["T-full-b010-s0", "T-full-b010-s1", "T-full-b010-s2"])]
TOOLS = ("driver", "wrench", "pliers")


def cell(xs, fmt):
    return " · ".join(fmt(x) for x in xs) + f" (평균 {fmt(sum(xs) / len(xs))})"


def main():
    head = "| 판 | 공구 있는 학습 사진 | " + " | ".join(f"{t} 맞게 찾음" for t in TOOLS) + " | 정밀도 | 오검출 · 오분류 |"
    print(head)
    print("|" + "---|" * (head.count("|") - 1))
    for label, n, ids in ROWS:
        sc = [json.loads((RES / i / "채점.json").read_text(encoding="utf-8")) for i in ids]
        tot = {t: sc[0]["클래스"][t]["tp"] + sc[0]["클래스"][t]["fn"] for t in TOOLS}
        rec = [cell([s["클래스"][t]["tp"] for s in sc], lambda x: f"{x:g}") + f" / {tot[t]}" for t in TOOLS]
        prec = cell([s["전체"]["precision"] for s in sc], lambda x: f"{x:.3f}")
        err = " · ".join(f"{s['오검출']}·{s['오분류']}" for s in sc)
        print(f"| {label} | {n} | " + " | ".join(rec) + f" | {prec} | {err} |")
    print("\n칸 = 시드 0 · 1 · 2 (평균) · 맞게 찾음 = 정답 박스 중 맞힌 수 / 정답 박스 수")


if __name__ == "__main__":
    main()
