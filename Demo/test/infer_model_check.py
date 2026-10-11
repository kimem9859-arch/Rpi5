#!/usr/bin/env python3
"""2a 출력 비교 — 같은 장을 지금 방식(InferVStreams)과 InferModel 로 각각 돌려 버튼 · 공구 상자와 손끝이 같은지 본다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §3.2 관문(같은 입력 → 같은 출력 = 확정 값)
실행: python3 Demo/test/infer_model_check.py <폴더(f*.jpg · 안경 원본) | 영상.mp4(화면 방향 녹화)> [--limit 120]
🔑 두 방식을 별도 프로세스로 돌린다 — 한 장치에 network group 방식과 InferModel 을 섞지 않는다.
결과 = 「같음 N / 다름 M」 · 다른 장 · 장당 추론 시간(버튼 · 손) · 종료 코드 0 = 다름 0.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

TEST = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(TEST)
SCORE_TOL = 1e-5


def _frames(src, limit):
    import cv2
    import frame_orient
    if os.path.isdir(src):
        out = []
        for p in sorted(glob.glob(os.path.join(src, "f*.jpg")))[:limit or None]:
            out.append(frame_orient.apply(cv2.imread(p)))      # 안경 원본 → 시연과 같은 방향
        return out
    cap, out = cv2.VideoCapture(src), []
    while not limit or len(out) < limit:
        ok, img = cap.read()
        if not ok:
            break
        out.append(img)                                        # 측정 녹화 = 이미 화면 방향
    cap.release()
    return out


def dump(src, limit, out):
    """한 방식으로 장마다 버튼 · 공구 상자 · 손끝 → JSON(이 프로세스의 SOP_INFER_MODEL 대로)."""
    sys.path.insert(0, DEMO)
    import config
    from detector import HailoDetector
    from hand_tracker import HandTracker
    btn = HailoDetector()
    tool = HailoDetector(hef_path=config.TOOL_HEF_PATH, names=dict(enumerate(config.TOOL_NAMES)))
    hand = HandTracker(log=lambda m: None)
    rows, t_btn, t_hand = [], [], []
    for img in _frames(src, limit):
        t0 = time.perf_counter()
        b = btn.detect(img)
        t1 = time.perf_counter()
        tip = hand.detect(img)
        t2 = time.perf_counter()
        tl = tool.detect(img)
        t_btn.append((t1 - t0) * 1000)
        t_hand.append((t2 - t1) * 1000)
        rows.append({"btn": [list(d) for d in b], "tool": [list(d) for d in tl], "tip": list(tip) if tip else None})
    for d in (btn, tool, hand):
        d.close()
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"mode": config.INFER_MODEL, "rows": rows, "btn_ms": t_btn, "hand_ms": t_hand}, f)


def _same_dets(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(sorted(a), sorted(b)):
        if x[0] != y[0] or x[2:] != y[2:] or abs(x[1] - y[1]) > SCORE_TOL:
            return False
    return True


def compare(a, b):
    """→ (같음, 다름, [다른 장 번호], 손끝 있는 장 수)."""
    same, diff, bad = 0, 0, []
    for i, (x, y) in enumerate(zip(a["rows"], b["rows"])):
        ok = _same_dets(x["btn"], y["btn"]) and _same_dets(x["tool"], y["tool"]) and x["tip"] == y["tip"]
        same += ok
        if not ok:
            diff += 1
            bad.append(i)
    if len(a["rows"]) != len(b["rows"]):
        diff += abs(len(a["rows"]) - len(b["rows"]))
    tips = sum(1 for x in a["rows"] if x["tip"])
    return same, diff, bad, tips


def main(argv=None):
    ap = argparse.ArgumentParser(description="2a 출력 비교(학교 방문 준비 설계 §3.2)")
    ap.add_argument("src")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--dump", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.dump:
        dump(a.src, a.limit, a.dump)
        return 0
    d = tempfile.mkdtemp()
    res = {}
    for mode in ("0", "1"):
        out = os.path.join(d, f"m{mode}.json")
        env = dict(os.environ, SOP_INFER_MODEL=mode)
        r = subprocess.run([sys.executable, os.path.abspath(__file__), a.src, "--limit", str(a.limit), "--dump", out],
                           cwd=DEMO, env=env, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not os.path.exists(out):
            print(f"❌ 방식 {mode} 실행 실패 — {r.stderr[-500:]}")
            return 2
        res[mode] = json.load(open(out, encoding="utf-8"))
    same, diff, bad, tips = compare(res["0"], res["1"])
    med = lambda v: sorted(v)[len(v) // 2] if v else 0     # noqa: E731
    print(f"> 같은 입력 {len(res['0']['rows'])}장 · 손끝 있는 장 {tips}")
    print(f"같음 {same} / 다름 {diff}" + (f" — 다른 장 {bad[:10]}" if bad else ""))
    for k in ("btn_ms", "hand_ms"):
        print(f"{k}: 지금 방식 중앙 {med(res['0'][k]):.1f} · InferModel 중앙 {med(res['1'][k]):.1f}")
    if bad:
        i = bad[0]
        print("첫 다른 장:", json.dumps({"지금": res["0"]["rows"][i], "InferModel": res["1"]["rows"][i]}, ensure_ascii=False)[:600])
    return 0 if diff == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
