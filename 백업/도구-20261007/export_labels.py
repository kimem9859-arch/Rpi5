"""벤치 검출 결과(rawdet_log.csv)를 YOLO 라벨(.txt)로 내보낸다 — 프리라벨.

    소스 모델은 그 로그를 만든 모델이다. 도구가 모델을 가리지 않으므로,
    v2로 촬영한 로그를 주면 v2 프리라벨이 나온다(재추론 불필요).

왜 필요한가:
    검출을 **초벌 라벨**로 쓰면 사람이 처음부터 5개를 다 그릴 필요가 없다.
    달성률 실측: v1 소스 42%(2026-07-13) → **v2 소스 92%**(2026-07-20 클린룸).
    v2는 파랑 B4도 잡으므로 "B4 전량 수동"은 더 이상 해당하지 않는다.

⚠️ 프리라벨을 검수 없이 학습에 쓰면 **소스 모델의 오류를 그대로 물려받는다.**
   특히 **빠진 박스**가 해롭다 — 버튼이 있는데 라벨이 없으면 학습은 그 자리를
   "버튼 없음"으로 가르친다. 검수 우선순위:
     ① 빠진 박스 채우기 — 단, **가려서 안 보이는 것은 그대로 둔다**(Modal, labeling_guide §③)
     ② 잘못된 클래스 수정 — 정답은 **진짜 버튼 정체**다(노란 버튼이 하얗게 보여도 B1)
     ③ 박스 타이트함 — 눈에 띄게 어긋난 것만. FSM이 ROI 겹침으로 접촉을 판정하므로
        박스가 크면 안 눌렀는데 닿았다고 오판할 수 있다.

⚠️ **평가용 test 셋에는 쓰지 말 것** — 평가 대상 모델로 정답을 만들면 순환논리다.

배경 오탐 필터:
    실측(2026-07-13, 4세션 15,577건)에서 버튼 bbox는 폭 19~94px, 종횡비 ~1.0(정사각).
    배경의 둥근 흰 물체(제빙기 뚜껑 등)가 B2로 오탐되는데 폭 116px로 크고 납작하다.
    → 크기·종횡비로 걸러낸다.

사용법:
    # 중복 제거된 이미지 폴더에 대해 라벨 생성
    python3 test/export_labels.py dataset/images --logs test/logs --out dataset/labels

    # 필터 없이 전량 (검수용)
    python3 test/export_labels.py dataset/images --logs test/logs --out dataset/labels --no-filter

출력:
    dataset/labels/<세션>__f00123.txt   — YOLO 형식: cls cx cy w h  (0~1 정규화)
    dataset/classes.txt                 — 클래스 이름
"""

import argparse
import collections
import csv
import os
import re

import cv2

CLASS_NAMES = ["B1", "B2", "B3", "B4", "EMO"]
CLASS_ID = {n: i for i, n in enumerate(CLASS_NAMES)}

# 실측 기반 필터 (2026-07-13, 4세션)
MIN_W, MAX_W = 15, 100      # 버튼 폭 p1=19 / p99=94
AR_MIN, AR_MAX = 0.6, 1.7   # 종횡비 중앙 ~1.0 (정사각). 납작한 배경물체 제외


