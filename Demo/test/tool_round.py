"""공구 초벌 반복 학습의 순수 부분 — 학습 데이터 만들기 · 떼어 두기 · 관문 셈 · 고르기.

시스템 python3 와 rfenv 둘 다에서 import 한다 — 표준 라이브러리만 쓴다(ultralytics·numpy 없이 시험하려고).
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-공구초벌-반복학습-design.md §4 · §6 · §7
🔴 원본 사진은 하드링크로 가리킨다(디스크 여유가 적다) — 원본을 옮기거나 고쳐 쓰지 않는다. 다른 파일 시스템이면 복사한다.
"""
from __future__ import annotations

import io
import math
import os
import re
import shutil
import tarfile
from pathlib import Path

TOOL_FIRST = 5                                    # 8종 번호(B1 B2 B3 B4 EMO driver wrench pliers)에서 공구 시작
TOOL_NAMES = ["driver", "wrench", "pliers"]       # tool_v3 순서와 같다


def tool_lines(lines):
    out = []
    for l in lines:
        p = l.split()
        if p and TOOL_FIRST <= int(p[0]) < TOOL_FIRST + len(TOOL_NAMES):
            out.append(" ".join([str(int(p[0]) - TOOL_FIRST)] + p[1:]))
    return out


def split_holdout(names, frac=0.2):
    """세션(<짧은 세션>__fNNNNN 의 앞부분)마다 프레임 번호 순서의 마지막 frac(올림)을 떼어 둔다 —
    무작위로 섞으면 이웃 프레임이 양쪽에 들어가 관문이 부풀려진다(설계 §4)."""
    by = {}
    for n in names:
        s, f = n.split("__f")
        by.setdefault(s, []).append((int(f), n))
    train, hold = [], []
    for s in sorted(by):
        xs = [n for _, n in sorted(by[s])]
        cut = len(xs) - math.ceil(len(xs) * frac)
        train += xs[:cut]; hold += xs[cut:]
    return train, hold


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_counts(preds, truths, thr=0.5):
    """사진 하나 — 같은 번호끼리 IoU 큰 순서로 짝짓는다. 잡은 수 · 가짜(짝 없는 예측) · 놓침(짝 없는 정답)."""
    pairs = sorted(((iou(p[1], t[1]), i, j) for i, p in enumerate(preds) for j, t in enumerate(truths) if p[0] == t[0]),
                   reverse=True)
    up, ut = set(range(len(preds))), set(range(len(truths)))
    for v, i, j in pairs:
        if v < thr:
            break
        if i in up and j in ut:
            up.discard(i); ut.discard(j)
    return {"caught": len(preds) - len(up), "fake": len(up), "missed": len(ut)}


def add_counts(a, b):
    return {k: a.get(k, 0) + b[k] for k in b}


def net(c):
    """순이익 — 잡은 박스 하나는 그리기 하나를 덜고, 가짜 하나는 지우기 하나를 더한다(설계 §6)."""
    return c["caught"] - c["fake"]


def pick(cands, current):
    """순이익이 가장 큰 후보(같으면 이름순 첫째)가 지금 모델보다 클 때만 그 이름 — 아니면 None(지금 모델 유지)."""
    if not cands:
        return None
    best = max(sorted(cands), key=lambda k: net(cands[k]))
    return best if net(cands[best]) > net(current) else None


def decide(cands, current):
    """라운드 결말 — 후보가 하나도 없으면 「학습 실패」(관문 패배와 구분 — 다음 판단을 그르치지 않게), 아니면 고르기."""
    if not cands:
        return "학습 실패", None
    chosen = pick(cands, current)
    return ("채택", chosen) if chosen else ("관문 패배", None)


def privacy_problems(names, exclude, cleared):
    """올리기 전 개인정보 관문 결속(설계 §5) — --exclude 이름이 목록에 없으면(오타) 문제 ·
    올릴 사진(names − exclude) 중 관문 통과 목록(cleared)에 없는 것이 있으면 문제."""
    out = [f"--exclude 의 이름이 images.txt 에 없다: {n}" for n in sorted(set(exclude) - set(names))]
    miss = sorted(set(names) - set(exclude) - set(cleared))
    if miss:
        out.append(f"개인정보 관문을 거치지 않은 사진 {len(miss)}장(예: {miss[:3]}) — 올리지 않는다")
    return out


def tool_index(name):
    n = name.replace("-in-hand", "")
    return TOOL_NAMES.index(n) if n in TOOL_NAMES else None


def yolo_to_boxes(lines, w, h):
    out = []
    for l in lines:
        p = l.split()
        if not p:
            continue
        c, cx, cy, bw, bh = int(p[0]), float(p[1]) * w, float(p[2]) * h, float(p[3]) * w, float(p[4]) * h
        out.append((c, [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]))
    return out


def is_demo_models(path, demo_models):
    p, d = Path(path).expanduser().resolve(), Path(demo_models).resolve()
    return p == d or d in p.parents


