#!/usr/bin/env python3
"""B3→EMO 오분류 자리 기준 채점 (rawdet 로그 오프라인 · 추론 없음)

출처: 성능검증-저널 §12.67-(2) 「버튼 검출 — 네 클래스는 오분류 0, B3 만 EMO 로 반복 오분류된다」.
당시 채점 스크립트가 저장되지 않아(§12.72-(2)) 기술된 방법을 다시 구현하고, VGA 기준선
세션에서 §12.67-(2) 값을 재현하는지 먼저 확인한 뒤 쓰도록 만들었다.

왜 자리 기준인가
    「그 클래스 이름이 붙은 박스가 나온 프레임 수」는 정확도가 아니다 — 정답표가 없으면
    B3 를 EMO 라고 불러도 EMO 검출로 세어진다. 콘솔은 고정이라 버튼마다 자리가 정해져 있으므로
    「직전에 각 버튼이 있던 자리에 지금 붙은 이름이 맞는가」로 센다.

방법 1 — 자리 기준 채점 (확정 오분류 · 하한)
    - 기억: 프레임마다 클래스별 **최고 score 박스 1개**(score ≥ --thr)의 중심을 기억한다.
    - 채점: score ≥ --thr 인 검출 d 마다, 직전 --window(기본 3) 프레임 안에 기억된 자리 중
      d 중심에서 반경 R 안에 있는 클래스 집합 C 를 구한다.
        C 가 비었음            → 채점 안 함(직전 자리 불명)
        d 의 이름 ∈ C          → 정답
        C 가 한 클래스 t 뿐    → 오분류 t→d 이름
        C 가 둘 이상(d 이름 없음) → 채점 안 함(자리 불확실)
      직전 자리가 확실할 때만 세므로 **하한**이다. 가짜 EMO 가 진짜 EMO 보다 score 가 높으면
      EMO 자리 기억이 B3 자리로 옮겨가 그 뒤 몇 프레임은 오히려 EMO→B3 로 세어질 수 있다.
    - 반경 R = 25px × (프레임 긴 변 / 640). rawdet 좌표는 왜곡보정·CCW90 회전 **뒤** 세로 프레임
      (VGA 480×640 · XGA 768×1024) 좌표이므로 긴 변은 640 또는 1024 → XGA 에서 40px.
      긴 변은 raw/<세션>/ 의 첫 PNG 헤더에서 읽고, PNG 가 없으면 좌표 최댓값(>640 이면 1024)으로 정한다.

방법 2 — 넓게 센 가짜 EMO (참고 · §12.67-(2) 「B3 자리 근접·B3 박스와 겹침(IoU>0.3) 포함」)
    EMO 박스가 ① 직전 --alt-window(기본 10) 프레임 안의 B3 자리(모든 raw B3 · score ≥0.5)
    반경 R 안에 있거나 ② 같은 프레임 B3 박스와 IoU > 0.3 이면 가짜 EMO 로 센다.
    score ≥0.5 / ≥0.65 / ≥0.80 건수와 score median·max 를 낸다.
    ⚠️ 원 스크립트의 B3 자리 기억 길이가 기록에 없다 — 10프레임은 VGA 기준선에 맞춰 고른 값이다.

분모
    「프레임」= rawdet 에 검출이 1건 이상 있는 프레임 수(§12.67-(2) 의 8,453 이 이 정의다 —
    S1·S2·S6·S5 + S3 공구 4개 세션). 저장 프레임 수(max frame)도 같이 낸다.

사용 예
    python3 b3emo_score.py '20260923_1400*_s1-still-*' '20260923_14013*_s2-move-*'
    python3 b3emo_score.py '20260923_18*_xga-rt-*' '20260923_19*_xga-rt-*' --events
장면은 세션 이름의 s<숫자> 로 묶는다(없으면 세션 이름 그대로).
"""
import argparse
import csv
import glob
import math
import os
import re
import statistics
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config          # noqa: E402 — 확정 기준은 런타임과 같은 값(측정도구 규칙: 도구는 config 에서 읽는다)
import frame_orient    # noqa: E402 — 픽셀 배율 단일 출처(px_scale)

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES = ["B1", "B2", "B3", "B4", "EMO"]
SUFFIX = "_rawdet_log.csv"


