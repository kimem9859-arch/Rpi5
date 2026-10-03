# 검증 — 새 버튼 모델에 시연 HEF 와 같은 입력 맞추기(640×640 늘리기)를 넣어 채점(Hailo 안 씀 · CPU) · 리뷰 2026-10-03 작성 · 실행: 검증_늘리기.py <pt> <채점 폴더 btn>
import sys, cv2
from pathlib import Path
DEMO = Path('/home/pi/sop-project/Rpi5/Demo'); sys.path.insert(0, str(DEMO / 'test'))
from score_lib import evaluate, operating_point, confusion
from ultralytics import YOLO
names = ["B1", "B2", "B3", "B4", "EMO"]; N8 = names + ["driver", "wrench", "pliers"]
E = Path(sys.argv[2]); m = YOLO(sys.argv[1])
per = {}
for p in sorted((E / 'images').iterdir()):
    img = cv2.imread(str(p)); h, w = img.shape[:2]
    s = cv2.resize(img, (640, 640))
    r = m.predict(s, conf=0.001, imgsz=640, verbose=False)[0]
    sx, sy = w / 640, h / 640
    gts = []
    for line in (E / 'labels' / f'{p.stem}.txt').read_text().splitlines():
        c, cx, cy, bw, bh = line.split(); n = N8[int(c)]
        cx, cy, bw, bh = map(float, (cx, cy, bw, bh))
        gts.append((names.index(n), (cx-bw/2)*w, (cy-bh/2)*h, (cx+bw/2)*w, (cy+bh/2)*h))
    preds = [(names.index(r.names[int(c)]), float(sc), b[0]*sx, b[1]*sy, b[2]*sx, b[3]*sy)
             for b, sc, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]
    per[p.stem] = (gts, preds)
ap = evaluate(per, names, (0.5,))[0.5]; op = operating_point(per, names, 0.65)
print('stretch640 mAP50 %.3f' % ap['mAP'], {n: round(ap['per_class'][n], 3) for n in names})
tp, fp, fn = (sum(op[n][k] for n in names) for k in ('tp', 'fp', 'fn'))
print('op0.65', {n: (op[n]['tp'], op[n]['fp'], op[n]['fn']) for n in names}, 'P %.3f R %.3f' % (tp/max(tp+fp,1), tp/max(tp+fn,1)))
# also truncate letterbox preds at 0.50 to mimic score_hef's YOLO_CONF_LOW cut (mAP 비교 조건)