def data_yaml(root):
    names = "".join(f"  {i}: {n}\n" for i, n in enumerate(TOOL_NAMES))
    return f"path: {root}\ntrain: images/train\nval: images/val\nnames:\n{names}"


def build_dataset(src, dst, frac=0.2, exclude=()):
    """회수 결과(src = ~/data/label_dataset/<장소> — labels/ · images.txt) → ultralytics 폴더(dst).
    공구 없는 사진도 빈 라벨로 넣는다(설계 §4). 라벨 파일이 없으면 FileNotFoundError 로 멈춘다.
    exclude = 개인정보 관문에서 뺀 사진 이름 — 학습·떼어 둔 양쪽에서 뺀다(설계 §5)."""
    src, dst = Path(src).expanduser(), Path(dst).expanduser()
    if dst.exists():
        raise FileExistsError(f"이미 있다: {dst} — 덮어쓰지 않는다")
    idx = {}
    for line in (src / "images.txt").read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            if k not in exclude:
                idx[k] = v
    train, val = split_holdout(sorted(idx), frac)
    for name in idx:                                     # 쓰기 전에 전부 확인 — 반쯤 만든 폴더를 남기지 않게
        if not (src / "labels" / f"{name}.txt").exists():
            raise FileNotFoundError(f"라벨 파일 없음: {name}")
    boxes = {}
    for part, ns in (("train", train), ("val", val)):
        (dst / "images" / part).mkdir(parents=True); (dst / "labels" / part).mkdir(parents=True)
        n = 0
        for name in ns:
            orig = Path(idx[name])
            img = dst / "images" / part / (name + orig.suffix)
            try:
                os.link(orig, img)
            except OSError:
                shutil.copy2(orig, img)
            lines = tool_lines((src / "labels" / f"{name}.txt").read_text(encoding="utf-8").splitlines())
            (dst / "labels" / part / f"{name}.txt").write_text("".join(x + "\n" for x in lines), encoding="utf-8")
            n += len(lines)
        boxes[part] = n
    (dst / "data.yaml").write_text(data_yaml(dst), encoding="utf-8")
    return {"train": train, "val": val, "boxes": boxes}


def pack_dataset(ds, tar_path, remote_root):
    """Colab 에 올릴 묶음 — <ds 이름>/images · labels 전부 + 원격 경로로 고친 data.yaml. 하드링크 사진도 실제 바이트로 들어간다.
    반환 = 넣은 파일 수."""
    ds = Path(ds)
    n = 0
    with tarfile.open(tar_path, "w") as t:
        for f in sorted(ds.rglob("*")):
            rel = f.relative_to(ds)
            if f.is_file() and rel.parts[0] in ("images", "labels") and f.suffix != ".cache":
                t.add(f, arcname=f"{ds.name}/{rel}"); n += 1
        y = data_yaml(f"{remote_root}/{ds.name}").encode("utf-8")
        info = tarfile.TarInfo(f"{ds.name}/data.yaml"); info.size = len(y)
        t.addfile(info, io.BytesIO(y)); n += 1
    return n


def remote_script(ds_name, starts, epochs, hours, ul_version):
    """Colab VM 에서 돌릴 학습 스크립트. starts = [(이름, 원격 가중치 경로)].
    🔴 성패는 표지(@@SETUP ok · @@DONE · @@FAIL)로만 판단한다 — colab exec 는 예외에도 종료 코드 0(저널 §12.41-(6)).
    저장 경로는 문서와 다를 수 있어(같은 곳) 실제 save_dir 을 표지에 싣는다."""
    return f"""import subprocess, sys, tarfile, time, traceback
print("@@SETUP start", flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics=={ul_version}"], check=True)
tarfile.open("/content/{ds_name}.tar").extractall("/content")
print("@@SETUP ok", flush=True)
from ultralytics import YOLO
for stem, w in {starts!r}:
    t0 = time.time()
    try:
        m = YOLO(w)
        m.train(data="/content/{ds_name}/data.yaml", imgsz=640, epochs={epochs}, time={hours}, val=False, device=0,
                workers=2, batch=16, project="/content/runs", name=stem, exist_ok=True, plots=False, verbose=False)
        print(f"@@DONE {{stem}} {{(time.time() - t0) / 60:.1f}} {{m.trainer.save_dir}}", flush=True)
    except Exception as e:
        print(f"@@FAIL {{stem}} {{type(e).__name__}}: {{e}}", flush=True)
        traceback.print_exc()
"""


def parse_markers(text):
    out = {"setup_ok": re.search(r"^@@SETUP ok\s*$", text, re.M) is not None, "done": {}, "fail": {}}   # 줄 첫머리만 — 원문 되비침 제외
    for m in re.finditer(r"^@@DONE (\S+) ([\d.]+) (\S+)\s*$", text, re.M):
        out["done"][m.group(1)] = {"minutes": float(m.group(2)), "dir": m.group(3)}
    for m in re.finditer(r"^@@FAIL (\S+) (.*)$", text, re.M):
        out["fail"][m.group(1)] = m.group(2).strip()
    return out
