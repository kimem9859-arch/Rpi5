"""버튼 초벌 기계 검토 시험 (일회용 조사) — 초벌 박스를 픽셀 단위로 맞추고, 이름을 여러 증거로 교차 확인해
「기계 확정」과 「사람에게 넘김(이유)」으로 가른다.

  cd Rpi5/Demo && python3 ../조사/기계검토-20260928/machine_review.py [--vis N]

증거
  ① 배치 틀  — 판에 고정된 버튼 5개의 상대 위치. 보이는 버튼에 닮음 변환(이동·회전·배율, 뒤집기 없음)을 맞춰
               각 박스가 어느 자리인지 정한다. 2개면 버튼 간격 ÷ 버튼 크기 비로 배율을 따로 확인한다.
  ② 색 계열  — 흰(B2) · 노랑(B1) · 파랑(B4 스티커) · 빨강 계열(B3·EMO)
  ③ 흰 테두리 무늬 — 빨강 계열 중 EMO 에만 있다
  박스 맞추기 — 박스 둘레 배경색과의 색 거리(Lab). 오츠로 버튼 속을 찾고, 속 거리 중앙값의 EDGE_FRAC 배를 가장자리로 삼아
               버튼 영역의 외접 사각형을 새 박스로.
확정 조건 — 초벌 이름 = 배치 틀 이름(여유 있게 1등) · 색 계열 일치 · (빨강 계열) 무늬 일치 · 박스 맞추기 성공
           (배경으로 새지 않음 · 예상 크기와 비슷 · 속이 찬 타원) · 흐리지 않음.
B4 = 실콘솔에서는 윗면 전체가 파랗게 보여(2026-09-28 확대 확인) 다른 버튼과 같이 맞춘다.
"""
import argparse, glob, itertools, json, math, os, sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, '/home/pi/sop-project/Rpi5/Demo')
from detector import create_detector  # noqa: E402

RAW = Path('/home/pi/sop-project/Rpi5/Demo/test/raw')
SLOTS = ['B1', 'B2', 'B3', 'B4', 'EMO']
FAMILY = {'B1': 'yellow', 'B2': 'white', 'B3': 'red', 'B4': 'blue', 'EMO': 'red'}
SESS = {  # 장면: (세션 접미어들, 사진 간격)
    '정지': (['184709_esp32_xga-rt-s1-r1', '184732_esp32_xga-rt-s1-r2', '184758_esp32_xga-rt-s1-r3'], 1),
    '좌우이동': (['184922_esp32_xga-rt-s2-r1', '184950_esp32_xga-rt-s2-r2', '185019_esp32_xga-rt-s2-r3'], 3),
    '누르기': (['185802_esp32_xga-rt-s6-r1', '190129_esp32_xga-rt-s6-r2'], 10),
    '공구': (['193013_esp32_tool-free-r1'], 15),
}
TEMPLATE_SESSION = '184709_esp32_xga-rt-s1-r1'   # 정지 장면 — 배치 틀을 여기서 만든다
EDGE_FRAC = 0.35   # 가장자리 기준 — 확대 사진 눈 비교로 정함(0.2 는 빛 번짐까지 · 오츠만은 그늘진 가장자리를 뺌). 사람 라벨로 맞춰야 한다


# ───────────────────────── 봉인(실험 1) ─────────────────────────
def sealed():
    sel = json.load(open(Path.home() / 'data/label_exp1/selection.json'))
    gap = {f'20260923_{p[0]}_console_v2': p[3] for p in sel['plan']}
    out = defaultdict(list)
    for p in sel['picked']:
        out[p['session']].append(p['frame'])
    return out, gap


# ───────────────────────── 초벌(조각 방식) ─────────────────────────
DET = None
last_margin = [None]
last_cost = [None]
TPL = [None, None]
NAMES = {0: 'B1', 1: 'B2', 2: 'B3', 3: 'B4', 4: 'EMO'}


