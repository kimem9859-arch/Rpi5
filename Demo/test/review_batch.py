"""검토 묶음 만들기 — 검토 전 분류 → 초벌(버튼 조각 방식 · 공구) → 기계 검토 → X-AnyLabeling 묶음 폴더.

실행(Demo/ 에서):
  python3 test/review_batch.py --sessions test/raw/<세션> [...] --template test/raw/<정지 세션> \\
      --used ~/data/label_batches/used.txt [--seal <봉인 목록.json>] \\
      --out ~/data/label_batches/b001 --size 200 [--seed 1]
출력: <out>/images/(순서 표시가 붙은 사진 + 같은 이름 .json) · classes.txt · manifest.json · 안내.txt · xanylabelingrc_단축키.yaml
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §3 · §4 · §5 · §6
🔴 원본을 옮기거나 지우지 않는다 — 사진은 복사한다. 🔴 --seal 을 주면 봉인 사진과 그 주변은 넣지 않는다
   (실험 1 의 50장 봉인은 실험 1 취소로 풀었다 — 설계 §4 · §13. 장소3 세션은 --sessions 에 넣지 않는다).
🔴 한 번 묶음에 넣은 원본은 --used 목록에 적어 다음 묶음에 다시 넣지 않고, 그것과 pHash 가 가까운 후보도 뺀다.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(DEMO))

import label_review as LR          # noqa: E402
import xany_io as X                # noqa: E402

RFENV = Path.home() / "env/rfenv/bin/python"
TOOL_MODEL = DEMO / "models/tool_v3.pt"
PHASH_THR = 6                      # 설계 §4 — 세션 전체를 합쳐
BLACK_MEAN = 12


def short_name(session):
    parts = Path(session).name.split("_")
    return f"{parts[0][4:]}-{parts[1]}"


def load_seal(path):
    sel = json.loads(Path(path).read_text(encoding="utf-8"))
    gap = {f"20260923_{p[0]}_console_v2": int(p[3]) for p in sel["plan"]}
    seal = {}
    for p in sel["picked"]:
        seal.setdefault(p["session"], []).append(int(p["frame"]))
    return seal, gap


def is_sealed(session, frame, seal, gap):
    return any(abs(frame - q) < gap.get(session, 0) for q in seal.get(session, []))


def drop_near(hashes, ref, thr):
    """이미 쓴 사진(ref)과 pHash 해밍거리 thr 이하인 후보를 뺀 번호 — 묶음마다 중복 제거가 새로 시작되지 않게(설계 §4)."""
    if not len(ref):
        return list(range(len(hashes)))
    R = np.stack(ref)
    return [i for i, h in enumerate(hashes) if np.count_nonzero(R != h, axis=1).min() > thr]


def button_model_record():
    """묶음 기록용 — 실제로 불러오는 버튼 모델(config 를 따른다). 시험 세트 순환 금지(설계 §11)를 기록으로 확인하려고."""
    import config
    path = config.HEF_MODEL_PATH if config.INFERENCE_BACKEND == "hailo" else config.PT_MODEL_PATH
    return {"backend": config.INFERENCE_BACKEND, "path": os.path.relpath(path, DEMO), "sha256_16": _sha(path),
            "conf": config.YOLO_CONF_LOW, "method": "tile2 — 세로 사진을 가로 두 조각(768×576)으로"}


def pick_frames(cands, size, seed):
    by = {}
    for c in cands:
        by.setdefault(c[0], []).append(c)
    total = len(cands)
    if total <= size:
        return sorted(cands)
    rng = random.Random(seed)
    quota = {s: int(size * len(v) / total) for s, v in by.items()}
    rest = size - sum(quota.values())
    for s in sorted(by, key=lambda s: -(size * len(by[s]) / total - quota[s]))[:rest]:
        quota[s] += 1
    out = []
    for s in sorted(by):
        out += rng.sample(by[s], quota[s])
    return sorted(out)


def compose_shapes(rev, tools):
    shapes, drafts = [], []
    for b in rev["boxes"]:
        if b["why"]:
            shapes.append(X.shape(b["name"], b["box"], b["score"], "확인: " + ", ".join(b["why"]), difficult=True))
            drafts.append({"label": b["name"], "box": b["box"], "kind": "check", "why": b["why"]})
        else:
            shapes.append(X.shape(b["name"], b["box"], b["score"], "기계 확정"))
            drafts.append({"label": b["name"], "box": b["box"], "kind": "auto", "why": []})
    for slot, box in rev["missing"]:
        lab = X.PROPOSAL_PREFIX + slot
        shapes.append(X.shape(lab, box, None, f"제안: 빠진 자리 — 맞으면 이름을 {slot} 로, 아니면 지우기"))
        drafts.append({"label": lab, "box": box, "kind": "propose", "why": []})
    for name, score, x1, y1, x2, y2 in tools:
        shapes.append(X.shape(name, [x1, y1, x2, y2], score, "공구 초벌 — 확인", difficult=True))
        drafts.append({"label": name, "box": [x1, y1, x2, y2], "kind": "tool", "why": []})
    kinds = {d["kind"] for d in drafts}
    kind = "check" if kinds & {"check", "tool"} else "propose" if "propose" in kinds else "auto"
    return shapes, drafts, kind


def batch_name(kind, blur, short, frame):
    pre = {"check": "a_check", "propose": "b_propose"}.get(kind) or ("d_blur" if blur else "c_auto")
    return f"{pre}__{short}__f{frame:05d}.png"


def _frame_sharp(img):
    return float(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


GUIDE = """검토 묶음 {batch} — 사진 {n}장 (만든 날 {created})

