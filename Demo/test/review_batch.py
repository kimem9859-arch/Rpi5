"""검토 묶음 만들기 — 검토 전 분류 → 초벌(버튼 조각 방식 · 공구) → 기계 검토 → X-AnyLabeling 묶음 폴더.

실행(Demo/ 에서):
  python3 test/review_batch.py --sessions test/raw/<세션> [...] --template test/raw/<정지 세션> \\
      --used ~/data/label_batches/used.txt [--seal <봉인 목록.json>] [--tool-model ~/data/label_models/tool_rN.pt] [--button-model ~/data/label_models/button_rN.pt] \\
      --out ~/data/label_batches/b001 --size 200 [--seed 1]
출력: <out>/images/(순서 표시가 붙은 사진 + 같은 이름 .json) · classes.txt · manifest.json · 안내.txt · xanylabelingrc_단축키.yaml
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §3 · §4 · §5 · §6
--button-model = 반복 학습 버튼 모델(spec 2026-09-29) — rfenv 에서 사진 통째로 초벌(조각 안 함) · 배치 틀·문턱도 그 모델로. 없으면 console_v2 조각.
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


def button_model_record(path=None):
    """묶음 기록용 — 실제로 쓴 버튼 모델. 시험 세트 순환 금지(설계 §11)를 기록으로 확인하려고.
    path = 반복 학습 버튼 모델(spec 2026-09-29) — 없으면 config 의 지금 모델(console_v2 조각)."""
    import config
    if path is not None:
        return {"backend": "pt-rfenv", "path": str(path), "sha256_16": _sha(path), "conf": config.YOLO_CONF_LOW,
                "method": "whole — 사진 통째로 · 비율 유지 여백 채우기 640(조각 안 함)"}
    path = config.HEF_MODEL_PATH if config.INFERENCE_BACKEND == "hailo" else config.PT_MODEL_PATH
    return {"backend": config.INFERENCE_BACKEND, "path": os.path.relpath(path, DEMO), "sha256_16": _sha(path),
            "conf": config.YOLO_CONF_LOW, "method": "tile2 — 세로 사진을 가로 두 조각(768×576)으로"}


TOOL_CONF = 0.25                   # 설계 §5.2 — 공구 초벌 점수 기준


def tool_model_record(path):
    """묶음 기록용 — 공구 초벌 모델(tool_v3 또는 반복 학습 tool_rN · spec 2026-09-28-공구초벌-반복학습 §6)."""
    return {"path": str(path), "sha256_16": _sha(path), "conf": TOOL_CONF}


def drop_nested(dets, thr=0.8):
    """같은 이름 공구 초벌이 다른 박스 안에 대부분(thr) 들어가 있으면 작은 것을 뺀다 — 손에 가려 조각과 전체를 따로 그린 것
    (b003 에서 29장 · 사용자 승인 2026-09-29). 라벨 규칙 ④(두 조각이면 박스 하나)와 같은 방향. 떨어진 같은 공구 둘·다른 이름은 그대로.
    dets = [[이름, 점수, x1, y1, x2, y2], ...]"""
    def area(b):
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    keep = []
    for i in sorted(range(len(dets)), key=lambda k: -area(dets[k][2:6])):
        b = dets[i][2:6]
        nested = False
        for j in keep:
            B = dets[j][2:6]
            if dets[j][0] == dets[i][0] and area(b):
                ix = max(0, min(b[2], B[2]) - max(b[0], B[0])); iy = max(0, min(b[3], B[3]) - max(b[1], B[1]))
                if ix * iy / area(b) >= thr:
                    nested = True; break
        if not nested:
            keep.append(i)
    return [dets[i] for i in sorted(keep)]


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


def compose_shapes(rev, tools, propose=False):
    """propose = 빠진 자리 제안을 넣을지 — 기본 끔(사용자 결정 2026-09-29 · b001~b004 제안 45개 안팎 중 쓸모 있던 것 0~8 ·
    설계 §6 ④ 개정). 버튼 관문(gate_button)도 이 기본을 따라 실제 작업과 같은 잣대로 센다."""
    shapes, drafts = [], []
    for b in rev["boxes"]:
        if b["why"]:
            shapes.append(X.shape(b["name"], b["box"], b["score"], "확인: " + ", ".join(b["why"]), difficult=True))
            drafts.append({"label": b["name"], "box": b["box"], "kind": "check", "why": b["why"]})
        else:
            shapes.append(X.shape(b["name"], b["box"], b["score"], "기계 확정"))
            drafts.append({"label": b["name"], "box": b["box"], "kind": "auto", "why": []})
    for slot, box in (rev["missing"] if propose else []):
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


GUIDE_URL = "https://claude.ai/artifact/9opbyZ6CTBGGFE3cku1md1"   # 라벨링 검토 안내서(원본 = Demo/docs/labeling_guide.md · 같은 주소로 다시 올린다)

GUIDE = """검토 묶음 {batch} — 사진 {n}장 (만든 날 {created})