def resolve(patterns, logs_dir):
    out = []
    for pat in patterns:
        pat = os.path.basename(pat)
        if pat.endswith(SUFFIX):
            pat = pat[: -len(SUFFIX)]
        hits = sorted(glob.glob(os.path.join(logs_dir, pat + "*" + SUFFIX)))
        if not hits:
            raise SystemExit(f"[오류] 일치하는 rawdet 로그 없음: {pat}")
        out += [h for h in hits if h not in out]
    return out


def load(path):
    frames = defaultdict(list)
    for r in csv.DictReader(open(path)):
        box = tuple(float(r[k]) for k in ("x1", "y1", "x2", "y2"))
        frames[int(r["frame"])].append((r["cls_name"], float(r["score"]), box))
    return frames


def long_side(session, frames, raw_dir):
    d = os.path.join(raw_dir, session)
    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    if pngs:
        with open(pngs[0], "rb") as f:
            head = f.read(24)
        w, h = struct.unpack(">II", head[16:24])
        return max(w, h), "PNG"
    mx = max((max(b[2], b[3]) for dets in frames.values() for _, _, b in dets), default=0)
    return (1024 if mx > 640 else 640), "좌표"


def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def score_position(frames, radius, thr, window):
    """방법 1. 반환 = (클래스별 Counter{(cls, 정답여부)}, 오분류 Counter{(참, 예측)}, 사건 목록)."""
    hist = {}
    res, conf, events = Counter(), Counter(), []
    for f in sorted(frames):
        mem = defaultdict(list)
        for g in range(f - window, f):
            for c, pts in hist.get(g, {}).items():
                mem[c] += pts
        for c, s, b in frames[f]:
            if s < thr:
                continue
            p = center(b)
            cands = {k for k, pts in mem.items() if any(math.dist(p, q) <= radius for q in pts)}
            if not cands:
                continue
            if c in cands:
                res[(c, True)] += 1
            elif len(cands) == 1:
                t = next(iter(cands))
                res[(t, False)] += 1
                conf[(t, c)] += 1
                events.append((f, t, c, s))
        best = {}
        for c, s, b in frames[f]:
            if s >= thr and (c not in best or s > best[c][0]):
                best[c] = (s, center(b))
        hist[f] = {c: [v[1]] for c, v in best.items()}
    return res, conf, events


def score_alt(frames, radius, window, iou_thr=0.3):
    """방법 2. 가짜 EMO 로 볼 EMO 박스들의 score 목록."""
    b3_hist, scores = [], []
    for f in sorted(frames):
        b3_now = [b for c, _, b in frames[f] if c == "B3"]
        b3_mem = [q for g, q in b3_hist if f - g <= window]
        for c, s, b in frames[f]:
            if c != "EMO":
                continue
            p = center(b)
            if any(math.dist(p, q) <= radius for q in b3_mem) or any(iou(b, x) > iou_thr for x in b3_now):
                scores.append(s)
        b3_hist += [(f, center(b)) for c, _, b in frames[f] if c == "B3"]
    return scores


def scene_of(session):
    m = re.search(r"[_-]s(\d+)[-_]", session)
    return f"S{m.group(1)}" if m else session


def pct(res, c):
    ok, bad = res[(c, True)], res[(c, False)]
    n = ok + bad
    return f"{100 * ok / n:.1f}% ({bad}/{n})" if n else "—"


