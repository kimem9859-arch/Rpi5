"""초벌 박스가 정답에 얼마나 꼭 맞나(읽기 전용 조사) — 입력방식비교.py 와 같은 사진·조건 · conf 0.65.
①② 는 묶음 도구가 실제로 쓰는 prelabel_tools.predict_boxes(늘리기 → 원본 좌표 되돌림 포함) · ③ 은 학습과 같은 [1024,768] 예측.
맞은 박스(같은 이름 · IoU ≥ 0.5 · 사진·종류마다 IoU 큰 순 1:1)마다 IoU 와 네 변의 어긋남(px · 원본 768×1024)을 잰다."""
import json
import sys
from pathlib import Path

R5 = Path("/home/pi/sop-project/Rpi5")
sys.path.insert(0, str(R5 / "학습")); sys.path.insert(0, str(R5 / "Demo/test"))
import prelabel_tools as PT  # noqa: E402
import scoring  # noqa: E402

H = Path.home(); SRC = H / "data/label_dataset/place1"; NAMES = ["driver", "wrench", "pliers"]
r2 = json.load(open(H / "data/label_models/tool_r2.json")); split = json.load(open(R5 / "학습/나눔/place1_v1.json"))
idx = dict(l.split("\t") for l in (SRC / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip())
names = sorted(set(split["공통"]["unused"]) & set(r2["val"])) + \
    [l.strip() for l in (R5 / "조사/재학습확인-20261003/채점사진.txt").read_text().splitlines() if l.strip()]
paths = [idx[n] for n in names]
gt = {}
for n, p in zip(names, paths):
    gt[p] = [(NAMES[g[0]], g[1:]) for g in scoring.gts_from_lines((SRC / "labels" / f"{n}.txt").read_text().splitlines(), NAMES, 768, 1024)]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def pred_in1024(model):
    from ultralytics import YOLO
    m = YOLO(model); out = {}
    for p in paths:
        r = m.predict(p, conf=0.65, imgsz=[1024, 768], verbose=False)[0]
        out[p] = [[r.names[int(c)], float(s), *b] for b, s, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]
    return out


conds = {
    "① T-full-base 늘림": lambda: PT.predict_boxes(str(H / "data/학습실험/E0c-tool-f120/best.pt"), paths, 0.65, (640, 640)),
    "② T-full-base 안 늘림": lambda: PT.predict_boxes(str(H / "data/학습실험/E0c-tool-f120/best.pt"), paths, 0.65),
    "③ T-full-in1024 원본비율": lambda: pred_in1024(str(H / "data/학습실험/E1c-tool-f120in1024/best.pt")),
}
res = {}
for cname, fn in conds.items():
    pr = fn(); ious, edges = [], []
    for p in paths:
        for t in NAMES:
            G = [g for nm, g in gt[p] if nm == t]; P = [d[2:6] for d in pr[p] if d[0] == t]
            pairs = sorted(((iou(g, q), i, j) for i, g in enumerate(G) for j, q in enumerate(P)), reverse=True)
            ug, up = set(), set()
            for v, i, j in pairs:
                if v >= 0.5 and i not in ug and j not in up:
                    ug.add(i); up.add(j); ious.append(v)
                    edges.append(max(abs(a - b) for a, b in zip(G[i], P[j])))
    ious.sort(); edges.sort(); n = len(ious)
    bins = {"≥0.9": sum(v >= 0.9 for v in ious), "0.8~0.9": sum(0.8 <= v < 0.9 for v in ious),
            "0.7~0.8": sum(0.7 <= v < 0.8 for v in ious), "0.5~0.7": sum(v < 0.7 for v in ious)}
    res[cname] = {"맞은 박스": n, "IoU 평균": round(sum(ious) / n, 3), "IoU 중앙": round(ious[n // 2], 3), "IoU 구간": bins,
                  "가장 어긋난 변 중앙 px": round(edges[n // 2], 1), "가장 어긋난 변 90% px": round(edges[int(n * 0.9)], 1)}
    print(cname, json.dumps(res[cname], ensure_ascii=False), flush=True)
Path(sys.argv[1]).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
