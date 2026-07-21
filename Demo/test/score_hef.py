"""console_v2 정량 채점 — 정답 라벨 대비 `.hef` 실추론 성능 측정.

왜 필요한가:
    §10.18까지의 수치는 "검출됐다"의 **빈도**일 뿐, "맞는 위치에 맞는 클래스로
    검출했는가"는 측정된 적이 없다. 옐로우등에서 B1이 검출률 97.5%로 최상위였으나
    실제로는 절반이 B2 오분류였다(§10.18) — 빈도만으로는 못 잡는 실패다.
    §10.16이 정한 **최종 판정의 유일한 경로**가 이 정량 채점이다.

측정 대상:
    `.pt` 가 아니라 **파이에서 실제 도는 `.hef`**. config.HEF_MODEL_PATH 또는 --hef.

⚠️ 이미지는 **로컬 원본 PNG**를 쓴다. Roboflow export 이미지는 JPG 재인코딩될 수 있고,
   §10.9에서 B4는 JPEG q90만으로도 사라지는 것이 측정됐다. 라벨만 Roboflow에서 받는다.
   정규화 YOLO 좌표는 축별 stretch 에 불변이라 전처리 설정과 무관하게 안전하다.

사용:
    # 실제 채점 (라벨링 완료 후)
    python3 test/score_hef.py --labels /tmp/rf_test/test/labels \
                              --images dataset/cleanroom_eval_20260720/test

    # 자기일관성 검증 (v2 프리라벨을 정답으로 → mAP50 ≈ 1.0 이어야 함)
    python3 test/score_hef.py --labels <프리라벨> --images <같은PNG> --self-check
"""

import argparse
import csv
import datetime
import os
import re
import sys

import cv2
import numpy as np

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, _TEST_DIR)

import config  # noqa: E402
from score_lib import confusion, evaluate, operating_point  # noqa: E402

CLASS_NAMES = ["B1", "B2", "B3", "B4", "EMO"]
_LOGS = os.path.join(_TEST_DIR, "logs")

# 파일명이 3중으로 다르다:
#   로컬        001_s007_<세션>__f00203.png      (흐림검토용 순위 접두)
#   업로드      <세션>__f00203.png
#   RF export   <세션>__f00203_png.rf.<hash>.jpg
# → `<세션>__f<번호>` 를 키로 정규화해 매칭한다.
_KEY = re.compile(r"(?:\d{3}_s\d{3}_)?(.+?__f\d+)(?:_png)?(?:\.rf\.[0-9a-f]+)?\.(?:png|jpg|jpeg|txt)$")


def _key(name):
    m = _KEY.match(os.path.basename(name))
    return m.group(1) if m else None


def load_labels(label_dir, wh):
    """YOLO 정규화 txt → {키: [(cls, x1,y1,x2,y2), ...]} (픽셀 좌표)."""
    w, h = wh
    out = {}
    for f in sorted(os.listdir(label_dir)):
        if not f.endswith(".txt") or f == "classes.txt":
            continue
        k = _key(f)
        if k is None:
            continue
        boxes = []
        for line in open(os.path.join(label_dir, f)):
            p = line.split()
            if len(p) < 5:
                continue
            c, cx, cy, bw, bh = int(p[0]), *map(float, p[1:5])
            boxes.append((c, (cx - bw / 2) * w, (cy - bh / 2) * h,
                          (cx + bw / 2) * w, (cy + bh / 2) * h))
        out[k] = boxes
    return out