설치, 설정, 검토 방법, 규칙은 안내서에 있습니다. 처음이라면 안내서를 먼저 읽어 주세요.
안내서 """ + GUIDE_URL + """

1. 공유 드라이브에서 이 묶음 폴더({batch})를 통째로 내려받습니다.
2. X-AnyLabeling에서 Ctrl+U로 폴더 안의 images 폴더를 엽니다.
3. 파일 목록 위에서부터 봅니다. a_check(확인 박스와 공구 초벌이 있는 사진)를 가장 꼼꼼히 보고, c_auto(기계 확정만 있는 사진)는 훑어봅니다. d_blur는 흐림 후보일 뿐 지울 사진이 아닙니다.
   박스 위 글자가 「기계 확정」이면 훑어보고, 「확인: 이유」이면 꼼꼼히 보고, 「공구 초벌 — 확인」이면 모두 꼼꼼히 봅니다.
4. 사진마다 오른쪽 플래그의 「검토함」을 체크합니다. 체크하지 않은 사진은 담당자가 결과를 받을 때 걸러집니다.
5. 다 끝나면 images 폴더의 .json 파일 {n}개를 공유 드라이브의 {batch}/returned 폴더에 올리고 담당자에게 보고합니다. 사진(.png)은 올리지 않습니다.
   처음 맡았다면 앞 10장만 먼저 {batch}/첫10장 폴더에 올리고 담당자에게 확인받습니다.
