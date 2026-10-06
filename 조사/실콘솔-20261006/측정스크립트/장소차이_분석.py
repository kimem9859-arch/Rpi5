"""장소1 ↔ 장소2 환경 차이 정량화 (읽기 전용 분석 · 2026-10-07 · 세션 76dd2d3d).

쓰는 법: python3 장소차이_분석.py <출력.json>   (약 45초 · 파이5 4코어)
결과·해석·한계 = ../README.md 「장소1 ↔ 장소2 환경 차이」 절.

판정 기준(계산 전에 고정):
  지표 하나를 「장소 차이」로 인정 = 같은 장면끼리
    ① 두 장소의 세션 중앙값 범위가 겹치지 않고
    ② AUC(장소2 한 장 > 장소1 한 장일 확률) ≥ 0.9 또는 ≤ 0.1
  종합 ① 처음 보는 세션 장소 맞히기(세션 하나 빼고 최근접 중심 · 7지표 · 어두움 뺀 6지표) 정확도
  종합 ② 색 분포 거리 — 장소 간 세션 쌍 최솟값 > 장소 안 세션 쌍 최댓값
"""
import glob, json, os, sys
from multiprocessing import Pool
import cv2
import numpy as np

RAW = "/home/pi/sop-project/Rpi5/Demo/test/raw"
CAP = "/home/pi/data/capture"
MAXN = 300

# (장소, 장면, 세션 이름, 폴더)
S = []
for r in (1, 2, 3):
    S.append(("P1", "정지", f"s1-r{r}", glob.glob(f"{RAW}/20260923_*xga-rt-s1-r{r}_*")[0]))
    S.append(("P1", "좌우·콘솔", f"s2-r{r}", glob.glob(f"{RAW}/20260923_*xga-rt-s2-r{r}_*")[0]))
for r in (1, 2):
    S.append(("P1", "누르기", f"s6-r{r}", glob.glob(f"{RAW}/20260923_*xga-rt-s6-r{r}_*")[0]))
S.append(("P1", "공구", "tool-r1", glob.glob(f"{RAW}/20260923_*tool-free-r1_*")[0]))
SCENE2 = {"0": "정지", "1": "좌우·콘솔", "2": "누르기", "3": "가림", "4": "머리움직임", "6": "공구"}
for d in sorted(glob.glob(f"{CAP}/20261006_*_장소2_*")):
    b = os.path.basename(d)
    sc = b.rsplit("_", 1)[1]
    if b.startswith("20261006_191942"):
        S.append(("P2dark", "어두움", "dark-" + b[9:15], d))
    else:
        S.append(("P2", SCENE2[sc], f"c{sc}-{b[9:15]}", d))


