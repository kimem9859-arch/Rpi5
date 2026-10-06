"""초벌 — ultralytics 모델(.pt)을 사진 목록에 돌려 JSON 으로 낸다(공구 · 버튼 반복 학습 모델). rfenv 파이썬 전용(ultralytics·torch).

실행(Demo/ 에서): ~/env/rfenv/bin/python test/prelabel_tools.py --list L.txt --out tools.json [--model models/tool_v3.pt] [--conf 0.25] [--stretch 640x640 | --imgsz 1024,768]
출력: {"<사진 경로>": [["driver", 0.41, x1, y1, x2, y2], ...], ...}
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §5.2 (점수 기준 0.25 — 공구를 거의 못 잡아 낮게)
--stretch = 사진을 그 크기로 늘려 넣고 박스를 원본 좌표로 되돌린다 — 640×640 늘리기로 학습한 모델(학습 체계 「늘리기640」 · T-full-base)은
  학습 때와 같은 그림을 봐야 한다. 없으면 원본 그대로(ultralytics 기본 = 비율 유지 여백 채우기).
--imgsz = 원본 그대로 넣을 때의 예측 크기 — 원본 비율로 학습한 모델(학습 체계 「원본768x1024」 · T-full-in1024)은 1024,768(기본 640 이면 작게 줄여 본다).
🔴 config 를 import 하지 않는다 — rfenv 에서 config import 가 GUI 의존을 끌어온다(tool_worker.py 와 같은 이유).
"""
import argparse
import json
from pathlib import Path


def parse_size(s):
    """「640x640」 → (가로, 세로) · 없으면 None."""
    if not s:
        return None
    w, h = s.lower().split("x")
    return int(w), int(h)


def parse_imgsz(s):
    """「1024,768」 → [1024, 768](세로, 가로) · 「640」 → 640 · 없으면 None."""
    if not s:
        return None
    v = [int(x) for x in str(s).split(",")]
    return v if len(v) > 1 else v[0]


def stretch_back(box, w0, h0, size):
    """늘린 사진(size = (가로, 세로))에 그린 박스를 원본(w0×h0) 좌표로 — 축마다 비율만 곱한다(사각형은 사각형 그대로 · 반올림만 남는다)."""
    fx, fy = w0 / size[0], h0 / size[1]
    x1, y1, x2, y2 = box
    return [round(x1 * fx), round(y1 * fy), round(x2 * fx), round(y2 * fy)]


def predict_boxes(model, paths, conf, stretch=None, imgsz=None):
    """사진 경로마다 [[이름, 점수, x1, y1, x2, y2], ...] — 묶음 초벌과 버튼 관문(train_tool_round)이 같은 함수로 그린다.
    stretch = (가로, 세로) 이면 그 크기로 늘려 넣고(cv2.resize · 학습 체계 train_one.py 와 같은 늘리기) 박스를 원본 좌표로 되돌린다.
    imgsz = 원본 그대로 넣을 때의 예측 크기(없으면 ultralytics 기본 640)."""
    from ultralytics import YOLO
    m = YOLO(model)
    out = {}
    for p in paths:
        if stretch:
            import cv2
            im = cv2.imread(p); h0, w0 = im.shape[:2]
            r = m.predict(cv2.resize(im, stretch), conf=conf, imgsz=max(stretch), verbose=False)[0]
            boxes = [stretch_back(b, w0, h0, stretch) for b in r.boxes.xyxy.tolist()]
        else:
            r = m.predict(p, conf=conf, verbose=False, **({"imgsz": imgsz} if imgsz else {}))[0]
            boxes = [[int(v) for v in b] for b in r.boxes.xyxy.tolist()]
        out[p] = [[r.names[int(c)].replace("-in-hand", ""), round(float(s), 4), *b]
                  for b, s, c in zip(boxes, r.boxes.conf.tolist(), r.boxes.cls.tolist())]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="models/tool_v3.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--stretch", help="늘려 넣을 크기 「가로x세로」(예 640x640) — 없으면 원본 그대로")
    ap.add_argument("--imgsz", help="원본 그대로 넣을 때 예측 크기 「세로,가로」(예 1024,768) — 없으면 640")
    a = ap.parse_args()
    paths = [l.strip() for l in Path(a.list).read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.stretch and a.imgsz:
        raise SystemExit("--stretch 와 --imgsz 는 함께 줄 수 없다(늘리기는 늘린 크기로 본다)")
    out = predict_boxes(a.model, paths, a.conf, parse_size(a.stretch), parse_imgsz(a.imgsz))
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"초벌 {len(paths)}장 · 박스 {sum(len(v) for v in out.values())} · 모델 {Path(a.model).name}")


if __name__ == "__main__":
    main()