1. 데스크톱 PowerShell 로 가져오기
   scp -r pi@pi1.tailf090b8.ts.net:~/data/label_batches/{batch} "$HOME\\Desktop\\"
2. X-AnyLabeling-CPU.exe → Desktop\\{batch}\\images 폴더 열기 (AI 자동 라벨은 쓰지 않는다)
3. 목록 순서 = a_check(사람 확인 박스·공구 초벌이 있음) → b_propose(빠진 자리 제안) → c_auto(기계 확정만 — 공구·빠진 물체만 훑기) → d_blur(흐림 후보)
   · 박스 설명 「기계 확정」 = 기계가 확정 / 「확인: 이유」 = 사람이 봐야 함 / 「공구 초벌 — 확인」
   · 이름이 「제안_B4」 같은 박스 = 빠진 자리 제안 → 맞으면 이름을 B4 로, 아니면 지우기 (남아 있으면 회수가 거부한다)
   · File → Save Automatically 를 켠다 — 박스를 고치는 순간 저장된다(고치지 않은 사진은 저장되지 않는다)
   · Flags 칸의 「검토함」: 고칠 게 없는 사진은 체크하고 D (체크하는 순간 저장된다). 박스를 고친 사진은 그냥 D
     (Flags 칸이 안 보이면 X-AnyLabeling 을 닫고 설정 파일(PowerShell: notepad "$HOME\.xanylabelingrc")의
      `flags: null` 을 `flags:` 와 `- 검토함` 두 줄로 바꾼다 — 3.3.5 는 flags 가 비면 Flags 칸을 숨긴다)
   · 체크 없이 넘겼다면 끝나고 「다 봤다」고 알려 준다 — 저장 흔적 없는 사진은 「봤고 고칠 게 없음」으로 받는다
   · F = 사진 속 박스를 차례로 확대(설정 loop_thru_labels) · D = 다음 사진
   · 규칙 = Rpi5/Demo/docs/labeling_guide.md (여백 0 · 가린 버튼은 동그라미 전체 · 알아볼 수 없으면 사진 전체에 exclude)
   · 기계 박스의 아래 끝선이 조금 짧거나 B4 위 끝선이 조금 넘친 것은 고치지 않는다(알려진 치우침 — 설계 §6 ①)
4. 끝나면 파이로 돌려보내기 (한 번만)
   scp -r "$HOME\\Desktop\\{batch}\\images" pi@pi1.tailf090b8.ts.net:~/data/label_batches/{batch}/returned
   · 다시 보낼 때는 고친 .json 만: scp "$HOME\\Desktop\\{batch}\\images\\<파일>.json" pi@pi1.tailf090b8.ts.net:~/data/label_batches/{batch}/returned/
     (폴더째 다시 보내면 returned\\images\\ 로 한 겹 더 들어가 회수가 거부한다)