def run(img):
    return [(NAMES[c], s, [x1, y1, x2, y2]) for c, s, x1, y1, x2, y2 in DET.detect(img)]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def inside(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / max(1, (a[2] - a[0]) * (a[3] - a[1]))


def tile(img):
    H, W = img.shape[:2]; th = W * 3 // 4; out = []
    for t in (0, H - th):
        for n, s, b in run(img[t:t + th]):
            b = [b[0], b[1] + t, b[2], b[3] + t]
            cut = (t > 0 and b[1] <= t + 3) or (t + th < H and b[3] >= t + th - 3)
            out.append((n, s, b, cut))
    keep = []
    for d in sorted(out, key=lambda d: (d[3], -d[1])):
        if not any(d[0] == k[0] and (iou(d[2], k[2]) > 0.3 or (d[3] and inside(d[2], k[2]) > 0.5)) for k in keep):
            keep.append(d)
    return [(n, s, b) for n, s, b, _ in keep]


# ───────────────────────── 픽셀 증거 ─────────────────────────
def snap(img, box):
    """박스 둘레 배경과 색이 다른 영역(오츠 문턱)의 외접 사각형. 실패면 None."""
    x1, y1, x2, y2 = box; w, h = x2 - x1, y2 - y1
    m = int(0.4 * max(w, h)); H, W = img.shape[:2]
    X1, Y1, X2, Y2 = max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m)
    crop = img[Y1:Y2, X1:X2]
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    ring = np.ones(crop.shape[:2], bool); ring[max(0, y1 - Y1):y2 - Y1, max(0, x1 - X1):x2 - X1] = False
    if ring.sum() < 30:
        return None
    d = np.linalg.norm(lab - np.median(lab[ring], axis=0), axis=2)
    d8 = np.clip(d * 255 / max(float(d.max()), 1.0), 0, 255).astype(np.uint8)
    _, core = cv2.threshold(d8, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 오츠는 버튼의 밝은 속만 잡아 그늘진 가장자리를 잘라먹는다 → 속 색 거리 중앙값의 EDGE_FRAC 배로 다시 가른다
    mask = (d8 > EDGE_FRAC * float(np.median(d8[core > 0]))).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labm, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    inner = np.zeros(mask.shape, bool); inner[max(0, y1 - Y1):y2 - Y1, max(0, x1 - X1):x2 - X1] = True
    best, bo = None, 0
    for k in range(1, n):
        ov = int(((labm == k) & inner).sum())
        if ov > bo:
            bo, best = ov, k
    if best is None:
        return None
    bx, by, bw, bh, area = st[best]
    leak = bx == 0 or by == 0 or bx + bw >= crop.shape[1] or by + bh >= crop.shape[0]
    fill = area / (math.pi * bw * bh / 4 + 1e-6)
    return {'box': [X1 + bx, Y1 + by, X1 + bx + bw, Y1 + by + bh], 'fill': fill, 'leak': leak,
            'mask': labm[by:by + bh, bx:bx + bw] == best, 'crop': crop[by:by + bh, bx:bx + bw]}


def color_family(crop, mask):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[mask]
    if len(hsv) < 20:
        return None
    h, s, v = np.median(hsv[:, 0]), np.median(hsv[:, 1]), np.median(hsv[:, 2])
    if s < 60 and v > 120:
        return 'white'
    if 12 <= h <= 40:
        return 'yellow'
    if 90 <= h <= 135:
        return 'blue'
    if h < 12 or h > 160:
        return 'red'
    return None


def rim_score(crop, mask):
    """버튼 영역 중 반지름 0.5~0.95 고리 안의 흰 픽셀 비율 — EMO 흰 테두리 무늬."""
    hh, ww = mask.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    r = np.sqrt(((xx - ww / 2) / (ww / 2)) ** 2 + ((yy - hh / 2) / (hh / 2)) ** 2)
    ring = (r >= 0.5) & (r <= 0.95)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 170)
    return float((white & ring).sum()) / max(1, int(ring.sum()))


