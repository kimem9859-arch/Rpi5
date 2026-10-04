"""실험 한 번 — 바탕 폴더(입력 방식) → 실험 폴더 → 학습(멈춤 콜백) → best.pt 채점 → 요약. 데스크톱 ~/학습실험/venv 에서 돈다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §5 ~ §8
실행: venv/bin/python train_one.py <작업.json>   (실행기가 부른다 · 종료 코드 0 = 정상 종료 · 3 = 이상 종료(점수0) · 그 밖 = 오류)
- 바탕 폴더 = 나눔·무리·입력 방식마다 한 번(잠금). 실험 폴더 = 사진·.npy 하드링크 + 라벨 복사 — ultralytics 가 라벨 캐시를 실험 폴더에 써서 동시 학습끼리 겹치지 않는다.
- 멈춤 콜백 = on_model_save — 8.4.171 에서 매 에폭 저장 직후(trainer.py 666행) · 「멈출지 확인」(688행) 앞에만 불린다(마지막 검증 때는 안 불림).
- 손실 NaN 은 ultralytics 가 last.pt 에서 최대 3번 되살리고 그래도 안 되면 오류로 끝낸다(_handle_nan_recovery) — 여기서 따로 보지 않는다.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scoring    # noqa: E402
import stoprules  # noqa: E402

EXIT_ABNORMAL = 3


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fingerprint(items):
    h = hashlib.sha256()
    for rel, f in sorted(items):
        h.update(rel.encode())
        h.update(Path(f).read_bytes())
    return h.hexdigest()[:16]


def label_fingerprint(base):
    """바탕 폴더 라벨 전체의 지문(상대 경로 + 내용) — 나눔 해시는 이름만 덮으므로 라벨 내용을 따로 가린다."""
    base = Path(base)
    return _fingerprint([(str(f.relative_to(base)), f) for f in (base / "labels").rglob("*.txt")])


def source_fingerprint(job):
    """바탕이 원본에서 복사해 올 라벨의 지문 — label_fingerprint(바탕)과 같으면 바탕이 원본과 같다."""
    src = Path(job["원본"]).expanduser()
    items = []
    for part in ("train", "val", "test"):
        lab_dir = src / ("labels8" if part == "test" else f"labels_{job['group']}")
        items += [(f"labels/{part}/{n}.txt", lab_dir / f"{n}.txt") for n in job["나눔"][part]]
    return _fingerprint(items)


def ensure_val8(job, base):
    """검증 몫 8종 라벨 — 채점(score_model)이 8종 번호로 이름을 읽는다. 없으면 임시 폴더에 쓴 뒤 이름 바꿈(1-2단계 §5.2)."""
    lv = Path(base) / "labels8_val"
    if lv.exists():
        return
    src = Path(job["원본"]).expanduser() / "labels8"
    tmp = Path(base) / "labels8_val.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    for n in job["나눔"]["val"]:
        shutil.copyfile(src / f"{n}.txt", tmp / f"{n}.txt")
    os.replace(tmp, lv)


def score_val(job, base, best):
    """best.pt 를 검증 몫으로 채점 — 탐색 목표값(채점 사진은 쓰지 않는다)."""
    sv = scoring.score_model(best, Path(base) / "images" / "val", Path(base) / "labels8_val",
                             job["names"], job["conf"], job["predict_imgsz"])
    return sv, {"검증목표": round(scoring.objective(sv, job["names"]), 4), "검증P": round(sv["전체"]["precision"], 4)}


def rescore_val(rd):
    """다시 학습 없이 — 끝난 실험의 best.pt 를 검증 몫으로 채점해 채점_검증.json · 요약(검증목표 · 검증P)을 남긴다."""
    rd = Path(rd).expanduser()
    job = json.loads((rd / "작업.json").read_text(encoding="utf-8"))
    base = prepare_base(job, Path(job["루트"]).expanduser())
    sv, extra = score_val(job, base, rd / "weights" / "best.pt")
    (rd / "채점_검증.json").write_text(json.dumps(sv, ensure_ascii=False, indent=1), encoding="utf-8")
    sp = rd / "요약.json"
    summ = json.loads(sp.read_text(encoding="utf-8"))
    summ.update(extra)
    sp.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    return extra


def prepare_base(job, root):
    """바탕 폴더 — images/<몫>/(입력 방식대로) · labels/<몫>/(학습·검증 = 무리 번호 · 채점 = 8종) · 학습·검증 사진의 .npy.
    .npy = 8.4.171 data/base.py 의 cache='disk' 와 같은 저장(np.save(cv2.imread(사진)))이라 학습이 그대로 읽는다."""
    import cv2
    import numpy as np
    src = Path(job["원본"]).expanduser()
    base = Path(root) / "data" / f"{job['나눔']['name']}_{job['group']}_{job['입력']}"
    base.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{base}.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        if (base / ".완료").exists():
            if label_fingerprint(base) != source_fingerprint(job):     # 준비로 원본 라벨을 고친 뒤 옛 바탕을 쓰지 않게
                raise RuntimeError(f"바탕 {base.name} 의 라벨이 원본과 다르다 — 원본 라벨이 바뀌었다 · 도는 실험이 없을 때 바탕을 지우고 다시 건다")
            ensure_val8(job, base)
            return base
        if base.exists():                       # 만들다 죽은 폴더 — 잘린 사진·.npy 를 그대로 쓰지 않게
            shutil.rmtree(base)
        for part in ("train", "val", "test"):
            (base / "images" / part).mkdir(parents=True, exist_ok=True)
            (base / "labels" / part).mkdir(parents=True, exist_ok=True)
            lab_dir = src / ("labels8" if part == "test" else f"labels_{job['group']}")
            for n in job["나눔"][part]:
                out = base / "images" / part / f"{n}.png"
                if not out.exists():
                    if job["stretch"]:
                        im = cv2.imread(str(src / "images" / f"{n}.png"))
                        cv2.imwrite(str(out), cv2.resize(im, tuple(job["stretch"])))   # detector.py 110행과 같은 늘리기
                    else:
                        os.link(src / "images" / f"{n}.png", out)
                shutil.copyfile(lab_dir / f"{n}.txt", base / "labels" / part / f"{n}.txt")
                npy = out.with_suffix(".npy")
                if part != "test" and not npy.exists():
                    np.save(str(npy), cv2.imread(str(out)), allow_pickle=False)
        ensure_val8(job, base)
        (base / ".완료").write_text(json.dumps({"시각": time.strftime("%Y-%m-%d %H:%M:%S"), "라벨지문": label_fingerprint(base)},
                                               ensure_ascii=False), encoding="utf-8")
    return base


def job_dataset(base, rd, job):
    ds = Path(rd) / "data"
    for part in ("train", "val"):
        (ds / "images" / part).mkdir(parents=True, exist_ok=True)
        (ds / "labels" / part).mkdir(parents=True, exist_ok=True)
        for n in job["나눔"][part]:
            for suf in (".png", ".npy"):
                dst = ds / "images" / part / f"{n}{suf}"
                if not dst.exists():
                    os.link(base / "images" / part / f"{n}{suf}", dst)
            shutil.copyfile(base / "labels" / part / f"{n}.txt", ds / "labels" / part / f"{n}.txt")
    names = "".join(f"  {i}: {x}\n" for i, x in enumerate(job["names"]))
    y = ds / "data.yaml"
    y.write_text(f"path: {ds}\ntrain: images/train\nval: images/val\nnames:\n{names}", encoding="utf-8")
    return y


def end_reason(reason, epochs_done, max_epochs):
    if reason:
        return reason
    return "최대에폭" if epochs_done >= max_epochs else "일찍멈춤"


def no_pin_memory(modules=None):
    """WSL 고정(page-locked) 메모리 한도 — 데이터로더의 pin_memory 를 끈다(학습 결과는 그대로 · GPU 로 옮기는 방식만 바뀐다).
    2026-10-03 속도 측정: 늘리기640 2개 동시 · 원본768x1024 1개가 「pin memory thread … CUDA error: out of memory」로 죽었다
    (GPU 최고치는 8GB 안). 8.4.171 은 끄는 설정이 없어(학습 = build_dataloader 기본 True · 검증 = pin_memory=self.training)
    두 모듈이 import 한 이름을 감싼다 — 판 고정이라 경로가 바뀌지 않는다."""
    if modules is None:
        import ultralytics.data.build as b
        import ultralytics.models.yolo.detect.train as t
        import ultralytics.models.yolo.detect.val as v
        modules = [b, t, v]
    for mod in modules:
        orig = getattr(mod, "build_dataloader", None)
        if orig is None or getattr(orig, "_no_pin", False):
            continue

        def wrapped(*a, _orig=orig, **k):
            k["pin_memory"] = False
            return _orig(*a, **k)

        wrapped._no_pin = True
        mod.build_dataloader = wrapped


def train(job, ds_yaml, rd):
    from ultralytics import YOLO
    no_pin_memory()
    st = job["멈춤"]
    state = {"best": [], "reason": None}
    csv = rd / "results.csv"
    if job.get("이어서") and csv.exists():
        state["best"] = stoprules.fitness_history(stoprules.csv_rows(csv.read_text(encoding="utf-8")))

    def on_model_save(tr):
        state["best"].append(float(tr.best_fitness or 0.0))
        ep = tr.epoch + 1
        map50 = float((tr.metrics or {}).get("metrics/mAP50(B)", 0.0))
        if stoprules.zero_score(ep, map50, st["점수0_에폭"], st["점수0_mAP50"]):
            state["reason"] = "점수0"
            tr.stop = True
        elif stoprules.saturated(state["best"], st["포화_에폭"], st["포화_향상"]):
            state["reason"] = "포화"
            tr.stop = True

    if job.get("이어서"):
        m = YOLO(str(rd / "weights" / "last.pt"))
        m.add_callback("on_model_save", on_model_save)
        m.train(resume=True)
    else:
        m = YOLO(str(Path(job["출발"]).expanduser()))
        m.add_callback("on_model_save", on_model_save)
        m.train(data=str(ds_yaml), project=str(rd.parent), name=rd.name, exist_ok=True, **job["train_kwargs"])
    return state


def versions():
    import torch
    import ultralytics
    return {"ultralytics": ultralytics.__version__, "torch": torch.__version__, "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "albumentations": importlib.util.find_spec("albumentations") is not None}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--검증채점":
        print(json.dumps(rescore_val(argv[1]), ensure_ascii=False))
        return 0
    job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    root = Path(job["루트"]).expanduser()
    rd = root / "runs" / job["id"]
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "작업.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    light = {**job, "나눔": {k: job["나눔"][k] for k in ("name", "해시") if k in job["나눔"]}}
    (rd / "설정.json").write_text(json.dumps(light, ensure_ascii=False, indent=1), encoding="utf-8")
    t0 = time.time()
    base = prepare_base(job, root)
    ds_yaml = rd / "data" / "data.yaml" if job.get("이어서") else job_dataset(base, rd, job)
    state = train(job, ds_yaml, rd)
    rows = stoprules.csv_rows((rd / "results.csv").read_text(encoding="utf-8"))
    reason = end_reason(state["reason"], len(rows), job["train_kwargs"]["epochs"])
    best = rd / "weights" / "best.pt"
    summ = {"id": job["id"], "group": job["group"], "입력": job["입력"], "바꾼것": job.get("바꾼것", ""),
            "나눔": light["나눔"], "종료이유": reason, "이상": reason == "점수0", "에폭": len(rows),
            "best_epoch": stoprules.best_epoch(rows), "분": round((time.time() - t0) / 60, 1),
            "끝": datetime.now().astimezone().isoformat(timespec="seconds"), "판": versions(),
            "코드해시": job.get("코드해시"), "conf": job.get("conf"), "속도재기": bool(job.get("속도재기")),
            "출발_sha256": sha256(Path(job["출발"]).expanduser()) if not job.get("이어서") else None,
            "이어서": bool(job.get("이어서")), "라벨지문": label_fingerprint(base),
            "best_sha256": sha256(best) if best.exists() else None}
    if not job.get("속도재기") and best.exists() and not summ["이상"]:
        sc = scoring.score_model(best, base / "images" / "test", base / "labels" / "test",
                                 job["names"], job["conf"], job["predict_imgsz"])
        (rd / "채점.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
        sv, extra = score_val(job, base, best)
        (rd / "채점_검증.json").write_text(json.dumps(sv, ensure_ascii=False, indent=1), encoding="utf-8")
        summ.update(extra)
    (rd / "요약.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    return EXIT_ABNORMAL if summ["이상"] else 0


if __name__ == "__main__":
    sys.exit(main())
