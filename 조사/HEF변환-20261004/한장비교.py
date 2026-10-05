"""HEF 사진 1장 추론이 .pt 와 같은 자리·같은 이름인가 — 학습 파라미터 체계 1-2단계 Task 15 Step 2(관문 2).

사용(Rpi5 에서):
  ~/env/rfenv/bin/python 조사/HEF변환-20261004/한장비교.py pt  <best.pt>   <사진.png> <pt.json>
  python3                조사/HEF변환-20261004/한장비교.py hef <model.hef> <사진.png> <hef.json>
  python3                조사/HEF변환-20261004/한장비교.py 비교 <pt.json> <hef.json> --names B1,B2,B3,B4,EMO

- 전처리 = 시연과 같은 늘리기 — .pt 는 학습 채점(scoring.score_model)처럼 640×640 으로 늘린 사진을 imgsz 640 으로,
  HEF 는 시연 검출기(Demo/detector.py HailoDetector.detect)를 그대로 쓴다.
- 좌표 = 정규화 xyxy(0~1) · 운용 임계 conf 0.65 이상만 비교 · 같은 이름끼리 IoU 가 가장 큰 것과 짝짓는다.
- 판정 = 박스 수가 같고 모든 짝의 IoU ≥ 0.9(계획의 「같은 자리」) — 점수 차이는 기록만.
"""
import json
import os
import sys

CONF = 0.65
RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def run_pt(model, img_path, out):
    import cv2
    from ultralytics import YOLO
    im = cv2.resize(cv2.imread(img_path), (640, 640))
    r = YOLO(model).predict(im, conf=0.001, imgsz=640, verbose=False)[0]
    dets = [{"cls": int(c), "score": float(s), "box": [v / 640 for v in xyxy]}
            for xyxy, s, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()) if s >= CONF]
    json.dump({"model": os.path.basename(model), "dets": dets}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f".pt {len(dets)}개 → {out}")


def run_hef(hef, img_path, out):
    import cv2
    sys.path.insert(0, os.path.join(RPI5, "Demo"))
    import config
    config.HEF_MODEL_PATH = hef                       # create_detector 전에 덮어써야 반영된다
    from detector import create_detector
    im = cv2.imread(img_path)
    h, w = im.shape[:2]
    d = create_detector()
    try:
        raw = d.detect(im)
    finally:
        d.close()
    dets = [{"cls": int(c), "score": float(s), "box": [x1 / w, y1 / h, x2 / w, y2 / h]}
            for c, s, x1, y1, x2, y2 in raw if s >= CONF]
    json.dump({"model": os.path.basename(hef), "dets": dets}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"HEF {len(dets)}개 → {out}")


def compare(pt_json, hef_json, names):
    a, b = json.load(open(pt_json))["dets"], json.load(open(hef_json))["dets"]
    used, rows = set(), []
    for x in sorted(a, key=lambda d: -d["score"]):
        best, bi = 0.0, None
        for i, y in enumerate(b):
            if i in used or y["cls"] != x["cls"]:
                continue
            v = iou(x["box"], y["box"])
            if v > best:
                best, bi = v, i
        if bi is not None:
            used.add(bi)
        rows.append((names[x["cls"]], x["score"], b[bi]["score"] if bi is not None else None, best))
    extra = [names[y["cls"]] for i, y in enumerate(b) if i not in used]
    for n, sp, sh, v in rows:
        print(f"  {n:<6} .pt {sp:.3f} · HEF {('%.3f' % sh) if sh is not None else '없음':>5} · IoU {v:.3f}")
    if extra:
        print(f"  HEF 에만 있는 박스: {extra}")
    ok = len(a) == len(b) and not extra and all(v >= 0.9 for *_, v in rows)
    print(("✅ 같은 자리 — " if ok else "❌ 다름 — ") + f".pt {len(a)}개 · HEF {len(b)}개 · 최저 IoU {min([v for *_, v in rows], default=0):.3f}")
    return ok


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "pt":
        run_pt(*sys.argv[2:5])
    elif mode == "hef":
        run_hef(*sys.argv[2:5])
    elif mode == "비교":
        names = sys.argv[sys.argv.index("--names") + 1].split(",") if "--names" in sys.argv else ["B1", "B2", "B3", "B4", "EMO"]
        sys.exit(0 if compare(sys.argv[2], sys.argv[3], names) else 1)
    else:
        sys.exit(__doc__)
