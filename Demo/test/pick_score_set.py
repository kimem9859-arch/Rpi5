"""채점 묶음 사진 고르기 — 사람이 검토한 라벨(collect_batch 출력 label_dataset/<장소>)에서 공구 종류별로 고르게.

실행(Demo/ 에서): python3 test/pick_score_set.py --dataset ~/data/label_dataset/place2 --out <목록.txt> [--per-tool 80] [--no-tool 60] [--seed 1]
출력: <목록.txt>(라벨 이름 한 줄씩 · 정렬) · <목록>.json(종류별 사진·박스 수 · 모자람 · 설정)
고르는 법: 사진 수가 적은 공구부터 그 공구가 있는 사진을 무작위로 채운다(이미 고른 사진이 그 공구를 담고 있으면 센다) →
  공구 없는 사진을 무작위로 더한다(잘못 잡는 경우를 재는 몫). 모자라면 있는 만큼 넣고 「모자람」에 적는다.
🔴 모델 초벌·검출로 고르지 않는다 — 평가 대상 모델이 찾은 사진만 뽑히면 놓친 공구가 채점에 안 잡혀 점수가 부푼다
   (데이터셋 스킬 「분할」 ③ · 사용자 2026-10-07 「공구의 종류별 분배를 잘해줘」).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CLASSES = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]   # collect_batch 8종 번호 순서(xany_io.CLASSES)
TOOLS = ["driver", "wrench", "pliers"]


def tool_boxes(lines):
    """8종 YOLO 라벨 줄 → {공구 이름: 박스 수}(공구만)."""
    out = {}
    for l in lines:
        if l.strip():
            n = CLASSES[int(l.split()[0])]
            if n in TOOLS:
                out[n] = out.get(n, 0) + 1
    return out


def pick(items, per_tool, no_tool, seed):
    """items = {라벨 이름: {공구: 박스 수}} → (고른 이름 정렬 목록, 보고).
    사진 수가 적은 공구부터 채워 흔한 공구가 드문 공구의 몫을 먼저 차지하지 않게 한다."""
    rng = random.Random(seed)
    picked = []
    order = sorted(TOOLS, key=lambda t: (sum(t in v for v in items.values()), TOOLS.index(t)))
    for t in order:
        have = sum(t in items[n] for n in picked)
        cands = [n for n in sorted(items) if t in items[n] and n not in picked]
        picked += rng.sample(cands, max(0, min(per_tool - have, len(cands))))
    empty = [n for n in sorted(items) if not items[n] and n not in picked]
    picked += rng.sample(empty, min(no_tool, len(empty)))
    rep = {"사진": len(picked), "공구별 사진": {}, "공구별 박스": {}, "공구 없는 사진": sum(not items[n] for n in picked), "모자람": {}}
    for t in TOOLS:
        rep["공구별 사진"][t] = sum(t in items[n] for n in picked)
        rep["공구별 박스"][t] = sum(items[n].get(t, 0) for n in picked)
        if rep["공구별 사진"][t] < per_tool:
            rep["모자람"][t] = per_tool - rep["공구별 사진"][t]
    if rep["공구 없는 사진"] < no_tool:
        rep["모자람"]["공구 없음"] = no_tool - rep["공구 없는 사진"]
    return sorted(picked), rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="collect_batch 출력 폴더(labels/ · images.txt)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-tool", type=int, default=80)
    ap.add_argument("--no-tool", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    ds = Path(a.dataset).expanduser()
    names = [l.split("\t")[0] for l in (ds / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    items = {n: tool_boxes((ds / "labels" / f"{n}.txt").read_text(encoding="utf-8").splitlines()) for n in names}
    picked, rep = pick(items, a.per_tool, a.no_tool, a.seed)
    out = Path(a.out).expanduser()
    if out.exists():
        raise SystemExit(f"이미 있다: {out} — 덮어쓰지 않는다")
    out.write_text("".join(n + "\n" for n in picked), encoding="utf-8")
    rep["설정"] = {"dataset": str(ds), "후보 사진": len(items), "per_tool": a.per_tool, "no_tool": a.no_tool, "seed": a.seed}
    out.with_suffix(".json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
