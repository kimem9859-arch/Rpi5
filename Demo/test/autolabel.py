"""5개 버튼을 색 + 기하 제약으로 자동 라벨링한다.

왜 이게 되는가:
    버튼은 **고정된 5개**이고 **같은 평면(패널)에 강체로 붙어** 있다. 그래서
    "색으로 후보를 찾고, 패널 위에 있고 서로 가까운 것만 남긴다"는 단순한 규칙이 통한다.

각 클래스의 난이도 (실측 HSV 분포, 2026-07-13):
    B1 노랑  Hue 23~29   채도 102~160  → 색이 매우 안정적. 쉽다.
    B3 핑크  Hue 161~177 채도  84~127  → 안정적. 쉽다.
    B4 파랑  Hue ~109    채도 ~170     → 파랑 원 스티커. 배경 파란 물체만 걸러내면 쉽다.
    EMO 빨강 Hue 15~160(!)              → 빨강은 Hue 0/180 경계를 넘고 광택으로 왜곡돼
                                          범위가 넓다. **EMO는 크고 링 모양**이라는 형태
                                          단서를 함께 쓴다.
    B2 흰    채도 0~28 (무채색)          → **색으로 못 찾는다.** 배경의 흰 물체(접시·제빙기
                                          뚜껑)와 구분이 안 된다. → **패널 위에 있는가**와
                                          **다른 버튼과의 근접성**으로 판별한다.

핵심 제약 (배경 오탐을 죽이는 것):
    ① 패널 위 — 주변이 어두워야 한다(검은 패널). 배경 물체는 밝은 곳에 있다.
    ② 버튼 무리 — 다른 버튼들과 가까워야 한다. 고립된 후보는 배경이다.
    ③ 크기·형태 — 실측 폭 19~94px, 종횡비 ~1.0 (정사각/원형).

⚠️ 정반사 프레임에서는 색이 날아가 B1·B3가 흰색이 된다. 이 스크립트는 그런 프레임의
   B1·B3를 놓치거나 B2로 오인할 수 있다. **정반사 세션은 사람이 반드시 검수해야 한다.**
   (정답은 진짜 버튼 정체다 — 노란 버튼이 하얗게 보여도 B1.)

사용법:
    python3 test/autolabel.py dataset/images --out dataset/labels_auto
    python3 test/autolabel.py dataset/images --out dataset/labels_auto --review 30   # 검수용 시각화
"""

import argparse
import collections
import os

import cv2
import numpy as np

CLASS_NAMES = ["B1", "B2", "B3", "B4", "EMO"]
CLASS_ID = {n: i for i, n in enumerate(CLASS_NAMES)}

# 실측 HSV 범위 (여유를 둠). 빨강은 Hue가 0/180을 넘나들어 두 구간으로 나눈다.
COLOR = {
    "B1":  [((15, 80, 60), (35, 255, 255))],                       # 노랑
    "B3":  [((155, 55, 60), (180, 255, 255))],                     # 핑크
    "B4":  [((95, 60, 30), (135, 255, 255))],                      # 파랑 스티커
    "EMO": [((0, 90, 60), (12, 255, 255)), ((165, 90, 60), (180, 255, 255))],  # 빨강(양끝)
}

MIN_W, MAX_W = 15, 100
AR_MIN, AR_MAX = 0.55, 1.8
FILL_MIN = 0.45          # 채워진 원 (링·얼룩 배제)
SURROUND_MAX = 115       # 주변 밝기 — 이보다 밝으면 패널 밖(배경)


def _blobs(mask, gray):
    """마스크에서 버튼 후보를 뽑는다. 크기·형태·패널 위 여부로 거른다."""
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(mask)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i, 0], st[i, 1], st[i, 2], st[i, 3], st[i, 4]
        if a < 25 or not (MIN_W <= w <= MAX_W) or not (MIN_W <= h <= MAX_W):
            continue
        if not (AR_MIN <= w / max(h, 1) <= AR_MAX):
            continue
        if a / (w * h) < FILL_MIN:
            continue
        # 패널 위인가 — 버튼을 둘러싼 링의 밝기를 본다. 검은 패널이면 어둡다.
        pad = max(4, int(w * 0.5))
        ys, ye = max(0, y - pad), min(gray.shape[0], y + h + pad)
        xs, xe = max(0, x - pad), min(gray.shape[1], x + w + pad)
        ring = gray[ys:ye, xs:xe].astype(float)
        m = np.ones(ring.shape, bool)
        m[y - ys:y - ys + h, x - xs:x - xs + w] = False
        if not m.any() or ring[m].mean() > SURROUND_MAX:
            continue
        out.append({"box": (x, y, w, h), "area": a, "c": (x + w / 2, y + h / 2)})
    return out


