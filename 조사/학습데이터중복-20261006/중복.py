"""공구 학습 사진의 「거의 같은 사진」 비율 — 라벨 박스로 센다(사진 비교 없음 · 읽기 전용).

같다의 정의: 공구 종류·개수가 같고, 이름별로 짝지은 박스가 모두 IoU ≥ 문턱(0.7 · 0.8 · 0.9).
- ① 학습 사진(place1_v1 공구 학습 몫 · 공구 있는 사진) 안에서 서로
- ② b010(사람 검토 라벨 · place1_v1 밖)이 ① 과 겹치는 비율
- ③ b011~b014(검토 전 · tool_r2 초벌 박스로 대신)이 ① 과 겹치는 비율
공구 없는 배경 사진은 박스가 없어 셈에서 뺀다. 좌표는 0~1 정규화(가로세로 같은 배율이라 IoU 불변).
사용: python3 중복.py
"""
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo/test")
import tool_round as TR  # noqa: E402  group_lines — 8종 라벨에서 공구 줄만

H = Path.home()
SRC = H / "data/label_dataset/place1"
NAMES = ["driver", "wrench", "pliers"]
SPLIT = json.load(open("/home/pi/sop-project/Rpi5/학습/나눔/place1_v1.json", encoding="utf-8"))
THRS = (0.7, 0.8, 0.9)


