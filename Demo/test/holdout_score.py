"""홀드아웃 채점 — `tool_v3` 대 `tool_v4` 를 **클래스별·조건별**로 잰다.

무엇을 재나 (설계 §4 관문 3):
    · **쥔 상태 재현율** — 「쥠」 조건 이미지에서 그 공구를 찾아내는 비율. 이것이 이번
      처방의 표적이다(§10.54: 놓으면 잘 잡히고 쥐면 무너진다).
    · **놓인 상태 재현율** — 회귀 감시. 쥔 쪽이 올라도 놓인 쪽이 무너지면 실패다
      (§10.38 에서 남의 valid 점수는 오르고 우리 도메인이 무너진 전례).
    · **오답 오검출** — 라벨과 맞지 않는 검출. 손이 보이는 화면의 오검출이
      오완료로 이어진다(§10.54-(5)).

🔴 **임계·전처리는 `config` 에서 읽는다.** 도구 기본값이 config 를 안 따라 이미 네 번
   물렸다(conf·ring·dwell·gap — CLAUDE.md 함정). 여기서 임계를 새로 정하지 않는다.

🔑 **`tool_v3` 도 같은 시험지로 채점한다.** v3 는 in-hand 클래스를 모르므로, 쥔 상태
   라벨(`wrench-in-hand`)에 대해 **평이름 검출(`wrench`)이 맞으면 정답**으로 친다.
   그래야 「쥔 공구를 찾아내는가」라는 같은 질문을 두 모델에 던지는 것이 된다.
   (v4 는 둘 중 어느 쪽으로 잡아도 정답 — 판정 로직이 `-in-hand` 접미어를 벗겨 쓴다.)

🔴 **홀드아웃은 1회만 개봉한다.** 합격선은 개봉 전에 계획서에 못 박혀 있다.

사용법:
    ~/env/rfenv/bin/python test/holdout_score.py <홀드아웃폴더> --model models/tool_v3.pt
    ~/env/rfenv/bin/python test/holdout_score.py <홀드아웃폴더> --model models/tool_v4.pt

    <홀드아웃폴더> = Roboflow YOLO 내보내기(하위에 images/ labels/) 또는 그 상위 폴더.
"""

import argparse
import glob
import os
import sys
from collections import defaultdict

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import config

IN_HAND_SUFFIX = "-in-hand"
CONDITIONS = ("place", "grip")


def normalize(cls):
    """라벨 이름의 표기 흔들림을 통일한다 — `wrench-in hand` → `wrench-in-hand`.

    🔴 왜 필요한가 (2026-09-04 실제 발생): 라벨링 중 클래스가 `-in hand`(하이픈 대신
       공백)로 만들어졌다. 그대로 채점하면 **「쥔 상태」가 통째로 「놓인 상태」로 집계**된다 —
       관문 3의 표적이 바로 그 클래스라 결과가 조용히 뒤집힌다. 사람 눈으로 잡기 어려운
       종류라 **읽는 쪽에서 막는다**(원본 라벨은 건드리지 않는다).
    """
    return cls.replace("-in hand", IN_HAND_SUFFIX).replace("_in_hand", IN_HAND_SUFFIX)


def base_name(cls):
    """`wrench-in-hand` → `wrench`. 판정 로직(`tool_state._base`)과 같은 규칙."""
    cls = normalize(cls)
    return cls[:-len(IN_HAND_SUFFIX)] if cls.endswith(IN_HAND_SUFFIX) else cls


def condition_of(path):
    """파일명에서 조건을 읽는다 — `..._wrench_grip_0007.png` → 'grip'.

    촬영 도구(`tool_probe --label`)가 붙인 이름이 그대로 살아 있어야 한다.
    """
    stem = os.path.basename(path).lower()
    for c in CONDITIONS:
        if f"_{c}_" in stem or stem.endswith(f"_{c}"):
            return c
    return "unknown"


