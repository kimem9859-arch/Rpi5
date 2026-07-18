"""저장된 raw 프레임(test/raw/<세션>)에 .hef를 재생해 검출을 재분석한다.

왜 필요한가:
    bench_detector.py가 저장하는 mp4는 **검출 오버레이가 그려진** 화면이라 재추론에 못 쓴다.
    `--save-raw`로 남긴 무손실 PNG(= detector.detect()에 건네진 바로 그 배열)가 있어야
    카메라·조명·삼각대를 다시 세우지 않고도 같은 입력에 다른 모델·다른 조건을 돌릴 수 있다.

주 용도:
    1. **console_v2 평가** — console_v1이 B4를 놓친 그 ESP32 프레임에 v2를 그대로 먹여 비교.
       `python3 test/replay_raw.py test/raw/<세션> --hef models/console_v2.hef`
    2. **요인 분리 재현**(§10.9) — 입력을 인위적으로 열화시켜 어느 요인이 검출을 죽이는지.
       `python3 test/replay_raw.py test/raw/<세션> --jpeg 30`
       `python3 test/replay_raw.py test/raw/<세션> --scale 0.74`
       `python3 test/replay_raw.py test/raw/<세션> --blur 0.8`
       `python3 test/replay_raw.py test/raw/<세션> --ablation`   # 조건 일괄 비교
    3. **임계값 튜닝** — 재촬영 없이 YOLO_CONF_HIGH 후보를 바꿔가며 confirm 통과율 확인.

주의:
    B4는 JPEG q90·블러 σ0.8·5% 리샘플만으로 사라진다(§10.9). 열화 옵션은 **분석용**이며,
    raw 자체는 절대 손실 압축으로 저장하지 않는다.
"""

import argparse
import collections
import csv
import datetime
import json
import os
import re
import statistics
import sys

import cv2
import numpy as np

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _DEMO_DIR)

import config  # noqa: E402

CLASS_NAMES = ["B1", "B2", "B3", "B4", "EMO"]


# =============================================================================
# 입력 열화 (요인 분리용)
# =============================================================================
def _jpeg(img, q):
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR) if ok else img


