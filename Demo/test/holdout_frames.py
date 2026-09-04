"""홀드아웃 프레임 고르기 — 촬영본에서 라벨링용 이미지를 추린다.

왜 필요한가 (2026-09-04):
    `tool_probe.py --save-clean` 이 1초에 1장씩 남기면 60초 세트에서 50~60장이 나온다.
    그중 서로 거의 같은 그림이 섞여 있어 **라벨링 시간만 먹고 판정에는 기여하지 않는다.**
    여기서 중복을 걸러 내고 시간 간격을 두어 N 장을 고른다.

🔑 중복 판정은 `dedupe_raw.py` 의 `phash`·`dedupe` 를 **그대로 가져다 쓴다.**
   같은 규칙을 복제하면 반드시 한쪽이 어긋난다(도구 기본값이 config 를 안 따라 4번 물린
   전례 — CLAUDE.md 함정). 임계 기본값도 그쪽과 같은 10 이다.

🔴 **고른 뒤에 다시 뽑지 않는다.** 이 산출물이 홀드아웃 test 세트가 되고, 채점은 1회만
   한다(설계 = ../../../docs/superpowers/specs/2026-09-03-공구-쥔상태-검출-design.md §4).

사용법:
    # 세트 하나
    python3 test/holdout_frames.py ~/holdout/wrench_grip --out ~/holdout/pick

    # 촬영 폴더 전체(하위 디렉터리 = 세트)
    python3 test/holdout_frames.py ~/holdout --all --out ~/holdout/pick
"""

import argparse
import glob
import os
import shutil
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dedupe_raw import dedupe, phash          # 🔑 중복 규칙의 단일 출처

IMG_EXT = (".png", ".jpg", ".jpeg")


def pick_frames(src_dir, n=40, thr=10):
    """`src_dir` 에서 라벨링용 프레임 n 장을 고른다.

    ① pHash 로 중복을 걸러 낸 뒤 ② 남은 것에서 **시간 간격을 두고** n 장을 고른다.
    파일명이 촬영 순서(`..._0007.png`)이므로 정렬이 곧 시간순이다.

    반환: (고른 경로 목록, 원본 수, 중복 제거 후 수)
    """
    files = sorted(f for f in glob.glob(os.path.join(src_dir, "*"))
                   if f.lower().endswith(IMG_EXT))
    if not files:
        return [], 0, 0

    hashes = []
    keep_files = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        hashes.append(phash(img))
        keep_files.append(f)

    kept = [keep_files[i] for i in dedupe(hashes, thr)]

    if len(kept) <= n:
        return kept, len(files), len(kept)
    # 균등 간격 — 앞뒤로 몰리지 않게 인덱스를 고르게 편다
    step = (len(kept) - 1) / (n - 1) if n > 1 else 0
    picked = [kept[round(i * step)] for i in range(n)]
    return picked, len(files), len(kept)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="촬영 폴더(세트) 또는 --all 과 함께 그 상위 폴더")
    ap.add_argument("--all", action="store_true", help="하위 디렉터리를 각각 세트로 처리")
    ap.add_argument("--n", type=int, default=40, help="세트당 고를 장수(기본 40)")
    ap.add_argument("--thr", type=int, default=10,
                    help="pHash 중복 임계 — dedupe_raw.py 와 같은 기본값 10")
    ap.add_argument("--out", default=None, help="고른 파일을 복사할 폴더(없으면 목록만 출력)")
    args = ap.parse_args()

    src = os.path.expanduser(args.src)
    sets = ([d for d in sorted(glob.glob(os.path.join(src, "*"))) if os.path.isdir(d)]
            if args.all else [src])
    if not sets:
        sys.exit(f"세트를 찾지 못했습니다: {src}")

    out_dir = os.path.expanduser(args.out) if args.out else None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    total = 0
    print(f"{'세트':<24}{'원본':>6}{'중복제거':>9}{'선정':>6}")
    for d in sets:
        picked, n_raw, n_uniq = pick_frames(d, args.n, args.thr)
        name = os.path.basename(d.rstrip("/"))
        mark = "" if len(picked) >= args.n else "  ⚠️ 부족"
        print(f"{name:<24}{n_raw:>6}{n_uniq:>9}{len(picked):>6}{mark}")
        for p in picked:
            if out_dir:
                shutil.copy2(p, os.path.join(out_dir, os.path.basename(p)))
        total += len(picked)

    print(f"\n합계 {total}장" + (f" → {out_dir}" if out_dir else " (복사 안 함 — --out 미지정)"))
    if out_dir:
        print("🔴 다음: Roboflow 업로드 시 **--split test 를 명시**한다(자동 랜덤 분할 금지).")


if __name__ == "__main__":
    main()