"""

SHORTCUTS = "digit_shortcuts:\n" + "".join(
    f"  {i}: {{mode: rectangle, label: {n}}}\n" for i, n in enumerate(X.CLASSES + [X.EXCLUDE], 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", nargs="+", required=True)
    ap.add_argument("--template", required=True, help="배치 틀·문턱을 만들 정지 장면 세션(같은 장소)")
    ap.add_argument("--seal", help="봉인 목록(selection.json) — 주면 그 사진과 주변을 뺀다")
    ap.add_argument("--used", required=True)
    ap.add_argument("--tool-model", default=str(TOOL_MODEL), help="공구 초벌 모델(기본 tool_v3 · 반복 학습 모델은 ~/data/label_models/)")
    ap.add_argument("--propose", action="store_true", help="빠진 자리 제안을 다시 켠다(기본 끔 · 사용자 결정 2026-09-29)")
    ap.add_argument("--button-model", help="버튼 초벌 모델(.pt · 반복 학습 button_rN · spec 2026-09-29) — 주면 사진 통째로(조각 안 함). 없으면 console_v2 조각")
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

    tpl_paths = sorted(Path(a.template).glob("f*.png"))
    tpl_imgs = [cv2.imread(str(p)) for p in tpl_paths]
    bmodel = Path(a.button_model).expanduser() if a.button_model else None
    if bmodel:                       # 새 버튼 모델 — rfenv 에서 묶음 사진·배치 틀 사진을 통째로 초벌(spec 2026-09-29 §6)
        import config
        bl, bj = out / "_buttons_list.txt", out / "_buttons.json"
        bl.write_text("\n".join([c[2] for c in pick] + [str(p) for p in tpl_paths]), encoding="utf-8")
        subprocess.run([str(RFENV), str(HERE / "prelabel_tools.py"), "--list", str(bl), "--out", str(bj),
                        "--model", str(bmodel), "--conf", str(config.YOLO_CONF_LOW)], check=True, cwd=str(DEMO))
        bdets = json.loads(bj.read_text(encoding="utf-8"))
        run = LR.lookup_run((cv2.imread(p), bdets[p]) for p in [c[2] for c in pick] + [str(q) for q in tpl_paths])
        tile = False
        bl.unlink(); bj.unlink()
    else:
        from detector import create_detector
        det = create_detector()

        def run(crop):
            return [(det.class_name(c), s, [x1, y1, x2, y2]) for c, s, x1, y1, x2, y2 in det.detect(crop)]
        tile = True

    T = LR.build_template(tpl_imgs, run, tile)
    th = LR.make_thresholds(tpl_imgs, run, tile)
    sharp_thr = float(np.percentile([_frame_sharp(i) for i in tpl_imgs], 5)) * 0.5

    lst = out / "_tools_list.txt"; tj = out / "_tools.json"
    lst.write_text("\n".join(c[2] for c in pick), encoding="utf-8")
    subprocess.run([str(RFENV), str(HERE / "prelabel_tools.py"), "--list", str(lst), "--out", str(tj),
                    "--model", str(Path(a.tool_model).expanduser()), "--conf", str(TOOL_CONF)], check=True, cwd=str(DEMO))
    tools = json.loads(tj.read_text(encoding="utf-8"))

    recs = []
    nested_dropped = 0
    for sess, fr, p in pick:
        img = cv2.imread(p); h, w = img.shape[:2]
        rev = LR.review(img, run, T, th, tile)
        tl = tools.get(p, []); tk = drop_nested(tl); nested_dropped += len(tl) - len(tk)
        shapes, drafts, kind = compose_shapes(rev, tk, propose=a.propose)
        blur = _frame_sharp(img) < sharp_thr
        name = batch_name(kind, blur, short_name(sess), fr)
        shutil.copy2(p, out / "images" / name)
        X.write_json(out / "images" / (Path(name).stem + ".json"), name, w, h,
                     [dict(s, shape_type="rectangle") for s in shapes])
        recs.append({"file": name, "original": p, "session": sess, "frame": fr, "w": w, "h": h,
                     "kind": kind, "blur": blur, "drafts": drafts})
    created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    man = {"batch": out.name, "created": created,
           "models": {"buttons": button_model_record(bmodel),
                      "tools": tool_model_record(Path(a.tool_model).expanduser())},
           "template": str(a.template), "propose": a.propose, "thresholds": th, "edge_frac": LR.EDGE_FRAC, "frame_sharp_thr": sharp_thr,
           "images": recs}
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "classes.txt").write_text("\n".join(X.CLASSES + [X.EXCLUDE]) + "\n", encoding="utf-8")
    (out / "xanylabelingrc_단축키.yaml").write_text(SHORTCUTS, encoding="utf-8")
    (out / "안내.txt").write_text(GUIDE.format(batch=out.name, n=len(recs), created=created), encoding="utf-8")
    with open(used_p, "a", encoding="utf-8") as f:
        f.write("".join(r["original"] + "\n" for r in recs))
    lst.unlink(); tj.unlink()
    from collections import Counter
    print("겹친 공구 초벌 뺀 수", nested_dropped)
    print("종류:", dict(Counter(r["kind"] for r in recs)), "· 흐림 후보", sum(r["blur"] for r in recs),
          "· 초벌:", dict(Counter(d["kind"] for r in recs for d in r["drafts"])))


if __name__ == "__main__":
    main()
