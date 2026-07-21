"""HOI(손 검출) 경로 실증 프로브 — Hailo 팜검출 + 핸드랜드마크.

왜 있나:
    MediaPipe가 Python 3.13/aarch64 휠을 제공하지 않아 손 검출이 막혀 있었다(§10.6·§4 NFR-1).
    그런데 MediaPipe의 손 모델(BlazePalm + BlazeHandLandmark)은 이미 Hailo로 포팅돼 있고,
    그 경로는 `hailo_platform`+numpy+cv2만 쓴다 — **mediapipe 패키지가 아예 불필요**하다.
    이 스크립트는 그 경로가 이 파이에서 실제로 도는지, 그리고 console_v2와 동시 구동이
    가능한지를 **기존 런타임 코드를 건드리지 않고** 확인한다.

    🔴 이것은 실증 프로브지 런타임 통합이 아니다. 채택 여부는 측정 후 사람이 결정한다.

사용:
    # 손 랜드마크가 나오는지 (정지 이미지)
    python3 test/hoi_probe.py --image test/raw/<세션>/f00203.png

    # console_v2와 동시 로드·FPS 측정
    python3 test/hoi_probe.py --image <png> --with-console --frames 30

전제:
    ~/hoi_probe/hailo8/{palm_detection_lite,hand_landmark_lite}.hef
    ~/hoi_probe/blaze_app_python/  (blaze_hailo·blaze_common)
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BLAZE = os.path.expanduser("~/hoi_probe/blaze_app_python")
_MODELS = os.path.expanduser("~/hoi_probe/hailo8")

sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_BLAZE, "blaze_common"))
sys.path.insert(0, os.path.join(_BLAZE, "blaze_hailo"))


def load_hand_models(hailo_infer, verbose=False):
    """팜·핸드 모델을 한 번만 로드한다.

    ⚠️ 반복 호출 금지 — 매 프레임 load_model 하면 VDevice 자원이 고갈돼
    HailoRTInvalidOperationException 이 난다(실측 확인). 모델 로드는 1회, 추론만 반복.
    """
    from blazedetector import BlazeDetector
    from blazelandmark import BlazeLandmark

    det = BlazeDetector("blazepalm", hailo_infer)
    det.set_debug(debug=verbose)
    det.load_model(os.path.join(_MODELS, "palm_detection_lite.hef"))

    lm = BlazeLandmark("blazehandlandmark", hailo_infer)
    lm.set_debug(debug=verbose)
    lm.load_model(os.path.join(_MODELS, "hand_landmark_lite.hef"))
    return det, lm


def run_hand(image_bgr, det, lm):
    """팜 검출 → ROI 추출 → 21점 랜드마크. blaze_app_python 의 흐름을 그대로 따른다."""
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    img1, scale1, pad1 = det.resize_pad(rgb)
    norm_det = det.predict_on_image(img1)
    if len(norm_det) == 0:
        return [], None

    dets = det.denormalize_detections(norm_det, scale1, pad1)
    xc, yc, sc, theta = det.detection2roi(dets)
    roi_img, roi_affine, roi_box = lm.extract_roi(rgb, xc, yc, theta, sc)
    # 손 모델은 (flag, landmarks, handedness) 3값, 그 외는 2값을 돌려준다.
    res = lm.predict(roi_img)
    flags, norm_lm = res[0], res[1]
    landmarks = lm.denormalize_landmarks(norm_lm, roi_affine)
    return landmarks, flags


def run_batch(dirpath, infer):
    """폴더 전량에 손 검출을 돌려 검출률·신뢰도를 집계한다.

    이 프로젝트에서 중요한 건 "손이 있으면 찾는가"이므로, 정답 라벨이 없는 상태에서는
    검출률과 score 분포가 신뢰도의 대리 지표다. (정확한 랜드마크 위치 평가는 별도 과제)
    """
    import statistics as st
    det, lm = load_hand_models(infer)
    files = sorted(f for f in os.listdir(dirpath) if f.endswith(".png"))
    hits, scores, times, nhands = 0, [], [], []
    for f in files:
        img = cv2.imread(os.path.join(dirpath, f))
        if img is None:
            continue
        t0 = time.perf_counter()
        landmarks, flags = run_hand(img, det, lm)
        times.append(time.perf_counter() - t0)
        if len(landmarks):
            hits += 1
            nhands.append(len(landmarks))
            if flags is not None:
                scores.append(float(np.max(flags)))
    n = len(files)
    print(f"\n【배치 결과】 {os.path.basename(dirpath)}  {n}장")
    print(f"  손 검출 프레임 : {hits}/{n}  ({hits/n*100:.1f}%)")
    if scores:
        print(f"  landmark score : 평균 {st.fmean(scores):.3f}  "
              f"min {min(scores):.3f}  median {st.median(scores):.3f}")
    if nhands:
        print(f"  프레임당 손 수 : 평균 {st.fmean(nhands):.2f}  최대 {max(nhands)}")
    print(f"  처리 시간      : 평균 {st.fmean(times)*1000:.1f}ms → {1/st.fmean(times):.1f} fps")
    return 0


def main():
    ap = argparse.ArgumentParser(description="HOI 경로 실증 프로브")
    ap.add_argument("--image", help="입력 PNG (기존 raw 프레임 재사용)")
    ap.add_argument("--batch", metavar="DIR",
                    help="폴더 내 PNG 전량에 대해 손 검출률·접촉 판정을 집계(신뢰도 측정용)")
    ap.add_argument("--with-console", action="store_true",
                    help="console_v2.hef 를 같은 VDevice 에 함께 로드해 동시 구동 확인")
    ap.add_argument("--frames", type=int, default=0, help=">0 이면 그 횟수만큼 반복해 FPS 측정")
    ap.add_argument("--viz", default=None, metavar="PNG",
                    help="손 랜드마크 + console_v2 버튼 박스를 겹쳐 그린 이미지를 저장 "
                         "(두 좌표계가 실제로 맞는지 눈으로 확인하는 용도)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if not args.image and not args.batch:
        print("--image 또는 --batch 중 하나가 필요합니다.")
        return 2

    from hailo_inference import HailoInference
    infer = HailoInference()

    if args.batch:
        return run_batch(args.batch, infer)

    img = cv2.imread(args.image)
    if img is None:
        print(f"❌ 이미지를 읽을 수 없습니다: {args.image}")
        return 2
    print(f"입력: {os.path.basename(args.image)}  {img.shape[1]}x{img.shape[0]}\n")

    # console_v2 동시 로드 — 같은 VDevice 에 세 번째 모델을 얹을 수 있는지가 핵심 질문이다.
    console_id = None
    if args.with_console:
        import config
        try:
            console_id = infer.load_model(config.HEF_MODEL_PATH)
            print(f"✅ console_v2 동시 로드 성공 (id={console_id})")
        except Exception as e:
            print(f"❌ console_v2 동시 로드 실패: {type(e).__name__}: {e}")
            print("   → 세 모델 동시 구동 불가. 구조 변경(스케줄러) 필요성의 근거.")

    det, lm = load_hand_models(infer, args.verbose)
    t0 = time.perf_counter()
    landmarks, flags = run_hand(img, det, lm)
    dt = time.perf_counter() - t0

    print(f"\n【손 검출 결과】 ({dt*1000:.0f}ms)")
    if len(landmarks) == 0:
        print("  손 검출 0건 — 이 프레임에 손이 없거나 경로가 동작하지 않음")
    else:
        print(f"  손 {len(landmarks)}개 · 랜드마크 {landmarks[0].shape}")
        # MediaPipe 손 랜드마크 인덱스 8 = 검지 끝(INDEX_FINGER_TIP). 접촉 판정의 기준점.
        for i, hand in enumerate(landmarks):
            tip = hand[8]
            print(f"  손{i}: 검지끝 = ({tip[0]:.0f}, {tip[1]:.0f})"
                  + (f"  score={flags[i][0]:.3f}" if flags is not None else ""))

    if args.viz:
        vis = img.copy()
        # console_v2 검출을 bench.db 에서 가져와 같은 캔버스에 그린다.
        # 두 좌표계가 어긋나 있으면 여기서 바로 드러난다.
        import re
        import sqlite3
        m = re.search(r"/([^/]+)/f(\d+)\.png$", os.path.abspath(args.image))
        if m:
            db = os.path.join(_DEMO, "test", "bench.db")
            if os.path.exists(db):
                con = sqlite3.connect(db)
                for cls, x1, y1, x2, y2 in con.execute(
                        "SELECT cls_name,x1,y1,x2,y2 FROM rawdet WHERE session_id=? AND frame=?",
                        (m.group(1), int(m.group(2)))):
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(vis, cls, (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        for hand in landmarks:
            for x, y, _ in hand:
                cv2.circle(vis, (int(x), int(y)), 2, (0, 0, 255), -1)
            tx, ty = int(hand[8][0]), int(hand[8][1])
            cv2.circle(vis, (tx, ty), 7, (255, 0, 255), 2)     # 검지 끝 강조
            cv2.putText(vis, "tip", (tx + 9, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
        cv2.imwrite(args.viz, vis)
        print(f"\n시각화 저장: {args.viz}  (초록=console_v2 버튼 / 빨강=손 21점 / 자홍=검지끝)")

    if args.frames > 0:
        ts = []
        for _ in range(args.frames):
            s = time.perf_counter()
            run_hand(img, det, lm)          # 모델은 위에서 이미 로드됨 — 추론만 반복
            ts.append(time.perf_counter() - s)
        m = float(np.mean(ts))
        print(f"\n【FPS】 {args.frames}회 · 평균 {m*1000:.1f}ms → {1/m:.1f} fps"
              f"  (min {min(ts)*1000:.0f} / max {max(ts)*1000:.0f}ms)")
        print("  ⚠️ 모델 파이프라인 상한이지 실시간 FPS가 아니다 — 실제 병목은 ESP32 경로(§10.11)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