def main():
    ap = argparse.ArgumentParser(description="B3→EMO 자리 기준 채점 (§12.67-(2) 재현)")
    ap.add_argument("sessions", nargs="+", help="세션 이름 또는 glob (…_rawdet_log.csv 앞부분)")
    ap.add_argument("--thr", type=float, default=config.YOLO_CONF_HIGH,
                    help=f"채점 score 기준 (기본 = 런타임 확정 기준 config.YOLO_CONF_HIGH {config.YOLO_CONF_HIGH})")
    ap.add_argument("--radius-base", type=float, default=25.0, help="VGA(긴 변 640) 기준 반경 px (기본 25)")
    ap.add_argument("--window", type=int, default=3, help="직전 자리 기억 프레임 수 (기본 3)")
    ap.add_argument("--alt-window", type=int, default=10, help="방법 2 의 B3 자리 기억 프레임 수 (기본 10)")
    ap.add_argument("--logs", default=os.path.join(HERE, "logs"))
    ap.add_argument("--raw", default=os.path.join(HERE, "raw"))
    ap.add_argument("--events", action="store_true", help="오분류 사건(프레임·score)을 모두 출력")
    args = ap.parse_args()

    paths = resolve(args.sessions, args.logs)
    by_scene = defaultdict(lambda: {"res": Counter(), "conf": Counter(), "frames": 0, "saved": 0})
    tot_conf, alt_scores = Counter(), []
    tot_frames = tot_saved = 0

    print("세션별")
    for path in paths:
        sess = os.path.basename(path)[: -len(SUFFIX)]
        frames = load(path)
        ls, src = long_side(sess, frames, args.raw)
        radius = args.radius_base * frame_orient.px_scale(ls, 0)
        res, conf, events = score_position(frames, radius, args.thr, args.window)
        alt = score_alt(frames, radius, args.alt_window)
        nf, saved = len(frames), max(frames, default=0)
        sc = by_scene[scene_of(sess)]
        sc["res"] += res
        sc["conf"] += conf
        sc["frames"] += nf
        sc["saved"] += saved
        tot_conf += conf
        alt_scores += alt
        tot_frames += nf
        tot_saved += saved
        print(f"  {sess}  긴변 {ls}({src}) R={radius:.0f}px  검출프레임 {nf}/{saved}  "
              f"B3→EMO {conf[('B3', 'EMO')]}  EMO→B3 {conf[('EMO', 'B3')]}  "
              f"기타 {sum(v for k, v in conf.items() if k not in (('B3', 'EMO'), ('EMO', 'B3')))}  "
              f"넓게(≥{args.thr}) {sum(s >= args.thr for s in alt)}")
        if args.events:
            for f, t, c, s in events:
                print(f"      f{f:05d}  {t}→{c}  score {s:.4f}")

    print(f"\n방법 1 — 자리 기준 (score ≥{args.thr} · 직전 {args.window}프레임 · 반경 {args.radius_base:g}px×긴변/640)")
    print("| 장면 | " + " | ".join(CLASSES) + " | B3→EMO | EMO→B3 | 검출 프레임 |")
    print("|---|" + "---|" * (len(CLASSES) + 3))
    for name in sorted(by_scene):
        sc = by_scene[name]
        print(f"| {name} | " + " | ".join(pct(sc["res"], c) for c in CLASSES)
              + f" | {sc['conf'][('B3', 'EMO')]} | {sc['conf'][('EMO', 'B3')]} | {sc['frames']} |")
    b3emo, emob3 = tot_conf[("B3", "EMO")], tot_conf[("EMO", "B3")]
    others = {k: v for k, v in tot_conf.items() if k not in (("B3", "EMO"), ("EMO", "B3"))}
    print(f"\n합계  B3→EMO {b3emo} · EMO→B3 {emob3} · 기타 조합 {others or 0}")
    print(f"      검출 프레임 {tot_frames} (저장 프레임 {tot_saved})  →  B3→EMO 비율 "
          f"{b3emo}/{tot_frames} = {100 * b3emo / max(1, tot_frames):.3f}%")

    print(f"\n방법 2 — 넓게 (B3 자리 직전 {args.alt_window}프레임 근접 또는 B3 박스 IoU>0.3)")
    for t in (0.5, 0.65, 0.80):
        print(f"  ≥{t:.2f}: {sum(s >= t for s in alt_scores)}건")
    if alt_scores:
        print(f"  가짜 EMO score median {statistics.median(alt_scores):.2f} · max {max(alt_scores):.2f}"
              f" (n={len(alt_scores)}, ≥0.5)")


if __name__ == "__main__":
    main()
