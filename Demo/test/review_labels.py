"""자동 라벨을 사람이 검토할 수 있게 시각화한다 — 업로드 전 검수용.

왜 필요한가:
    자동 라벨(autolabel.py)은 848장 중 79%를 채우지만 완벽하지 않다. 검증 없이 올리면
    잘못된 라벨이 그대로 학습된다. 특히:
      - **정반사 프레임**: 색이 날아가 B1·B3를 놓치거나 B2로 오인한다(v1과 같은 함정).
      - **저조도 프레임**: B3(핑크)의 채도가 무너져 검출이 안 된다.
    → 사람이 눈으로 확인해야 한다.

의심스러운 것부터 보여준다:
    848장을 순서대로 넘기는 건 비효율적이다. **문제 있을 확률 순으로 정렬**한다:
      1) 라벨 수가 5개가 아닌 것 (놓쳤거나 중복)
      2) 같은 클래스가 2개 이상 (오탐)
      3) 정상(5개)은 뒤로

출력:
    <out>/review/00001_[결함요약]_<원본명>.jpg   — 박스가 그려진 이미지
    <out>/review/_INDEX.txt                      — 파일별 결함 목록
    <out>/contact_sheet_NN.jpg                   — 12장씩 묶은 대조표(빠르게 훑기용)

사용법:
    python3 test/review_labels.py dataset/images dataset/labels_auto --out dataset/review
    # 그 뒤 파일 탐색기나 이미지 뷰어로 dataset/review/ 를 넘겨보며 확인
"""

import argparse
import collections
import os

import cv2
import numpy as np

CLASS_NAMES = ["B1", "B2", "B3", "B4", "EMO"]
COLORS = {
    "B1": (0, 215, 255), "B2": (230, 230, 230), "B3": (180, 105, 255),
    "B4": (255, 140, 0), "EMO": (0, 0, 235),
}


def load(path, W, H):
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path):
        p = line.split()
        if len(p) != 5:
            continue
        cls = CLASS_NAMES[int(p[0])]
        cx, cy, bw, bh = (float(x) for x in p[1:])
        out.append((cls, int((cx - bw / 2) * W), int((cy - bh / 2) * H),
                    int(bw * W), int(bh * H)))
    return out


def diagnose(dets):
    """무엇이 의심스러운가. (심각도, 요약) — 심각도가 클수록 먼저 보여준다."""
    c = collections.Counter(d[0] for d in dets)
    problems = []
    sev = 0
    missing = [n for n in CLASS_NAMES if c[n] == 0]
    dup = [n for n in CLASS_NAMES if c[n] > 1]
    if dup:
        problems.append("중복:" + ",".join(dup))
        sev += 10 * len(dup)          # 오탐이 제일 위험 — 틀린 라벨을 학습한다
    if missing:
        problems.append("누락:" + ",".join(missing))
        sev += len(missing)
    if not problems:
        return 0, "OK"
    return sev, " ".join(problems)


def draw(img, dets, tag):
    v = img.copy()
    for cls, x, y, w, h in dets:
        col = COLORS[cls]
        cv2.rectangle(v, (x, y), (x + w, y + h), col, 2)
        cv2.putText(v, cls, (x, max(y - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
    bar = np.zeros((26, v.shape[1], 3), np.uint8)
    color = (0, 200, 0) if tag == "OK" else (0, 165, 255)
    cv2.putText(bar, tag, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
    return np.vstack([bar, v])


def main():
    ap = argparse.ArgumentParser(description="자동 라벨 검수용 시각화")
    ap.add_argument("images")
    ap.add_argument("labels")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only-problems", action="store_true",
                    help="문제 있는 것만 출력 (정상 5개짜리는 건너뜀)")
    ap.add_argument("--sheet", type=int, default=12, help="대조표 한 장에 넣을 이미지 수")
    args = ap.parse_args()

    rv = os.path.join(args.out, "review")
    os.makedirs(rv, exist_ok=True)

    rows = []
    for sess in sorted(os.listdir(args.images)):
        idir = os.path.join(args.images, sess)
        ldir = os.path.join(args.labels, sess)
        if not os.path.isdir(idir):
            continue
        for f in sorted(os.listdir(idir)):
            if not f.endswith(".png"):
                continue
            img = cv2.imread(os.path.join(idir, f))
            H, W = img.shape[:2]
            dets = load(os.path.join(ldir, f[:-4] + ".txt"), W, H)
            sev, tag = diagnose(dets)
            rows.append((sev, sess, f, img, dets, tag))

    rows.sort(key=lambda r: -r[0])            # 의심스러운 것 먼저
    if args.only_problems:
        rows = [r for r in rows if r[0] > 0]

    stat = collections.Counter()
    idx = []
    sheet = []
    sheet_no = 0

    for i, (sev, sess, f, img, dets, tag) in enumerate(rows, 1):
        stat["문제" if sev else "정상"] += 1
        vis = draw(img, dets, f"[{len(dets)}] {tag}")
        safe = tag.replace(":", "").replace(",", "").replace(" ", "_")
        cv2.imwrite(os.path.join(rv, f"{i:04d}_{safe}_{f[:-4]}.jpg"), vis,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        idx.append(f"{i:04d}  {tag:<28} {sess}/{f}")

        sheet.append(cv2.resize(vis, (320, 260)))
        if len(sheet) == args.sheet:
            cols = 4
            r_ = [np.hstack(sheet[j:j + cols]) for j in range(0, len(sheet), cols)]
            sheet_no += 1
            cv2.imwrite(os.path.join(args.out, f"contact_sheet_{sheet_no:02d}.jpg"),
                        np.vstack(r_), [cv2.IMWRITE_JPEG_QUALITY, 88])
            sheet = []
    if sheet:
        cols = 4
        while len(sheet) % cols:
            sheet.append(np.zeros_like(sheet[0]))
        r_ = [np.hstack(sheet[j:j + cols]) for j in range(0, len(sheet), cols)]
        sheet_no += 1
        cv2.imwrite(os.path.join(args.out, f"contact_sheet_{sheet_no:02d}.jpg"),
                    np.vstack(r_), [cv2.IMWRITE_JPEG_QUALITY, 88])

    with open(os.path.join(rv, "_INDEX.txt"), "w") as fh:
        fh.write("\n".join(idx) + "\n")

    print(f"검수 이미지 {len(rows)}장 → {rv}")
    print(f"대조표 {sheet_no}장 → {args.out}/contact_sheet_*.jpg  (한 장에 {args.sheet}개)")
    print()
    print(f"  정상(5개 라벨) : {stat['정상']}장")
    print(f"  확인 필요      : {stat['문제']}장   ← 파일명 앞부분이 작을수록 의심 큼")
    print()
    print("파일명 규칙: <순번>_<결함>_<원본명>.jpg   (순번 = 의심 순서)")
    print("  중복:xx → 같은 클래스가 2개 이상 잡힘. **오탐이라 가장 위험**(틀린 라벨을 학습)")
    print("  누락:xx → 그 버튼을 못 찾음. 사람이 그려야 함")
    print()
    print("먼저 볼 것: contact_sheet_01.jpg (가장 의심스러운 것들이 앞에 온다)")


if __name__ == "__main__":
    main()
