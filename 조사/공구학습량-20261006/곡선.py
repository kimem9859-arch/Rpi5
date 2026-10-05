"""공구 학습량 곡선 — 절반 · 지금 · +b010 의 채점(292장 · conf 0.65 · IoU 0.5)을 시드별·평균으로 한 표에
+ b011~b014 를 넣으면 학습 구간에 드는 장수(설계 §6 「예상 장수를 함께」 · 초벌 박스는 장수 세기에만).

설계 = 상위 docs/superpowers/specs/2026-10-06-공구학습량곡선-design.md §6.
실행(Rpi5 에서): python3 조사/공구학습량-20261006/곡선.py — 결과 = 학습/결과/<id>/채점.json(받기 뒤).
지금 = T-full-base-albu(결과 폴더 E13-tool-base · …s1 · …s2).
"""
import glob
import json
import sys
from pathlib import Path

RPI5 = Path(__file__).resolve().parents[2]
RES = RPI5 / "학습" / "결과"
sys.path.insert(0, str(RPI5 / "학습"))
import split as SP  # noqa: E402
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
        rec = [" · ".join(str(s["클래스"][t]["tp"]) for s in sc) + f" (평균 {sum(s['클래스'][t]['tp'] for s in sc) / 3:.1f}) / {tot[t]}"
               for t in TOOLS]
        prec = cell([s["전체"]["precision"] for s in sc], lambda x: f"{x:.3f}")
        err = (" · ".join(f"{s['오검출']}·{s['오분류']}" for s in sc)
               + f" (평균 {sum(s['오검출'] for s in sc) / 3:.1f}·{sum(s['오분류'] for s in sc) / 3:.1f})")
        print(f"| {label} | {n} | " + " | ".join(rec) + f" | {prec} | {err} |")
    print("\n칸 = 시드 0 · 1 · 2 (평균) · 맞게 찾음 = 정답 박스 중 맞힌 수 / 정답 박스 수")
    print()
    b011_b014()


def b011_b014():
    """b011~b014 사진을 place1_v1 경계(add_new 와 같은 규칙)로 나눠 센다 · 공구 있음 = tool_r2 초벌 JSON(검토 전 · 참고)."""
    base = SP.load_split(RPI5 / "학습" / "나눔" / "place1_v1.json")
    edge = {}
    for n in base["공통"]["val"] + base["공통"]["test"] + base["공통"]["unused"]:
        edge[SP.session_of(n)] = min(edge.get(SP.session_of(n), SP.frame_no(n)), SP.frame_no(n))
    tot = zone = pos = nosess = 0
    for b in ("b011", "b012", "b013", "b014"):
        for f in sorted(glob.glob(str(Path.home() / f"data/label_batches/{b}/images/*.png"))):
            n = "__".join(Path(f).stem.split("__")[-2:])
            tot += 1
            if SP.session_of(n) not in edge:
                nosess += 1
                continue
            if edge[SP.session_of(n)] - SP.frame_no(n) > SP.GAP:
                zone += 1
                j = Path(f).with_suffix(".json")
                pos += j.exists() and any(x.get("label") in TOOLS for x in json.loads(j.read_text(encoding="utf-8")).get("shapes", []))
    print(f"b011~b014 {tot}장 · 학습 구간 {zone} · 그중 초벌 공구 있음 {pos}(참고) · 구간 밖 {tot - zone - nosess} · 바탕판에 없는 세션 {nosess}")


if __name__ == "__main__":
    main()
