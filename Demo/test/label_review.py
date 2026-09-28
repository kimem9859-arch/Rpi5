"""버튼 초벌 기계 검토 — 조각 방식 초벌 · 박스 맞추기 · 이름 교차 확인 → 기계 확정 / 사람에게 넘김.

정본 설계 = 상위 sop-project docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §5.1 · §6 · §6-b
시험 근거 = Rpi5 조사/초벌박스-20260928/ · 조사/기계검토-20260928/ (그 시험 코드를 동작 그대로 옮겼다)

🔴 검출은 인자로 받는다 — run(frame) → [(이름, 점수, [x1, y1, x2, y2])]. Hailo 없이 시험하려고.
   실제 초벌은 review_batch.py 가 detector.create_detector() 로 run 을 만든다.
🔴 EDGE_FRAC 는 그대로 쓴다 — 사람 끝선에 맞추는 보정은 하지 않는다(사용자 결정 2026-09-28 · 설계 §6 ①). 알려진 치우침 =
   아래 끝선이 짧다(B1 제외) · B4 위 끝선이 넘친다. 여백을 더하는 쪽으로 바꾸지 않는다.
"""
from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter, defaultdict

import cv2
import numpy as np

SLOTS = ["B1", "B2", "B3", "B4", "EMO"]
FAMILY = {"B1": "yellow", "B2": "white", "B3": "red", "B4": "blue", "EMO": "red"}
EDGE_FRAC = 0.35          # 가장자리 = 버튼 속 색 거리 중앙값의 이 비율(잠정)
MARGIN_MIN = 0.15         # 배치 틀: 「다른 자리 배정」과의 비용 차가 이보다 커야 자리를 믿는다
COST_MAX = 0.5            # 배치 틀: 이보다 나쁜 맞춤은 믿지 않는다
SIZE_RANGE = (0.75, 1.3)  # 맞춘 박스 지름 ÷ 배치 틀이 예상한 지름
ROT_MAX = math.radians(40)
ANISO_MAX = 1.6           # 아핀 변환의 찌그러짐 한도


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def inside(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / max(1, (a[2] - a[0]) * (a[3] - a[1]))


def tile_detect(img, run, tile=True):
    """세로 사진을 가로 모양 두 조각(폭 × 폭·3/4, 위·아래)으로 잘라 각각 검출해 합친다(설계 §5.1).
    합치기 = 같은 클래스가 IoU 0.3 초과면 하나(잘리지 않은 것 → 점수 순) · 잘린 박스가 온전한 박스에 50% 이상 들면 버림.
    tile=False = 사진 통째로 한 번 — 비율 유지 여백 채우기로 배운 새 버튼 모델(spec 2026-09-29-버튼초벌-반복학습 §6)."""
    H, W = img.shape[:2]
    th = W * 3 // 4
    if not tile or H <= th:                       # 통째로 한 번(새 모델) · 조각을 낼 만큼 세로가 길지 않다
        return [(n, s, list(b)) for n, s, b in run(img)]
    out = []
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


def snap(img, box, edge_frac=EDGE_FRAC):
    """박스 둘레 배경색과의 색 거리(Lab) — 오츠로 버튼 속을 찾고 속 거리 중앙값 × edge_frac 을 가장자리로.
    반환 = 버튼 영역의 외접 사각형과 속 찬 정도·배경으로 샌 여부. 실패면 None."""
    x1, y1, x2, y2 = [int(v) for v in box]; w, h = x2 - x1, y2 - y1
    m = int(0.4 * max(w, h)); H, W = img.shape[:2]
    X1, Y1, X2, Y2 = max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m)
    crop = img[Y1:Y2, X1:X2]
    if crop.size == 0:
        return None
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
    ring = np.ones(crop.shape[:2], bool); ring[max(0, y1 - Y1):y2 - Y1, max(0, x1 - X1):x2 - X1] = False
    if ring.sum() < 30:
        return None
    d = np.linalg.norm(lab - np.median(lab[ring], axis=0), axis=2)
    d8 = np.clip(d * 255 / max(float(d.max()), 1.0), 0, 255).astype(np.uint8)
    _, core = cv2.threshold(d8, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if not (core > 0).any():
        return None
    mask = (d8 > edge_frac * float(np.median(d8[core > 0]))).astype(np.uint8)
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
    bx, by, bw, bh, area = (int(v) for v in st[best])      # numpy 정수 → 파이썬 정수(묶음 기록 JSON 에 쓴다)
    leak = bx == 0 or by == 0 or bx + bw >= crop.shape[1] or by + bh >= crop.shape[0]
    fill = area / (math.pi * bw * bh / 4 + 1e-6)
    return {"box": [X1 + bx, Y1 + by, X1 + bx + bw, Y1 + by + bh], "fill": fill, "leak": leak,
            "mask": labm[by:by + bh, bx:bx + bw] == best, "crop": crop[by:by + bh, bx:bx + bw]}


def color_family(crop, mask):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[mask]
    if len(hsv) < 20:
        return None
    h, s, v = np.median(hsv[:, 0]), np.median(hsv[:, 1]), np.median(hsv[:, 2])
    if s < 60 and v > 120:
        return "white"
    if 12 <= h <= 40:
        return "yellow"
    if 90 <= h <= 135:
        return "blue"
    if h < 12 or h > 160:
        return "red"
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
    g = img[max(0, y1):y2, max(0, x1):x2]
    if g.size == 0:
        return 0.0
    return float(cv2.Laplacian(cv2.cvtColor(g, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def _similarity(src, dst):
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    ms, md = src.mean(0), dst.mean(0); a, b = src - ms, dst - md
    den = (a ** 2).sum()
    if den < 1e-9:
        return None
    c = (a * b).sum() / den; s_ = (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() / den
    R = np.array([[c, -s_], [s_, c]])
    return math.hypot(c, s_), math.atan2(s_, c), lambda p: (np.asarray(p, float) - ms) @ R.T + md


def _affine(src, dst):
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    A = np.hstack([src, np.ones((len(src), 1))])
    M, *_ = np.linalg.lstsq(A, dst, rcond=None)
    L = M[:2].T
    det = np.linalg.det(L)
    if det <= 0:
        return None
    sv = np.linalg.svd(L, compute_uv=False)
    if sv[0] / sv[1] > ANISO_MAX:
        return None
    return math.sqrt(det), math.atan2(L[1, 0], L[0, 0]), \
        lambda p: np.hstack([np.asarray(p, float), np.ones((len(p), 1))]) @ M


def fit_layout(T, dets):
    """dets = [(cx, cy, 지름)]. 각 박스를 자리(또는 None = 버튼 아님, 최대 1개)에 배정하는 경우를 모두 맞춰 본다.
    2~3점 = 닮음 변환 · 4점 이상 = 아핀. 여유 = 「어느 박스든 다른 자리로 배정한」 최선과의 비용 차."""
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
        f = _affine(src, dst) if len(idx) >= 4 else _similarity(src, dst)
        if f is None:
            continue
        scale, rot, apply = f
        if abs(rot) > ROT_MAX:
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
    alt = [r[0] for r in results[1:] if any(a and b and a != b for a, b in zip(best[1], r[1]))]
    margin = (alt[0] - best[0]) if alt else 9.0
    return {"cost": best[0], "assign": best[1], "margin": margin, "scale": best[2], "apply": best[3]}


def _diam(b):
    return ((b[2] - b[0]) + (b[3] - b[1])) / 2


def build_template(imgs, run, tile=True):
    """버튼 5개가 한 번씩만 잡힌 사진들에서 맞춘 박스의 중심·지름 중앙값 = 배치 틀(설계 §6 ⑦)."""
    acc = defaultdict(list)
    for img in imgs:
        ds = tile_detect(img, run, tile)
        c = Counter(n for n, _, _ in ds)
        if sorted(c) != SLOTS or max(c.values()) > 1:
            continue
        for n, s, b in ds:
            sn = snap(img, b)
            if sn is None or sn["leak"]:
                continue
            b = sn["box"]
            acc[n].append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, _diam(b)))
    missing = [n for n in SLOTS if not acc[n]]
    if missing:
        raise ValueError(f"배치 틀을 만들 수 없다 — 버튼 5개가 한 번씩 잡힌 사진이 없다(빠진 자리 {missing})")
    return {n: tuple(float(v) for v in np.median(np.array(acc[n]), axis=0)) for n in SLOTS}


def make_thresholds(imgs, run, tile=True):
    """무늬·흐림·속 찬 정도 문턱 — 배치 틀과 같은 정지 장면 사진에서 정한다(설계 §6 ⑦)."""
    rims = defaultdict(list); sharp, fills = [], []
    for img in imgs:
        for n, s, b in tile_detect(img, run, tile):
            sharp.append(sharpness(img, b))
            if n in ("B3", "EMO"):
                sn = snap(img, b)
                if sn is not None and color_family(sn["crop"], sn["mask"]) == "red":
                    rims[n].append(rim_score(sn["crop"], sn["mask"]))
            sn = snap(img, b)
            if sn is not None and not sn["leak"]:
                fills.append(sn["fill"])
    if not rims["B3"] or not rims["EMO"] or not sharp or not fills:
        raise ValueError("문턱을 정할 표본이 없다 — 정지 장면에 B3·EMO 가 보여야 한다")
    return {"rim_lo": float(np.median(rims["B3"])), "rim_hi": float(np.percentile(rims["EMO"], 5)),
            "sharp": float(np.percentile(sharp, 5)) * 0.5, "fill": float(np.percentile(fills, 2)) * 0.9,
            "margin": MARGIN_MIN, "cost": COST_MAX}


def review(img, run, T, th, tile=True):
    """한 장 검토. 박스마다 이유(why)가 비면 기계 확정, 있으면 사람에게(설계 §6 ③)."""
    boxes = []
    for n, s, b in tile_detect(img, run, tile):
        sn = snap(img, b)
        fam = rim = None
        if sn is not None:
            fam = color_family(sn["crop"], sn["mask"])
            if fam == "red":
                rim = rim_score(sn["crop"], sn["mask"])
        box = sn["box"] if sn is not None else list(b)
        boxes.append({"name": n, "score": float(s), "pre": list(b), "snap": sn, "box": box,
                      "fam": fam, "rim": rim, "sharp": sharpness(img, b)})
    dets = [((x["box"][0] + x["box"][2]) / 2, (x["box"][1] + x["box"][3]) / 2, _diam(x["box"])) for x in boxes]
    lay = fit_layout(T, dets) if 2 <= len(boxes) <= 7 else None
    nvis = len(boxes)
    for i, x in enumerate(boxes):
        why = []
        L = lay["assign"][i] if lay else None
        x["layout"] = L
        if nvis < 2:
            why.append("버튼 1개")
        elif lay is None or lay["margin"] < th["margin"] or lay["cost"] > th["cost"]:
            why.append("배치 불확실")
        elif L is None:
            why.append("배치상 버튼 아님")
        elif L != x["name"]:
            why.append("배치≠초벌")
        sn = x["snap"]
        if sn is None or sn["leak"]:
            why.append("박스 맞추기 실패")
            x["box"] = list(x["pre"])      # 샌 사각형은 잘라낸 영역 끝까지 번진다 — 사람에게는 검출기 박스를 보인다(배치 틀 입력 dets 는 그대로)
        else:
            if sn["fill"] < th["fill"]:
                why.append("가림·모양 이상")
            if lay and L:
                exp = lay["scale"] * T[L][2]
                if not (SIZE_RANGE[0] < dets[i][2] / exp < SIZE_RANGE[1]):
                    why.append("크기 이상")
        if x["fam"] != FAMILY[x["name"]]:
            why.append("색≠초벌")
        if x["fam"] == "red" and x["rim"] is not None:
            if (x["name"] == "EMO" and x["rim"] < th["rim_lo"]) or (x["name"] == "B3" and x["rim"] > th["rim_hi"]):
                why.append("무늬≠초벌")
        if x["sharp"] < th["sharp"]:
            why.append("흐림")
        x["why"] = why
    missing = []
    if lay and sum(1 for a in lay["assign"] if a) >= 3:
        H, W = img.shape[:2]
        for sl in SLOTS:
            if sl not in lay["assign"]:
                cx, cy = lay["apply"]([T[sl][:2]])[0]
                if 0 < cx < W and 0 < cy < H:
                    r = lay["scale"] * T[sl][2] / 2
                    missing.append((sl, [int(cx - r), int(cy - r), int(cx + r), int(cy + r)]))
    for x in boxes:          # 큰 배열은 넘기지 않는다
        x.pop("snap", None)
    return {"boxes": boxes, "missing": missing, "nvis": nvis}


def _img_key(img):
    return hashlib.sha1(np.ascontiguousarray(img).tobytes()).hexdigest() + str(img.shape)


def lookup_run(pairs):
    """미리 그린 초벌(rfenv prelabel_tools 의 JSON 모양)을 run 으로 — pairs = (사진, [[이름, 점수, x1, y1, x2, y2], ...]) 반복자.
    사진 바이트로 찾는다(같은 파일을 다시 읽어도 찾는다 · 사진을 붙잡아 두지 않는다).
    🔴 모르는 사진(조각 등)이면 KeyError — tile=True 와 섞어 쓰는 실수를 조용히 넘기지 않는다."""
    table = {_img_key(img): [(r[0], float(r[1]), list(r[2:6])) for r in rows] for img, rows in pairs}

    def run(img):
        k = _img_key(img)
        if k not in table:
            raise KeyError("미리 그린 초벌이 없는 사진 — 조각을 넘겼거나(tile=False 로 불러야 한다) 목록에 없는 사진")
        return [(n, s, list(b)) for n, s, b in table[k]]
    return run
