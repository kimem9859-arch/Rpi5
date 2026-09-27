"""기계 확정 표본 눈 검사지 — 묶음의 기계 확정 버튼 박스를 무작위로 뽑아 그림 모음으로(설계 §11 관문).

실행(Demo/ 에서): python3 test/audit_batch.py <묶음 폴더> [--n 50] [--seed 1]
출력: <묶음>/audit/audit_p1.jpg … (한 장 25칸) · audit_list.csv(번호 → 사진·이름·박스)
칸 = 박스 둘레를 확대(박스 크기의 4배 영역) · 초록 = 기계가 확정한 박스 · 위에 번호와 이름.
사용자는 틀린 번호만 「이름 / 박스 / 버튼아님」으로 알려 준다. 🔴 이름 틀림이 1건이라도 나오면 그 유형의 기계 확정을 끈다.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import cv2
import numpy as np

TILE, COLS, PER = 300, 5, 25


def sample_auto(man, n, seed):
    pool = [(r, d) for r in man["images"] for d in r["drafts"] if d["kind"] == "auto"]
    return random.Random(seed).sample(pool, min(n, len(pool)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch"); ap.add_argument("--n", type=int, default=50); ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    bd = Path(a.batch).expanduser()
    man = json.loads((bd / "manifest.json").read_text(encoding="utf-8"))
    pick = sample_auto(man, a.n, a.seed)
    (bd / "audit").mkdir(exist_ok=True)
    with open(bd / "audit" / "audit_list.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["번호", "사진", "원본", "이름", "x1", "y1", "x2", "y2"])
        for i, (r, d) in enumerate(pick, 1):
            w.writerow([i, r["file"], r["original"], d["label"], *[int(v) for v in d["box"]]])
    tiles = []
    for i, (r, d) in enumerate(pick, 1):
        img = cv2.imread(r["original"]); H, W = img.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in d["box"]]; cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rr = 2 * max(x2 - x1, y2 - y1)
        X1, Y1, X2, Y2 = int(max(0, cx - rr)), int(max(0, cy - rr)), int(min(W, cx + rr)), int(min(H, cy + rr))
        c = img[Y1:Y2, X1:X2].copy(); z = TILE / max(c.shape[:2])
        c = cv2.resize(c, (int(c.shape[1] * z), int(c.shape[0] * z)), interpolation=cv2.INTER_NEAREST)
        cv2.rectangle(c, (int((x1 - X1) * z), int((y1 - Y1) * z)), (int((x2 - X1) * z), int((y2 - Y1) * z)), (0, 255, 0), 2)
        t = np.zeros((TILE + 34, TILE, 3), np.uint8); t[34:34 + c.shape[0], :c.shape[1]] = c
        cv2.putText(t, f"{i}  {d['label']}", (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        tiles.append(t)
    while len(tiles) % COLS:
        tiles.append(np.zeros_like(tiles[0]))
    for pg in range(0, len(tiles), PER):
        part = tiles[pg:pg + PER]
        rows = [np.hstack(part[k:k + COLS]) for k in range(0, len(part), COLS)]
        cv2.imwrite(str(bd / "audit" / f"audit_p{pg // PER + 1}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"검사지 {len(pick)}칸 →", bd / "audit")


if __name__ == "__main__":
    main()
