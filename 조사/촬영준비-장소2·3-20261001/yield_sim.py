"""장소1 실제 사진으로 capture_dataset 의 장면별 예상 취득 장수를 잰다(일회용 분석).

① 세션마다 perf 로그의 프레임 시각으로 「I 초마다 1장」을 다시 고른다(촬영 도구와 같은 규칙).
② 묶음 도구(review_batch)와 같은 거름 — 깨짐(seam>0.02·washed>0.25) · 검은 화면(mean<12) · pHash 6 중복.
③ 흐림 후보 = 장소1 묶음 문턱(frame_sharp_thr) 아래 — 지우지 않으나 품질 저하로 따로 센다.
"""
import collections
import csv
import datetime
import glob
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

DEMO = Path("/home/pi/sop-project/Rpi5/Demo")
sys.path.insert(0, str(DEMO / "test")); sys.path.insert(0, str(DEMO))
import cv2                      # noqa: E402
import dedupe_raw               # noqa: E402
import frame_health             # noqa: E402

LB = Path.home() / "data/label_batches"
SHARP_THR = json.load(open(LB / "b009/manifest.json"))["frame_sharp_thr"]
TEST = Path(sys.argv[1])        # 오늘 시운전 세션
P = "20260923_{}_esp32_xga-rt-{}_console_v2"
GROUPS = {
    "s1 정지": [P.format("184709", "s1-r1"), P.format("184732", "s1-r2"), P.format("184758", "s1-r3")],
    "s2 이동": [P.format("184922", "s2-r1"), P.format("184950", "s2-r2"), P.format("185019", "s2-r3")],
    "s6 SOP작업": [P.format("185802", "s6-r1"), P.format("190129", "s6-r2")],
    "공구 자유": ["20260923_193013_esp32_tool-free-r1_console_v2"],
}


def tmap(tag):
    f = DEMO / f"test/logs/{tag}_perf_log.csv"
    out = {}
    for r in csv.DictReader(open(f)):
        h, m, s = r["timestamp"].split(":")
        out[int(r["frame"])] = int(h) * 3600 + int(m) * 60 + float(s)
    return out


def sample(frames, tm, every):
    keep, last = [], None
    for fr in frames:
        t = tm.get(fr)
        if t is None:
            continue
        if last is None or t - last >= every:
            keep.append(fr); last = t
    return keep


def metric(path):
    img = cv2.imread(path)
    seam, washed = frame_health.metrics(Path(path))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return path, {"bad": seam > 0.02 or washed > 0.25, "black": float(img.mean()) < 12,
                  "sharp": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                  "hash": dedupe_raw.phash(img)}


def evaluate(paths, M, dur):
    ok = [p for p in paths if not M[p]["bad"] and not M[p]["black"]]
    uniq_i = dedupe_raw.dedupe([M[p]["hash"] for p in ok], 6)
    uniq = [ok[i] for i in uniq_i]
    blur = sum(M[p]["sharp"] < SHARP_THR for p in uniq)
    return {"sec": round(dur, 1), "saved": len(paths), "quality_ok": len(ok),
            "unique": len(uniq), "blur_in_unique": blur,
            "per_min_saved": round(len(paths) / dur * 60, 1),
            "per_min_unique": round(len(uniq) / dur * 60, 1)}


def main():
    plan = {}                   # (group, every) → (paths, dur)
    need = set()
    for g, tags in GROUPS.items():
        for every in (0.272, 0.2):
            allp, dur = [], 0.0
            for tag in tags:
                tm = tmap(tag)
                pngs = {int(Path(p).stem[1:]): p for p in glob.glob(str(DEMO / f"test/raw/{tag}/f*.png"))}
                keep = sample(sorted(pngs), tm, every)
                allp += [pngs[f] for f in keep]
                dur += max(tm.values()) - min(tm.values())
            plan[(g, every)] = (allp, dur); need |= set(allp)
    tp = sorted(glob.glob(str(TEST / "f*.png")))
    ts = [os.path.getmtime(p) for p in tp]
    plan[("오늘 시운전(실제 도구)", 0.272)] = (tp, ts[-1] - ts[0]); need |= set(tp)

    with Pool(4) as pool:
        M = dict(pool.map(metric, sorted(need), chunksize=16))
    res = {f"{g} @{e}": evaluate(p, M, d) for (g, e), (p, d) in plan.items()}
    # 묶음 도구는 같은 장소 세션 전체를 합쳐 중복을 거른다 — 장면 사이 겹침까지 본다(s1 정지 제외)
    uni = [(g, p) for (g, e), (ps, _) in plan.items() if e == 0.272 and g in GROUPS and g != "s1 정지" for p in ps]
    ok = [(g, p) for g, p in uni if not M[p]["bad"] and not M[p]["black"]]
    keep = dedupe_raw.dedupe([M[p]["hash"] for _, p in ok], 6)
    res["장소 전체 합쳐 중복 제거 @0.272"] = dict(collections.Counter(ok[i][0] for i in keep))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    json.dump(res, open(Path(sys.argv[2]), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