def iou(a, b):
    """두 박스(x1,y1,x2,y2)의 IoU."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def match(gt, dets, thr=0.5):
    """정답 박스마다 맞는 검출이 있는지 가린다.

    반환: (적중 라벨 인덱스 집합, 어느 정답과도 안 맞은 검출 수)

    🔑 **클래스 비교는 접미어를 벗기고 한다** — `wrench-in-hand` 정답에 `wrench` 검출이
       오면 정답이다(위 머리 주석의 v3 호환 규칙). 위치가 맞는데 「쥠」 여부만 다른 것을
       오검출로 세면 두 모델을 같은 잣대로 비교할 수 없다.
    """
    hit = set()
    used = set()
    for gi, (gcls, gbox) in enumerate(gt):
        for di, (dcls, dbox) in enumerate(dets):
            if di in used or base_name(dcls) != base_name(gcls):
                continue
            if iou(gbox, dbox) >= thr:
                hit.add(gi)
                used.add(di)
                break
    return hit, len(dets) - len(used)


def load_labels(lbl_path, names, w, h):
    """YOLO 라벨 → [(클래스명, (x1,y1,x2,y2)), ...] (픽셀 좌표)."""
    out = []
    if not os.path.exists(lbl_path):
        return out
    for line in open(lbl_path):
        p = line.split()
        if len(p) < 5:
            continue
        ci = int(p[0])
        cx, cy, bw, bh = (float(v) for v in p[1:5])
        out.append((normalize(names[ci]) if 0 <= ci < len(names) else f"?{ci}",
                    ((cx - bw / 2) * w, (cy - bh / 2) * h,
                     (cx + bw / 2) * w, (cy + bh / 2) * h)))
    return out


def load_names(root):
    """홀드아웃의 data.yaml 에서 클래스 이름을 읽는다(그 세트의 정의가 정본)."""
    import re
    for cand in (os.path.join(root, "data.yaml"),
                 os.path.join(os.path.dirname(root), "data.yaml")):
        if os.path.exists(cand):
            txt = open(cand).read()
            m = re.search(r"names:\s*(\[.*?\])", txt, re.S)
            if m:
                return re.findall(r"['\"]?([^'\",\[\]]+?)['\"]?\s*(?:,|\])", m.group(1))
            return [l.strip()[2:].strip() for l in txt.split("names:")[1].splitlines()
                    if l.strip().startswith("- ")]
    sys.exit(f"data.yaml 을 찾지 못했습니다: {root}")


def score(model_path, holdout_dir, conf=None, iou_thr=0.5):
    """모델 하나를 홀드아웃으로 채점한다.

    반환: {(조건, 클래스): {'gt': n, 'hit': n}}, 조건별 오검출 수
    """
    from ultralytics import YOLO

    conf = config.TOOL_CONF if conf is None else conf
    names = load_names(holdout_dir)
    imgs = sorted(f for f in glob.glob(os.path.join(holdout_dir, "**", "*"), recursive=True)
                  if f.lower().endswith((".jpg", ".jpeg", ".png")) and os.sep + "images" + os.sep in f)
    if not imgs:
        sys.exit(f"이미지를 찾지 못했습니다: {holdout_dir}")

    model = YOLO(model_path)
    tally = defaultdict(lambda: {"gt": 0, "hit": 0})
    false_pos = defaultdict(int)

    for ip in imgs:
        lp = ip.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep)
        lp = os.path.splitext(lp)[0] + ".txt"
        res = model.predict(ip, conf=conf, verbose=False)[0]
        h, w = res.orig_shape
        gt = load_labels(lp, names, w, h)
        dets = [(normalize(res.names[int(b.cls[0])]),
                 tuple(float(v) for v in b.xyxy[0])) for b in res.boxes]
        hit, fp = match(gt, dets, iou_thr)
        cond = condition_of(ip)
        for gi, (gcls, _b) in enumerate(gt):
            key = (cond, gcls)
            tally[key]["gt"] += 1
            tally[key]["hit"] += 1 if gi in hit else 0
        false_pos[cond] += fp
    return dict(tally), dict(false_pos), len(imgs), conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("holdout", help="홀드아웃 폴더(하위에 images/ labels/)")
    ap.add_argument("--model", required=True, help="채점할 .pt 경로")
    ap.add_argument("--conf", type=float, default=None,
                    help="신뢰도 임계 — 기본은 config.TOOL_CONF (운용값 그대로)")
    ap.add_argument("--iou", type=float, default=0.5, help="정답 매칭 IoU (기본 0.5)")
    args = ap.parse_args()

    tally, fps, n_img, conf = score(args.model, os.path.expanduser(args.holdout),
                                    args.conf, args.iou)
    print(f"모델 {os.path.basename(args.model)} · 이미지 {n_img} · conf {conf} · IoU {args.iou}")

    # 🔑 **클래스 기준이 정본이다.** `-in-hand` 접미어가 「쥠/놓임」을 이미 담고 있고,
    #    세트(파일명) 단위 조건은 그렇지 않다 — `driver_grip` 세트 안의 렌치·플라이어는
    #    실제로는 **놓인 상태**다. 세트로 뭉뚱그리면 그것들이 「쥠」으로 잘못 집계된다.
    by_cls = defaultdict(lambda: {"gt": 0, "hit": 0})
    for (_cond, cls), v in tally.items():
        by_cls[cls]["gt"] += v["gt"]
        by_cls[cls]["hit"] += v["hit"]

    print(f"\n■ 클래스별 (판정 근거)")
    print(f"{'클래스':<22}{'정답':>6}{'적중':>6}{'재현율':>9}")
    for cls in sorted(by_cls, key=lambda c: (c.endswith(IN_HAND_SUFFIX), c)):
        g, h = by_cls[cls]["gt"], by_cls[cls]["hit"]
        mark = "  ← 쥔 상태" if cls.endswith(IN_HAND_SUFFIX) else ""
        print(f"{cls:<22}{g:>6}{h:>6}{h / g * 100 if g else 0:>8.0f}%{mark}")
    print(f"{'오검출(전체)':<22}{sum(fps.values()):>6}")

    print(f"\n■ 촬영 세트별 (참고 — 세트 안에도 놓인 공구가 섞여 있다)")
    print(f"{'세트조건':<10}{'클래스':<22}{'정답':>6}{'적중':>6}")
    for cond in list(CONDITIONS) + ["unknown"]:
        for key in sorted(k for k in tally if k[0] == cond):
            v = tally[key]
            print(f"{cond:<10}{key[1]:<22}{v['gt']:>6}{v['hit']:>6}")
    print("\n🔴 인용 시 조건을 함께 옮긴다 — 카메라·임계·구도·세션 수.")


if __name__ == "__main__":
    main()
