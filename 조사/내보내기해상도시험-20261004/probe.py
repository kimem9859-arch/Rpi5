"""내보내기 해상도 시험 — 640 으로 학습한 모델에 채점 292장을 두 크기로 넣어 채점한다(.pt · 데스크톱 CPU).

물음(사용자 2026-10-04 「②를 해보는 것으로」): 학습은 640 늘리기 그대로 두고 ONNX·HEF 입력만 768×1024 로 내보내면 정확도가 달라지나.
  640늘리기     = 지금 시연과 같다 — 원본을 640×640 으로 늘린 사진 · imgsz 640
  768x1024원본  = 768×1024 로 내보낸 HEF 가 받을 입력 — 원본 그대로 · imgsz [1024, 768](세로, 가로) · 늘리기 없음
같은 가중치 · 같은 라벨(정규화 좌표 — 축별 늘리기에 IoU 가 변하지 않는다) · 채점 = 학습/scoring.score_model 그대로(재구현 금지).
CPU 로 돈다(CUDA_VISIBLE_DEVICES 비움 · 스레드 4) — 탐색 T1 이 GPU 를 쓰고 있다. HEF(int8) 전 값이다.

실행(데스크톱): cd <이 폴더 사본> && ~/학습실험/venv/bin/python probe.py  → 결과.json
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import torch  # noqa: E402

torch.set_num_threads(4)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring  # noqa: E402

R = Path.home() / "학습실험"
MODELS = {"button": ["E0b-button-s0", "E0b-button-s1", "E0b-button-s2"],
          "tool": ["E0c-tool-f120", "E0c-tool-f120s1", "E0c-tool-f120s2"]}
COND = {"640늘리기": ("늘리기640", 640), "768x1024원본": ("원본768x1024", [1024, 768])}

out = {"조건": {k: {"바탕": v[0], "imgsz": v[1]} for k, v in COND.items()}, "장치": "cpu", "torch": torch.__version__, "결과": {}}
for g, ids in MODELS.items():
    for i in ids:
        job = json.loads((R / "runs" / i / "작업.json").read_text(encoding="utf-8"))
        for cname, (mode, imgsz) in COND.items():
            base = R / "data" / f"place1_v1_{g}_{mode}"
            t0 = time.time()
            sc = scoring.score_model(R / "runs" / i / "weights" / "best.pt", base / "images" / "test", base / "labels" / "test",
                                     job["names"], job["conf"], imgsz)
            out["결과"][f"{i}|{cname}"] = {"시간_s": round(time.time() - t0, 1), **sc}
            c = sc["클래스"]
            print(f"{i:18s} {cname:12s} " + " ".join(f"{n} {c[n]['tp']}/{c[n]['tp'] + c[n]['fn']}" for n in job["names"])
                  + f" · 오검출 {sc['오검출']} · 오분류 {sc['오분류']} · mAP50 {sc['mAP50']:.3f} · {time.time() - t0:.0f}s", flush=True)
(Path(__file__).resolve().parent / "결과.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("끝")
