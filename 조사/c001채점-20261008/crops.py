"""Task 2 — 쥠/놓임 표시용 모음 사진(공구 정답 258개) · 표시 검사 (설계 §2.4 · 결과를 보기 전에).

만들기: python3 crops.py            → ~/data/c001채점/쥠놓임/sheet_NN.jpg · index.json
검사:   python3 crops.py --check    → 쥠놓임.json 이 258개를 모두 덮고 값이 쥠·놓임·애매인지
전체:   python3 crops.py --full <번호 …> → full_NN.jpg — 잘라 낸 사진으로 손이 안 보이는 박스를 사진 전체로(6 × 2)
"""
import argparse
import sys

import cv2
import numpy as np

import common as C

TILE, COLS, ROWS, MARGIN = 220, 6, 5, 0.35
OUT = C.W / "쥠놓임"
TAGS = C.HERE / "쥠놓임.json"


def items():
    sd, out = C.set_dir("c001"), []
    for n in C.set_names("c001"):
        im = cv2.imread(str(sd / "orig" / f"{n}.png"))
        h, w = im.shape[:2]
        for line in (sd / "labels_tool" / f"{n}.txt").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c, cx, cy, bw, bh = line.split()
            cx, cy, bw, bh = map(float, (cx, cy, bw, bh))
            x1, y1, x2, y2 = (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h
            mx, my = (x2 - x1) * MARGIN, (y2 - y1) * MARGIN
            X1, Y1 = max(0, int(x1 - mx)), max(0, int(y1 - my))
            X2, Y2 = min(w, int(x2 + mx)), min(h, int(y2 + my))
            crop = im[Y1:Y2, X1:X2].copy()
            cv2.rectangle(crop, (int(x1) - X1, int(y1) - Y1), (int(x2) - X1, int(y2) - Y1), (0, 255, 0), 2)
            out.append({"번호": len(out) + 1, "key": f"{n}|{C.NAMES['tool'][int(c)]}", "crop": crop})
    return out


def tile(it):
    crop = it["crop"]
    s = TILE / max(crop.shape[:2])
    small = cv2.resize(crop, (max(1, int(crop.shape[1] * s)), max(1, int(crop.shape[0] * s))))
    t = np.full((TILE + 24, TILE, 3), 255, np.uint8)
    t[24:24 + small.shape[0], :small.shape[1]] = small
    cv2.putText(t, f"{it['번호']} {it['key'].split('|')[1]}", (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    return t


def make():
    its = items()
    OUT.mkdir(parents=True, exist_ok=True)
    per = COLS * ROWS
    for k in range(0, len(its), per):
        tiles = [tile(it) for it in its[k:k + per]]
        tiles += [np.full_like(tiles[0], 255)] * (per - len(tiles))
        rows = [np.hstack(tiles[r * COLS:(r + 1) * COLS]) for r in range(ROWS)]
        cv2.imwrite(str(OUT / f"sheet_{k // per + 1:02d}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    C.write_json(OUT / "index.json", [{"번호": it["번호"], "key": it["key"]} for it in its])
    print(f"박스 {len(its)} · 모음 사진 {(len(its) + per - 1) // per}장 → {OUT}")


def full(nums):
    idx = {it["번호"]: it["key"] for it in C.load_json(OUT / "index.json")}
    tiles = []
    for k in nums:
        n, cls = idx[k].split("|")
        im = cv2.imread(str(C.set_dir("c001") / "orig" / f"{n}.png"))
        h, w = im.shape[:2]
        for line in (C.set_dir("c001") / "labels_tool" / f"{n}.txt").read_text(encoding="utf-8").splitlines():
            c, cx, cy, bw, bh = line.split()
            if C.NAMES["tool"][int(c)] == cls:
                cx, cy, bw, bh = map(float, (cx, cy, bw, bh))
                cv2.rectangle(im, (int((cx - bw / 2) * w), int((cy - bh / 2) * h)), (int((cx + bw / 2) * w), int((cy + bh / 2) * h)), (0, 255, 0), 4)
        t = cv2.resize(im, (300, 400))
        cv2.putText(t, f"{k} {cls}", (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        tiles.append(t)
    for j in range(0, len(tiles), 12):
        part = tiles[j:j + 12] + [np.full_like(tiles[0], 255)] * (12 - len(tiles[j:j + 12]))
        cv2.imwrite(str(OUT / f"full_{j // 12 + 1:02d}.jpg"), np.vstack([np.hstack(part[:6]), np.hstack(part[6:])]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"전체 사진 {len(tiles)}장 → full_01~{(len(tiles) + 11) // 12:02d}.jpg")
    return 0


def check():
    idx = C.load_json(OUT / "index.json")
    tags = C.load_json(TAGS)["표시"]
    keys = {it["key"] for it in idx}
    bad = sorted(keys ^ set(tags)) + [k for k, v in tags.items() if v not in ("쥠", "놓임", "애매")]
    print(f"표시 {len(tags)} / 박스 {len(keys)} · 문제 {len(bad)}" + (f" — {bad[:5]}" if bad else ""))
    from collections import Counter
    print(dict(Counter(tags.values())))
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--full", nargs="+", type=int)
    a = ap.parse_args()
    sys.exit(check() if a.check else full(a.full) if a.full else make())
