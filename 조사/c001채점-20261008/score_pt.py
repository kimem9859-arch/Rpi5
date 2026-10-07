"""Task 3·5 — .pt 채점: 학습 체계의 채점 함수 그대로 + 사진별 기록 (설계 §4.2).

실행(rfenv): ~/env/rfenv/bin/python score_pt.py --set <c001|dark|place1_292> [--ids <결과 폴더 …>] [--force]
  --ids 없으면 설정 20개 × 시드 3 = 60개. 끝난 모델(사진 수가 맞는 출력)은 건너뛴다(끊김 대비).
계산 = scoring.score_model 과 같은 순서(predict conf 0.001 → gts_from_lines → preds_from → summarize) — 새로 쓰지 않는다.
"""
import argparse
import platform
import sys
import time

import common as C
import scoring

KEEP = 0.25            # 사진별 기록에 남길 예측 점수 하한(분석용 · mAP 는 실행 중 0.001 까지로 계산) — 설계 §4.2


MODES = {"늘리기640": (640, [640, 640]), "원본768x1024": ([1024, 768], None)}   # 학습/trainconf.py INPUT_MODES 의 (predict_imgsz, stretch)


def model_input(rid):
    """입력 방식 · 추론 크기 = 결과 폴더 설정.json(학습 때 job 이 쓴 값) — trainconf 표와 어긋나면 멈춘다."""
    cfg, su = C.load_json(C.RESULTS / rid / "설정.json"), C.load_json(C.RESULTS / rid / "요약.json")
    mode, imgsz = cfg["입력"], cfg["predict_imgsz"]
    if MODES.get(mode) != (imgsz, cfg.get("stretch")):
        sys.exit(f"🔴 {rid} 입력 방식 {mode} · 추론 크기 {imgsz} · 늘리기 {cfg.get('stretch')} 가 trainconf 표와 다르다")
    return mode, imgsz, su.get("best_sha256")


def score_one(rid, set_name, env):
    from ultralytics import YOLO
    g = C.group_of_id(rid)
    names = C.NAMES[g]
    mode, imgsz, best_sha = model_input(rid)
    sd = C.set_dir(set_name)
    img_dir = sd / ("s640" if mode == "늘리기640" else "orig")
    m = YOLO(str(C.MODELS / rid / "best.pt"))
    if [m.names[k] for k in sorted(m.names)] != names:
        sys.exit(f"🔴 {rid} 종류 이름 {m.names} ≠ {names}")
    per_image, rec = {}, {}
    for n in C.set_names(set_name):
        r = m.predict(str(img_dir / f"{n}.png"), conf=0.001, imgsz=imgsz, verbose=False)[0]
        h, w = r.orig_shape
        gts = scoring.gts_from_lines((sd / "labels8" / f"{n}.txt").read_text(encoding="utf-8").splitlines(), names, w, h)
        preds = scoring.preds_from(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist(), r.names, names)
        per_image[n] = (gts, preds)
        rec[n] = {"wh": [w, h], "gt": [list(x) for x in gts], "pred": [list(p) for p in preds if p[1] >= KEEP]}
    return {"id": rid, "setting": C.setting_of_id(rid), "group": g, "set": set_name, "입력": mode, "imgsz": imgsz,
            "요약": scoring.summarize(per_image, names, C.CONF), "사진별": rec, "환경": env, "best_sha256": best_sha}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True, choices=["c001", "dark", "place1_292"])
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    import torch
    import ultralytics
    env = {"ultralytics": ultralytics.__version__, "torch": torch.__version__, "장치": "cpu", "기계": platform.machine()}
    ids = a.ids or C.all_ids()
    want = len(C.set_names(a.set))
    for k, rid in enumerate(ids, 1):
        out = C.W / "out" / "pt" / a.set / f"{rid}.json"
        if out.exists() and not a.force and C.load_json(out)["요약"]["사진"] == want:
            print(f"[{k}/{len(ids)}] {rid} 건너뜀(있음)", flush=True)
            continue
        t0 = time.time()
        C.write_json(out, score_one(rid, a.set, env))
        print(f"[{k}/{len(ids)}] {rid} {a.set} {time.time() - t0:.0f}초", flush=True)


if __name__ == "__main__":
    main()
