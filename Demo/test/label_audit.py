"""라벨 export 를 훑어 검수 전에 기계가 잡을 수 있는 것을 잡는다 — 데이터확보 설계 §9 기계 점검.

왜 필요한가:
    `tool_v4` 는 「양 끝을 감싸는 박스 하나」 지침이 라벨 작업자에게 전달되지 않아
    렌치 라벨이 **머리 조각만** 남았고, 그 사실이 **채점 단계에서야** 드러나 한 사이클을
    통째로 버렸다(§12.63). 조각 박스는 같은 클래스의 다른 박스보다 **작고 덜 길쭉하다** —
    사람이 표본으로 훑기 전에 기계가 전량에서 그 후보를 뽑아낸다.

    🔑 §12.63 의 「쥔 ÷ 놓인 면적비」는 쓸 수 없다 — 쥔/놓인을 다른 클래스로 두지 않기로
    했기 때문이다(설계 §3.1). 같은 신호를 **클래스 안의 이상치**로 잡는다.

사용법:
    python3 test/label_audit.py <export폴더>
    python3 test/label_audit.py <export폴더> --json r.json
    python3 test/label_audit.py --selftest              # 합성 입력 자가시험

판정:
    ① 8종 밖 클래스 이름이 있다 → **종료 코드 1(실패)**
    ②③④ 조각 박스 의심 목록 · 배경 비율 · 클래스별 장수는 **보고만** 한다 — 사람이 본다.
       🔑 배경 비율을 실패로 삼지 않는 이유 = 업로드분에서 배경을 지우지 않고
          학습 버전의 Filter Null 로 맞추기 때문이다(설계 §6).
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
from pathlib import Path

CLASSES = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]


def _read_names(root: Path) -> list[str]:
    txt = (root / "data.yaml").read_text(encoding="utf-8")
    line = next(l for l in txt.splitlines() if l.strip().startswith("names:"))
    return [s.strip().strip("'\"") for s in line.split("[", 1)[1].rsplit("]", 1)[0].split(",")]


def audit(root: Path, bg_max: float = 0.10) -> dict:
    names = _read_names(root)
    unknown = [n for n in names if n not in CLASSES]
    if any((root / s).exists() for s in ("train", "valid", "test")):
        label_files = sorted(p for split in ("train", "valid", "test")
                             for p in (root / split / "labels").glob("*.txt"))
    else:
        label_files = sorted((root / "labels").glob("*.txt"))
    per_class: dict[str, dict] = {n: {"images": 0, "boxes": 0} for n in names}
    boxes: dict[str, list[tuple[str, float, float]]] = {n: [] for n in names}
    empty = 0
    for f in label_files:
        rows = [r.split() for r in f.read_text(encoding="utf-8").splitlines() if r.strip()]
        if not rows:
            empty += 1
            continue
        seen = set()
        for r in rows:
            n = names[int(r[0])]
            w, h = float(r[3]), float(r[4])
            per_class[n]["boxes"] += 1
            boxes[n].append((f.name, w * h, (w / h) if h else 0.0))
            seen.add(n)
        for n in seen:
            per_class[n]["images"] += 1
    suspects = []
    for n, bs in boxes.items():
        if len(bs) < 4:            # 표본이 너무 적으면 중앙값이 뜻을 갖지 못한다
            continue
        med_a = statistics.median(b[1] for b in bs)
        med_r = statistics.median(b[2] for b in bs)
        for fn, a, r in bs:
            if a < med_a * 0.5 or r < med_r * 0.5:
                suspects.append({"file": fn, "cls": n, "area": a, "ratio": r,
                                 "median_area": med_a, "median_ratio": med_r})
    total = len(label_files)
    return {"names": names, "unknown_classes": unknown, "per_class": per_class,
            "images": total, "background_images": empty,
            "background_ratio": (empty / total) if total else 0.0,
            "background_max": bg_max, "suspects": suspects}


def _selftest() -> int:
    """합성 export 를 만들어 판정 4종이 기대대로 나오는지 확인한다."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "train" / "labels").mkdir(parents=True)
        (root / "data.yaml").write_text(
            "names: [B1, B2, B3, B4, EMO, driver, wrench, pliers]\n", encoding="utf-8")
        L = root / "train" / "labels"
        # wrench(6) 정상 박스 4개 — 면적 0.02, 종횡비 4.0(길쭉)
        for i in range(4):
            (L / f"ok{i}.txt").write_text("6 0.5 0.5 0.2828 0.0707\n", encoding="utf-8")
        # wrench 조각 박스 1개 — 면적 0.004(중앙값의 0.2배), 종횡비 1.0
        (L / "frag.txt").write_text("6 0.5 0.5 0.0632 0.0632\n", encoding="utf-8")
        # 배경(박스 0개) 1장
        (L / "bg.txt").write_text("", encoding="utf-8")
        r = audit(root)
    assert r["unknown_classes"] == [], r["unknown_classes"]
    assert [s["file"] for s in r["suspects"]] == ["frag.txt"], r["suspects"]
    assert r["background_ratio"] == 1 / 6, r["background_ratio"]
    assert r["per_class"]["wrench"]["images"] == 5, r["per_class"]
    assert r["per_class"]["wrench"]["boxes"] == 5, r["per_class"]
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export", nargs="?", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--bg-max", type=float, default=0.10)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.export:
        ap.error("export 폴더를 주거나 --selftest 를 쓴다")
    r = audit(a.export, a.bg_max)
    print(f"사진 {r['images']}장 · 배경 {r['background_images']}장")
    for n, v in r["per_class"].items():
        print(f"  {n:8s} 사진 {v['images']:5d} · 박스 {v['boxes']:5d}")
    print(f"① 클래스 이름 {'❌ ' + str(r['unknown_classes']) if r['unknown_classes'] else '✅ 8종'}")
    print(f"② 조각 박스 의심 {len(r['suspects'])}건 — 사람이 본다")
    for s in r["suspects"][:20]:
        print(f"  {s['cls']:8s} {s['file']} 면적 {s['area']:.4f}(중앙 {s['median_area']:.4f})"
              f" 종횡비 {s['ratio']:.2f}(중앙 {s['median_ratio']:.2f})")
    print(f"③ 배경 비율 {r['background_ratio']:.1%} — 보고만(학습 버전에서 Filter Null 로 맞춘다)")
    if a.json:
        a.json.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if r["unknown_classes"] else 0


if __name__ == "__main__":
    sys.exit(main())
