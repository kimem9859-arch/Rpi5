"""초벌 버튼 박스가 실제 버튼 윤곽보다 얼마나 큰지 — 세로 실행(XGA) vs 7월 가로(학습과 같은 늘림 방향) 비교. 일회용."""
import csv, glob, statistics as st, sys
import cv2, numpy as np
T = '/home/pi/sop-project/Rpi5/Demo/test/'
GROUPS = {
  'XGA 세로 (지금)': [f'{T}raw/20260923_1847{s}_esp32_xga-rt-s1-r{r}_console_v2' for s, r in (('09', 1), ('32', 2), ('58', 3))],
  '7월 VGA 가로 (학습과 같은 조건)': sorted(glob.glob(f'{T}raw/20260720_1547*_esp32_cleanroom-fluorescent_console_v2')
                                  + glob.glob(f'{T}raw/20260720_1548*_esp32_cleanroom-fluorescent_console_v2')
                                  + glob.glob(f'{T}raw/20260720_1549*_esp32_cleanroom-fluorescent_console_v2')),
}
def fit(img, box):
    x1, y1, x2, y2 = box; w, h = x2 - x1, y2 - y1
    m = int(0.5 * max(w, h)); H, W = img.shape[:2]
    X1, Y1, X2, Y2 = max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m)
    c = img[Y1:Y2, X1:X2].astype(np.int32)
    ring = np.ones(c.shape[:2], bool); ring[y1 - Y1:y2 - Y1, x1 - X1:x2 - X1] = False
    bg = np.median(c[ring], axis=0)
    mask = (np.linalg.norm(c - bg, axis=2) > 45).astype(np.uint8)
    n, lab, stats, cen = cv2.connectedComponentsWithStats(mask, 8)
    cy, cx = (y1 + y2) // 2 - Y1, (x1 + x2) // 2 - X1
    k = lab[cy, cx]
    if k == 0:
        return None
    bx, by, bw, bh, area = stats[k]
    if area < 0.2 * w * h:
        return None
    return bw, bh
if __name__ == '__main__':
    for name, sessions in GROUPS.items():
        rw, rh, asp_box, asp_btn = [], [], [], []
        for s in sessions:
            log = s.replace('/raw/', '/logs/') + '_rawdet_log.csv'
            rows = list(csv.DictReader(open(log)))
            by = {}
            for r in rows:
                by.setdefault(int(r['frame']), []).append(r)
            for p in sorted(glob.glob(f'{s}/f*.png')):
                fr = int(p.split('/f')[-1][:5]); img = cv2.imread(p)
                for r in by.get(fr, []):
                    if r['cls_name'] == 'B4':      # 검정 몸통이 판과 구분 안 돼 제외
                        continue
                    box = [int(r[k]) for k in ('x1', 'y1', 'x2', 'y2')]
                    f = fit(img, box)
                    if not f: continue
                    bw, bh = f; w, h = box[2] - box[0], box[3] - box[1]
                    rw.append(w / bw); rh.append(h / bh); asp_box.append(h / w); asp_btn.append(bh / bw)
        q = lambda v: f'{st.median(v):.2f} (사분위 {np.percentile(v,25):.2f}~{np.percentile(v,75):.2f})'
        print(f'\n[{name}] 세션 {len(sessions)} · 박스 {len(rw)}개 (B4 제외)')
        print('  박스 폭 ÷ 버튼 폭    ', q(rw)); print('  박스 높이 ÷ 버튼 높이', q(rh))
        print('  박스 세로/가로 비    ', q(asp_box)); print('  버튼 세로/가로 비    ', q(asp_btn))
