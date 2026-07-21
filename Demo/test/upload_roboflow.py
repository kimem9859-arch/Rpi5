"""데이터셋(이미지 + 프리라벨)을 Roboflow에 일괄 업로드한다.

⚠️ 분할(split) 규칙 — v1의 실패를 반복하지 않기 위한 핵심 설계

    console_v1은 **같은 영상 2개를 프레임 랜덤 분할**해 학습했다. 그 결과 train과 test에
    거의 같은 프레임이 들어가 mAP 0.993이 나왔지만, 실추론에서 B4는 0%였다.
    → **Roboflow의 자동 랜덤 분할을 절대 쓰지 않는다.** 업로드 시점에 split을 명시한다.

    이 스크립트의 분할:
      - train/valid = **세션 내 시간순 분할**(앞 80% train / 뒤 20% valid).
        세션마다 조건(각도·정반사·저조도)이 다르므로 세션 통째로 떼면 그 조건이
        학습에서 완전히 빠진다. 시간순으로 나누면 모든 조건이 양쪽에 남으면서도,
        인접 프레임 누출은 pHash 중복제거(dedupe_raw.py)로 이미 제거돼 있다.
      - test = **비워둔다**. valid는 같은 방·같은 조명이라 낙관적일 수밖에 없다.
        **정직한 최종 성능은 다른 날·다른 조명에서 찍은 별도 세션**으로만 잴 수 있다.
        그 세션을 찍은 뒤 `--split test`로 따로 올린다.

사용법:
    cd ~/sop-project/Rpi5
    cp .env.example .env      # 그리고 .env 에 ROBOFLOW_API_KEY 입력
    .rfvenv/bin/python Demo/test/upload_roboflow.py --dry-run    # 무엇이 올라갈지 확인
    .rfvenv/bin/python Demo/test/upload_roboflow.py              # 실제 업로드

    # 나중에 test 세션을 찍으면:
    .rfvenv/bin/python Demo/test/upload_roboflow.py --only <세션명> --split test
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv
from roboflow import Roboflow

DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(DEMO, "dataset", "images")
LABELS = os.path.join(DEMO, "dataset", "labels")

WORKSPACE = "eung-min"
PROJECT = "console_v2-mjefr"
VALID_RATIO = 0.20          # 세션 내 뒤쪽 20%를 valid 로

# YOLO 라벨은 클래스를 숫자로만 적는다. 이걸 안 넘기면 Roboflow에 "0","1"…로 올라간다.
LABELMAP = {"0": "B1", "1": "B2", "2": "B3", "3": "B4", "4": "EMO"}


def collect(only=None, split_override=None):
    """세션별로 (이미지경로, 라벨경로, split, 태그) 목록을 만든다."""
    items = []
    for sess in sorted(os.listdir(IMAGES)):
        if only and sess != only:
            continue
        img_dir = os.path.join(IMAGES, sess)
        lbl_dir = os.path.join(LABELS, sess)
        if not os.path.isdir(img_dir):
            continue
        files = sorted(f for f in os.listdir(img_dir) if f.endswith(".png"))
        n = len(files)
        cut = int(n * (1 - VALID_RATIO))     # 시간순: 앞 80% train, 뒤 20% valid
        for i, f in enumerate(files):
            if split_override:
                split = split_override
            else:
                split = "train" if i < cut else "valid"
            items.append((
                os.path.join(img_dir, f),
                os.path.join(lbl_dir, f[:-4] + ".txt"),
                split,
                sess,
            ))
    return items


def main():
    ap = argparse.ArgumentParser(description="Roboflow 일괄 업로드 (이미지 + 프리라벨)")
    ap.add_argument("--dry-run", action="store_true", help="올리지 않고 계획만 출력")
    ap.add_argument("--only", default=None, help="특정 세션만")
    ap.add_argument("--split", default=None, choices=["train", "valid", "test"],
                    help="split 강제 지정 (test 세션 업로드 시 사용)")
    ap.add_argument("--project", default=PROJECT)
    args = ap.parse_args()

    items = collect(args.only, args.split)
    if not items:
        print("업로드할 이미지가 없습니다.")
        return

    # 계획 요약
    by = {}
    for _, _, split, sess in items:
        by.setdefault(sess, {}).setdefault(split, 0)
        by[sess][split] += 1
    print(f"프로젝트: {WORKSPACE}/{args.project}\n")
    print(f"{'세션':<24}{'train':>7}{'valid':>7}{'test':>6}")
    print("-" * 46)
    tot = {"train": 0, "valid": 0, "test": 0}
    for sess, d in by.items():
        for k in tot:
            tot[k] += d.get(k, 0)
        print(f"{sess:<24}{d.get('train',0):>7}{d.get('valid',0):>7}{d.get('test',0):>6}")
    print("-" * 46)
    print(f"{'합계':<24}{tot['train']:>7}{tot['valid']:>7}{tot['test']:>6}   (총 {len(items)}장)")
    print()
    if not tot["test"]:
        print("⚠️  test 가 비어 있다. 이것이 의도된 상태다 —")
        print("    valid 는 같은 방·같은 조명이라 낙관적이다. 정직한 성능은")
        print("    **다른 날·다른 조명**에서 찍은 별도 세션으로만 잴 수 있다.")
        print()

    if args.dry_run:
        print("(--dry-run: 실제 업로드는 하지 않았다)")
        return

    load_dotenv(os.path.join(os.path.dirname(DEMO), ".env"))
    key = os.getenv("ROBOFLOW_API_KEY")
    if not key or "여기에" in key:
        print("❌ ROBOFLOW_API_KEY 가 없다. Rpi5/.env 에 넣어라 (.env.example 참고).")
        sys.exit(1)

    rf = Roboflow(api_key=key)
    project = rf.workspace(WORKSPACE).project(args.project)

    ok = fail = 0
    t0 = time.time()
    for i, (img, lbl, split, sess) in enumerate(items, 1):
        try:
            # 이미지와 라벨을 한 번에. 라벨이 비어 있어도 이미지는 올린다
            # (사람이 Roboflow에서 B4 등을 채워야 하므로).
            has_label = os.path.exists(lbl) and os.path.getsize(lbl) > 0
            project.single_upload(
                image_path=img,
                annotation_path=lbl if has_label else None,
                # YOLO 라벨은 클래스가 숫자뿐이다. labelmap을 안 주면 "0","1"이 클래스명이 된다.
                annotation_labelmap=LABELMAP if has_label else None,
                # Roboflow는 이미지 해시로 어노테이션을 캐시한다. 이걸 안 켜면 재업로드 시
                # "already annotated"로 스킵되고 **옛 라벨이 그대로 남는다**.
                annotation_overwrite=True,
                split=split,
                tag_names=[sess],          # 세션 태그 → 나중에 필터·재분할에 쓴다
                batch_name=sess,
                num_retry_uploads=3,
            )
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  ⚠️ 실패 {os.path.basename(img)}: {e}")
        if i % 25 == 0 or i == len(items):
            el = time.time() - t0
            print(f"  {i}/{len(items)}  성공 {ok} 실패 {fail}  ({el:.0f}s, "
                  f"남은 예상 {el/i*(len(items)-i):.0f}s)")

    print(f"\n완료: 성공 {ok} / 실패 {fail}")
    print(f"→ https://app.roboflow.com/{WORKSPACE}/{args.project}")
    print()
    print("다음 (Roboflow 웹에서 사람이 할 일) — 우선순위 순:")
    print("  1. 빠진 박스 채우기 — 라벨이 없으면 '버튼 없음'으로 학습된다")
    print("     ※ 단, **가려서 안 보이는 것은 그대로 둔다**(Modal — labeling_guide §③)")
    print("  2. 잘못된 클래스 수정")
    print("     ※ 정답은 **진짜 버튼 정체**다. 노란 버튼이 하얗게 보여도 B1.")
    print("  3. 배경 오탐 삭제 — 흰 접시·제빙기 뚜껑 등이 B2로 잡힌 것")
    print("  4. 박스 타이트함 — 눈에 띄게 어긋난 것만")
    print()
    print("⚠️ 버전 생성 시 Roboflow의 **자동 랜덤 분할을 쓰지 마라**.")
    print("   업로드 때 지정한 split 을 유지해야 한다(프레임을 섞으면 누출).")


if __name__ == "__main__":
    main()
