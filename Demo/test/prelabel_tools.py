"""공구 초벌 — tool_v3.pt 를 사진 목록에 돌려 JSON 으로 낸다. rfenv 파이썬 전용(ultralytics·torch).

실행(Demo/ 에서): ~/env/rfenv/bin/python test/prelabel_tools.py --list L.txt --out tools.json [--model models/tool_v3.pt] [--conf 0.25]
출력: {"<사진 경로>": [["driver", 0.41, x1, y1, x2, y2], ...], ...}
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §5.2 (점수 기준 0.25 — 공구를 거의 못 잡아 낮게)
🔴 config 를 import 하지 않는다 — rfenv 에서 config import 가 GUI 의존을 끌어온다(tool_worker.py 와 같은 이유).
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="models/tool_v3.pt")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    from ultralytics import YOLO
    m = YOLO(a.model)
    paths = [l.strip() for l in Path(a.list).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = {}
    for p in paths:
        r = m.predict(p, conf=a.conf, verbose=False)[0]
        out[p] = [[r.names[int(c)].replace("-in-hand", ""), round(float(s), 4), *[int(v) for v in b]]
                  for b, s, c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"공구 초벌 {len(paths)}장 · 박스 {sum(len(v) for v in out.values())}")


if __name__ == "__main__":
    main()
