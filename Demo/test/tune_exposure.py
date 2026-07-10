"""USB 웹캠 노출값 튜닝 — 정반사로 버튼 색이 날아가지 않는 exposure를 고른다.

배경: 아케이드 버튼은 표면이 광택이라 조명이 정반사되면 버튼 면이 하얗게 포화된다.
      B1(노랑)·B2(흰)·B3(핑크)는 형태가 같고 색으로만 구분되므로, 포화가 생기면
      전부 "흰 버튼 = B2"로 오분류된다(2026-07-10 실측: USB confirmed 트랙의 94%가 B2).
      웹캠 자동노출(AE)은 이 포화를 막아주지 못하므로 수동 고정이 필요하다.

      단, WB는 자동(AWB)을 유지한다. UVC 드라이버는 색온도(R↔B) 축만 제공하고 틴트(G↔M)가
      없어 형광등 녹색 스파이크를 수동으로 못 잡는다(2026-07-10 실측: 최대 6500K에서도
      흰 버튼 G=206 vs B/R=148/145로 초록 캐스트 잔존). 자동 AWB가 더 정확했다.

사용법:
    cd ~/sop-project/Rpi5/Demo
    python3 test/tune_exposure.py --roi 250,80,490,330 --detect 20   # 권장
    python3 test/tune_exposure.py                                     # 포화도만(모델 미사용)

    --detect N: 노출값마다 N프레임을 실제 모델로 추론해 클래스별 검출수를 센다.
                포화도보다 이쪽이 결정적 — **5클래스가 모두 잡히면서 B4 conf가 가장 높은 값**을 고른다.

    고른 값으로 벤치 실행:
    python3 test/bench_detector.py --source usb --lock-exposure --exposure <값>

측정 예 (2026-07-10, 일반 형광등·APC900):
    exp 120 → B4 0/20 (검정 패널에 묻힘)
    exp 250 → 5클래스 20/20, B4 conf 0.801  ← 채택
    exp 400 → B4는 잡히나 노랑·핑크 채도 급락(정반사 포화)
"""

import argparse
import os
import subprocess
import sys
import time

import cv2

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_OUT_DIR  = os.path.join(_TEST_DIR, "exposure_samples")

CLASS_NAMES   = ["B1", "B2", "B3", "B4", "EMO"]
DEFAULT_SWEEP = [20, 40, 60, 80, 100, 120, 157, 200, 250, 320, 400]


