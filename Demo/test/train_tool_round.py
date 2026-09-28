"""공구 초벌 반복 학습 한 라운드 — 학습 데이터 만들기 → 출발 가중치마다 학습 → 떼어 둔 사진 관문 → 고르기 → 저장.

실행(Demo/ 에서, rfenv): ~/env/rfenv/bin/python test/train_tool_round.py --data ~/data/label_dataset/place1 --round 1 \\
    --start models/yolov8n.pt models/tool_v3.pt --current models/tool_v3.pt [--epochs 50] [--probe]
출력: <work>/tool_r<N>/(학습 폴더 · runs/) · <models>/tool_r<N>.pt(채택했을 때만) · <models>/tool_r<N>.json(항상)
--probe = 첫 출발 가중치로 1 에폭만 돌려 시간을 잰다(<work>/tool_r<N>_probe · 저장·채택 없음) — 설계 §5
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-공구초벌-반복학습-design.md
🔴 config 를 import 하지 않는다(prelabel_tools 와 같은 이유). 🔴 결과 모델을 Demo/models/ 에 두지 않는다(설계 §7).
"""
import argparse
import datetime
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tool_round as TR          # noqa: E402

CONF = 0.25                      # 초벌과 같은 점수 기준(설계 §6)
HOURS_PER_START = 1.4            # 출발점마다 시간 상한 — 두 출발점이 한 라운드 3시간 안(설계 §1)


def train(start, ds, name, epochs, hours):
    from ultralytics import YOLO
    t = time.time()
    # val=False — 학습 중 성적 재기(가장 좋은 에폭 고르기·일찍 멈추기)에 떼어 둔 사진을 쓰지 않는다. 그 사진은 관문 채점에만 쓴다(설계 §4).
    # 그래서 마지막 에폭 모델(last.pt)을 쓰고, 시간은 time 상한이 지킨다.
    YOLO(str(start)).train(data=str(ds / "data.yaml"), imgsz=640, epochs=epochs, time=hours, val=False,
                           device="cpu", workers=2, batch=8, project=str(ds / "runs"), name=name, exist_ok=False,
                           plots=False, verbose=False)
    return ds / "runs" / name / "weights" / "last.pt", (time.time() - t) / 60


def gate(model_path, ds):
    """떼어 둔 사진에서 잡은 수·가짜·놓침 — 번호가 아니라 이름으로 짝짓는다(다른 공구 모델의 이름 표기 대비)."""
    from ultralytics import YOLO
    m = YOLO(str(model_path))
    tot = {"caught": 0, "fake": 0, "missed": 0}
    for p in sorted((ds / "images" / "val").iterdir()):
        r = m.predict(str(p), conf=CONF, imgsz=640, verbose=False)[0]
        h, w = r.orig_shape
        preds = [(TR.tool_index(r.names[int(c)]), b) for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist())]
        preds = [x for x in preds if x[0] is not None]
        truths = TR.yolo_to_boxes((ds / "labels" / "val" / (p.stem + ".txt")).read_text(encoding="utf-8").splitlines(), w, h)
        tot = TR.add_counts(tot, TR.match_counts(preds, truths))
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--start", nargs="+", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--work", default="~/data/label_train")
    ap.add_argument("--models", default="~/data/label_models")
    a = ap.parse_args()
    models = Path(a.models).expanduser()
    if TR.is_demo_models(models, HERE.parent / "models"):
        sys.exit("🔴 결과 모델을 Demo/models 에 두지 않는다(설계 §7)")
    ds = Path(a.work).expanduser() / (f"tool_r{a.round}" + ("_probe" if a.probe else ""))
    info = TR.build_dataset(a.data, ds)
    print(f"학습 {len(info['train'])}장(공구 {info['boxes']['train']}) · 떼어 둔 {len(info['val'])}장(공구 {info['boxes']['val']})")
    if a.probe:
        _, minutes = train(a.start[0], ds, "probe", 1, None)
        print(f"1 에폭 {minutes:.1f}분 → 예상 {minutes * a.epochs * len(a.start):.0f}분"
              f"(출발 {len(a.start)} × {a.epochs} 에폭 · 시간 상한 전 · 1 에폭 값은 학습 중 성적 재기 포함)")
        return
    rec = {"round": a.round, "data": str(Path(a.data).expanduser()), "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "train": info["train"], "val": info["val"], "boxes": info["boxes"], "epochs": a.epochs, "val_during_train": False,
           "hours_per_start": HOURS_PER_START, "conf": CONF, "starts": {}}
    cands = {}
    for s in a.start:
        name = Path(s).stem
        best, minutes = train(s, ds, name, a.epochs, HOURS_PER_START)
        c = gate(best, ds); cands[name] = c
        rec["starts"][name] = {"weights": s, "best": str(best), "minutes": round(minutes, 1), **c, "net": TR.net(c)}
        print(f"[{name}] {minutes:.0f}분 · 떼어 둔 사진: 잡음 {c['caught']} · 가짜 {c['fake']} · 놓침 {c['missed']} · 순이익 {TR.net(c)}")
    cur = gate(a.current, ds)
    rec["current"] = {"weights": a.current, **cur, "net": TR.net(cur)}
    print(f"[지금 {Path(a.current).stem}] 잡음 {cur['caught']} · 가짜 {cur['fake']} · 놓침 {cur['missed']} · 순이익 {TR.net(cur)}")
    chosen = TR.pick(cands, cur)
    rec["chosen"] = chosen
    models.mkdir(parents=True, exist_ok=True)
    if chosen:
        dst = models / f"tool_r{a.round}.pt"
        shutil.copy2(rec["starts"][chosen]["best"], dst)
        rec["model"] = str(dst)
        print(f"✅ 채택 {chosen} → {dst}")
    else:
        rec["model"] = None
        print("❌ 채택 없음 — 지금 모델을 계속 쓴다")
    (models / f"tool_r{a.round}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
