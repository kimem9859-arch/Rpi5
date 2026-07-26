"""raw 세션 전량에 손 검출을 돌려 프레임별 결과를 캐시한다 (HOI DB 1단계).

왜 별도 단계인가:
    팜 추론은 세션당 3~10분이라 22세션 × 임계 2개면 1~2시간이다. 그런데 입력(raw PNG)이
    정본이라 **한 번 만들면 바뀌지 않는다.** 반면 DB 재구축(`hoi_import.py`)은 판정 규칙이
    바뀔 때마다 다시 돌리고 싶다. 둘을 묶으면 재구축마다 1~2시간이 붙어 **아무도 재구축하지
    않게 되므로** 캐시를 사이에 둔다.

사용:
    python3 test/hoi_probe_batch.py --thresh 0.5          # 전 세션 (이미 있는 캐시는 스킵)
    python3 test/hoi_probe_batch.py --thresh 0.2
    python3 test/hoi_probe_batch.py --thresh 0.5 --only far-high --force

산출:
    test/palm_cache/<세션>_t{임계}_ring{링}.csv  (gitignore)

🔴 임계는 파이프라인에 대입해 **임계별로 다시 돌린다** — 한 번 돌린 뒤 점수로 걸러내는
   방식이 아니다. `blazepalm` 의 가중 NMS 가 임계 아래 앵커까지 섞어 평균내므로, 게이트를
   열어놓고 내부 점수를 읽으면 **반대 결론이 난다**(통합문서 §10.25 방법론 함정).

⚠️ `--thresh` 는 필수다. 이 임계는 `blaze_app_python` 설정 안에 있어 `config.py` 에
   노출돼 있지 않다(§10.25) — 기본값을 두면 그 값이 어디서 왔는지 추적이 끊긴다.

설계: docs/superpowers/specs/2026-07-26-HOI-DB-design.md
"""

import argparse
import csv
import os
import sys

import cv2
import numpy as np

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_TEST_DIR)
RAW_DIR = os.path.join(_TEST_DIR, "raw")
LOGS_DIR = os.path.join(_TEST_DIR, "logs")
CACHE_DIR = os.path.join(_TEST_DIR, "palm_cache")

sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, _TEST_DIR)

import config                                        # noqa: E402
import roi_zones                                     # noqa: E402  판정 규칙 단일 출처

TIP = 8          # 검지 끝 랜드마크 인덱스 (blaze 규약)
COLUMNS = ["frame", "n_palm", "flag", "tip_x", "tip_y",
           "palm_cx", "palm_cy", "palm_size", "zone_label", "zone_level"]


def cache_path(session, thresh, ring):
    return os.path.join(CACHE_DIR, f"{session}_t{thresh}_ring{ring}.csv")


def load_button_boxes(session):
    """rawdet 로그 → {frame: [(cls, x1,y1,x2,y2)]}.

    ROI 구역 판정에 필요하다. 로그가 없으면 빈 dict — zone 은 NULL 로 남는다.
    """
    path = os.path.join(LOGS_DIR, f"{session}_rawdet_log.csv")
    boxes = {}
    if not os.path.exists(path):
        return boxes
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            boxes.setdefault(int(r["frame"]), []).append(
                (r["cls_name"], int(r["x1"]), int(r["y1"]), int(r["x2"]), int(r["y2"])))
    return boxes