def yolo_boxes(n):
    """사람 라벨(8종) → [(이름, x1, y1, x2, y2)] 공구만."""
    out = []
    for line in TR.group_lines((SRC / "labels" / f"{n}.txt").read_text(encoding="utf-8").splitlines(), "tool"):
        c, cx, cy, w, h = line.split()
        cx, cy, w, h = map(float, (cx, cy, w, h))
        out.append((NAMES[int(c)], cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    return out


def draft_boxes(path):
    """초벌 JSON(X-AnyLabeling) → 공구만 정규화."""
    d = json.load(open(path, encoding="utf-8"))
    W, Hh = d["imageWidth"], d["imageHeight"]
    out = []
    for s in d.get("shapes", []):
        if s.get("label") in NAMES:
            xs = [p[0] for p in s["points"]]
            ys = [p[1] for p in s["points"]]
            out.append((s["label"], min(xs) / W, min(ys) / Hh, max(xs) / W, max(ys) / Hh))
    return out


def iou(a, b):
    x1, y1, x2, y2 = max(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3]), min(a[4], b[4])
    i = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = (a[3] - a[1]) * (a[4] - a[2]) + (b[3] - b[1]) * (b[4] - b[2]) - i
    return i / u if u > 0 else 0.0


def min_match_iou(A, B):
    """같은 이름끼리 탐욕 짝짓기 · 종류·개수가 다르면 0 · 같으면 짝 IoU 의 최솟값."""
    if sorted(x[0] for x in A) != sorted(x[0] for x in B):
        return 0.0
    worst = 1.0
    for name in set(x[0] for x in A):
        a = [x for x in A if x[0] == name]
        b = [x for x in B if x[0] == name]
        pairs = sorted(((iou(p, q), i, j) for i, p in enumerate(a) for j, q in enumerate(b)), reverse=True)
        ua, ub, got = set(), set(), []
        for v, i, j in pairs:
            if i not in ua and j not in ub:
                ua.add(i); ub.add(j); got.append(v)
        worst = min(worst, min(got))
    return worst


def ses(n):
    return n.split("__f")[0]


def frame(n):
    return int(n.split("__f")[1])


def best_match(B, pool, n=None):
    """pool 에서 B 와 짝 IoU 최솟값이 가장 큰 사진 (값, 이름). n = 자기 자신 제외."""
    best = (0.0, None)
    for m, A in pool.items():
        if m == n:
            continue
        v = min_match_iou(A, B)
        if v > best[0]:
            best = (v, m)
    return best


def summarize(label, items, pool):
    res = {t: 0 for t in THRS}
    dists = []
    for n, B in items.items():
        v, m = best_match(B, pool, n)
        for t in THRS:
            if v >= t:
                res[t] += 1
        if v >= 0.8 and ses(m) == ses(n):
            dists.append(abs(frame(m) - frame(n)))
    tot = len(items)
    print(f"{label}: 공구 있는 사진 {tot}장 — 거의 같은 사진이 있는 비율 " +
          " · ".join(f"IoU≥{t} {res[t]}장({res[t] / tot * 100:.0f}%)" for t in THRS))
    if dists:
        ds = sorted(dists)
        print(f"   IoU≥0.8 짝의 프레임 거리(같은 세션) 중앙값 {ds[len(ds) // 2]} · 10프레임 이내 {sum(d <= 10 for d in ds)}/{len(ds)}")
    return res


def groups(pool, t=0.8):
    """IoU≥t 로 이어지는 무리 수 = 「사실상 다른 장면」 대략값."""
    names = list(pool)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if ses(a) == ses(b) and min_match_iou(pool[a], pool[b]) >= t:
                parent[find(a)] = find(b)
    return len({find(n) for n in names})


def main():
    train = {n: yolo_boxes(n) for n in SPLIT["tool"]["train"]}
    bg = sum(1 for v in train.values() if not v)
    pool = {n: v for n, v in train.items() if v}
    print(f"학습 몫 {len(train)}장(배경 {bg}) · 공구 있는 사진 {len(pool)}장 · 세션 {dict(Counter(ses(n) for n in pool))}")
    summarize("① 학습 사진끼리", pool, pool)
    for t in THRS:
        print(f"   IoU≥{t} 로 이은 무리 수(사실상 다른 장면 대략) = {groups(pool, t)} / {len(pool)}")

    used = set().union(*[set(v) for v in SPLIT["공통"].values()], *[set(v) for v in SPLIT["tool"].values()],
                       *[set(v) for v in SPLIT["button"].values()])
    idx = [l.split("\t")[0] for l in (SRC / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    b010 = {n: yolo_boxes(n) for n in idx if n not in used}
    b010 = {n: v for n, v in b010.items() if v}
    summarize("② b010(사람 검토 · 나눔 밖)", b010, pool)

    drafts = {}
    for b in ("b011", "b012", "b013", "b014"):
        for f in glob.glob(str(H / f"data/label_batches/{b}/images/*.json")):
            n = "__".join(Path(f).stem.split("__")[-2:])
            v = draft_boxes(f)
            if v:
                drafts[n] = v
    summarize("③ b011~b014(tool_r2 초벌 박스 · 검토 전 · 참고)", drafts, pool)



def per_box(label, items, pool):
    """박스마다 — 시간상 가장 가까운 학습 사진(같은 세션)의 같은 이름 박스와 IoU 최댓값 · 중심 이동(박스 크기 대비)."""
    by = {}
    for m in pool:
        by.setdefault(ses(m), []).append(m)
    ious, shifts, fd = [], [], []
    for n, B in items.items():
        cand = by.get(ses(n), [])
        if not cand:
            continue
        m = min(cand, key=lambda x: abs(frame(x) - frame(n)) if x != n else 10**9)
        fd.append(abs(frame(m) - frame(n)))
        for b in B:
            same = [a for a in pool[m] if a[0] == b[0]]
            if not same:
                ious.append(0.0); continue
            a = max(same, key=lambda a: iou(a, b))
            ious.append(iou(a, b))
            w = max(b[3] - b[1], 1e-6); h = max(b[4] - b[2], 1e-6)
            shifts.append(((((a[1] + a[3]) - (b[1] + b[3])) / 2 / w) ** 2 + (((a[2] + a[4]) - (b[2] + b[4])) / 2 / h) ** 2) ** 0.5)
    q = lambda xs, p: sorted(xs)[int(len(xs) * p)]
    print(f"{label}: 박스 {len(ious)}개 · 가장 가까운 학습 사진까지 프레임 중앙값 {q(fd, .5)} — "
          f"짝 IoU 중앙값 {q(ious, .5):.2f} (25%·75% = {q(ious, .25):.2f}·{q(ious, .75):.2f}) · 짝 없음 {sum(v == 0 for v in ious)} · "
          f"중심 이동 중앙값 = 박스 크기의 {q(shifts, .5) * 100:.0f}%")



if __name__ == "__main__":
    main()
    train = {n: yolo_boxes(n) for n in SPLIT["tool"]["train"]}
    pool = {n: v for n, v in train.items() if v}
    used = set().union(*[set(v) for v in SPLIT["공통"].values()], *[set(v) for v in SPLIT["tool"].values()],
                       *[set(v) for v in SPLIT["button"].values()])
    idx = [l.split("\t")[0] for l in (SRC / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    b010 = {n: v for n in idx if n not in used for v in [yolo_boxes(n)] if v}
    drafts = {}
    for b in ("b011", "b012", "b013", "b014"):
        for f in glob.glob(str(H / f"data/label_batches/{b}/images/*.json")):
            n = "__".join(Path(f).stem.split("__")[-2:])
            v = draft_boxes(f)
            if v:
                drafts[n] = v
    print("--- 박스 단위")
    per_box("① 학습 사진 ↔ 가장 가까운 다른 학습 사진", pool, pool)
    per_box("② b010 ↔ 가장 가까운 학습 사진", b010, pool)
    per_box("③ b011~b014(초벌) ↔ 가장 가까운 학습 사진", drafts, pool)