def main():
    ap = argparse.ArgumentParser(description="console_v2 정량 채점 (.hef)")
    ap.add_argument("--labels", required=True, help="YOLO 정규화 라벨(.txt) 폴더")
    ap.add_argument("--images", required=True, help="원본 PNG 폴더 (로컬 무손실)")
    ap.add_argument("--hef", default=None, help="사용할 .hef (기본 config.HEF_MODEL_PATH)")
    ap.add_argument("--conf", type=float, default=None,
                    help=f"운용 임계 (기본 config.YOLO_CONF_HIGH={config.YOLO_CONF_HIGH})")
    ap.add_argument("--self-check", action="store_true",
                    help="자기일관성 모드 — mAP50 이 1.0 근처인지 판정해 배관 검증")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    if args.hef:
        config.HEF_MODEL_PATH = args.hef      # create_detector 전에 덮어써야 반영된다
    conf_op = args.conf if args.conf is not None else config.YOLO_CONF_HIGH

    imgs = {}
    for f in sorted(os.listdir(args.images)):
        if f.endswith(".png"):
            k = _key(f)
            if k:
                imgs[k] = os.path.join(args.images, f)
    if not imgs:
        print(f"❌ PNG 를 찾지 못했습니다: {args.images}")
        return 2

    probe = cv2.imread(next(iter(imgs.values())))
    h, w = probe.shape[:2]
    labels = load_labels(args.labels, (w, h))

    keys = sorted(set(imgs) & set(labels))
    print(f"모델   : {os.path.basename(config.HEF_MODEL_PATH)}")
    print(f"이미지 : {len(imgs)}장 ({w}x{h})   라벨: {len(labels)}개   "
          f"→ 채점 대상 {len(keys)}장")
    if len(keys) < len(imgs) or len(keys) < len(labels):
        print(f"  ⚠️ 매칭 실패 — 이미지만 {len(set(imgs)-set(labels))}개 / "
              f"라벨만 {len(set(labels)-set(imgs))}개 (채점에서 제외)")
    if not keys:
        print("❌ 매칭된 이미지가 없습니다. 파일명 규약을 확인하세요.")
        return 2

    from detector import create_detector      # config 수정 후 import
    detector = create_detector()
    per_image = {}
    try:
        for i, k in enumerate(keys, 1):
            img = cv2.imread(imgs[k])
            dets = detector.detect(img)       # 런타임과 동일 경로(원본 좌표 복원)
            per_image[k] = (labels[k], [(c, s, x1, y1, x2, y2)
                                        for c, s, x1, y1, x2, y2 in dets])
            if i % 25 == 0 or i == len(keys):
                print(f"  추론 {i}/{len(keys)}")
    finally:
        detector.close()

    # ── mAP ────────────────────────────────────────────────────────────────
    thrs = tuple(round(t, 2) for t in np.arange(0.5, 0.96, 0.05))
    res = evaluate(per_image, CLASS_NAMES, thrs)
    ap50 = res[0.5]
    m5095 = float(np.nanmean([res[t]["mAP"] for t in thrs]))

    print(f"\n{'='*60}\n【mAP】  (§10.14 학습값과 같은 형식 — 직접 대조 가능)\n{'='*60}")
    print(f"  mAP50     : {ap50['mAP']:.3f}")
    print(f"  mAP50-95  : {m5095:.3f}")
    print(f"  클래스별 AP50    : " +
          " / ".join(f"{n} {ap50['per_class'][n]:.3f}" for n in CLASS_NAMES))
    print(f"  클래스별 AP50-95 : " +
          " / ".join(f"{n} {np.nanmean([res[t]['per_class'][n] for t in thrs]):.3f}"
                     for n in CLASS_NAMES))

    # ── 운용점 ─────────────────────────────────────────────────────────────
    op = operating_point(per_image, CLASS_NAMES, conf_op)
    print(f"\n【운용점 conf={conf_op}】  FSM 이 실제로 보는 값")
    print(f"  {'cls':<5}{'TP':>6}{'FP':>6}{'FN':>6}{'precision':>11}{'recall':>9}{'F1':>8}")
    for n in CLASS_NAMES:
        s = op[n]
        print(f"  {n:<5}{s['tp']:>6}{s['fp']:>6}{s['fn']:>6}"
              f"{s['precision']:>11.3f}{s['recall']:>9.3f}{s['f1']:>8.3f}")
    tp = sum(op[n]["tp"] for n in CLASS_NAMES)
    fp = sum(op[n]["fp"] for n in CLASS_NAMES)
    fn = sum(op[n]["fn"] for n in CLASS_NAMES)
    P, R = tp / max(tp + fp, 1e-12), tp / max(tp + fn, 1e-12)
    print(f"  {'전체':<4}{tp:>6}{fp:>6}{fn:>6}{P:>11.3f}{R:>9.3f}"
          f"{2*P*R/max(P+R,1e-12):>8.3f}")

    # ── 임계값 스윕 ────────────────────────────────────────────────────────
    print(f"\n【임계값 스윕】  현재 운용값 {conf_op} 이 적절한지")
    print(f"  {'conf':>6}{'TP':>7}{'FP':>6}{'FN':>6}{'precision':>11}{'recall':>9}{'F1':>8}")
    for c in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
        s = operating_point(per_image, CLASS_NAMES, c)
        t = sum(s[n]["tp"] for n in CLASS_NAMES)
        f_ = sum(s[n]["fp"] for n in CLASS_NAMES)
        n_ = sum(s[n]["fn"] for n in CLASS_NAMES)
        p, r = t / max(t + f_, 1e-12), t / max(t + n_, 1e-12)
        mark = " ←현재" if abs(c - conf_op) < 1e-9 else ""
        print(f"  {c:>6.2f}{t:>7}{f_:>6}{n_:>6}{p:>11.3f}{r:>9.3f}"
              f"{2*p*r/max(p+r,1e-12):>8.3f}{mark}")

    # ── 혼동행렬 ───────────────────────────────────────────────────────────
    mat = confusion(per_image, CLASS_NAMES, conf_op)
    cols = CLASS_NAMES + ["미검출"]
    print(f"\n【혼동행렬 conf={conf_op}】  행=정답 · 열=예측")
    print("  ⭐ 오분류(대각선 밖)는 미검출보다 위험하다 — FSM 이 순서 위반을 통과시킨다")
    print(f"  {'':<8}" + "".join(f"{c:>8}" for c in cols))
    for i, n in enumerate(CLASS_NAMES):
        print(f"  {n:<8}" + "".join(f"{mat[i][j]:>8}" for j in range(len(cols))))
    print(f"  {'오검출':<6}" + "".join(f"{mat[len(CLASS_NAMES)][j]:>8}"
                                       for j in range(len(CLASS_NAMES))) + f"{'-':>8}")
    off = int(sum(mat[i][j] for i in range(len(CLASS_NAMES))
                  for j in range(len(CLASS_NAMES)) if i != j))
    print(f"\n  → 클래스 간 오분류 총 {off}건" +
          ("  ⚠️ 확인 필요" if off else "  ✅ 없음"))

    # ── 자기일관성 판정 ────────────────────────────────────────────────────
    if args.self_check:
        ok = ap50["mAP"] >= 0.95
        print(f"\n{'='*60}")
        print(f"【자기일관성 검증】 mAP50 = {ap50['mAP']:.3f}  → "
              + ("✅ 통과 (채점 배관 정상)" if ok else "❌ 실패 — 좌표계·매칭·AP 중 버그"))
        print("  예측과 정답이 같은 데이터이므로 1.0 에 가까워야 한다.")
        print("  완전한 1.0 이 아닌 것은 정상 — 프리라벨 생성 시 크기·종횡비 필터가")
        print("  일부 검출을 걸러내며, 그 검출은 채점에서 FP 로 잡힌다.")
        print("  ※ 이 모드에서는 mAP50-95 가 mAP50 과 같게 나온다(버그 아님) —")
        print("    예측 박스가 정답과 동일해 IoU 가 항상 1.0 이라 임계를 올려도 매칭이")
        print("    유지된다. 임계 민감도 자체는 score_lib 테스트 ④가 검증한다.")

    # ── CSV ────────────────────────────────────────────────────────────────
    if not args.no_csv:
        os.makedirs(_LOGS, exist_ok=True)
        stem = os.path.splitext(os.path.basename(config.HEF_MODEL_PATH))[0]
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_LOGS, f"score_{ts}_{stem}.csv")
        with open(path, "w", newline="") as fh:
            w_ = csv.writer(fh)
            w_.writerow(["metric", "class", "value"])
            w_.writerow(["images", "", len(keys)])
            w_.writerow(["mAP50", "", f"{ap50['mAP']:.4f}"])
            w_.writerow(["mAP50-95", "", f"{m5095:.4f}"])
            for n in CLASS_NAMES:
                w_.writerow(["AP50", n, f"{ap50['per_class'][n]:.4f}"])
                w_.writerow(["AP50-95", n,
                             f"{np.nanmean([res[t]['per_class'][n] for t in thrs]):.4f}"])
                s = op[n]
                for k2 in ("tp", "fp", "fn", "precision", "recall", "f1"):
                    w_.writerow([f"op@{conf_op}_{k2}", n, s[k2]])
            for i, n in enumerate(CLASS_NAMES):
                for j, c in enumerate(cols):
                    if mat[i][j]:
                        w_.writerow(["confusion", f"{n}->{c}", int(mat[i][j])])
        print(f"\n결과 저장: {os.path.relpath(path, _DEMO_DIR)}")

    print("\n🔴 이 수치는 통합문서 §10 기재 전 사용자 확인을 거친다(단일정본 규칙).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
