"""USB 웹캠 노출값 튜닝 — 정반사로 버튼 색이 날아가지 않는 exposure를 고른다.

배경: 아케이드 버튼은 표면이 광택이라 조명이 정반사되면 버튼 면이 하얗게 포화된다.
      B1(노랑)·B2(흰)·B3(핑크)는 형태가 같고 색으로만 구분되므로, 포화가 생기면
      전부 "흰 버튼 = B2"로 오분류된다(2026-07-10 실측: USB confirmed 트랙의 94%가 B2).
      웹캠 자동노출(AE)은 이 포화를 막아주지 못하므로 수동 고정이 필요하다.

사용법:
    cd ~/sop-project/Rpi5/Demo
    python3 test/tune_exposure.py                      # 기본 스윕 + 샘플 이미지 저장
    python3 test/tune_exposure.py --roi 200,100,440,400  # 버튼 영역만 평가(권장)

    → test/exposure_samples/exp_<값>.png 를 눈으로 확인해
      버튼 색(노랑·핑크)이 살아있는 가장 밝은 값을 고른다.

    고른 값으로 벤치 실행:
    python3 test/bench_detector.py --source usb --lock-exposure --exposure <값>
"""

import argparse
import os
import subprocess
import time

import cv2

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_OUT_DIR  = os.path.join(_TEST_DIR, "exposure_samples")

DEFAULT_SWEEP = [20, 40, 60, 80, 100, 120, 157, 200, 250, 320, 400]


def _setc(dev, name, val):
    subprocess.run(["v4l2-ctl", "-d", dev, "-c", f"{name}={val}"],
                   capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description="USB 웹캠 노출 스윕 — 포화 없는 값 찾기")
    ap.add_argument("--index", type=int, default=0, help="웹캠 장치 인덱스")
    ap.add_argument("--wb", type=int, default=4600, help="white_balance_temperature (K)")
    ap.add_argument("--roi", type=str, default=None,
                    help="평가 영역 x1,y1,x2,y2 (버튼 패널만 지정하면 정확도↑)")
    ap.add_argument("--values", type=str, default=None,
                    help="스윕할 exposure 목록 (쉼표구분). 기본 20~400")
    args = ap.parse_args()

    dev = f"/dev/video{args.index}"
    sweep = [int(v) for v in args.values.split(",")] if args.values else DEFAULT_SWEEP
    roi = tuple(int(v) for v in args.roi.split(",")) if args.roi else None

    os.makedirs(_OUT_DIR, exist_ok=True)

    cap = cv2.VideoCapture(args.index)
    if not cap.isOpened():
        print(f"웹캠(index {args.index}) 열기 실패.")
        return

    # 자동 해제 — auto_exposure=1(Manual)을 먼저 걸어야 exposure_time_absolute가 활성화된다.
    _setc(dev, "auto_exposure", 1)
    _setc(dev, "white_balance_automatic", 0)
    _setc(dev, "white_balance_temperature", args.wb)

    print(f"장치 {dev}  WB {args.wb}K 고정  ROI {roi or '전체'}\n")
    print(f"{'exposure':>9} {'평균밝기':>9} {'포화≥250':>10} {'판정':>8}")
    print("-" * 42)

    for e in sweep:
        _setc(dev, "exposure_time_absolute", e)
        time.sleep(0.4)
        for _ in range(5):        # 설정 반영 대기 (버퍼 비우기)
            cap.read()
        ok, frame = cap.read()
        if not ok:
            continue

        eval_area = frame
        if roi:
            x1, y1, x2, y2 = roi
            eval_area = frame[y1:y2, x1:x2]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        gray = cv2.cvtColor(eval_area, cv2.COLOR_BGR2GRAY)
        mean = gray.mean()
        blown = (gray >= 250).mean() * 100

        # 포화 1% 미만이면 색이 보존된다고 본다(경험칙).
        verdict = "✅ 양호" if blown < 1.0 else ("⚠ 주의" if blown < 5.0 else "❌ 포화")
        print(f"{e:>9} {mean:>9.1f} {blown:>9.1f}% {verdict:>8}")

        cv2.imwrite(os.path.join(_OUT_DIR, f"exp_{e:03d}.png"), frame)

    cap.release()
    print(f"\n샘플 이미지: test/exposure_samples/exp_*.png")
    print("→ 버튼 색(노랑·핑크)이 살아있는 가장 밝은 값을 고르세요.")
    print("   너무 어두우면 B4(검정)가 배경에 묻히고, 너무 밝으면 B1·B3가 B2로 오분류됩니다.")


if __name__ == "__main__":
    main()
