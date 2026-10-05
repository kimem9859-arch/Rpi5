"""판정용 사진 — 사진마다 두 패널(왼쪽 tool_r2 · 오른쪽 T-full-base 시드 0) · 박스 번호 R1.. / T1..
시드 1·2 박스 중 같은 이름으로 R·T0 박스와 IoU 0.5 이상 겹치는 것이 없으면 셋째 사진(_추가)에 S1-1.. / S2-1.. 로 그린다.
결과 = 짝.json(시드 1·2 박스 → 이어받을 R·T0 박스 번호 또는 추가 번호).
"""
import json
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
OUT = Path.home() / "data/학습실험/라벨링모델비교-20261005"
COL = {"R": (0, 220, 255), "T0": (255, 200, 0), "T1": (80, 255, 80), "T2": (255, 80, 255)}


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x2 - x1) * max(0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u else 0


def draw(im, bxs, col, tag, title, ids=None):
    im = im.copy()
    cv2.rectangle(im, (0, 0), (im.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(im, title, (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    for i, (name, s, x1, y1, x2, y2) in enumerate(bxs, 1):
        p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
        cv2.rectangle(im, p1, p2, col, 3)
        t = f"{ids[i - 1] if ids else f'{tag}{i}'} {name} {s:.2f}"
        (tw, th), _ = cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        ty = max(int(y1), th + 40)
        cv2.rectangle(im, (int(x1), ty - th - 8), (int(x1) + tw + 6, ty), (0, 0, 0), -1)
        cv2.putText(im, t, (int(x1) + 3, ty - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    return im


def main():
    d = json.load(open(HERE / "예측.json", encoding="utf-8"))["사진"]
    OUT.mkdir(parents=True, exist_ok=True)
    pair = {}
    for k, (n, v) in enumerate(sorted(d.items()), 1):
        im = cv2.imread(v["원본"])
        left = draw(im, v["R"], COL["R"], "R", f"#{k:03d} tool_r2")
        right = draw(im, v["T0"], COL["T0"], "T", f"#{k:03d} T-full-base s0")
        cv2.imwrite(str(OUT / f"{k:03d}_박스.png"), cv2.hconcat([left, right]))
        pair[n] = {"번호": k}
        extra = []
        for seed, tag in (("T1", "S1-"), ("T2", "S2-")):
            got = []
            for b in v[seed]:
                cands = [(iou(b[2:], o[2:]), f"{src}{j}") for src, key in (("R", "R"), ("T", "T0"))
                         for j, o in enumerate(v[key], 1) if o[0] == b[0]]
                best = max(cands, default=(0, None))
                if best[0] >= 0.5:
                    got.append(best[1])
                else:
                    extra.append((seed, tag, b))
                    got.append(f"{tag}{sum(1 for e in extra if e[0] == seed)}")
            pair[n][seed] = got
        if extra:
            im2 = im.copy()
            for seed, tag, b in extra:
                i = sum(1 for e in extra[:extra.index((seed, tag, b)) + 1] if e[0] == seed)
                im2 = draw(im2, [b], COL[seed], tag, f"#{k:03d} s1/s2 extra", ids=[f"{tag}{i}"])
            cv2.imwrite(str(OUT / f"{k:03d}_추가.png"), im2)
    (HERE / "짝.json").write_text(json.dumps(pair, ensure_ascii=False, indent=1), encoding="utf-8")
    print("사진", len(d), "· 추가 사진", sum(1 for p in pair.values() if any(str(x).startswith("S") for s in ("T1", "T2") for x in p[s])))


if __name__ == "__main__":
    main()