"""

SHORTCUTS = "digit_shortcuts:\n" + "".join(
    f"  {i}: {{mode: rectangle, label: {n}}}\n" for i, n in enumerate(X.CLASSES + [X.EXCLUDE], 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", nargs="+", required=True)
    ap.add_argument("--template", required=True, help="배치 틀·문턱을 만들 정지 장면 세션(같은 장소)")
    ap.add_argument("--seal", help="봉인 목록(selection.json) — 주면 그 사진과 주변을 뺀다")
    ap.add_argument("--used", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    if out.exists() and any(out.iterdir()):
        sys.exit(f"이미 있다: {out} — 덮어쓰지 않는다")
    (out / "images").mkdir(parents=True)
    seal, gap = load_seal(Path(a.seal).expanduser()) if a.seal else ({}, {})
    used_p = Path(a.used).expanduser(); used_p.parent.mkdir(parents=True, exist_ok=True)
    used = set(used_p.read_text(encoding="utf-8").split()) if used_p.exists() else set()

    import dedupe_raw
    import frame_health
    cands = []
    for sdir in a.sessions:
        sdir = Path(sdir); sess = sdir.name
        for p in sorted(sdir.glob("f*.png")):
            p = p.resolve(); fr = int(p.stem[1:])
            if is_sealed(sess, fr, seal, gap) or str(p) in used:
                continue
            seam, washed = frame_health.metrics(p)
            if seam > 0.02 or washed > 0.25:
                continue
            cands.append((sess, fr, str(p)))
    keep_c = []
    hashes = []
    for c in cands:
        img = cv2.imread(c[2])
        if img is None or float(img.mean()) < BLACK_MEAN:
            continue
        keep_c.append(c); hashes.append(dedupe_raw.phash(img))
    used_h = [dedupe_raw.phash(im) for im in (cv2.imread(q) for q in sorted(used)) if im is not None]
    n_ok = len(keep_c)
    far = drop_near(hashes, used_h, PHASH_THR)
    keep_c = [keep_c[i] for i in far]; hashes = [hashes[i] for i in far]
    uniq = [keep_c[i] for i in dedupe_raw.dedupe(hashes, PHASH_THR)]
    pick = pick_frames(uniq, a.size, a.seed)
    print(f"후보 {len(cands)} → 검은·깨짐 뺀 {n_ok} → 쓴 사진과 닮은 것 뺀 {len(keep_c)} → 중복 뺀 {len(uniq)} → 묶음 {len(pick)}")

    from detector import create_detector
    det = create_detector()

    def run(crop):
        return [(det.class_name(c), s, [x1, y1, x2, y2]) for c, s, x1, y1, x2, y2 in det.detect(crop)]

    tpl_imgs = [cv2.imread(str(p)) for p in sorted(Path(a.template).glob("f*.png"))]
    T = LR.build_template(tpl_imgs, run)
    th = LR.make_thresholds(tpl_imgs, run)
    sharp_thr = float(np.percentile([_frame_sharp(i) for i in tpl_imgs], 5)) * 0.5

    lst = out / "_tools_list.txt"; tj = out / "_tools.json"
    lst.write_text("\n".join(c[2] for c in pick), encoding="utf-8")
    subprocess.run([str(RFENV), str(HERE / "prelabel_tools.py"), "--list", str(lst), "--out", str(tj),
                    "--model", str(TOOL_MODEL)], check=True, cwd=str(DEMO))
    tools = json.loads(tj.read_text(encoding="utf-8"))

    recs = []
    for sess, fr, p in pick:
        img = cv2.imread(p); h, w = img.shape[:2]
        rev = LR.review(img, run, T, th)
        shapes, drafts, kind = compose_shapes(rev, tools.get(p, []))
        blur = _frame_sharp(img) < sharp_thr
        name = batch_name(kind, blur, short_name(sess), fr)
        shutil.copy2(p, out / "images" / name)
        X.write_json(out / "images" / (Path(name).stem + ".json"), name, w, h,
                     [dict(s, shape_type="rectangle") for s in shapes])
        recs.append({"file": name, "original": p, "session": sess, "frame": fr, "w": w, "h": h,
                     "kind": kind, "blur": blur, "drafts": drafts})
    created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    man = {"batch": out.name, "created": created,
           "models": {"buttons": button_model_record(),
                      "tools": {"path": "models/tool_v3.pt", "sha256_16": _sha(TOOL_MODEL), "conf": 0.25}},
           "template": str(a.template), "thresholds": th, "edge_frac": LR.EDGE_FRAC, "frame_sharp_thr": sharp_thr,
           "images": recs}
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "classes.txt").write_text("\n".join(X.CLASSES + [X.EXCLUDE]) + "\n", encoding="utf-8")
    (out / "xanylabelingrc_단축키.yaml").write_text(SHORTCUTS, encoding="utf-8")
    (out / "안내.txt").write_text(GUIDE.format(batch=out.name, n=len(recs), created=created), encoding="utf-8")
    with open(used_p, "a", encoding="utf-8") as f:
        f.write("".join(r["original"] + "\n" for r in recs))
    lst.unlink(); tj.unlink()
    from collections import Counter
    print("종류:", dict(Counter(r["kind"] for r in recs)), "· 흐림 후보", sum(r["blur"] for r in recs),
          "· 초벌:", dict(Counter(d["kind"] for r in recs for d in r["drafts"])))


if __name__ == "__main__":
    main()
