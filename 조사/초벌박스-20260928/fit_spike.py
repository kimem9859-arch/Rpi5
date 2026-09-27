"""초벌 박스 느슨함 해결 시험 (일회용) — 같은 사진에 4가지 방식으로 초벌을 만들고 박스가 버튼에 얼마나 맞는지 잰다.
base   = 지금 방식(세로 사진 통째로 640×640 늘림)
tile   = 세로 사진을 가로 모양 두 조각(768×576, 128px 겹침)으로 잘라 각각 640×640 늘림 → 학습 때와 같은 늘림 방향
pad    = 정사각형으로 여백 채운 뒤 640 (늘림 없음)
shrink = base 박스 높이만 0.87배(중심 고정)
"""
import glob, os, sys, statistics as st
from collections import Counter
import cv2, numpy as np
sys.path.insert(0, '/home/pi/sop-project/Rpi5/Demo')
from detector import create_detector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from box_fit import fit
R = '/home/pi/sop-project/Rpi5/Demo/test/raw/20260923_'
FRAMES = []
for s in ('184709_esp32_xga-rt-s1-r1', '184732_esp32_xga-rt-s1-r2', '184758_esp32_xga-rt-s1-r3'):
    FRAMES += [('정지', p) for p in sorted(glob.glob(f'{R}{s}_console_v2/f*.png'))]
FRAMES += [('좌우이동', p) for p in sorted(glob.glob(f'{R}184922_esp32_xga-rt-s2-r1_console_v2/f*.png'))[::5]]
FRAMES += [('누르기', p) for p in sorted(glob.glob(f'{R}185802_esp32_xga-rt-s6-r1_console_v2/f*.png'))[::17]]
det = create_detector(); names = {0: 'B1', 1: 'B2', 2: 'B3', 3: 'B4', 4: 'EMO'}
def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - ix*iy
    return ix*iy/u if u else 0
def run(img):
    return [(names[c], s, [x1, y1, x2, y2]) for c, s, x1, y1, x2, y2 in det.detect(img)]
def tile(img):
    H, W = img.shape[:2]; th = W * 3 // 4; tops = [0, H - th]; out = []
    for t in tops:
        for n, s, b in run(img[t:t+th]):
            b = [b[0], b[1] + t, b[2], b[3] + t]
            cut_top, cut_bot = (t > 0 and b[1] <= t + 3), (t + th < H and b[3] >= t + th - 3)
            out.append((n, s, b, cut_top or cut_bot))
    def inside(a, b):   # a 넓이 중 b 안에 든 비율
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy / max(1, (a[2]-a[0]) * (a[3]-a[1]))
    keep = []
    for d in sorted(out, key=lambda d: (d[3], -d[1])):          # 잘리지 않은 것·점수 높은 것 먼저
        if not any(d[0] == k[0] and (iou(d[2], k[2]) > 0.3 or (d[3] and inside(d[2], k[2]) > 0.5)) for k in keep):
            keep.append(d)
    return [(n, s, b) for n, s, b, _ in keep]
def pad(img):
    H, W = img.shape[:2]; S = max(H, W); c = np.full((S, S, 3), 114, np.uint8); c[:H, :W] = img
    return run(c)
def shrink(ds):
    out = []
    for n, s, (x1, y1, x2, y2) in ds:
        cy, h = (y1 + y2) / 2, (y2 - y1) * 0.87; out.append((n, s, [x1, int(cy - h/2), x2, int(cy + h/2)]))
    return out
res = {m: {'rw': [], 'rh': [], 'ab': [], 'n': Counter(), 'dup': 0, 'frames': Counter()} for m in ('base', 'tile', 'pad', 'shrink')}
for scene, p in FRAMES:
    img = cv2.imread(p); b = run(img)
    for m, ds in (('base', b), ('tile', tile(img)), ('pad', pad(img)), ('shrink', shrink(b))):
        r = res[m]; r['frames'][scene] += 1
        cnt = Counter(n for n, _, _ in ds); r['dup'] += sum(1 for v in cnt.values() if v > 1)
        for n, s, box in ds:
            r['n'][(scene, n)] += 1
            if n == 'B4': continue
            f = fit(img, box)
            if f:
                w, h = box[2]-box[0], box[3]-box[1]; r['rw'].append(w/f[0]); r['rh'].append(h/f[1]); r['ab'].append(h/w)
print('사진', Counter(s for s, _ in FRAMES))
for m, r in res.items():
    md = lambda v: f'{st.median(v):.2f}'
    print(f"\n[{m}] 폭비 {md(r['rw'])} · 높이비 {md(r['rh'])} · 박스 세로/가로 {md(r['ab'])} · 같은 버튼 2개 이상 {r['dup']}건")
    for scene in ('정지', '좌우이동', '누르기'):
        print('   ', scene, {c: r['n'][(scene, c)] for c in ('B1', 'B2', 'B3', 'B4', 'EMO')}, '/ 사진', r['frames'][scene])
