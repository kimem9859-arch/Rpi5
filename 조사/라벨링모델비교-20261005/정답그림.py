"""Claude 수정본(정답) 박스와 세 패널 그림 — tool_r2 | T-full-base s0 | Claude 수정.

- 정답 박스 = 그 공구를 「맞음」으로 판정한 박스(R · T0 · 시드 1·2)의 좌표 중앙값.
  모두 놓친 공구 3개는 격자 확대로 직접 정한 좌표(아래 DRAWN · 안내서 ④ 두 조각은 박스 하나).
- 모델 패널 색 = 판정: 맞음 초록 · 중복·어긋남 주황 · 이름 틀림 보라 · 가짜 빨강 · 애매 회색. 0.65 미만 박스는 가는 선.
결과 = 정답.json · ~/data/학습실험/라벨링모델비교-20261005/패널/NNN.jpg
"""
import json
from pathlib import Path
from statistics import median

import cv2

HERE = Path(__file__).resolve().parent
OUT = Path.home() / "data/학습실험/라벨링모델비교-20261005/패널"
DRAWN = {("006", "D"): [265, 480, 415, 870], ("031", "D"): [198, 505, 300, 728], ("038", "P"): [115, 240, 435, 535]}
NAME = {"driver": "driver", "wrench": "wrench", "pliers": "pliers"}
C = {"ok": (60, 200, 60), "dup": (0, 150, 255), "off": (0, 150, 255), "cls": (220, 60, 220), "F": (40, 40, 230), "A": (150, 150, 150)}
KO = {"ok": "맞음", "dup": "중복", "off": "어긋남", "cls": "이름틀림", "F": "가짜", "A": "애매"}

pred = json.load(open(HERE / "예측.json", encoding="utf-8"))["사진"]
pair = json.load(open(HERE / "짝.json", encoding="utf-8"))
judge = json.load(open(HERE / "판정.json", encoding="utf-8"))
by_no = {f"{v['번호']:03d}": n for n, v in pair.items()}


def judged(no):
    """모델별 [(판정, 박스)] — 박스 = [이름, 점수, x1, y1, x2, y2]."""
    n, j = by_no[no], judge[no]
    v = pred[n]
    out = {"R": [(j["R"].get(f"R{i}"), b) for i, b in enumerate(v["R"], 1)],
           "T0": [(j["T"].get(f"T{i}"), b) for i, b in enumerate(v["T0"], 1)]}
    for m in ("T1", "T2"):
        out[m] = [((j.get("S", {}).get(r) if r.startswith("S") else j["R" if r.startswith("R") else "T"].get(r)), b)
                  for r, b in zip(pair[n][m], v[m])]
    return out


def kind(jv, objs, seen):
    if jv == "A":
        return "A"
    if jv in objs:
        if jv in seen:
            return "dup"
        seen.add(jv)
        return "ok"
    if jv == "F":
        return "F"
    return "off" if jv.endswith("~") else "cls"


def put(im, text, org, col, scale=0.6):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    x, y = org
    y = max(y, th + 4)
    cv2.rectangle(im, (x, y - th - 6), (x + tw + 6, y + 2), (0, 0, 0), -1)
    cv2.putText(im, text, (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, scale, col, 2)


def panel(im, title, items, foot):
    im = im.copy()
    for col, thick, label, (x1, y1, x2, y2) in items:
        cv2.rectangle(im, (int(x1), int(y1)), (int(x2), int(y2)), col, thick)
        put(im, label, (int(x1), int(y1)), col)
    cv2.rectangle(im, (0, 0), (im.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(im, title, (8, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.rectangle(im, (0, im.shape[0] - 40), (im.shape[1], im.shape[0]), (0, 0, 0), -1)
    cv2.putText(im, foot, (8, im.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)
    return im


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gt_all, meta = {}, {}
    for no, j in sorted(judge.items()):
        jd = judged(no)
        objs = j["공구"]
        gt = {}
        for o, desc in objs.items():
            bs = [b for m in jd for jv, b in jd[m] if jv == o]
            if bs:
                gt[o] = [desc.split(" ·")[0], *(round(median(b[k] for b in bs), 1) for k in range(2, 6)), "모델"]
            else:
                gt[o] = [desc.split(" ·")[0], *DRAWN[(no, o)], "직접"]
        gt_all[no] = gt
        im = cv2.imread(pred[by_no[no]]["원본"])
        panels, info = [], {}
        for m, title in (("R", "tool_r2"), ("T0", "T-full-base s0")):
            seen, items, cnt = set(), [], {}
            tag = "R" if m == "R" else "T"
            for i, (jv, b) in enumerate(jd[m], 1):
                k = kind(jv, objs, seen)
                cnt[k] = cnt.get(k, 0) + 1
                items.append((C[k], 3 if b[1] >= 0.65 else 1, f"{tag}{i} {b[0]} {b[1]:.2f}", b[2:]))
            miss = [objs[o].split(" ·")[0] for o in objs if o not in seen]
            info[m] = {"놓침": miss, **{KO[k]: v for k, v in cnt.items()}}
            foot = "missed: " + (", ".join(miss) if miss else "-")
            panels.append(panel(im, f"#{no} {title}", items, foot))
        items = [((60, 200, 60) if g[5] == "모델" else (255, 220, 0), 3, f"{g[0]}" + (" (drawn)" if g[5] == "직접" else ""), g[1:5])
                 for g in gt.values()]
        panels.append(panel(im, f"#{no} corrected", items, f"tools: {len(gt)}"))
        out = cv2.hconcat(panels)
        out = cv2.resize(out, (1152, 512), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(OUT / f"{no}.jpg"), out, [cv2.IMWRITE_JPEG_QUALITY, 80])
        meta[no] = {"묶음": pred[by_no[no]]["묶음"], "프레임": by_no[no], "공구": {o: d for o, d in objs.items()},
                    "메모": j.get("메모", ""), "R": info["R"], "T0": info["T0"]}
    (HERE / "정답.json").write_text(json.dumps(gt_all, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("그림", len(meta), "장 →", OUT)


if __name__ == "__main__":
    main()
