"""흰 면장갑 손 vs 맨손 — 시연 손 모델(HandTracker) 검출 예비 비교. 추론만 · Rpi5/Demo 코드 무수정.

입력: c001 「쥠」 공구 77개(`조사/c001채점-20261008/쥠놓임.json` · Claude 육안) + 이 폴더 `분류.json`(장갑/맨손/애매 · Claude 육안 1명)
사진: ~/data/c001채점/sets/c001/orig/<id>.png (시연과 같은 처리 — 상하 반전 → 왜곡 보정 → 반시계 90° · 768×1024)
실행: cd Rpi5/Demo && python3 ../조사/장갑손검출-20261009/run.py
🔴 camera_thread 를 import 하지 않는다(Hailo 첫 추론 멈춤 — 2026-10-09 실측).
"""
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEMO = HERE.parents[1] / "Demo"
sys.path.insert(0, str(DEMO))
os.chdir(DEMO)
import config                      # noqa: E402
from hand_tracker import HandTracker, TIP   # noqa: E402

S = Path.home() / "data" / "c001채점" / "sets" / "c001"
NAMES = ["driver", "wrench", "pliers"]
held = json.load(open(HERE / "분류.json", encoding="utf-8"))   # [{"번호", "key", "손"}]


def tool_box(n, tool, w, h):
    for line in (S / "labels_tool" / f"{n}.txt").read_text().splitlines():
        c, cx, cy, bw, bh = line.split()
        if NAMES[int(c)] == tool:
            cx, cy, bw, bh = map(float, (cx, cy, bw, bh))
            return ((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h)
    return None


ht = HandTracker()
print("hand", ht.available, ht.reason, "min_score", config.HAND_MIN_SCORE, flush=True)
rows = []
for it in held:
    n, tool = it["key"].split("|")
    im = cv2.imread(str(S / "orig" / f"{n}.png"))
    h, w = im.shape[:2]
    tip = ht.detect(im)
    score = getattr(ht, "last_score", None)
    # 진단 — 손이 안 잡혔을 때 팜 단계에서 막혔나 랜드마크 점수에서 막혔나(같은 내부 단계를 읽기만)
    palm, flag_max = None, None
    if tip is None:
        rgb = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
        img1, scale1, pad1 = ht._det.resize_pad(rgb)
        norm = ht._det.predict_on_image(img1)
        palm = len(norm)
        if palm:
            dets = ht._det.denormalize_detections(norm, scale1, pad1)
            xc, yc, sc, theta = ht._det.detection2roi(dets)
            roi_img, roi_affine, _ = ht._lm.extract_roi(rgb, xc, yc, theta, sc)
            res = ht._lm.predict(roi_img)
            flag_max = float(np.max(np.asarray(res[0], dtype=float).reshape(-1))) if len(res[0]) else None
    x1, y1, x2, y2 = tool_box(n, tool, w, h)
    mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.1
    in_box = tip is not None and (x1 - mx) <= tip[0] <= (x2 + mx) and (y1 - my) <= tip[1] <= (y2 + my)
    rows.append({**it, "손검출": tip is not None, "검지끝": tip, "점수": score, "검지끝_공구상자안": bool(in_box),
                 "진단_팜수": palm, "진단_랜드마크최대점수": flag_max})
    print(it["번호"], it["손"], tool, "손" if tip else "-", "상자안" if in_box else "", palm, flag_max, flush=True)

summ = {}
for g in ("장갑", "맨손"):
    r = [x for x in rows if x["손"] == g]
    k1, k2 = sum(x["손검출"] for x in r), sum(x["검지끝_공구상자안"] for x in r)
    summ[g] = {"n": len(r), "손검출": f"{k1}/{len(r)}", "손검출률": round(k1 / len(r), 3) if r else None,
               "검지끝_공구상자안": f"{k2}/{len(r)}", "비율": round(k2 / len(r), 3) if r else None}
summ["애매(뺌)"] = sum(1 for x in rows if x["손"] == "애매")
json.dump({"조건": {"HAND_MIN_SCORE": config.HAND_MIN_SCORE, "상자_여유": 0.1}, "요약": summ, "사진": rows},
          open(HERE / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(summ, ensure_ascii=False))
