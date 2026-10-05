"""공구 라벨링 모델 비교 — b011~b014 에서 사진 100장을 고르고 tool_r2 · T-full-base(시드 0·1·2) 예측을 저장한다.

- 후보 = b011~b014 의 0923-193013(공구 세션) 사진 중 두 모델의 학습 프레임에서 모두 36 프레임 넘게 떨어진 것
  (T-full-base = place1_v1 공구 학습 몫 + 버린 배경 + 학습 중 검증 · tool_r2 = 학습 311장 · 36 = split.GAP).
- 고르기 = 시드 20261005 무작위 100장 — 모델 결과(초벌 유무)는 쓰지 않는다(데이터셋 스킬 · 순환논리 금지).
- 입력 = 학습 때 그대로 — T-full-base 는 640×640 늘리기(train_one.py:136) · tool_r2 는 원본(imgsz 640 · tool_round.py:239).
- 예측 = conf 0.25 이상 모두(라벨링 운용점) · 좌표는 원본 768×1024 픽셀.
rfenv 로 돈다: ~/env/rfenv/bin/python 고르기_추론.py
"""
import glob
import json
import random
from pathlib import Path

import cv2
from ultralytics import YOLO

H = Path.home()
HERE = Path(__file__).resolve().parent
OUT = H / "data/학습실험/라벨링모델비교-20261005"
RAW = Path("/home/pi/sop-project/Rpi5/Demo/test/raw/20260923_193013_esp32_tool-free-r1_console_v2")
SES = "0923-193013"
GAP = 36
SEED = 20261005
N = 100
CONF = 0.25


def frames(names):
    return [int(n.split("__f")[1]) for n in names if n.startswith(SES)]


def candidates():
    r2 = json.load(open(H / "data/label_models/tool_r2.json"))
    sp = json.load(open(HERE.parent.parent / "학습/나눔/place1_v1.json"))
    fit_t = frames(sp["tool"]["train"] + sp["tool"]["bg_dropped"] + sp["공통"]["val"])
    fit_r = frames(r2["train"])
    out = []
    for b in ("b011", "b012", "b013", "b014"):
        for p in sorted(glob.glob(str(H / f"data/label_batches/{b}/images/*.png"))):
            n = "__".join(Path(p).stem.split("__")[-2:])
            if not n.startswith(SES):
                continue
            f = int(n.split("__f")[1])
            if min(abs(f - x) for x in fit_t) > GAP and min(abs(f - x) for x in fit_r) > GAP:
                out.append((b, n))
    return out


def boxes(r, scale):
    sx, sy = scale
    return [[r.names[int(c)], round(float(s), 3), *(round(v, 1) for v in (x1 * sx, y1 * sy, x2 * sx, y2 * sy))]
            for (x1, y1, x2, y2), s, c in zip(r.boxes.xyxyn.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]


def main():
    cand = candidates()
    pick = sorted(random.Random(SEED).sample(cand, N), key=lambda x: x[1])
    models = {
        "R": (H / "data/label_models/tool_r2.pt", False),
        "T0": (H / "data/학습실험/E0c-tool-f120/best.pt", True),
        "T1": (H / "data/학습실험/E0c-tool-f120s1/best.pt", True),
        "T2": (H / "data/학습실험/E0c-tool-f120s2/best.pt", True),
    }
    loaded = {k: YOLO(str(w)) for k, (w, _) in models.items()}
    pred = {}
    for b, n in pick:
        src = RAW / f"f{n.split('__f')[1]}.png"
        im = cv2.imread(str(src))
        h, w = im.shape[:2]
        st = cv2.resize(im, (640, 640))
        pred[n] = {"묶음": b, "원본": str(src), "크기": [w, h]}
        for k, (_, stretch) in models.items():
            r = loaded[k].predict(st if stretch else im, conf=CONF, imgsz=640, verbose=False)[0]
            pred[n][k] = boxes(r, (w, h))
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"후보": len(cand), "고름": N, "시드": SEED, "conf": CONF, "세션": SES, "GAP": GAP,
            "모델": {k: str(w) for k, (w, _) in models.items()}}
    (HERE / "예측.json").write_text(json.dumps({"조건": meta, "사진": pred}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"후보 {len(cand)} · 고름 {N} · 묶음별", {b: sum(1 for x, _ in pick if x == b) for b in ("b011", "b012", "b013", "b014")})


if __name__ == "__main__":
    main()
