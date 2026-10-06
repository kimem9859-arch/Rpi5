"""채점 묶음 만들기 — 이미 사람이 검토한 라벨을 다음 검토자에게 넘기는 묶음(사진마다 여러 사람 검토).

실행(Demo/ 에서): python3 test/score_batch.py --names <목록.txt> --dataset ~/data/label_dataset/<라벨 폴더> --out ~/data/label_batches/c001 [--round 1]
  --names   = pick_score_set.py 가 고른 라벨 이름(<짧은 세션>__fNNNNN)
  --dataset = 앞 검토의 결과(collect_batch 출력 — labels/ · images.txt). 1회차 = 학습 묶음 회수본 · 2회차 = 1회차 회수본
출력: <out>/images/(s_score__<라벨 이름>.png + 같은 이름 .json — 앞 검토 결과를 박스로 · 「검토함」 꺼짐) · classes.txt · manifest.json · 안내.txt · 단축키
회수 = collect_batch.py 그대로(파일 이름 규칙 <앞머리>__<짧은 세션>__fNNNNN 이 같다).
  1회차 회수 → 학습 라벨 폴더(예 ~/data/label_dataset/place2)로 — 학습·채점 라벨이 갈리지 않게 같은 폴더를 덮는다.
  2회차 = 1회차 회수본으로 다시 이 도구 → 회수 → 같은 폴더. collect_batch 가 sources.json 으로 채점 라벨을 지킨다
  (학습 묶음을 다시 회수해도 덮지 못한다 · 다시 회수 순서 = 학습 묶음 → 채점 1회차 → 2회차).
🔴 유효 범위 — 채점 사진도 학습 사진으로 들어간다(사용자 2026-10-07). 이 라벨로 학습한 모델(장소2 를 배운 2단계)은 이 묶음으로 채점하지 않는다.
🔴 used 목록에 적지 않는다 — 이미 학습 묶음에 들어간 사진이다. 🔴 사진은 복사한다(원본을 옮기지 않는다).
🔴 채점 라벨 조건(데이터셋 스킬 「분할」) — 평가 대상 모델 초벌로 시작한 라벨은 사진마다 2명 이상이 검토한다. 이 묶음이 그 다음 사람의 몫이다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_batch as RB      # noqa: E402
import xany_io as X            # noqa: E402

PREFIX = "s_score"
TOOLS = {"driver", "wrench", "pliers"}

GUIDE = """채점 묶음 {batch} — 사진 {n}장 · {round}회차 검토 (만든 날 {created})

이 묶음은 모델 점수를 매길 「정답」이 됩니다. 앞 검토자가 이미 한 번 고친 라벨이 박스로 들어 있습니다.
같은 사진을 여러 사람이 차례로 검토해야 정답으로 씁니다 — 앞 사람이 놓친 것을 찾는 것이 이 묶음의 일입니다.

1. 공유 드라이브에서 이 묶음 폴더({batch})를 통째로 내려받아 X-AnyLabeling에서 images 폴더를 엽니다(Ctrl+U).
2. 모든 사진을 처음부터 끝까지 꼼꼼히 봅니다 — 박스 위 글자가 「앞 검토 결과 — 다시 확인」이어도 맞다고 가정하지 않습니다.
   ① 빠진 공구·버튼이 없는지(가려진 것·화면 끝에 걸린 것 포함) ② 박스가 물체에 꼭 맞는지 ③ 이름이 맞는지 봅니다.
