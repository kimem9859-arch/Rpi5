"""Task 1 — 작업 폴더 · 라벨 고정 · 무리별 라벨 · 늘린 사진 · 크기 경계 · 관문 ③④⑤ (설계 §4.7 · §6).

실행(시스템 python3): python3 prep.py [--refreeze]
출력: ~/data/c001채점/sets/<c001|dark|place1_292>/ · ~/data/c001채점/prep.json
종료 코드 0 = 관문 ③④⑤ 모두 통과 · 1 = 하나라도 실패(중단 규칙 ①).
🔒 이 폴더에 라벨고정.json 이 있으면 지금 라벨을 그 고정본과 먼저 대조하고, 다르면 작업 폴더를 건드리지 않고 멈춘다.
   라벨을 바꿔 다시 채점할 때만(예: c001_2 회수 뒤) --refreeze — 그 뒤 채점은 모두 --force 로 다시(README §6 · 최종 리뷰 I2).
"""
import argparse
import datetime
import hashlib
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

import common as C
import split as SP


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def set_lists():
    """묶음 → (이름 목록, {이름: (원본 사진, 8종 라벨)})."""
    man = C.load_json(C.C001_MANIFEST)
    c001 = sorted(e["file"][len("s_score__"):-len(".png")] for e in man["images"])
    idx = dict(l.split("\t") for l in (C.PLACE2 / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip())
    dark = sorted(n for n, p in idx.items() if Path(p).parent.name == C.DARK_SESSION)
    src2 = {n: (Path(idx[n]), C.PLACE2 / "labels" / f"{n}.txt") for n in set(c001) | set(dark)}
    d1 = SP.load_split(C.LEARN / "나눔" / "place1_v1.json")
    p1 = sorted(d1["공통"]["test"])
    src1 = {n: ((C.STAGE1 / "images" / f"{n}.png").resolve(), C.STAGE1 / "labels8" / f"{n}.txt") for n in p1}
    return {"c001": (c001, src2), "dark": (dark, src2), "place1_292": (p1, src1)}


def source_shas(lists):
    """묶음 → {이름: 지금 라벨 파일 sha256} — 작업 폴더를 만들기 전에 고정본과 대조한다."""
    return {s: {n: sha(src[n][1]) for n in names if src[n][1].exists()} for s, (names, src) in lists.items()}


def freeze_problems(new, frozen):
    """다시 실행할 때 — 고정본(라벨고정.json)과 이름·내용이 다른 라벨 목록(설계 §2.1 🔒 · 최종 리뷰 I2)."""
    probs = [f"{n} 라벨 내용이 고정본과 다름" for n in sorted(set(new) & set(frozen)) if new[n] != frozen[n]]
    probs += [f"{n} 고정본에 있는데 지금 없음" for n in sorted(set(frozen) - set(new))]
    probs += [f"{n} 고정본에 없는 새 라벨" for n in sorted(set(new) - set(frozen))]
    return probs


def split_line(line):
    """8종 줄 → (무리, 무리 번호 줄) — 버튼 0~4 · 공구 5·6·7 → 0·1·2(설계 §4.3)."""
    c, *rest = line.split()
    name = C.NAMES8[int(c)]
    g = "button" if name in C.NAMES["button"] else "tool"
    return g, " ".join([str(C.NAMES[g].index(name)), *rest])


def build(set_name, names, src):
    sd = C.set_dir(set_name)
    if sd.exists():
        shutil.rmtree(sd)
    for sub in ("orig", "s640", "labels8", "labels_button", "labels_tool"):
        (sd / sub).mkdir(parents=True)
    (sd / "names.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    shas, probs, boxes = {}, [], Counter()
    for n in names:
        img, lab = src[n]
        if not lab.exists():
            probs.append(f"{set_name} {n} 라벨 없음")
            continue
        im = cv2.imread(str(img))
        if im is None or im.shape[:2] != (1024, 768):
            probs.append(f"{set_name} {n} 사진 크기 {None if im is None else im.shape}")
            continue
        os.symlink(img, sd / "orig" / f"{n}.png")
        cv2.imwrite(str(sd / "s640" / f"{n}.png"), cv2.resize(im, (640, 640)))   # train_one.py 136 · detector.py 115 와 같은 늘리기
        shutil.copyfile(lab, sd / "labels8" / f"{n}.txt")
        shas[n] = sha(sd / "labels8" / f"{n}.txt")
        out = {"button": [], "tool": []}
        for line in (sd / "labels8" / f"{n}.txt").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = int(line.split()[0])
            if not 0 <= c < len(C.NAMES8):
                probs.append(f"{set_name} {n} 라벨 번호 {c}(범위 밖)")
                continue
            g, l2 = split_line(line)
            out[g].append(l2)
            boxes[C.NAMES8[c]] += 1
        for g, lines in out.items():
            (sd / f"labels_{g}" / f"{n}.txt").write_text("".join(x + "\n" for x in lines), encoding="utf-8")
    return shas, probs, boxes


def gate3(lists, built):
    probs = []
    for s, want in (("c001", 194), ("dark", 22), ("place1_292", 292)):
        if len(lists[s][0]) != want:
            probs.append(f"{s} 사진 {len(lists[s][0])} ≠ {want}")
        probs += built[s][1]
    if dict(built["c001"][2]) != C.C001_BOXES:
        probs.append(f"c001 박스 구성 {dict(built['c001'][2])} ≠ 설계 §2.1 {C.C001_BOXES}")
    for s in lists:                                   # 무리별 폴더의 번호 범위(설계 §4.3 🔴)
        for g in C.NAMES:
            for f in (C.set_dir(s) / f"labels_{g}").glob("*.txt"):
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip() and not 0 <= int(line.split()[0]) < len(C.NAMES[g]):
                        probs.append(f"{s} labels_{g}/{f.name} 번호 범위 밖")
    return probs


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def gate4(lists):
    probs = []
    splits = {C.load_json(C.RESULTS / i / "요약.json")["나눔"]["name"] for i in C.all_ids()}
    for sp in sorted(splits):
        leaked = [x for x in _strings(C.load_json(C.LEARN / "나눔" / f"{sp}.json")) if x.startswith("1006-")]
        if leaked:
            probs.append(f"나눔 {sp} 에 장소2 이름 {len(leaked)}개")
    for s in ("c001", "dark"):
        if not all(n.startswith("1006-") for n in lists[s][0]):
            probs.append(f"{s} 에 장소2 아닌 이름")
    if any(n.startswith("1006-") for n in lists["place1_292"][0]):
        probs.append("place1_292 에 장소2 이름")
    return probs, sorted(splits)


def gate5():
    probs = []
    for i in C.all_ids():
        rec = C.load_json(C.RESULTS / i / "요약.json").get("best_sha256")
        if sha(C.MODELS / i / "best.pt") != rec:
            probs.append(f"{i} best.pt sha256 ≠ 요약.json")
    for name, path, _g, pair, _s in C.HEFS:
        v = C.RESULTS / pair / "변환.json"
        rec = C.load_json(v if v.exists() else C.MODELS / pair / "변환.json")["해시"]["model.hef"]
        if sha(path) != rec:
            probs.append(f"{name} sha256 ≠ 변환.json")
    return probs


def size_bounds():
    """설계 §6 박스 크기 3등분 — c001 정답 박스 넓이(768×1024 픽셀)로 무리마다 미리 정한다."""
    out = {}
    for g in C.NAMES:
        areas = []
        for n in C.set_names("c001"):
            for line in (C.set_dir("c001") / f"labels_{g}" / f"{n}.txt").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    _c, _cx, _cy, bw, bh = map(float, line.split())
                    areas.append(bw * 768 * bh * 1024)
        out[g] = [float(np.percentile(areas, 100 / 3)), float(np.percentile(areas, 200 / 3))]
    return out


def train_composition():
    """설계 §3.4 — 설정마다 학습 사진 · 배경 · 박스 구성 · 라벨 지문(실행 때 다시 확인) · HEF 보정 장수."""
    import train_one as TO
    out = {}
    for name, g, ids, _use in C.SETTINGS:
        sus = [C.load_json(C.RESULTS / i / "요약.json") for i in ids]
        sp = sus[0]["나눔"]["name"]
        d = SP.load_split(C.LEARN / "나눔" / f"{sp}.json")
        tr, va, te = SP.lists_for(d, g)
        job = {"원본": str(C.STAGE1), "group": g,
               "나눔": {"train": tr, "val": va, "test": te, "test_session": SP.session_test(d, g)}}
        fp = TO.source_fingerprint(job)
        box, bg = Counter(), 0
        for n in tr:
            lines = [l for l in (C.STAGE1 / f"labels_{g}" / f"{n}.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
            bg += not lines
            box.update(C.NAMES[g][int(l.split()[0])] for l in lines)
        recs = [s.get("라벨지문") for s in sus]
        out[name] = {"무리": g, "나눔": sp, "학습": len(tr), "배경": bg, "학습중검증": len(va), "채점": len(te),
                     "세션채점": len(job["나눔"]["test_session"]), "박스": {k: box[k] for k in C.NAMES[g]},
                     "라벨확인": "같음" if all(r == fp for r in recs) else "기록 전" if all(r is None for r in recs) else "다름"}
    calib = {}
    for hname, _path, _g, pair, _s in C.HEFS:
        v = C.RESULTS / pair / "변환.json"
        b = C.load_json(v if v.exists() else C.MODELS / pair / "변환.json")["보정"]
        calib[hname] = {"장수": b["장수"], "나눔": b["나눔"], "몫": b["몫"]}
    return out, calib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refreeze", action="store_true", help="라벨이 바뀐 것을 알고 새로 고정한다(그 뒤 채점은 --force)")
    a = ap.parse_args()
    lists = set_lists()
    frozen_path = C.HERE / "라벨고정.json"
    if frozen_path.exists() and not a.refreeze:
        frozen = C.load_json(frozen_path)["묶음"]
        now = source_shas(lists)
        probs = [f"{s}: {p}" for s in lists for p in freeze_problems(now[s], frozen.get(s, {}).get("라벨_sha256", {}))]
        if probs:
            print("🔴 라벨이 고정본(라벨고정.json)과 다르다 — 작업 폴더를 건드리지 않고 멈춘다 · 일부러 바꿨으면 --refreeze 뒤 모든 채점 --force")
            print("\n".join(probs[:20]))
            return 1
    built = {s: build(s, names, src) for s, (names, src) in lists.items()}
    g3 = gate3(lists, built)
    g4, splits = gate4(lists)
    g5 = gate5()
    comp, calib = train_composition()
    g3 += [f"{k} 학습 라벨 지문 다름" for k, v in comp.items() if v["라벨확인"] == "다름"]     # 설계 §3.4 = 18 같음 · 2 기록 전
    rec = {"만든 시각": datetime.datetime.now().isoformat(timespec="seconds"),
           "묶음": {s: {"사진": len(lists[s][0]), "라벨_sha256": built[s][0],
                       "지문": hashlib.sha256("".join(f"{n}{h}" for n, h in sorted(built[s][0].items())).encode()).hexdigest()[:16],
                       "박스": dict(built[s][2])} for s in lists},
           "크기경계": size_bounds(), "나눔": splits, "학습구성": comp, "HEF보정": calib,
           "관문": {"③ 사진·라벨": g3, "④ 누출": g4, "⑤ 모델 파일": g5}}
    C.write_json(C.W / "prep.json", rec)
    for k, v in rec["관문"].items():
        print(f"{k}: {'✅' if not v else '❌ ' + ' · '.join(v[:10])}")
    for s, b in rec["묶음"].items():
        print(f"{s}: 사진 {b['사진']} · 지문 {b['지문']} · 박스 {b['박스']}")
    print(f"크기경계 {rec['크기경계']}")
    for k, v in comp.items():
        print(f"  {k}: 학습 {v['학습']}(배경 {v['배경']}) · 검증 {v['학습중검증']} · 박스 {v['박스']} · 라벨 {v['라벨확인']}")
    print(f"HEF 보정 {calib}")
    return 1 if any(rec["관문"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
