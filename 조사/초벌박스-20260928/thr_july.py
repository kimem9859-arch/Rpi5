"""7월 VGA 가로(학습과 같은 늘림 방향) 박스 여유를 버튼 윤곽 문턱별로 잰다 — 「여유 약 10%」가 측정 기준에 달린 값인지 확인."""
import csv, glob, os, statistics as st
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'box_fit.py')).read().split("if __name__")[0]
for thr in (20, 30, 45, 70):
    ns = {}; exec(src.replace('> 45', f'> {thr}'), ns)
    rw, rh = [], []
    for s in ns['GROUPS']['7월 VGA 가로 (학습과 같은 조건)']:
        rows = list(csv.DictReader(open(s.replace('/raw/', '/logs/') + '_rawdet_log.csv'))); by = {}
        for r in rows: by.setdefault(int(r['frame']), []).append(r)
        for p in sorted(glob.glob(f'{s}/f*.png'))[::3]:
            fr = int(p.split('/f')[-1][:5]); img = cv2.imread(p)
            for r in by.get(fr, []):
                if r['cls_name'] == 'B4': continue
                b = [int(r[k]) for k in ('x1', 'y1', 'x2', 'y2')]; f = ns['fit'](img, b)
                if f: rw.append((b[2]-b[0])/f[0]); rh.append((b[3]-b[1])/f[1])
    print(f'윤곽 문턱 {thr:3d}: 박스폭/버튼폭 {st.median(rw):.2f} · 박스높이/버튼높이 {st.median(rh):.2f} · n={len(rw)}')