3. 사진마다 오른쪽 플래그의 「검토함」을 체크합니다(고칠 게 없어도 체크해야 저장됩니다).
4. 다 끝나면 images 폴더의 .json 파일 {n}개를 공유 드라이브의 {batch}/returned 폴더에 올리고 담당자에게 보고합니다.
안내서 """ + RB.GUIDE_URL + "\n"


def yolo_to_shapes(lines, w, h):
    """8종 YOLO 줄(정규화 중심·크기) → 앞 검토 결과 박스(픽셀 x1·y1·x2·y2) + 초벌 기록(drafts).
    drafts 의 kind = 공구 「tool」 · 버튼 「check」 — collect_batch 의 수정 집계가 이 회차에 고친 박스를 센다."""
    shapes, drafts = [], []
    for l in lines:
        if not l.strip():
            continue
        c, cx, cy, bw, bh = l.split()
        name = X.CLASSES[int(c)]
        cx, cy, bw, bh = float(cx) * w, float(cy) * h, float(bw) * w, float(bh) * h
        box = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]     # 반올림하지 않는다 — 고치지 않으면 라벨 글자 그대로 돌아온다
        shapes.append(X.shape(name, box, None, "앞 검토 결과 — 다시 확인", difficult=True))
        drafts.append({"label": name, "box": box, "kind": "tool" if name in TOOLS else "check", "why": ["앞 검토 결과"]})
    return shapes, drafts


def source_batches(root):
    """원본 경로 → (처음 초벌을 그린 학습 묶음 이름, 그 묶음의 초벌 모델 기록) — 채점 묶음(kind = score)은 건너뛴다."""
    out = {}
    for m in sorted(Path(root).glob("*/manifest.json")):
        man = json.loads(m.read_text(encoding="utf-8"))
        if man.get("kind") == "score":
            continue
        for r in man.get("images", []):
            out.setdefault(r["original"], (man["batch"], man.get("models")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--round", type=int, default=1, help="이 묶음이 채점 라벨의 몇 번째 추가 검토인지(기록용)")
    ap.add_argument("--batches", default="~/data/label_batches", help="학습 묶음 폴더들 — 사진마다 처음 초벌을 그린 묶음·모델을 찾아 기록한다")
    a = ap.parse_args()
    out = Path(a.out).expanduser()
    if out.exists() and any(out.iterdir()):
        sys.exit(f"이미 있다: {out} — 덮어쓰지 않는다")
    ds = Path(a.dataset).expanduser()
    idx = dict(l.split("\t") for l in (ds / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip())
    names = [l.strip() for l in Path(a.names).expanduser().read_text(encoding="utf-8").splitlines() if l.strip()]
    missing = [n for n in names if n not in idx or not (ds / "labels" / f"{n}.txt").exists()]
    if missing:
        sys.exit(f"앞 검토 라벨이 없는 이름 {len(missing)}개(예: {missing[:3]}) — 그 사진은 아직 회수되지 않았다")
    imgs = {n: cv2.imread(idx[n]) for n in names}
    bad = [n for n, im in imgs.items() if im is None]
    if bad:
        sys.exit(f"원본 사진을 못 읽은 이름 {len(bad)}개(예: {[idx[n] for n in bad[:3]]}) — 폴더를 만들지 않았다")
    src = source_batches(Path(a.batches).expanduser())
    (out / "images").mkdir(parents=True)
    recs = []
    for n in names:
        p = idx[n]
        h, w = imgs[n].shape[:2]
        shapes, drafts = yolo_to_shapes((ds / "labels" / f"{n}.txt").read_text(encoding="utf-8").splitlines(), w, h)
        fname = f"{PREFIX}__{n}.png"
        shutil.copy2(p, out / "images" / fname)
        X.write_json(out / "images" / f"{PREFIX}__{n}.json", fname, w, h, shapes)
        recs.append({"file": fname, "original": p, "session": Path(p).parent.name, "frame": int(n.split("__f")[1]),
                     "w": w, "h": h, "kind": "check", "blur": False, "drafts": drafts,
                     "from_batch": src.get(p, (None, None))[0]})
    created = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    first = {}
    for r in recs:
        b = r["from_batch"]
        if b:
            first[b] = src[r["original"]][1]
    man = {"batch": out.name, "created": created, "kind": "score", "round": a.round,
           "누적 검토 회차": a.round + 1,
           "누적 검토 회차 뜻": "학습 묶음 검토 1 + 채점 묶음 회차 — 같은 사람이 두 회차를 보면 사람 수는 그보다 적다(점수 인용 때 확인)",
           "유효 범위": "이 라벨을 학습하지 않은 모델의 채점에만 쓴다 — 채점 사진도 학습에 들어가므로 이 라벨로 학습한 모델은 다른 장소(장소3)로 채점",
           "처음 초벌": first, "처음 초벌 못 찾음": sum(r["from_batch"] is None for r in recs),
           "source": {"dataset": str(ds), "names": str(Path(a.names).expanduser())}, "images": recs}
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "classes.txt").write_text("\n".join(X.CLASSES + [X.EXCLUDE]) + "\n", encoding="utf-8")
    (out / "xanylabelingrc_단축키.yaml").write_text(RB.SHORTCUTS, encoding="utf-8")
    (out / "안내.txt").write_text(GUIDE.format(batch=out.name, n=len(recs), round=a.round, created=created), encoding="utf-8")
    print(f"✅ 채점 묶음 {out.name} · {a.round}회차 · 사진 {len(recs)} · 박스 {sum(len(r['drafts']) for r in recs)}")


if __name__ == "__main__":
    main()
