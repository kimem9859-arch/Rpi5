#!/usr/bin/env python3
"""재압축 검출 비교(임시) — 안경 원본을 더 압축해 저장하면 버튼 · 손 검출이 얼마나 달라지나(학교 방문 준비 설계 §4.3).

실행: python3 Demo/test/jpeg_quality_probe.py <폴더(f*.jpg) | 영상.mp4> [--q 85 75 65 55] [--limit 120] [--unorient]
🔴 임시 값이다 — 파이(OpenCV)의 JPEG 품질 숫자와 카메라 칩(jpeg_quality 10~63)의 숫자는 뜻이 다르다 → 방향만 본다 · 학교 필수.
   크기 비가 비슷한 쪽을 비교 대상으로 읽는다(펌웨어 변형의 실제 장 크기는 학교에서 받기 도구로 잰다).
"""
import argparse
import glob
import os
import sys

TEST = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(TEST)
sys.path.insert(0, DEMO)
sys.path.insert(0, TEST)

import cv2           # noqa: E402
import numpy as np   # noqa: E402


def _frames(src, limit, unorient):
    """→ [(원본 JPEG 바이트, 풀린 장)] — 영상이면 품질 95 로 다시 압축한 것을 「원본」으로 본다."""
    out = []
    if os.path.isdir(src):
        for p in sorted(glob.glob(os.path.join(src, "f*.jpg")))[:limit or None]:
            b = open(p, "rb").read()
            out.append((b, cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)))
    else:
        from fake_camera import unorient as _un
        cap = cv2.VideoCapture(src)
        while not limit or len(out) < limit:
            ok, img = cap.read()
            if not ok:
                break
            img = _un(img) if unorient else img
            b = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
            out.append((b, cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)))
        cap.release()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="재압축 검출 비교(임시 · 학교 방문 준비 설계 §4.3)")
    ap.add_argument("src")
    ap.add_argument("--q", type=int, nargs="+", default=[85, 75, 65, 55])
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--unorient", action="store_true", help="영상이 화면 방향(측정 녹화)이면 안경 원본 방향으로")
    a = ap.parse_args(argv)
    import frame_orient
    from detector import create_detector
    from hand_tracker import HandTracker
    det = create_detector()
    hand = HandTracker(log=lambda m: None)
    frames = _frames(a.src, a.limit, a.unorient)
    if not frames:
        print("장이 없다")
        return 2

    def look(img):
        o = frame_orient.apply(img)
        cls = tuple(sorted({det.class_name(d[0]) for d in det.detect(o)}))
        return cls, hand.detect(o) is not None

    base = [look(img) for _, img in frames]
    hand0 = sum(h for _, h in base) / len(base)
    print("> 임시 — 파이 JPEG 품질 숫자 ≠ 카메라 칩 jpeg_quality · 방향만 본다 · 학교 필수(설계 D16)")
    print(f"> 원본 {len(frames)}장 · 장 평균 {sum(len(b) for b, _ in frames) / len(frames) / 1000:.1f}KB · 손 찾음 {hand0 * 100:.0f}%")
    print("| 품질 | 크기 비 | 버튼 클래스 같음 | 손 찾음 |")
    print("|---|---|---|---|")
    for q in a.q:
        ratio, same, hands = [], 0, 0
        for (b, img), (cls0, _) in zip(frames, base):
            enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1]
            ratio.append(len(enc) / len(b))
            cls, h = look(cv2.imdecode(enc, cv2.IMREAD_COLOR))
            same += cls == cls0
            hands += h
        n = len(frames)
        print(f"| {q} | {np.mean(ratio):.2f} | {same / n * 100:.0f}% | {hands / n * 100:.0f}% |")
    det.close()
    hand.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