def parse_name(fname):
    """'20260713_174153_esp32__f00123.png' → (세션, 프레임번호)"""
    m = re.match(r"(.+?)__f(\d+)\.png$", fname)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"f(\d+)\.png$", fname)     # 세션 접두 없는 경우
    return None, int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser(description="rawdet_log → YOLO 라벨 (프리라벨)")
    ap.add_argument("images", help="이미지 폴더 (dedupe_raw.py --out 결과)")
    ap.add_argument("--logs", default="test/logs", help="rawdet_log.csv 가 있는 폴더")
    ap.add_argument("--out", required=True, help="라벨(.txt) 출력 폴더")
    ap.add_argument("--conf", type=float, default=0.50,
                    help="이 신뢰도 미만 검출은 버림 (기본 0.50 = CONF_LOW)")
    ap.add_argument("--no-filter", action="store_true", help="크기·종횡비 필터 끄기")
    ap.add_argument("--classes-out", default=None,
                    help="classes.txt를 쓸 경로. labels/ 안에 두면 세션 폴더 순회 시 "
                         "파일을 폴더로 오인하므로 dataset/classes.txt 처럼 부모에 둘 것")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # 세션별 rawdet_log 로드 → (세션, 프레임) → 검출 목록
    det = collections.defaultdict(list)
    for f in os.listdir(args.logs):
        if not f.endswith("_rawdet_log.csv"):
            continue
        sess = f[: -len("_rawdet_log.csv")]
        with open(os.path.join(args.logs, f)) as fh:
            for r in csv.DictReader(fh):
                det[(sess, int(r["frame"]))].append(r)

    images = sorted(f for f in os.listdir(args.images) if f.endswith(".png"))
    stats = collections.Counter()
    filtered = collections.Counter()
    no_label = []

    for img_name in images:
        sess, frame_no = parse_name(img_name)
        if frame_no is None:
            continue
        rows = det.get((sess, frame_no), [])

        img = cv2.imread(os.path.join(args.images, img_name))
        H, W = img.shape[:2]

        lines = []
        for r in rows:
            if float(r["score"]) < args.conf:
                continue
            name = r["cls_name"]
            if name not in CLASS_ID:
                continue
            x1, y1, x2, y2 = (int(r[k]) for k in ("x1", "y1", "x2", "y2"))
            w, h = x2 - x1, y2 - y1
            if w <= 0 or h <= 0:
                continue

            if not args.no_filter:
                ar = w / h
                if not (MIN_W <= w <= MAX_W) or not (AR_MIN <= ar <= AR_MAX):
                    filtered[name] += 1          # 배경 오탐 추정 → 제외
                    continue

            # YOLO 형식: 중심좌표·크기를 0~1로 정규화. 이미지 밖으로 나간 박스는 자른다.
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(W, x2), min(H, y2)
            cx, cy = (x1 + x2) / 2 / W, (y1 + y2) / 2 / H
            bw, bh = (x2 - x1) / W, (y2 - y1) / H
            lines.append(f"{CLASS_ID[name]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            stats[name] += 1

        txt = os.path.join(args.out, img_name.replace(".png", ".txt"))
        with open(txt, "w") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
        if not lines:
            no_label.append(img_name)

    if args.classes_out:
        with open(args.classes_out, "w") as fh:
            fh.write("\n".join(CLASS_NAMES) + "\n")
        print(f"클래스맵: {args.classes_out}")

    n = len(images)
    print(f"이미지 {n}장 → 라벨 {n}개 생성 ({args.out})\n")
    print("【프리라벨 생성 결과】")
    for c in CLASS_NAMES:
        # 소스 모델이 못 잡는 클래스를 드러낸다. 임계는 소스 무관하게 적용 —
        # v1은 B4가, 유색 조명에서는 B2·B4가 여기 걸린다(§10.18).
        note = "  ⚠️ 프레임의 절반도 못 잡음 → 수동 보충 필요" if stats[c] < n * 0.5 else ""
        print(f"  {c:<4}{stats[c]:>6}건  (프레임당 {stats[c]/n:.2f}){note}")

    if filtered:
        print(f"\n배경 오탐 필터로 제외: {sum(filtered.values())}건 {dict(filtered)}")
        print("  (버튼은 폭 19~94px·종횡비 ~1.0. 그 밖은 배경 물체로 간주)")

    if no_label:
        print(f"\n⚠️ 검출 0건인 이미지: {len(no_label)}장 — 전량 수동 라벨 필요")

    print("\n" + "=" * 60)
    print("다음 단계 — 라벨링 툴(Roboflow)에서 검수할 것 (우선순위 순):")
    print("  1. 빠진 박스 채우기 — 가장 해롭다(라벨 없으면 '버튼 없음'으로 학습된다)")
    print("     ※ 단, **가려서 안 보이는 것은 그대로 둔다**(Modal — labeling_guide §③)")
    print("  2. 잘못된 클래스 수정")
    print("     ※ 정답은 **진짜 버튼 정체**다. 노란 버튼이 하얗게 보여도 B1.")
    print("  3. 박스 타이트함 — 눈에 띄게 어긋난 것만(FSM이 ROI 겹침으로 접촉 판정)")
    print("=" * 60)


if __name__ == "__main__":
    main()
