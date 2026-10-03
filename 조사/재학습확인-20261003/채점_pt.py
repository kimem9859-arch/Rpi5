"""떼어 둔 사진 채점 — .pt 모델을 score_lib(score_hef 와 같은 계산)로 잰다: mAP50 · 운용점 precision/recall · 혼동행렬.
🔴 계산은 같아도 입력 조건이 다르다 — score_hef(HEF)는 detector 가 config.YOLO_CONF_LOW(0.50) 미만을 버려 PR 곡선이 잘린다 ·
   여기는 0.001 부터 · int8 대 fp32 · 늘리기 대 비율 유지. 지금 버튼 모델과는 mAP 가 아니라 운용점으로 비교한다(리뷰 2026-10-03).

실행(Rpi5/Demo/ 에서, rfenv): ~/env/rfenv/bin/python ../조사/재학습확인-20261003/채점_pt.py --model <pt> --group button|tool \\
    --images <폴더> --labels <폴더>   (폴더 = 기준선채점-20261003/준비.py --only 채점사진.txt 의 btn/ 또는 tool/)
- 라벨 = 8종 번호(B1 B2 B3 B4 EMO driver wrench pliers) — 이름으로 짝지어 무리 순서로 바꾼다(모델의 번호 순서가 달라도 맞게).
- 운용 문턱 = config(버튼 YOLO_CONF_HIGH · 공구 TOOL_CONF) — 다시 정하지 않는다.
- 추론은 conf 0.001 로 한 번 하고(mAP 용) 운용점은 그 위에서 거른다 — ultralytics NMS 는 점수 높은 박스부터 남기므로
  거른 결과가 운용 문턱으로 돌린 것과 같다(낮은 박스가 높은 박스를 지우지 못한다).
"""
import argparse
import sys
from pathlib import Path


DEMO = Path(__file__).resolve().parents[2] / "Demo"
sys.path.insert(0, str(DEMO)); sys.path.insert(0, str(DEMO / "test"))
import config                                            # noqa: E402
from score_lib import confusion, evaluate, operating_point  # noqa: E402

NAMES8 = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]
GROUPS = {"button": (["B1", "B2", "B3", "B4", "EMO"], config.YOLO_CONF_HIGH),
          "tool": (["driver", "wrench", "pliers"], config.TOOL_CONF)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--group", choices=GROUPS, required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--labels", required=True)
    a = ap.parse_args()
    from ultralytics import YOLO
    names, conf = GROUPS[a.group]
    m = YOLO(a.model)
    per_image = {}
    imgs = sorted(p for p in Path(a.images).iterdir() if p.suffix.lower() in (".png", ".jpg"))
    for p in imgs:
        r = m.predict(str(p), conf=0.001, verbose=False)[0]
        h, w = r.orig_shape
        gts = []
        for line in (Path(a.labels) / f"{p.stem}.txt").read_text().splitlines():
            c, cx, cy, bw, bh = line.split(); n = NAMES8[int(c)]
            if n in names:
                cx, cy, bw, bh = map(float, (cx, cy, bw, bh))
                gts.append((names.index(n), (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
        preds = [(names.index(r.names[int(c)]), float(s), *map(float, b))
                 for b, s, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()) if r.names[int(c)] in names]
        per_image[p.stem] = (gts, preds)
    ap50 = evaluate(per_image, names, (0.5,))[0.5]
    op = operating_point(per_image, names, conf)
    print(f"모델 {Path(a.model).name} · 사진 {len(per_image)} · 정답 박스 {sum(len(g) for g, _ in per_image.values())} · 운용 conf {conf} · IoU 0.5")
    print(f"mAP50 {ap50['mAP']:.3f} · 클래스별 AP50 " + " / ".join(f"{n} {ap50['per_class'][n]:.3f}" for n in names))
    print(f"{'cls':<8}{'TP':>5}{'FP':>5}{'FN':>5}{'precision':>11}{'recall':>8}")
    for n in names:
        s = op[n]; print(f"{n:<8}{s['tp']:>5}{s['fp']:>5}{s['fn']:>5}{s['precision']:>11.3f}{s['recall']:>8.3f}")
    tp, fp, fn = (sum(op[n][k] for n in names) for k in ("tp", "fp", "fn"))
    print(f"{'전체':<7}{tp:>5}{fp:>5}{fn:>5}{tp / max(tp + fp, 1):>11.3f}{tp / max(tp + fn, 1):>8.3f}")
    mat = confusion(per_image, names, conf)
    print("혼동행렬 (행=정답 · 열=예측 · 끝 열=미검출 · 끝 행=오검출)")
    print("        " + "".join(f"{c:>8}" for c in names + ["미검출"]))
    for i, n in enumerate(names):
        print(f"{n:<8}" + "".join(f"{int(v):>8}" for v in mat[i]))
    print(f"{'오검출':<6}" + "".join(f"{int(v):>8}" for v in mat[len(names)][:len(names)]))
    off = int(sum(mat[i][j] for i in range(len(names)) for j in range(len(names)) if i != j))
    print(f"클래스 간 오분류 {off}건")


if __name__ == "__main__":
    main()
