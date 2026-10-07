"""Task 7 — 오류 분석(설계 §6): 종류 · 장면 · 밝기 · 쥠/놓임 · 크기 · 끝 걸림 · 비슷한 물체 → 오류분석.md + 오류 사진.

실행(python3): python3 analyze.py [--self-test]
🔴 이 칸들은 사후 층화 — 원인 분석에만 쓰고 성능 수치로 인용하지 않는다(수치인용 규칙). 칸 정답 < 10 이면 사진 목록.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

import common as C
from score_lib import confusion, iou, operating_point

EDGE_PX = 2
BANDS = ((0, 83, "83 미만"), (83, 115.0001, "83~115"), (115.0001, 256, "115 초과"))     # 설계 §2.2(장소1 값으로 미리)



def image_status(gt, pred, names):
    """사진 한 장 → ({종류: {정답, 맞음, 놓침, 잘못}}, [(정답, 예측) 오분류]) — score_lib 그대로(설계 §4.4)."""
    one = {"x": ([tuple(g) for g in gt], [tuple(p) for p in pred])}
    op = operating_point(one, names, C.CONF)
    mat = confusion(one, names, C.CONF)
    k = len(names)
    mis = [(names[i], names[j]) for i in range(k) for j in range(k) if i != j and mat[i][j]]
    return {n: {"정답": op[n]["tp"] + op[n]["fn"], "맞음": op[n]["tp"], "놓침": op[n]["fn"], "잘못": op[n]["fp"]} for n in names}, mis


ORDER = ["83 미만", "83~115", "115 초과", "작음", "중간", "큼", "쥠", "놓임", "애매", "끝 걸림", "안쪽", "191017", "공구 없는 사진", "그 밖"]


def cell_key(v):
    """칸 순서 — 어두움 → 밝음 · 작음 → 큼 · 그 밖은 글자순(장면 번호·종류)."""
    return (ORDER.index(v), "") if v in ORDER else (len(ORDER), v)


def band(v):
    return next(lab for lo, hi, lab in BANDS if lo <= v < hi)


def self_test():
    names = C.NAMES["button"]
    gt = [[0, 10, 10, 50, 50], [2, 100, 100, 150, 150]]
    pred = [[0, 0.9, 11, 11, 50, 50], [4, 0.8, 100, 100, 150, 150], [1, 0.7, 300, 300, 340, 340], [3, 0.3, 0, 0, 5, 5]]
    st, mis = image_status(gt, pred, names)
    ok = (st["B1"] == {"정답": 1, "맞음": 1, "놓침": 0, "잘못": 0} and st["B3"]["놓침"] == 1 and st["EMO"]["잘못"] == 1
          and st["B2"]["잘못"] == 1 and st["B4"]["잘못"] == 0 and mis == [("B3", "EMO")])
    ok = ok and band(82.9) == "83 미만" and band(83) == "83~115" and band(115) == "83~115" and band(115.5) == "115 초과"
    print("자체 시험 " + ("✅" if ok else f"❌ {st} {mis}"))
    return 0 if ok else 1



def attrs():
    """사진 이름 → 장면 · 세션 · 밝기(회색 평균) — 밝기는 ~/data/c001채점/밝기.json 에 한 번 계산해 둔다."""
    idx = dict(l.split("\t") for l in (C.PLACE2 / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip())
    bpath = C.W / "밝기.json"
    bright = C.load_json(bpath) if bpath.exists() else {}
    out, scenes = {}, {}
    for s in ("c001", "dark"):
        for n in C.set_names(s):
            sess = Path(idx[n]).parent
            if sess.name not in scenes:
                scenes[sess.name] = C.load_json(sess / "session.json")["scene"]
            if n not in bright:
                bright[n] = float(cv2.cvtColor(cv2.imread(idx[n]), cv2.COLOR_BGR2GRAY).mean())
            out[n] = {"세션": sess.name, "장면": scenes[sess.name], "밝기": band(bright[n])}
    C.write_json(bpath, bright)
    return out


def box_axes(n, g, gt, wh, info, tags, bounds):
    """정답 박스 하나의 칸들 — 종류마다 사진에 많아야 1개라 (사진, 종류)로 박스가 정해진다(설계 §2.1)."""
    c, x1, y1, x2, y2 = gt
    name = C.NAMES[g][int(c)]
    area = (x2 - x1) * (y2 - y1) * (768 / wh[0]) * (1024 / wh[1])       # .pt 늘린 좌표도 원본 픽셀 넓이로
    size = "작음" if area < bounds[0] else "중간" if area < bounds[1] else "큼"
    edge = "끝 걸림" if (x1 <= EDGE_PX or y1 <= EDGE_PX or x2 >= wh[0] - EDGE_PX or y2 >= wh[1] - EDGE_PX) else "안쪽"
    ax = {"종류": name, "장면": info["장면"], "밝기": info["밝기"], "크기": size, "끝": edge,
          "가위 세션": "191017" if info["세션"].startswith("20261006_191017") else "그 밖"}
    if g == "tool":
        ax["쥠/놓임"] = tags.get(f"{n}|{name}", "표시 없음")
    return name, ax


def tally(model_recs, g, info, tags, bounds):
    """모델들(HEF · 시드)의 사진별 기록 → 놓침 {축: {칸: [정답, [모델별 놓침], 놓친 사진, 칸의 사진]}} · 잘못 찾음 {축: {칸: [사진, [모델별]]}}.

    칸(크기 · 끝 등)은 모델 0 의 정답(원본 좌표)으로 (사진, 종류)마다 한 번 정해 모든 모델에 쓴다 —
    .pt 의 늘린 좌표 반올림으로 같은 박스가 다른 칸에 들지 않게(최종 리뷰 M5).
    """
    names = C.NAMES[g]
    T = defaultdict(lambda: defaultdict(lambda: [0, [0] * len(model_recs), set(), set()]))
    F = defaultdict(lambda: defaultdict(lambda: [0, [0] * len(model_recs), set()]))
    for n in model_recs[0]:
        r0 = model_recs[0][n]
        axes = dict(box_axes(n, g, gt, r0.get("wh", [768, 1024]), info[n], tags, bounds) for gt in r0["gt"])
        for name, ax in axes.items():
            for a, v in ax.items():
                T[a][v][0] += 1
                T[a][v][3].add(n)
        for m, rec in enumerate(model_recs):
            st, _mis = image_status(rec[n]["gt"], rec[n]["pred"], names)
            for name, ax in axes.items():
                if st[name]["놓침"]:
                    for a, v in ax.items():
                        T[a][v][1][m] += 1
                        T[a][v][2].add(n)
            fp = sum(st[x]["잘못"] for x in names)
            empty = "공구 없는 사진" if g == "tool" and not rec[n]["gt"] else "그 밖"
            for a, v in (("장면", info[n]["장면"]), ("밝기", info[n]["밝기"]), ("공구 없음", empty),
                         ("가위 세션", "191017" if info[n]["세션"].startswith("20261006_191017") else "그 밖")):
                if m == 0:
                    F[a][v][0] += 1
                F[a][v][1][m] += fp
                if fp:
                    F[a][v][2].add(n)
    return T, F


FEW = 10          # 칸의 사진이 이보다 적으면 비율 대신 사진 목록(설계 §6 · 사진 수 기준 — 최종 리뷰 I1)


def render(title, labels, T, F):
    md = [f"### {title}", "", f"> 칸 = {' · '.join(labels)} 의 놓침(정답 박스 기준) · 잘못 찾음(사진 기준) · "
          f"「적음」 = 칸의 사진 {FEW}장 미만(비율을 읽지 않는다 · 사진 목록)", ""]
    for a, cells in T.items():
        md += [f"#### 놓침 — {a}", "", "| 칸 | 정답 | 사진 | 놓침 | 적음 · 놓친 사진 |", "|---|---|---|---|---|"]
        for v, (tot, miss, imgs, allimgs) in sorted(cells.items(), key=lambda kv: cell_key(kv[0])):
            few = len(allimgs) < FEW
            md.append(f"| {v} | {tot} | {len(allimgs)} | {' · '.join(map(str, miss))} | "
                      f"{('적음' + (' — ' + ', '.join(sorted(imgs)) if imgs else '')) if few else ''} |")
        md.append("")
    for a, cells in F.items():
        md += [f"#### 잘못 찾음 — {a}", "", "| 칸 | 사진 | 잘못 찾음 | 적음 · 잘못 찾은 사진 |", "|---|---|---|---|"]
        md += [f"| {v} | {tot} | {' · '.join(map(str, fp))} | {('적음' + (' — ' + ', '.join(sorted(imgs)) if imgs else '')) if tot < FEW else ''} |"
               for v, (tot, fp, imgs) in sorted(cells.items(), key=lambda kv: cell_key(kv[0]))] + [""]
    return md


def ser(T, F):
    return {"놓침": {a: {v: {"정답": t, "놓침": m, "사진": sorted(i), "사진수": len(al)} for v, (t, m, i, al) in c.items()} for a, c in T.items()},
            "잘못": {a: {v: {"사진": t, "잘못": f, "잘못사진": sorted(i)} for v, (t, f, i) in c.items()} for a, c in F.items()}}


def overlay(n, set_name, rec, g):
    im = cv2.imread(str(C.set_dir(set_name) / "orig" / f"{n}.png"))
    names = C.NAMES[g]
    for c, x1, y1, x2, y2 in rec["gt"]:
        cv2.rectangle(im, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 0), 3)
        cv2.putText(im, names[int(c)], (int(x1), max(15, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
    for c, s, x1, y1, x2, y2 in rec["pred"]:
        if s < C.CONF:
            continue
        hit = any(int(gc) == int(c) and iou((x1, y1, x2, y2), (gx1, gy1, gx2, gy2)) >= 0.5 for gc, gx1, gy1, gx2, gy2 in rec["gt"])
        col = (255, 120, 0) if hit else (0, 0, 255)
        cv2.rectangle(im, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
        cv2.putText(im, f"{names[int(c)]} {s:.2f}", (int(x1), min(im.shape[0] - 5, int(y2) + 22)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    cv2.putText(im, f"{set_name} {n}", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return cv2.resize(im, (384, 512))


def sheets(hef_name, g, items):
    """오류 사진(놓침 · 잘못 · 오분류가 하나라도) → 3 × 2 모음 — 초록 = 정답 · 파랑 = 맞은 예측 · 빨강 = 틀린 예측."""
    out = C.W / "오류사진" / hef_name
    out.mkdir(parents=True, exist_ok=True)
    tiles = [overlay(n, s, rec, g) for s, n, rec in items]
    for k in range(0, len(tiles), 6):
        t = tiles[k:k + 6] + [np.zeros_like(tiles[0])] * (6 - len(tiles[k:k + 6]))
        cv2.imwrite(str(out / f"sheet_{k // 6 + 1:02d}.jpg"), np.vstack([np.hstack(t[:3]), np.hstack(t[3:])]), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return (len(tiles) + 5) // 6


def main():
    info = attrs()
    tags = C.load_json(C.HERE / "쥠놓임.json")["표시"]
    bounds = C.load_json(C.W / "prep.json")["크기경계"]
    md = ["# c001 오류 분석 (자동 생성 — analyze.py)", "",
          "> 🔴 사후 층화 — 원인 분석용 · 성능 수치로 인용하지 않는다. 운용점 0.65 · IoU 0.5 · 밝기 칸 경계 83 · 115(설계 §2.2) · 크기 경계 = c001 정답 넓이 3등분(prep.json).", ""]
    js = {}
    for hname, sname in (("B-full-base-s0_ours-L2", "B-full-base"), ("T-full-base-albu-s0_ours-L2", "T-full-base-albu")):
        g = C.setting(sname)[1]
        h = {s: C.load_json(C.W / "out" / "hef" / s / f"{hname}.json")["사진별"] for s in ("c001", "dark")}
        pts = [C.load_json(C.W / "out" / "pt" / "c001" / f"{i}.json")["사진별"] for i in C.setting(sname)[2]]
        md += [f"## {sname}", ""]
        models = [f"HEF {hname}"] + [f".pt {i}" for i in C.setting(sname)[2]]
        T, F = tally([h["c001"]] + pts, g, info, tags, bounds[g])
        md += render(f"c001 {len(h['c001'])}장", models, T, F)
        js[sname] = {"모델": models, "c001": ser(T, F)}
        T, F = tally([h["dark"]], g, info, tags, bounds[g])
        md += render("보조 22장(참고)", [f"HEF {hname}"], T, F)
        js[sname]["dark"] = ser(T, F)
        items = []
        for s in ("c001", "dark"):
            for n, rec in h[s].items():
                st, mis = image_status(rec["gt"], rec["pred"], C.NAMES[g])
                if mis or any(v["놓침"] or v["잘못"] for v in st.values()):
                    items.append((s, n, rec))
        k = sheets(hname, g, items) if items else 0
        md += [f"- 오류 사진 {len(items)}장 → `~/data/c001채점/오류사진/{hname}/sheet_01~{k:02d}.jpg`(Claude 가 보고 결과.md 「오류 유형」에)", ""]
    (C.HERE / "오류분석.md").write_text("\n".join(md), encoding="utf-8")
    C.write_json(C.HERE / "오류분석.json", js)
    print("오류분석.md · 오류분석.json 저장")
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    sys.exit(self_test() if a.self_test else main())
