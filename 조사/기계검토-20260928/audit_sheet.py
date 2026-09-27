"""기계 확정 박스 무작위 100개 눈 검사지 — 사용자가 틀린 번호만 고른다(일회용 조사).

  cd Rpi5/Demo && python3 ../조사/기계검토-20260928/audit_sheet.py
출력 = 이 폴더 audit_p1~4.jpg(한 장에 25칸) · audit_list.csv(번호 → 세션·프레임·이름·박스)
칸 = 박스 주변을 3배 확대(이웃 버튼이 보이게 박스 크기의 4배 영역) · 초록 = 기계가 확정한 박스 · 번호 · 이름
"""
import csv, random, sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import machine_review as M  # noqa: E402
from detector import create_detector  # noqa: E402

SEED, N, PER_PAGE, COLS, TILE = 20260928, 100, 25, 5, 300
ONLY = sys.argv[1] if len(sys.argv) > 1 else None   # 예: B4 → 그 버튼만 25개
PREFIX = f'audit_{ONLY}' if ONLY else 'audit'


def main():
    M.DET = create_detector()
    T, _ = M.build_template()
    # 문턱은 machine_review.main 과 같은 방식(정지 장면)으로 — 그 코드를 그대로 부른다
    th = thresholds()
    confirmed = []
    for scene, sess, fr, p in M.frames():
        img = cv2.imread(p); boxes, _, _ = M.review(img, T, th)
        for x in boxes:
            if not x['why']:
                confirmed.append((scene, sess, fr, p, x['name'], [int(v) for v in x['box']]))
    print('기계 확정 박스', len(confirmed))
    if ONLY:
        confirmed = [c for c in confirmed if c[4] == ONLY]
    count = 25 if ONLY else N
    pick = random.Random(SEED).sample(confirmed, count)
    with open(HERE / f'{PREFIX}_list.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['번호', '장면', '세션', '프레임', '이름', 'x1', 'y1', 'x2', 'y2'])
        for i, (scene, sess, fr, p, n, b) in enumerate(pick, 1):
            w.writerow([i, scene, sess, fr, n, *b])
    tiles = []
    for i, (scene, sess, fr, p, n, b) in enumerate(pick, 1):
        img = cv2.imread(p); H, W = img.shape[:2]
        x1, y1, x2, y2 = b; cx, cy = (x1 + x2) / 2, (y1 + y2) / 2; r = 2 * max(x2 - x1, y2 - y1)
        X1, Y1, X2, Y2 = int(max(0, cx - r)), int(max(0, cy - r)), int(min(W, cx + r)), int(min(H, cy + r))
        c = img[Y1:Y2, X1:X2].copy(); z = TILE / max(c.shape[:2])
        c = cv2.resize(c, (int(c.shape[1] * z), int(c.shape[0] * z)), interpolation=cv2.INTER_NEAREST)
        cv2.rectangle(c, (int((x1 - X1) * z), int((y1 - Y1) * z)), (int((x2 - X1) * z), int((y2 - Y1) * z)), (0, 255, 0), 2)
        t = np.zeros((TILE + 34, TILE, 3), np.uint8); t[34:34 + c.shape[0], :c.shape[1]] = c
        cv2.putText(t, f'{i}  {n}', (6, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.rectangle(t, (0, 0), (TILE - 1, TILE + 33), (90, 90, 90), 1)
        tiles.append(t)
    for pg in range(0, count, PER_PAGE):
        part = tiles[pg:pg + PER_PAGE]
        rows = [np.hstack(part[k:k + COLS]) for k in range(0, len(part), COLS)]
        cv2.imwrite(str(HERE / f'{PREFIX}_p{pg // PER_PAGE + 1}.jpg'), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print('검사지 →', sorted(p.name for p in HERE.glob(f'{PREFIX}_p*.jpg')))


def thresholds():
    import glob
    from collections import defaultdict
    rims = defaultdict(list); sharp, fills = [], []
    for p in sorted(glob.glob(str(M.RAW / f'20260923_{M.TEMPLATE_SESSION}_console_v2/f*.png'))):
        img = cv2.imread(p)
        for n, s, b in M.tile(img):
            sharp.append(M.sharpness(img, b))
            sn = M.snap(img, b)
            if sn is None:
                continue
            if n in ('B3', 'EMO') and M.color_family(sn['crop'], sn['mask']) == 'red':
                rims[n].append(M.rim_score(sn['crop'], sn['mask']))
            if not sn['leak']:
                fills.append(sn['fill'])
    return {'rim_lo': float(np.median(rims['B3'])), 'rim_hi': float(np.percentile(rims['EMO'], 5)),
            'sharp': float(np.percentile(sharp, 5)) * 0.5, 'fill': float(np.percentile(fills, 2)) * 0.9,
            'margin': 0.15, 'cost': 0.5}


if __name__ == '__main__':
    main()
