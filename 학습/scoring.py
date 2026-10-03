"""설정 비교 채점 — best.pt 로 채점 몫을 추론해 score_lib 로 잰다(계산은 score_lib 그대로 · 재구현 금지).

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §8
- 사진마다 추론하는 규칙은 조사/재학습확인-20261003/채점_pt.py 와 같다 — 추론 conf 0.001 · 8종 라벨을 이름으로 짝짓기.
- 운용 문턱(conf)은 파이 config(버튼 YOLO_CONF_HIGH · 공구 TOOL_CONF)에서 걸기가 실어 보낸다.
- 데스크톱에서는 걸기가 score_lib.py 를 이 파일 옆에 함께 보낸다.
"""
import math
from pathlib import Path

from score_lib import confusion, evaluate, operating_point

NAMES8 = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]   # place1 data.yaml 순서


def gts_from_lines(lines, names, w, h):
    out = []
    for line in lines:
        p = line.split()
        if not p:
            continue
        n = NAMES8[int(p[0])]
        if n in names:
            cx, cy, bw, bh = map(float, p[1:5])
            out.append((names.index(n), (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
    return out


def preds_from(xyxy, confs, clss, model_names, names):
    return [(names.index(model_names[int(c)]), float(s), *map(float, b))
            for b, s, c in zip(xyxy, confs, clss) if model_names[int(c)] in names]


def _num(v):
    return None if isinstance(v, float) and math.isnan(v) else v


def summarize(per_image, names, conf):
    ap = evaluate(per_image, names, (0.5,))[0.5]
    op = operating_point(per_image, names, conf)
    mat = confusion(per_image, names, conf)
    k = len(names)
    tp, fp, fn = (sum(op[n][x] for n in names) for x in ("tp", "fp", "fn"))
    return {
        "사진": len(per_image), "정답박스": sum(len(g) for g, _ in per_image.values()), "conf": conf, "iou": 0.5,
        "mAP50": _num(ap["mAP"]), "AP50": {n: _num(v) for n, v in ap["per_class"].items()},
        "클래스": {n: {x: op[n][x] for x in ("tp", "fp", "fn", "precision", "recall")} for n in names},
        "전체": {"tp": tp, "fp": fp, "fn": fn, "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1)},
        "오분류": int(sum(mat[i][j] for i in range(k) for j in range(k) if i != j)),
        "오검출": int(sum(mat[k][:k])),
        "혼동": [[int(v) for v in row] for row in mat],
    }


def score_model(model_path, images_dir, labels_dir, names, conf, imgsz):
    """images_dir 의 사진(입력 방식대로 준비된 것)을 imgsz 로 추론 → summarize. labels_dir = 8종 라벨."""
    from ultralytics import YOLO
    m = YOLO(str(model_path))
    per_image = {}
    for p in sorted(Path(images_dir).glob("*.png")):
        r = m.predict(str(p), conf=0.001, imgsz=imgsz, verbose=False)[0]
        h, w = r.orig_shape
        gts = gts_from_lines((Path(labels_dir) / f"{p.stem}.txt").read_text(encoding="utf-8").splitlines(), names, w, h)
        preds = preds_from(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist(), r.names, names)
        per_image[p.stem] = (gts, preds)
    return summarize(per_image, names, conf)
