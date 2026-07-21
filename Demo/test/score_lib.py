"""객체검출 채점 계산 — IoU·매칭·AP·mAP·혼동행렬.

왜 분리했나:
    채점 로직의 버그는 **조용히 틀린 숫자**를 낳고, 그 숫자가 문서(§10)와 발표로 간다.
    파이에 pycocotools·ultralytics가 없어 직접 구현하므로, 검증 가능하게 떼어 두었다.
    자체 테스트: `python3 test/score_lib.py`

규약:
    box   = (x1, y1, x2, y2) 픽셀 좌표
    gt    = [(cls_id, x1,y1,x2,y2), ...]
    pred  = [(cls_id, score, x1,y1,x2,y2), ...]
    매칭은 **클래스별·신뢰도 내림차순 greedy** — 표준 VOC/COCO 방식.
    AP는 **all-point 보간**(COCO·VOC2010 이후 방식. 11-point 아님).
"""

import numpy as np


def iou(a, b):
    """두 박스의 IoU. a, b = (x1,y1,x2,y2)."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _ap_from_pr(rec, prec):
    """P-R 곡선 아래 면적 (all-point 보간).

    precision을 뒤에서부터 누적 최대로 단조화한 뒤, recall 증가분과 곱해 더한다.
    """
    mrec = np.concatenate(([0.0], rec, [1.0]))
    mpre = np.concatenate(([0.0], prec, [0.0]))
    for i in range(len(mpre) - 2, -1, -1):          # precision 단조 감소화
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.where(mrec[1:] != mrec[:-1])[0]        # recall 이 변한 지점만
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def average_precision(preds, gts, iou_thr=0.5):
    """한 클래스의 AP.

    preds : [(image_key, score, box), ...]  — 전체 이미지에 걸친 그 클래스 예측 전량
    gts   : {image_key: [box, ...]}         — 그 클래스 정답
    """
    n_gt = sum(len(v) for v in gts.values())
    if n_gt == 0:
        return float("nan"), 0, 0          # 정답이 없는 클래스는 AP 정의 불가
    if not preds:
        return 0.0, 0, n_gt

    preds = sorted(preds, key=lambda p: -p[1])
    matched = {k: np.zeros(len(v), dtype=bool) for k, v in gts.items()}
    tp = np.zeros(len(preds))
    fp = np.zeros(len(preds))

    for i, (key, _score, box) in enumerate(preds):
        cand = gts.get(key, [])
        best, best_j = 0.0, -1
        for j, g in enumerate(cand):
            if matched[key][j]:
                continue                    # 정답 하나당 예측 하나만 (중복은 FP)
            v = iou(box, g)
            if v > best:
                best, best_j = v, j
        if best >= iou_thr and best_j >= 0:
            matched[key][best_j] = True
            tp[i] = 1
        else:
            fp[i] = 1

    ctp, cfp = np.cumsum(tp), np.cumsum(fp)
    rec = ctp / n_gt
    prec = ctp / np.maximum(ctp + cfp, 1e-12)
    return _ap_from_pr(rec, prec), int(ctp[-1]), n_gt


def evaluate(per_image, class_names, iou_thrs=(0.5,)):
    """전 클래스 AP·mAP.

    per_image : {image_key: (gt_list, pred_list)}
    반환      : {iou_thr: {"per_class": {name: ap}, "mAP": float}}
    """
    out = {}
    for thr in iou_thrs:
        per_class = {}
        for cid, name in enumerate(class_names):
            gts = {k: [b for c, *b in gt if c == cid] for k, (gt, _) in per_image.items()}
            gts = {k: v for k, v in gts.items() if v}
            preds = [(k, s, b) for k, (_, pr) in per_image.items()
                     for c, s, *b in pr if c == cid]
            ap, _tp, _n = average_precision(preds, gts, thr)
            per_class[name] = ap
        vals = [v for v in per_class.values() if not np.isnan(v)]
        out[thr] = {"per_class": per_class,
                    "mAP": float(np.mean(vals)) if vals else float("nan")}
    return out


def operating_point(per_image, class_names, conf, iou_thr=0.5):
    """운용 임계 conf 에서의 클래스별 TP/FP/FN → P/R/F1.

    FSM 이 실제로 보는 값이므로 mAP 와 별개로 중요하다.
    """
    stat = {n: {"tp": 0, "fp": 0, "fn": 0} for n in class_names}
    for _k, (gt, pred) in per_image.items():
        pred = [p for p in pred if p[1] >= conf]
        for cid, name in enumerate(class_names):
            g = [tuple(b) for c, *b in gt if c == cid]
            p = sorted([(s, tuple(b)) for c, s, *b in pred if c == cid], key=lambda x: -x[0])
            used = [False] * len(g)
            for _s, pb in p:
                best, bj = 0.0, -1
                for j, gb in enumerate(g):
                    if used[j]:
                        continue
                    v = iou(pb, gb)
                    if v > best:
                        best, bj = v, j
                if best >= iou_thr and bj >= 0:
                    used[bj] = True
                    stat[name]["tp"] += 1
                else:
                    stat[name]["fp"] += 1
            stat[name]["fn"] += used.count(False)
    for n, s in stat.items():
        s["precision"] = s["tp"] / max(s["tp"] + s["fp"], 1e-12)
        s["recall"] = s["tp"] / max(s["tp"] + s["fn"], 1e-12)
        s["f1"] = (2 * s["precision"] * s["recall"]
                   / max(s["precision"] + s["recall"], 1e-12))
    return stat


def confusion(per_image, class_names, conf, iou_thr=0.5):
    """혼동행렬 — 정답 클래스 × 예측 클래스 (+ background).

    ⭐ 이 프로젝트에서 가장 중요한 지표다. 검출률만 보면 옐로우등의 'B2를 B1으로'
    같은 오분류를 놓친다(§10.18에서 실제로 겪음). 오분류는 미검출보다 위험하다 —
    FSM 이 순서 위반을 통과시킨다.

    행 = 정답(+background: 정답 없는데 예측함) / 열 = 예측(+background: 놓침)
    """
    n = len(class_names)
    mat = np.zeros((n + 1, n + 1), dtype=int)     # 마지막 인덱스 = background
    for _k, (gt, pred) in per_image.items():
        pred = [p for p in pred if p[1] >= conf]
        used = [False] * len(pred)
        for gcls, *gb in gt:
            best, bj = 0.0, -1
            for j, (_pc, _ps, *pb) in enumerate(pred):
                if used[j]:
                    continue
                v = iou(tuple(gb), tuple(pb))
                if v > best:
                    best, bj = v, j
            if best >= iou_thr and bj >= 0:
                used[bj] = True
                mat[gcls][pred[bj][0]] += 1        # 정답 gcls 를 pred 로 인식
            else:
                mat[gcls][n] += 1                  # 놓침 (FN)
        for j, (pc, _ps, *_b) in enumerate(pred):
            if not used[j]:
                mat[n][pc] += 1                    # 배경을 pc 로 오검출 (FP)
    return mat


# =============================================================================
# 자체 테스트 — 채점 숫자를 믿으려면 이게 통과해야 한다
# =============================================================================
def _test():
    C = ["A", "B"]
    box = [10, 10, 50, 50]

    # ① 완벽 예측 → AP 1.0
    pi = {"i1": ([(0, *box)], [(0, 0.9, *box)])}
    r = evaluate(pi, C, (0.5,))[0.5]
    assert abs(r["per_class"]["A"] - 1.0) < 1e-9, r
    assert np.isnan(r["per_class"]["B"]), "정답 없는 클래스는 nan"

    # ② 예측 0건 → AP 0
    r = evaluate({"i1": ([(0, *box)], [])}, C, (0.5,))[0.5]
    assert r["per_class"]["A"] == 0.0

    # ③ 클래스 틀림 → AP 0 + 혼동행렬에 기록
    pi = {"i1": ([(0, *box)], [(1, 0.9, *box)])}
    assert evaluate(pi, C, (0.5,))[0.5]["per_class"]["A"] == 0.0
    m = confusion(pi, C, 0.0)
    assert m[0][1] == 1, m       # 정답 A 를 B 로

    # ④ IoU 임계 경계 — 겹침이 작으면 미매칭
    small = [10, 10, 30, 50]     # 정답과 IoU = 0.5
    assert abs(iou(box, small) - 0.5) < 1e-9, iou(box, small)
    assert evaluate({"i1": ([(0, *box)], [(0, 0.9, *small)])}, C, (0.5,))[0.5]["per_class"]["A"] == 1.0
    assert evaluate({"i1": ([(0, *box)], [(0, 0.9, *small)])}, C, (0.75,))[0.75]["per_class"]["A"] == 0.0

    # ⑤ 중복 예측은 FP — 정답 1개에 예측 2개면 AP < 1
    pi = {"i1": ([(0, *box)], [(0, 0.9, *box), (0, 0.8, *box)])}
    ap = evaluate(pi, C, (0.5,))[0.5]["per_class"]["A"]
    assert abs(ap - 1.0) < 1e-9, f"recall 1.0 지점 precision 1.0 이라 AP 1.0 이 맞다: {ap}"
    op = operating_point(pi, C, 0.0)
    assert op["A"]["tp"] == 1 and op["A"]["fp"] == 1, op["A"]

    # ⑥ 손계산 대조 — 정답 2개, 예측 3개(TP,FP,TP 순)
    #    누적 P = [1/1, 1/2, 2/3], R = [0.5, 0.5, 1.0]
    #    단조화 후 AP = 0.5*1.0 + 0.5*(2/3) = 0.8333...
    g1, g2 = [0, 0, 10, 10], [100, 100, 110, 110]
    pi = {"i1": ([(0, *g1), (0, *g2)],
                 [(0, 0.9, *g1), (0, 0.8, 200, 200, 210, 210), (0, 0.7, *g2)])}
    ap = evaluate(pi, C, (0.5,))[0.5]["per_class"]["A"]
    assert abs(ap - (0.5 + 0.5 * 2 / 3)) < 1e-9, ap

    # ⑦ 미검출·오검출이 혼동행렬 background 행/열에 들어가는지
    pi = {"i1": ([(0, *g1)], [(1, 0.9, 200, 200, 210, 210)])}
    m = confusion(pi, C, 0.0)
    assert m[0][2] == 1, "정답 A 놓침 → background 열"
    assert m[2][1] == 1, "배경을 B 로 오검출 → background 행"

    print("✅ score_lib 자체 테스트 7종 통과")


if __name__ == "__main__":
    _test()
