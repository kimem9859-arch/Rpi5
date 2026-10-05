"""버튼 초벌 관문 — 떼어 둔 사진에서 후보마다 초벌 + 기계 검토를 돌려 사용자 최종 라벨(버튼)과 대조한다.

실행(Demo/ 에서, 시스템 python3 — Hailo·cv2): python3 test/gate_button.py --ds ~/data/label_train/button_r1 \\
    --template test/raw/<정지 세션> --cand yolov8n=<dets.json> [--cand ...] --current console_v2|이름=<dets.json> --out <gate.json>
dets.json = {사진 경로: [[이름, 점수, x1, y1, x2, y2], ...]} — 떼어 둔 사진과 배치 틀 사진 전부(train_tool_round 가 rfenv 에서
  prelabel_tools.predict_boxes 로 만든다 · 경로 열쇠 = tool_round.gate_paths). 새 모델은 사진 통째로(tile=False).
--current console_v2 = 지금 방식(Hailo console_v2 · 조각)으로 잰다 — 시연 프로그램이 Hailo 를 쓰고 있으면 실패한다.
출력(JSON) = {"cands": {이름: 셈 또는 {"error": 이유}}, "current": {"name": 이름, **셈}} · 셈 = collect_batch.button_work
정본 설계 = 상위 docs/superpowers/specs/2026-09-29-버튼초벌-반복학습-design.md §7
🔴 짝짓기는 회수 집계(collect_batch.edit_stats)와 같다 — 관문 값과 묶음 값이 같은 잣대. 🔴 같은 장소 값 — 성능으로 인용하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(DEMO))

import collect_batch as CB     # noqa: E402
import label_review as LR      # noqa: E402
import review_batch as RB      # noqa: E402
import tool_round as TR        # noqa: E402


def truths(ds, name, w, h):
    lines = (Path(ds) / "labels" / "val" / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    return [{"label": TR.BUTTON_NAMES[c], "box": b} for c, b in TR.yolo_to_boxes(lines, w, h)]


def evaluate(run, tile, tpl_imgs, val):
    """val = [(사진, 최종 박스 [{"label", "box"}])] → collect_batch.button_work 셈. 배치 틀·문턱도 같은 run 으로 만든다(spec §6)."""
    T = LR.build_template(tpl_imgs, run, tile)
    th = LR.make_thresholds(tpl_imgs, run, tile)
    total = {k: Counter() for k in ("auto", "check", "propose", "tool")}
    added = Counter()
    for img, fin in val:
        _, drafts, _ = RB.compose_shapes(LR.review(img, run, T, th, tile), [])
        s = CB.edit_stats(drafts, fin)
        for k in total:
            total[k].update(s[k])
        added.update(s["추가"])
    return CB.button_work({**{k: dict(v) for k, v in total.items()}, "추가": dict(added)})


def json_run(path, paths):
    dets = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [p for p in paths if p not in dets]
    if missing:
        raise KeyError(f"초벌 JSON 에 없는 사진 {len(missing)}장(예: {missing[:2]}) — 경로 열쇠가 어긋났다(tool_round.gate_paths)")
    return LR.lookup_run((cv2.imread(p), dets[p]) for p in paths)


def hailo_run():
    from detector import create_detector
    det = create_detector()
    return lambda crop: [(det.class_name(c), s, [x1, y1, x2, y2]) for c, s, x1, y1, x2, y2 in det.detect(crop)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--cand", action="append", default=[], help="이름=초벌 JSON(여러 번)")
    ap.add_argument("--current", required=True, help="console_v2(Hailo 조각 방식) 또는 이름=초벌 JSON")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ds = Path(a.ds).expanduser().resolve()
    vp, tp = TR.gate_paths(ds, a.template)
    tpl = [cv2.imread(p) for p in tp]
    val = []
    for p in vp:
        img = cv2.imread(p); h, w = img.shape[:2]
        val.append((img, truths(ds, Path(p).stem, w, h)))
    print(f"관문 — 떼어 둔 {len(val)}장 · 최종 버튼 {sum(len(f) for _, f in val)} · 배치 틀 {len(tpl)}장")
    res = {"cands": {}, "current": None}
    for spec in a.cand:
        name, j = spec.split("=", 1)
        try:
            res["cands"][name] = evaluate(json_run(j, vp + tp), False, tpl, val)
        except ValueError as e:                  # 배치 틀·문턱을 못 만들면 그 후보는 겨루지 못한다(지금 방식은 아래에서 그대로 멈춘다)
            res["cands"][name] = {"error": str(e)}
        print(f"  {name}: {res['cands'][name]}")
    if a.current == "console_v2":
        res["current"] = {"name": "console_v2", **evaluate(hailo_run(), True, tpl, val)}
    else:
        name, j = a.current.split("=", 1)
        res["current"] = {"name": name, **evaluate(json_run(j, vp + tp), False, tpl, val)}
    print(f"  지금 {res['current']}")
    Path(a.out).expanduser().write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