def probe_session(raw_dir, session, det, lm, thresh, ring):
    """세션 하나의 전 프레임에 손 검출 + ROI 구역 판정. → 행 목록."""
    boxes = load_button_boxes(session)
    rows = []
    for name in sorted(f for f in os.listdir(raw_dir) if f.endswith(".png")):
        frame = int(name[1:6])
        img = cv2.imread(os.path.join(raw_dir, name))
        if img is None:
            continue
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img1, scale1, pad1 = det.resize_pad(rgb)
        norm_det = det.predict_on_image(img1)

        n_palm = len(norm_det)
        flag = tip_x = tip_y = pcx = pcy = psz = None
        zone_label = zone_level = None

        if n_palm:
            dets = det.denormalize_detections(norm_det, scale1, pad1)
            xc, yc, sc, theta = det.detection2roi(dets)
            pcx, pcy, psz = float(xc[0]), float(yc[0]), float(sc[0])
            roi_img, roi_affine, roi_box = lm.extract_roi(rgb, xc, yc, theta, sc)
            res = lm.predict(roi_img)
            flags, norm_lm = res[0], res[1]
            landmarks = lm.denormalize_landmarks(norm_lm, roi_affine)
            if flags is not None and len(flags):
                flag = float(np.max(flags))
            if len(landmarks):
                tip_x = float(landmarks[0][TIP][0])
                tip_y = float(landmarks[0][TIP][1])
                # 🔴 판정은 roi_zones 가 한다 — 여기에 링 규칙을 다시 쓰지 않는다.
                if frame in boxes:
                    zone_label, zone_level = roi_zones.zone_at_point(
                        tip_x, tip_y, boxes[frame], ring)

        rows.append([frame, n_palm, flag, tip_x, tip_y,
                     pcx, pcy, psz, zone_label, zone_level])
    return rows


def write_cache(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"                 # 중단 시 반쪽 캐시가 남지 않도록
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(
        description="raw 세션 전량 손 검출 → palm_cache (HOI DB 1단계)")
    ap.add_argument("--thresh", type=float, required=True,
                    help="팜 검출 임계(blazepalm min_score_thresh). 필수 — config에 없는 값이다")
    ap.add_argument("--ring", type=int, default=None,
                    help="ROI 링 폭 px. 기본 = config.HAND_ROI_RING_PX(런타임과 동일)")
    ap.add_argument("--only", type=str, default=None,
                    help="세션 이름에 이 문자열이 든 것만 처리(부분일치)")
    ap.add_argument("--force", action="store_true", help="이미 있는 캐시도 다시 만든다")
    args = ap.parse_args()

    ring = args.ring if args.ring is not None else config.HAND_ROI_RING_PX

    # 대상 = raw 폴더가 있고 GPIO 눌림 로그도 있는 세션 (HOI 분석 대상의 정의)
    sessions = []
    for name in sorted(os.listdir(RAW_DIR)):
        if not os.path.isdir(os.path.join(RAW_DIR, name)):
            continue
        if not os.path.exists(os.path.join(LOGS_DIR, f"{name}_gpio_log.csv")):
            continue
        if args.only and args.only not in name:
            continue
        sessions.append(name)

    if not sessions:
        print("❌ 대상 세션이 없습니다 (raw + gpio 로그 둘 다 있어야 합니다)")
        return 2

    todo = [s for s in sessions
            if args.force or not os.path.exists(cache_path(s, args.thresh, ring))]
    print(f"팜 임계 {args.thresh} · 링 {ring}px")
    print(f"대상 {len(sessions)}세션 · 처리 {len(todo)} · 스킵 {len(sessions) - len(todo)}\n")
    if not todo:
        print("✅ 모두 캐시되어 있습니다 (--force 로 재생성)")
        return 0

    from hoi_probe import load_hand_models          # blaze 경로 주입 부작용이 있어 여기서
    from hailo_inference import HailoInference
    det, lm = load_hand_models(HailoInference())
    det.min_score_thresh = args.thresh              # 🔴 파이프라인에 대입 (사후 필터링 아님)
    print(f"모델 로드 완료 (적용 임계 {det.min_score_thresh})\n")

    for i, session in enumerate(todo, 1):
        out = cache_path(session, args.thresh, ring)
        rows = probe_session(os.path.join(RAW_DIR, session), session, det, lm,
                             args.thresh, ring)
        write_cache(out, rows)
        hit = sum(1 for r in rows if r[1])
        print(f"[{i}/{len(todo)}] {session}  {len(rows)}프레임 · 팜검출 {hit} "
              f"({hit / max(len(rows), 1) * 100:.1f}%) → {os.path.basename(out)}", flush=True)

    print(f"\n✅ {len(todo)}세션 캐시 완료 → {CACHE_DIR}")
    print("   다음: python3 test/hoi_import.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