def frame_stats(path):
    im = cv2.imread(path)
    im = cv2.resize(im, (im.shape[1] // 2, im.shape[0] // 2), interpolation=cv2.INTER_AREA)
    y = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    st = dict(
        밝기=float(y.mean()),
        대비=float(y.std()),
        흰뭉갬=float((y >= 250).mean() * 100),
        어두움=float((y <= 20).mean() * 100),
        채도=float(hsv[..., 1].mean()),
        색감_노랑=float(lab[..., 2].mean() - 128),  # + 노랑 / - 파랑
        색감_빨강=float(lab[..., 1].mean() - 128),  # + 빨강 / - 초록
    )
    h = cv2.calcHist([hsv], [0, 1], None, [30, 16], [0, 180, 0, 256])
    return st, h


def session(args):
    place, scene, name, d = args
    fs = sorted(glob.glob(d + "/*.png"))
    idx = np.linspace(0, len(fs) - 1, min(MAXN, len(fs))).round().astype(int)
    rows, H = [], None
    for i in sorted(set(idx)):
        st, h = frame_stats(fs[i])
        rows.append(st)
        H = h if H is None else H + h
    H = H / H.sum()
    return dict(place=place, scene=scene, name=name, dir=d, n_total=len(fs), rows=rows, hist=H)


def auc(a, b):  # P(b > a) + 0.5 P(=)
    a, b = np.asarray(a), np.asarray(b)
    allv = np.concatenate([a, b])
    ranks = allv.argsort().argsort().astype(float) + 1
    # 동점 평균 순위
    _, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, ranks)
    ranks = (sums / cnt)[inv]
    rb = ranks[len(a):].sum()
    return (rb - len(b) * (len(b) + 1) / 2) / (len(a) * len(b))


if __name__ == "__main__":
    with Pool(4) as p:
        R = p.map(session, S)
    KEYS = list(R[0]["rows"][0].keys())
    out = {"sessions": [], "criteria": __doc__}
    for s in R:
        med = {k: float(np.median([r[k] for r in s["rows"]])) for k in KEYS}
        out["sessions"].append(dict(place=s["place"], scene=s["scene"], name=s["name"], n_used=len(s["rows"]), n_total=s["n_total"], median=med))

    # 1) 장면별 비교
    print("== 장면별 (세션 중앙값 범위 · AUC = 장소2 한 장이 장소1 한 장보다 클 확률)")
    scene_res = {}
    for sc in ["정지", "좌우·콘솔", "누르기", "공구", "전체"]:
        A = [s for s in R if s["place"] == "P1" and (sc == "전체" or s["scene"] == sc)]
        B = [s for s in R if s["place"] == "P2" and (sc == "전체" or s["scene"] == sc)]
        if not A or not B:
            continue
        print(f"-- {sc}  장소1 세션 {len(A)}개 {sum(len(s['rows']) for s in A)}장 · 장소2 세션 {len(B)}개 {sum(len(s['rows']) for s in B)}장")
        scene_res[sc] = {}
        for k in KEYS:
            ma = [np.median([r[k] for r in s["rows"]]) for s in A]
            mb = [np.median([r[k] for r in s["rows"]]) for s in B]
            va = [r[k] for s in A for r in s["rows"]]
            vb = [r[k] for s in B for r in s["rows"]]
            u = auc(va, vb)
            sep = max(ma) < min(mb) or max(mb) < min(ma)
            ok = sep and (u >= 0.9 or u <= 0.1)
            scene_res[sc][k] = dict(p1_med=float(np.median(va)), p2_med=float(np.median(vb)), p1_rng=[float(min(ma)), float(max(ma))], p2_rng=[float(min(mb)), float(max(mb))], auc=float(u), sep=bool(sep), diff=bool(ok))
            print(f"   {k:6s} 장소1 {np.median(va):7.2f} [{min(ma):7.2f}~{max(ma):7.2f}]  장소2 {np.median(vb):7.2f} [{min(mb):7.2f}~{max(mb):7.2f}]  AUC {u:.3f}  {'차이 ✅' if ok else ('범위 분리' if sep else '겹침')}")
    out["scene"] = scene_res

    # 2) 처음 보는 세션 장소 맞히기 (최근접 중심 · 표준화) — 7지표 · 어두움 뺀 6지표
    PR = [s for s in R if s["place"] in ("P1", "P2")]
    allv = {k: [r[k] for s in PR for r in s["rows"]] for k in KEYS}
    print("== 지표별 프레임 최솟값~최댓값:", {k: (round(min(v), 3), round(max(v), 3)) for k, v in allv.items()})

    def loso(keys):
        X = {s["name"]: np.array([[r[k] for k in keys] for r in s["rows"]]) for s in PR}
        correct = total = 0
        per = []
        for s in PR:
            tr = [t for t in PR if t is not s]
            allx = np.concatenate([X[t["name"]] for t in tr])
            mu, sd = allx.mean(0), allx.std(0) + 1e-9
            c1 = ((np.concatenate([X[t["name"]] for t in tr if t["place"] == "P1"]) - mu) / sd).mean(0)
            c2 = ((np.concatenate([X[t["name"]] for t in tr if t["place"] == "P2"]) - mu) / sd).mean(0)
            z = (X[s["name"]] - mu) / sd
            pred = np.where(((z - c2) ** 2).sum(1) < ((z - c1) ** 2).sum(1), "P2", "P1")
            per.append((s["place"], s["name"], s["scene"], float((pred == s["place"]).mean())))
            correct += int((pred == s["place"]).sum())
            total += len(pred)
        return correct, total, per

    out["loso"] = {}
    for tag, keys in (("7지표", KEYS), ("6지표(어두움 뺌)", [k for k in KEYS if k != "어두움"])):
        correct, total, per = loso(keys)
        print(f"== 처음 보는 세션 장소 맞히기 {tag}: {correct}/{total} = {100*correct/total:.1f}%")
        for p in per:
            print(f"   {p[0]} {p[1]:16s} {p[2]:8s} {100*p[3]:5.1f}%")
        out["loso"][tag] = dict(correct=correct, total=total, per=per)

    # 3) 색 분포 거리 (H×S 히스토그램 · 바타차리야 0=같음 1=완전히 다름)
    D = []
    for i, a in enumerate(PR):
        for b in PR[i + 1:]:
            d = cv2.compareHist(a["hist"].astype(np.float32), b["hist"].astype(np.float32), cv2.HISTCMP_BHATTACHARYYA)
            kind = "같은 장소" if a["place"] == b["place"] else "다른 장소"
            same_scene = a["scene"] == b["scene"]
            D.append((kind, same_scene, a["place"], a["name"], b["name"], float(d)))
    for kind in ("같은 장소", "다른 장소"):
        v = [x[5] for x in D if x[0] == kind]
        print(f"== 색 분포 거리 {kind}: 쌍 {len(v)} · 최소 {min(v):.3f} · 중앙 {np.median(v):.3f} · 최대 {max(v):.3f}")
    for pl in ("P1", "P2"):
        v = [x[5] for x in D if x[0] == "같은 장소" and x[2] == pl]
        print(f"   같은 장소 {pl}: 최소 {min(v):.3f} · 중앙 {np.median(v):.3f} · 최대 {max(v):.3f}")
    v = [x[5] for x in D if x[0] == "다른 장소" and x[1]]
    print(f"   다른 장소 · 같은 장면끼리: 최소 {min(v):.3f} · 중앙 {np.median(v):.3f} · 최대 {max(v):.3f}")
    out["hist_pairs"] = D

    # 어두운 조명 세션 (참고)
    dk = [s for s in R if s["place"] == "P2dark"][0]
    print("== 참고 장소2 어두운 조명:", {k: round(float(np.median([r[k] for r in dk["rows"]])), 2) for k in KEYS})
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
