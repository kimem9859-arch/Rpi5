"""raw 프레임의 중복을 pHash로 걸러낸다 — 학습 데이터 준비 1단계.

왜 필요한가:
    영상에서 뽑은 프레임은 서로 거의 같다. 실측(2026-07-13): 12fps ESP32 촬영에서
    인접 프레임의 47%가 사실상 동일했고, 10프레임마다 1장만 저장해도 30%가 중복이었다.
    중복은 두 가지 해를 끼친다:
      ① 라벨링 낭비 — 같은 그림을 여러 번 그린다
      ② **데이터 누출** — 랜덤 분할 시 train과 test에 닮은 프레임이 들어가 mAP가 부풀려진다.
         console_v1이 정확히 이 함정에 빠졌다(같은 영상 2개를 프레임 랜덤 분할 →
         mAP 0.993인데 실추론 B4 0%). 분할 **전에** 반드시 제거해야 한다.

사용법:
    # 측정만 (아무것도 지우지 않음) — 촬영이 충분했는지 확인
    python3 test/dedupe_raw.py test/raw/<세션> --report

    # 실제 제거 → 고유 프레임만 새 폴더로 복사
    python3 test/dedupe_raw.py test/raw/<세션> --out dataset/images/<세션>

    # 여러 세션 한 번에
    python3 test/dedupe_raw.py test/raw/*_esp32 --out dataset/images

임계값(--thr):
    두 프레임의 pHash 해밍거리가 이 값 이하면 중복으로 본다(0=완전동일, 64=완전다름).
    기본 10. 낮추면 덜 지우고, 높이면 더 공격적으로 지운다.
"""

import argparse
import os
import shutil

import cv2
import numpy as np


def phash(img, size=8):
    """지각 해시 — 리사이즈·압축·미세 변화에 둔감하고 내용이 다르면 크게 달라진다."""
    gray = cv2.cvtColor(cv2.resize(img, (32, 32)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    dct = cv2.dct(gray)[:size, :size]
    return (dct > np.median(dct)).flatten()


def dedupe(hashes, thr):
    """탐욕적 중복 제거 — 이미 남긴 것들과 모두 thr 초과로 다른 것만 남긴다."""
    keep = []
    for i, h in enumerate(hashes):
        if all(np.count_nonzero(h != hashes[j]) > thr for j in keep):
            keep.append(i)
    return keep


def main():
    ap = argparse.ArgumentParser(description="raw 프레임 중복 제거 (pHash)")
    ap.add_argument("dirs", nargs="+", help="raw 세션 폴더 (여러 개 가능)")
    ap.add_argument("--thr", type=int, default=10,
                    help="해밍거리 임계 — 이 값 이하면 중복 (기본 10)")
    ap.add_argument("--out", default=None,
                    help="고유 프레임을 복사할 폴더. 없으면 측정만 하고 끝")
    ap.add_argument("--report", action="store_true", help="측정만 (--out 무시)")
    args = ap.parse_args()

    total_in = total_out = 0

    for d in args.dirs:
        if not os.path.isdir(d):
            print(f"⚠️  건너뜀 (폴더 아님): {d}")
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith(".png"))
        if not files:
            continue

        hashes = [phash(cv2.imread(os.path.join(d, f))) for f in files]
        keep = dedupe(hashes, args.thr)

        n, k = len(files), len(keep)
        total_in += n
        total_out += k

        # 인접 프레임 유사도 — 촬영 중 자세를 실제로 바꿨는지 보여준다
        adj = [np.count_nonzero(hashes[i] != hashes[i + 1]) for i in range(n - 1)]
        near_dup = sum(1 for a in adj if a <= 5) / max(len(adj), 1) * 100

        print(f"\n[{os.path.basename(d.rstrip('/'))}]")
        print(f"  저장 {n}장 → 고유 {k}장  (중복 {n-k}장, {(1-k/n)*100:.0f}%)")
        print(f"  인접 프레임 중복률: {near_dup:.0f}%"
              + ("   ⚠️ 촬영 중 자세 변화가 부족했다" if near_dup > 30 else ""))

        if args.out and not args.report:
            sess = os.path.basename(d.rstrip("/"))
            dst = args.out if len(args.dirs) == 1 else os.path.join(args.out, sess)
            os.makedirs(dst, exist_ok=True)
            for i in keep:
                # 세션명을 파일명에 넣는다 — 나중에 세션 단위로 분할해야 하므로
                # (프레임 단위 분할은 누출을 일으킨다) 출처를 잃으면 안 된다.
                shutil.copy2(os.path.join(d, files[i]),
                             os.path.join(dst, f"{sess}__{files[i]}"))
            print(f"  → {dst} 에 {k}장 복사")

    if len(args.dirs) > 1:
        print(f"\n{'='*46}")
        print(f"합계: {total_in}장 → 고유 {total_out}장 "
              f"(중복 {(1-total_out/max(total_in,1))*100:.0f}% 제거)")
    print()
    print("※ 분할은 반드시 **세션 단위**로. 프레임을 섞으면 train/test에 닮은 프레임이")
    print("  들어가 mAP가 거짓으로 높아진다(console_v1이 겪은 함정).")


if __name__ == "__main__":
    main()