def sharpness(img, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    g = cv2.cvtColor(img[max(0, y1):y2, max(0, x1):x2], cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var()) if g.size else 0.0


# ───────────────────────── 배치 틀 ─────────────────────────
def similarity(src, dst):
    """src→dst 닮음 변환(뒤집기 없음). 반환 = (배율, 회전, 이동, 적용 함수)."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    ms, md = src.mean(0), dst.mean(0); a, b = src - ms, dst - md
    den = (a ** 2).sum()
    if den < 1e-9:
        return None
    c = (a * b).sum() / den; s_ = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() / den
    scale, rot = math.hypot(c, s_), math.atan2(s_, c)
    R = np.array([[c, -s_], [s_, c]])
    return scale, rot, lambda p: (np.asarray(p, float) - ms) @ R.T + md


def affine(src, dst):
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    A = np.hstack([src, np.ones((len(src), 1))])
    M, *_ = np.linalg.lstsq(A, dst, rcond=None)          # 3x2
    L = M[:2].T
    det = np.linalg.det(L)
    if det <= 0:
        return None
    sv = np.linalg.svd(L, compute_uv=False)
    if sv[0] / sv[1] > 1.6:                               # 기울기·찌그러짐이 너무 크면 버린다
        return None
    rot = math.atan2(L[1, 0], L[0, 0])
    return math.sqrt(det), rot, lambda p: np.hstack([np.asarray(p, float), np.ones((len(p), 1))]) @ M


def fit_layout(T, dets):
    """dets = [(cx, cy, diam)]. 각 박스를 자리(또는 None=버튼 아님)에 배정하는 경우를 모두 맞춰 본다.
    2~3점 = 닮음 변환 · 4점 이상 = 아핀(원근을 흡수). 여유 = 「어느 박스든 다른 자리로 배정한」 최선과의 비용 차."""
    k = len(dets)
    if k < 2:
        return None
    results = []
    for assign in itertools.product(SLOTS + [None], repeat=k):
        used = [a for a in assign if a]
        if len(used) != len(set(used)) or len(used) < 2 or assign.count(None) > 1:
            continue
        idx = [i for i, a in enumerate(assign) if a]
        src = [T[assign[i]][:2] for i in idx]; dst = [dets[i][:2] for i in idx]
        f = affine(src, dst) if len(idx) >= 4 else similarity(src, dst)
        if f is None:
            continue
        scale, rot, apply = f
        if abs(rot) > math.radians(40):
            continue
        pred = apply(src)
        diam = np.array([dets[i][2] for i in idx])
        res = np.linalg.norm(pred - np.asarray(dst), axis=1) / diam
        size = np.log(diam / (scale * np.array([T[assign[i]][2] for i in idx])))
        cost = float((res ** 2).mean() + (size ** 2).mean() + 0.5 * assign.count(None))
        results.append((cost, assign, scale, apply))
    if not results:
        return None
    results.sort(key=lambda r: r[0])
    best = results[0]
    alt = [r[0] for r in results[1:]
           if any(a and b and a != b for a, b in zip(best[1], r[1]))]
    margin = (alt[0] - best[0]) if alt else 9.0
    return {'cost': best[0], 'assign': best[1], 'margin': margin, 'scale': best[2], 'apply': best[3]}


def build_template():
    fs = sorted(glob.glob(str(RAW / f'20260923_{TEMPLATE_SESSION}_console_v2/f*.png')))
    acc = defaultdict(list)
    for p in fs:
        ds = tile(cv2.imread(p))
        c = Counter(n for n, _, _ in ds)
        if sorted(c) != SLOTS or max(c.values()) > 1:
            continue
        img = cv2.imread(p)
        for n, s, b in ds:
            sn = snap(img, b)
            if sn is None or sn['leak']:
                continue
            b = sn['box']
            acc[n].append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, ((b[2] - b[0]) + (b[3] - b[1])) / 2))
    return {n: tuple(np.median(np.array(v), axis=0)) for n, v in acc.items()}, len(acc['B1'])


# ───────────────────────── 한 장 검토 ─────────────────────────
def review(img, T, th):
    ds = tile(img); boxes = []
    for n, s, b in ds:
        sn = snap(img, b)
        fam = rim = None
        if sn is not None:
            fam = color_family(sn['crop'], sn['mask'])
            if fam == 'red':
                rim = rim_score(sn['crop'], sn['mask'])
        box = sn['box'] if sn is not None else b
        boxes.append({'name': n, 'score': s, 'pre': b, 'snap': sn, 'box': box, 'fam': fam, 'rim': rim,
                      'sharp': sharpness(img, b)})
    dets = [((x['box'][0] + x['box'][2]) / 2, (x['box'][1] + x['box'][3]) / 2,
             ((x['box'][2] - x['box'][0]) + (x['box'][3] - x['box'][1])) / 2) for x in boxes]
    lay = fit_layout(T, dets) if 2 <= len(boxes) <= 7 else None
    last_margin[0] = lay['margin'] if lay else None
    last_cost[0] = lay['cost'] if lay else None
    nvis = len(boxes)
    for i, x in enumerate(boxes):
        why = []
        L = lay['assign'][i] if lay else None
        x['layout'] = L
        if nvis < 2:
            why.append('버튼 1개')
        elif lay is None or lay['margin'] < th['margin'] or lay['cost'] > th['cost']:
            why.append('배치 불확실')
        elif L is None:
            why.append('배치상 버튼 아님')
        elif L != x['name']:
            why.append('배치≠초벌')
        if True:
            sn = x['snap']
            if sn is None or sn['leak']:
                why.append('박스 맞추기 실패')
            else:
                if sn['fill'] < th['fill']:
                    why.append('가림·모양 이상')
                if lay and L:
                    exp = lay['scale'] * T[L][2]; got = dets[i][2]
                    if not (0.75 < got / exp < 1.3):
                        why.append('크기 이상')
            if x['fam'] != FAMILY[x['name']]:
                why.append('색≠초벌')
            if x['fam'] == 'red' and x['rim'] is not None:
                if (x['name'] == 'EMO' and x['rim'] < th['rim_lo']) or (x['name'] == 'B3' and x['rim'] > th['rim_hi']):
                    why.append('무늬≠초벌')
        if x['sharp'] < th['sharp']:
            why.append('흐림')
        x['why'] = why
    missing = []
    if lay and sum(1 for a in lay['assign'] if a) >= 3:
        H, W = img.shape[:2]
        for sl in SLOTS:
            if sl not in lay['assign']:
                cx, cy = lay['apply']([T[sl][:2]])[0]
                if 0 < cx < W and 0 < cy < H:
                    r = lay['scale'] * T[sl][2] / 2
                    missing.append((sl, [int(cx - r), int(cy - r), int(cx + r), int(cy + r)]))
    return boxes, missing, nvis


def frames():
    seal, gap = sealed()
    for scene, (ss, step) in SESS.items():
        for s in ss:
            sess = f'20260923_{s}_console_v2'
            for p in sorted(glob.glob(str(RAW / sess / 'f*.png')))[::step]:
                fr = int(Path(p).stem[1:])
                if any(abs(fr - q) < gap.get(sess, 0) for q in seal.get(sess, [])):
                    continue
                yield scene, sess, fr, p


def main():
    global DET
    ap = argparse.ArgumentParser(); ap.add_argument('--vis', type=int, default=0)
    a = ap.parse_args()
    DET = create_detector()
    T, n_t = build_template()
    print('배치 틀(정지 장면', n_t, '장 중앙값):', {k: tuple(round(v) for v in T[k]) for k in SLOTS})
    # 문턱 — 정지 장면(선명·5개 모두)에서 정한다
    rims = defaultdict(list); sharp, fills = [], []
    for p in sorted(glob.glob(str(RAW / f'20260923_{TEMPLATE_SESSION}_console_v2/f*.png'))):
        img = cv2.imread(p)
        for n, s, b in tile(img):
            sharp.append(sharpness(img, b))
            if n in ('B3', 'EMO'):
                sn = snap(img, b)
                if sn is not None and color_family(sn['crop'], sn['mask']) == 'red':
                    rims[n].append(rim_score(sn['crop'], sn['mask']))
            sn = snap(img, b)
            if sn is not None and not sn['leak']:
                fills.append(sn['fill'])
    th = {'rim_lo': float(np.median(rims['B3'])), 'rim_hi': float(np.percentile(rims['EMO'], 5)),
          'sharp': float(np.percentile(sharp, 5)) * 0.5, 'fill': float(np.percentile(fills, 2)) * 0.9,
          'margin': 0.15, 'cost': 0.5}
    print('무늬 점수(정지) B3 %.3f~%.3f 중앙 %.3f · EMO %.3f~%.3f' % (
        min(rims['B3']), max(rims['B3']), np.median(rims['B3']), min(rims['EMO']), max(rims['EMO'])))
    print('문턱:', {k: round(float(v), 3) for k, v in th.items()})
    stat = defaultdict(Counter); why = defaultdict(Counter); snapfit = defaultdict(list); vis = []
    miss = Counter(); nframes = Counter(); margins = defaultdict(list); costs = defaultdict(list)
    for scene, sess, fr, p in frames():
        img = cv2.imread(p); boxes, missing, nvis = review(img, T, th)
        g = '1개' if nvis == 1 else '2개' if nvis == 2 else '3개 이상' if nvis >= 3 else '0개'
        nframes[(scene, g)] += 1
        miss[(scene, g)] += len(missing)
        for x in boxes:
            k = (scene, g)
            if x['why']:
                stat[k]['사람'] += 1
                for w in x['why']:
                    why[k][w] += 1
            else:
                stat[k]['기계 확정'] += 1
                if x['snap'] is not None:
                    snapfit[x['name']].append(((x['box'][2] - x['box'][0]) / (x['pre'][2] - x['pre'][0]),
                                               (x['box'][3] - x['box'][1]) / (x['pre'][3] - x['pre'][1])))
        if a.vis and nvis >= 1:
            vis.append((scene, sess, fr, None, None, None, p))
        margins[scene].append(None if not boxes or nvis < 2 else (last_margin[0]))
        costs[scene].append(None if not boxes or nvis < 2 else last_cost[0])
    print('\n장면 · 보이는 버튼 | 사진 | 박스: 기계 확정 / 사람 | 빠진 자리 제안 | 사람에게 넘긴 이유(중복 포함)')
    for k in sorted(nframes, key=lambda k: (list(SESS).index(k[0]), k[1])):
        if k[1] == '0개':
            print(f'{k[0]:5} · {k[1]:6} | {nframes[k]:4} | 버튼 없음'); continue
        print(f"{k[0]:5} · {k[1]:6} | {nframes[k]:4} | {stat[k]['기계 확정']:4} / {stat[k]['사람']:4} | {miss[k]:3} | {dict(why[k].most_common())}")
    print('\n기계 확정 박스의 크기 변화(맞춘 박스 ÷ 초벌 박스, 중앙값 폭·높이):',
          {n: tuple(round(float(np.median([v[i] for v in snapfit[n]])), 2) for i in (0, 1)) for n in snapfit})
    for sc in SESS:
        m = [v for v in margins[sc] if v is not None]
        if m:
            c = [v for v in costs[sc] if v is not None]
            print(f'배치 {sc}: 여유 사분위 {np.percentile(m,25):.2f} 중앙 {np.median(m):.2f} · 비용 중앙 {np.median(c):.3f} 90% {np.percentile(c,90):.3f}')
    if a.vis:
        TPL[:] = [T, th]
        draw_sheet(vis, a.vis)


def draw_sheet(vis, per_scene):
    pick = []
    for scene in SESS:
        cand = [v for v in vis if v[0] == scene]
        step = max(1, len(cand) // per_scene)
        pick += cand[::step][:per_scene]
    tiles = []
    for scene, sess, fr, _i, _b, _m, p in pick:
        img = cv2.imread(p); boxes, missing, _ = review(img, TPL[0], TPL[1])
        im = img.copy()
        for x in boxes:
            col = (0, 200, 0) if not x['why'] else (0, 140, 255)
            b = [int(v) for v in x['box']]
            cv2.rectangle(im, (b[0], b[1]), (b[2], b[3]), col, 2)
            t = x['name'] if not x['why'] else f"{x['name']}? " + ','.join(
                {'배치≠초벌': 'lay', '색≠초벌': 'col', '무늬≠초벌': 'rim', '흐림': 'blur', '가림·모양 이상': 'occ',
                 '박스 맞추기 실패': 'snap', '크기 이상': 'size', '배치 불확실': 'lay?', '버튼 1개': '1btn',
                 '배치상 버튼 아님': 'notbtn'}.get(w, w) for w in x['why'])
            cv2.putText(im, t, (b[0], max(12, b[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2)
        for sl, b in missing:
            cv2.rectangle(im, (b[0], b[1]), (b[2], b[3]), (255, 0, 255), 2)
            cv2.putText(im, sl + ' missing?', (b[0], max(12, b[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)
        cv2.putText(im, f'{sess[16:30]} f{fr}', (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        tiles.append(cv2.resize(im, (384, 512)))
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    cv2.imwrite(str(HERE / 'review_sheet.jpg'), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print('그림 →', HERE / 'review_sheet.jpg')


if __name__ == '__main__':
    main()