def _setc(dev, name, val):
    subprocess.run(["v4l2-ctl", "-d", dev, "-c", f"{name}={val}"],
                   capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description="USB 웹캠 노출 스윕 — 포화 없는 값 찾기")
    ap.add_argument("--index", type=int, default=0, help="웹캠 장치 인덱스")
    ap.add_argument("--wb", type=int, default=None,
                    help="white_balance_temperature(K) 고정. 미지정=자동 AWB(권장)")
    ap.add_argument("--roi", type=str, default=None,
                    help="평가 영역 x1,y1,x2,y2 (버튼 패널만 지정하면 정확도↑)")
    ap.add_argument("--values", type=str, default=None,
                    help="스윕할 exposure 목록 (쉼표구분). 기본 20~400")
    ap.add_argument("--detect", type=int, default=0, metavar="N",
                    help="노출값마다 N프레임을 실제 모델로 추론해 클래스별 검출수 출력. "
                         "포화도보다 이쪽이 결정적 기준 — 5클래스가 모두 잡히는 값을 고른다")
    args = ap.parse_args()

    dev = f"/dev/video{args.index}"
    sweep = [int(v) for v in args.values.split(",")] if args.values else DEFAULT_SWEEP
    roi = tuple(int(v) for v in args.roi.split(",")) if args.roi else None

    os.makedirs(_OUT_DIR, exist_ok=True)

    cap = cv2.VideoCapture(args.index)
    if not cap.isOpened():
        print(f"웹캠(index {args.index}) 열기 실패.")
        return

    # 노출만 수동으로. auto_exposure=1(Manual)을 먼저 걸어야 exposure_time_absolute가 활성화된다.
    # WB는 자동 유지 — UVC는 색온도(R↔B) 축만 제공하고 틴트(G↔M)가 없어 형광등 녹색
    # 스파이크를 수동으로 못 잡는다(최대 6500K에서도 초록 캐스트 잔존). 자동 AWB가 더 정확.
    _setc(dev, "auto_exposure", 1)
    if args.wb is not None:
        _setc(dev, "white_balance_automatic", 0)
        _setc(dev, "white_balance_temperature", args.wb)
    else:
        _setc(dev, "white_balance_automatic", 1)

    wb_desc = f"{args.wb}K 고정" if args.wb is not None else "자동(권장)"
    print(f"장치 {dev}  WB {wb_desc}  ROI {roi or '전체'}\n")
    detector = None
    if args.detect > 0:
        sys.path.insert(0, os.path.dirname(_TEST_DIR))   # Demo/ 를 import 경로에
        from detector import create_detector
        detector = create_detector()
        print(f"{'exposure':>9} {'포화%':>7} | " + "".join(f"{n:>5}" for n in CLASS_NAMES)
              + f" | {'B4 conf':>9} {'판정':>14}")
        print("-" * 74)
    else:
        print(f"{'exposure':>9} {'평균밝기':>9} {'포화≥250':>10} {'판정':>8}")
        print("-" * 42)

    for e in sweep:
        _setc(dev, "exposure_time_absolute", e)
        time.sleep(0.45)
        for _ in range(8):        # 설정 반영 대기 (버퍼 비우기)
            cap.read()
        ok, frame = cap.read()
        if not ok:
            continue

        eval_area = frame
        if roi:
            x1, y1, x2, y2 = roi
            eval_area = frame[y1:y2, x1:x2]

        gray = cv2.cvtColor(eval_area, cv2.COLOR_BGR2GRAY)
        blown = (gray >= 250).mean() * 100

        if detector:
            # 포화도보다 결정적인 기준 — 모델이 5클래스를 실제로 구분하는가.
            counts = {n: 0 for n in CLASS_NAMES}
            b4_conf = []
            for _ in range(args.detect):
                ok2, f2 = cap.read()
                if not ok2:
                    continue
                for cls_id, score, *_ in detector.detect(f2):
                    name = CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else str(cls_id)
                    counts[name] = counts.get(name, 0) + 1
                    if name == "B4":
                        b4_conf.append(score)
            missing = [n for n in CLASS_NAMES if counts[n] == 0]
            verdict = "✅ 전클래스" if not missing else "❌ 미검출:" + ",".join(missing)
            b4m = f"{max(b4_conf):.3f}" if b4_conf else "-"
            print(f"{e:>9} {blown:>6.1f}% | " + "".join(f"{counts[n]:>5}" for n in CLASS_NAMES)
                  + f" | {b4m:>9} {verdict:>14}")
        else:
            # 포화 1% 미만이면 색이 보존된다고 본다(경험칙).
            verdict = "✅ 양호" if blown < 1.0 else ("⚠ 주의" if blown < 5.0 else "❌ 포화")
            print(f"{e:>9} {gray.mean():>9.1f} {blown:>9.1f}% {verdict:>8}")

        if roi:
            cv2.rectangle(frame, (roi[0], roi[1]), (roi[2], roi[3]), (0, 255, 0), 2)
        cv2.imwrite(os.path.join(_OUT_DIR, f"exp_{e:03d}.png"), frame)

    cap.release()
    if detector:
        detector.close()
    print(f"\n샘플 이미지: test/exposure_samples/exp_*.png")
    print("→ (--detect) 5클래스가 모두 잡히면서 B4 conf가 가장 높은 값을 고르세요.")
    print("   너무 어두우면 B4(검정)가 검정 패널에 묻히고, 너무 밝으면 B1·B3가 B2로 오분류됩니다.")


if __name__ == "__main__":
    main()