def _scale(img, s):
    """s배로 축소했다가 원래 크기로 복원 — 해상도(고주파) 손실을 흉내낸다."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _blur(img, sigma):
    return cv2.GaussianBlur(img, (0, 0), sigma) if sigma > 0 else img


def _make_degrade(jpeg_q, scale_s, blur_s):
    def fn(img):
        if scale_s and scale_s != 1.0:
            img = _scale(img, scale_s)
        if blur_s:
            img = _blur(img, blur_s)
        if jpeg_q:
            img = _jpeg(img, jpeg_q)
        return img
    return fn


# =============================================================================
def _load_frames(raw_dir, limit=None):
    names = sorted(n for n in os.listdir(raw_dir) if n.endswith(".png"))
    if limit:
        names = names[:limit]
    frames = []
    for n in names:
        img = cv2.imread(os.path.join(raw_dir, n), cv2.IMREAD_COLOR)
        if img is not None:
            frames.append((n, img))
    return frames


def _frame_no(png_name):
    m = re.search(r"(\d+)", png_name)
    return int(m.group(1)) if m else -1


def _run(detector, frames, degrade, conf_high, csv_writer=None):
    """반환: 클래스별 (검출수, 검출프레임수, score리스트). csv_writer가 있으면 검출별 행 기록."""
    counts = collections.Counter()
    hits   = collections.defaultdict(set)
    scores = collections.defaultdict(list)
    for name, img in frames:
        for cls_id, score, *box in detector.detect(degrade(img) if degrade else img):
            cn = CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else str(cls_id)
            counts[cn] += 1
            hits[cn].add(name)
            scores[cn].append(score)
            if csv_writer:
                x1, y1, x2, y2 = (list(box) + [None] * 4)[:4]
                csv_writer.writerow([_frame_no(name), cn, f"{score:.4f}", x1, y1, x2, y2])
    return counts, hits, scores


def _open_csv(raw_dir, hef_path, conf_high, degrade_label):
    """logs/replay/에 검출 CSV 생성 — db_import.py가 '# meta:' 줄을 읽어 적재한다."""
    replay_dir = os.path.join(_TEST_DIR, "logs", "replay")
    os.makedirs(replay_dir, exist_ok=True)
    run_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session = os.path.basename(os.path.normpath(raw_dir))
    hef = os.path.basename(hef_path)
    path = os.path.join(replay_dir, f"{run_ts}_{os.path.splitext(hef)[0]}_{session}.csv")
    f = open(path, "w", newline="")
    meta = {"run_ts": run_ts, "session": session, "hef": hef,
            "conf_high": conf_high, "conf_low": config.YOLO_CONF_LOW,
            "degrade": degrade_label}
    f.write("# meta: " + json.dumps(meta, ensure_ascii=False) + "\n")
    w = csv.writer(f)
    w.writerow(["frame", "cls_name", "score", "x1", "y1", "x2", "y2"])
    return f, w, path


def _report(label, frames, counts, hits, scores, conf_high):
    n = len(frames)
    print(f"\n[{label}]  {n}프레임")
    print(f"  {'cls':<5}{'검출':>7}{'프레임율':>10}{'median':>9}{'max':>8}{'≥conf_high':>12}")
    for c in CLASS_NAMES:
        s = scores[c]
        if not s:
            print(f"  {c:<5}{0:>7}{'0.0%':>10}{'-':>9}{'-':>8}{0:>12}")
            continue
        over = sum(1 for v in s if v >= conf_high)
        print(f"  {c:<5}{counts[c]:>7}{len(hits[c])/n*100:>9.1f}%"
              f"{statistics.median(s):>9.3f}{max(s):>8.3f}{over:>12}")


def main():
    ap = argparse.ArgumentParser(description="저장된 raw 프레임에 .hef 재생·재분석")
    ap.add_argument("raw_dir", help="test/raw/<세션> 경로")
    ap.add_argument("--hef", default=None, help="사용할 .hef (기본 config.HEF_MODEL_PATH)")
    ap.add_argument("--limit", type=int, default=None, help="앞 N프레임만 사용")
    ap.add_argument("--jpeg", type=int, default=None, metavar="Q", help="JPEG 품질 Q로 열화")
    ap.add_argument("--scale", type=float, default=None, metavar="S", help="S배 축소→복원 열화")
    ap.add_argument("--blur", type=float, default=None, metavar="SIGMA", help="가우시안 블러 열화")
    ap.add_argument("--conf-high", type=float, default=None,
                    help="confirm 임계값 (기본 config.YOLO_CONF_HIGH)")
    ap.add_argument("--ablation", action="store_true",
                    help="§10.9 요인 분리 조건들을 일괄 비교 (원본/해상도↓/JPEG/블러)")
    ap.add_argument("--no-csv", action="store_true",
                    help="logs/replay/ 검출 CSV 기록 끄기 (기본은 기록 → db_import.py로 적재)")
    args = ap.parse_args()

    if not os.path.isdir(args.raw_dir):
        print(f"raw 디렉토리 없음: {args.raw_dir}")
        return

    mpath = os.path.join(args.raw_dir, "manifest.json")
    if os.path.exists(mpath):
        with open(mpath) as f:
            man = json.load(f)
        print(f"[manifest] source={man.get('source')}  flip={man.get('flip_mode')}  "
              f"exposure={man.get('exposure')}  backend={man.get('backend')}")
        print(f"           hef={man.get('hef_path')}  conf_high={man.get('yolo_conf_high')}")
    else:
        print("[manifest] 없음 — 촬영 조건 불명")

    if args.hef:
        config.HEF_MODEL_PATH = args.hef        # create_detector 전에 덮어써야 반영된다
    conf_high = args.conf_high or config.YOLO_CONF_HIGH

    frames = _load_frames(args.raw_dir, args.limit)
    if not frames:
        print("PNG 프레임이 없습니다.")
        return
    print(f"[raw] {len(frames)}프레임 로드  |  hef={config.HEF_MODEL_PATH}  conf_high={conf_high}")

    from detector import create_detector      # config 수정 후 import
    detector = create_detector()

    try:
        if args.ablation:
            # §10.9 재현: 각 요인이 단독으로 B4를 죽이는지.
            conds = [
                ("원본",              None),
                ("해상도↓ scale0.74", _make_degrade(None, 0.74, None)),
                ("해상도↓ scale0.95", _make_degrade(None, 0.95, None)),
                ("JPEG q30",         _make_degrade(30, None, None)),
                ("JPEG q90",         _make_degrade(90, None, None)),
                ("블러 σ0.5",         _make_degrade(None, None, 0.5)),
                ("블러 σ0.8",         _make_degrade(None, None, 0.8)),
            ]
            print(f"\n=== 요인 분리 (B4 중심) ===")
            print(f"{'조건':<18}{'B4 검출':>10}{'B4 median':>11}{'B4 max':>9}   {'B1/B2/B3/EMO 검출':>18}")
            print("-" * 72)
            for label, deg in conds:
                counts, hits, scores = _run(detector, frames, deg, conf_high)
                b4 = scores["B4"]
                med = f"{statistics.median(b4):.3f}" if b4 else "-"
                mx  = f"{max(b4):.3f}" if b4 else "-"
                oth = "/".join(str(counts[c]) for c in ["B1", "B2", "B3", "EMO"])
                print(f"{label:<18}{len(b4):>5}/{len(frames):<4}{med:>11}{mx:>9}   {oth:>18}")
        else:
            degrade = None
            parts = []
            if args.scale: parts.append(f"scale {args.scale}")
            if args.blur:  parts.append(f"blur σ{args.blur}")
            if args.jpeg:  parts.append(f"JPEG q{args.jpeg}")
            if parts:
                degrade = _make_degrade(args.jpeg, args.scale, args.blur)
            label = " + ".join(parts) if parts else "원본"
            csv_f = csv_w = csv_path = None
            if not args.no_csv:
                csv_f, csv_w, csv_path = _open_csv(
                    args.raw_dir, config.HEF_MODEL_PATH, conf_high, label)
            try:
                counts, hits, scores = _run(detector, frames, degrade, conf_high, csv_w)
            finally:
                if csv_f:
                    csv_f.close()
            _report(label, frames, counts, hits, scores, conf_high)
            if csv_path:
                print(f"\n[csv] {csv_path}  (db_import.py 실행 시 DB에 적재됨)")
    finally:
        detector.close()


if __name__ == "__main__":
    main()