def _white_blobs(img, gray):
    """B2(흰)는 색이 없다. 밝고 채도 낮은 덩어리를 찾되 패널 위인 것만."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 주변(검은 패널)보다 확연히 밝고 무채색인 영역
    mask = cv2.inRange(hsv, (0, 0, max(90, int(gray.mean() * 1.25))), (180, 70, 255))
    return _blobs(mask, gray)


def detect(img):
    """한 프레임에서 5클래스를 찾는다. 반환: [(cls, x, y, w, h)]"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    cand = {}
    for cls, ranges in COLOR.items():
        m = None
        for lo, hi in ranges:
            part = cv2.inRange(hsv, lo, hi)
            m = part if m is None else cv2.bitwise_or(m, part)
        cand[cls] = _blobs(m, gray)
    cand["B2"] = _white_blobs(img, gray)

    # 유색 버튼(B1·B3·B4·EMO)은 클래스당 1개 — 가장 큰 것.
    # 배경에 같은 색 물체가 있어도, 패널 위 제약을 이미 통과했으므로 대개 버튼이다.
    picked = {}
    for cls in ["B1", "B3", "B4", "EMO"]:
        if cand[cls]:
            picked[cls] = max(cand[cls], key=lambda b: b["area"])

    # B2는 배경 흰 물체와 헷갈린다 → **다른 버튼과 가장 가까운** 후보를 고른다.
    # (버튼들은 한 패널에 모여 있고, 배경 접시는 멀리 떨어져 있다.)
    if cand["B2"]:
        anchors = [p["c"] for p in picked.values()]
        if anchors:
            scale = np.median([p["box"][2] for p in picked.values()])
            def dist(b):
                return min(np.hypot(b["c"][0] - a[0], b["c"][1] - a[1]) for a in anchors) / max(scale, 1)
            near = [b for b in cand["B2"] if dist(b) < 8]     # 버튼 폭의 8배 이내
            if near:
                picked["B2"] = min(near, key=dist)
        elif len(cand["B2"]) == 1:
            picked["B2"] = cand["B2"][0]

    return [(cls, *p["box"]) for cls, p in picked.items()]


def main():
    ap = argparse.ArgumentParser(description="5클래스 버튼 자동 라벨링 (색 + 기하 제약)")
    ap.add_argument("images", help="이미지 루트 (세션 폴더들이 들어있는)")
    ap.add_argument("--out", required=True, help="라벨 출력 루트")
    ap.add_argument("--review", type=int, default=0, metavar="N",
                    help="검수용 시각화 N장 저장 (out/_review/)")
    args = ap.parse_args()

    stats = collections.Counter()
    per_sess = {}
    review_left = args.review

    for sess in sorted(os.listdir(args.images)):
        img_dir = os.path.join(args.images, sess)
        if not os.path.isdir(img_dir):
            continue
        out_dir = os.path.join(args.out, sess)
        os.makedirs(out_dir, exist_ok=True)
        files = sorted(f for f in os.listdir(img_dir) if f.endswith(".png"))
        c = collections.Counter()

        for f in files:
            img = cv2.imread(os.path.join(img_dir, f))
            H, W = img.shape[:2]
            dets = detect(img)

            lines = []
            for cls, x, y, w, h in dets:
                cx, cy = (x + w / 2) / W, (y + h / 2) / H
                lines.append(f"{CLASS_ID[cls]} {cx:.6f} {cy:.6f} {w/W:.6f} {h/H:.6f}")
                c[cls] += 1
                stats[cls] += 1
            with open(os.path.join(out_dir, f[:-4] + ".txt"), "w") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))

            if review_left > 0 and len(dets) >= 4:
                rv = os.path.join(args.out, "_review")
                os.makedirs(rv, exist_ok=True)
                vis = img.copy()
                col = {"B1": (0, 215, 255), "B2": (220, 220, 220), "B3": (180, 105, 255),
                       "B4": (255, 140, 0), "EMO": (0, 0, 230)}
                for cls, x, y, w, h in dets:
                    cv2.rectangle(vis, (x, y), (x + w, y + h), col[cls], 2)
                    cv2.putText(vis, cls, (x, max(y - 4, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, col[cls], 1)
                cv2.imwrite(os.path.join(rv, f), vis)
                review_left -= 1

        per_sess[sess] = (len(files), c)

    print("【자동 라벨 결과】")
    print(f"{'세션':<24}{'장수':>5}" + "".join(f"{n:>6}" for n in CLASS_NAMES))
    print("-" * 62)
    total_n = 0
    for sess, (n, c) in per_sess.items():
        total_n += n
        print(f"{sess:<24}{n:>5}" + "".join(f"{c[x]:>6}" for x in CLASS_NAMES))
    print("-" * 62)
    print(f"{'합계':<24}{total_n:>5}" + "".join(f"{stats[x]:>6}" for x in CLASS_NAMES))
    s = sum(stats.values())
    print(f"\n총 {s}개 / 이상치 {total_n*5}개 → 달성률 {s/(total_n*5)*100:.0f}%")
    if args.review:
        print(f"검수 시각화: {os.path.join(args.out, '_review')}")
    print("\n⚠️ 정반사 프레임은 색이 날아가 B1·B3를 놓치거나 B2로 오인할 수 있다.")
    print("   Roboflow에서 반드시 검수할 것. 정답은 **진짜 버튼 정체**다.")


if __name__ == "__main__":
    main()
