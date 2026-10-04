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


def label_fingerprint(base):
    """바탕 폴더 라벨 전체의 지문(이름 + 내용) — 나눔 해시는 이름만 덮으므로 라벨이 바뀐 바탕을 가린다."""
    h = hashlib.sha256()
    for f in sorted((Path(base) / "labels").rglob("*.txt")):
        h.update(str(f.relative_to(base)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def read_fingerprint(base):
    try:
        return json.loads((Path(base) / ".완료").read_text(encoding="utf-8")).get("라벨지문")
    except (OSError, ValueError, AttributeError):
        return None                             # 옛 표지(시각 한 줄)


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
            "이어서": bool(job.get("이어서")), "라벨지문": read_fingerprint(base),
            "best_sha256": sha256(best) if best.exists() else None}
    if not job.get("속도재기") and best.exists() and not summ["이상"]:
        sc = scoring.score_model(best, base / "images" / "test", base / "labels" / "test",
                                 job["names"], job["conf"], job["predict_imgsz"])
        (rd / "채점.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    (rd / "요약.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    return EXIT_ABNORMAL if summ["이상"] else 0


if __name__ == "__main__":
    sys.exit(main())
