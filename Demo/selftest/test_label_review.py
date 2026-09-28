"""label_review — 버튼 기계 검토의 픽셀·배치 판정을 합성 사진으로 고정한다.

실행: python3 Demo/selftest/test_label_review.py
정본 설계: ../../docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §5.1 · §6
⚠️ Hailo·모델이 필요 없다 — 검출은 가짜 함수(FakeRun)로 주입한다.
"""
import os
import sys

import cv2
import numpy as np

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import label_review as R

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


H, W = 1024, 768
POS = {"B1": (228, 662), "B2": (194, 350), "B3": (517, 349), "B4": (513, 635), "EMO": (387, 782)}
RAD = {"B1": 26, "B2": 29, "B3": 25, "B4": 27, "EMO": 30}
COL = {"B1": (0, 215, 255), "B2": (240, 240, 240), "B3": (150, 130, 240),
       "B4": (200, 90, 40), "EMO": (40, 40, 210)}                     # BGR


def panel(names=tuple(POS), blur=0.0, extra=None, jitter=None):
    img = np.full((H, W, 3), (70, 72, 70), np.uint8)
    for n in names:
        cx, cy = POS[n]; r = RAD[n]
        if jitter and n in jitter:
            cx, cy = cx + jitter[n][0], cy + jitter[n][1]
        cv2.circle(img, (cx, cy), r, COL[n], -1, lineType=cv2.LINE_AA)
        if n == "EMO":
            for a0, a1 in ((20, 160), (200, 340)):
                cv2.ellipse(img, (cx, cy), (int(r * 0.72), int(r * 0.72)), 0, a0, a1, (245, 245, 245), 4)
    if extra:                                   # (중심, 반지름, 색) — 버튼이 아닌 흰 덩어리(장갑 흉내)
        (cx, cy), r, c = extra
        cv2.circle(img, (cx, cy), r, c, -1, lineType=cv2.LINE_AA)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    return img


def loose(n, pos=None):
    cx, cy = pos or POS[n]; r = RAD[n]
    return [cx - r - 6, cy - r - 8, cx + r + 6, cy + r + 8]      # 초벌처럼 조금 느슨한 박스


class FakeRun:
    """tile_detect 는 사진마다 위 조각 → 아래 조각 순서로 두 번 부른다. 참 박스를 그 조각 좌표로 돌려준다."""

    def __init__(self, truth):
        self.truth, self.k = truth, 0

    def __call__(self, crop):
        th = W * 3 // 4
        t = 0 if self.k % 2 == 0 else H - th
        self.k += 1
        out = []
        for n, s, (x1, y1, x2, y2) in self.truth:
            yy1, yy2 = max(y1, t), min(y2, t + th)
            if yy2 - yy1 > 0:
                out.append((n, s, [x1, yy1 - t, x2, yy2 - t]))
        return out


TRUTH = [(n, 0.9, loose(n)) for n in POS]


def ready():
    imgs = [panel() for _ in range(3)]
    T = R.build_template(imgs, FakeRun(TRUTH))
    th = R.make_thresholds(imgs, FakeRun(TRUTH))
    return T, th


def test_박스_맞추기():
    print("[1] 느슨한 초벌 박스를 버튼 테두리에 맞춘다 (가장자리 35%)")
    img = panel()
    for n in POS:
        cx, cy = POS[n]; r = RAD[n]
        sn = R.snap(img, loose(n))
        exp = [cx - r, cy - r, cx + r + 1, cy + r + 1]
        ok = sn is not None and all(abs(a - b) <= 2 for a, b in zip(sn["box"], exp))
        check(ok, f"{n}: {None if sn is None else sn['box']} ≈ {exp}")


def test_색_계열():
    print("[2] 색 계열 — 흰·노랑·파랑·빨강")
    img = panel()
    want = {"B1": "yellow", "B2": "white", "B3": "red", "B4": "blue", "EMO": "red"}
    for n in POS:
        sn = R.snap(img, loose(n))
        check(sn is not None and R.color_family(sn["crop"], sn["mask"]) == want[n], f"{n} → {want[n]}")


def test_EMO_무늬():
    print("[3] 흰 테두리 무늬 점수 — EMO 가 B3 보다 뚜렷이 크다")
    img = panel()
    e = R.snap(img, loose("EMO")); b = R.snap(img, loose("B3"))
    re_, rb = R.rim_score(e["crop"], e["mask"]), R.rim_score(b["crop"], b["mask"])
    check(re_ > rb + 0.1, f"EMO {re_:.3f} > B3 {rb:.3f} + 0.1")


def test_배치_틀_정답():
    print("[4] 배치 틀 — 제자리 5개는 이름대로 배정되고 헷갈림 여유가 크다")
    T, _ = ready()
    dets = [(POS[n][0], POS[n][1], 2 * RAD[n]) for n in POS]
    lay = R.fit_layout(T, dets)
    check(lay is not None and list(lay["assign"]) == list(POS), f"배정 {None if lay is None else lay['assign']}")
    check(lay is not None and lay["margin"] > R.MARGIN_MIN, "여유 > MARGIN_MIN")


def test_전부_맞으면_기계_확정():
    print("[5] 5개가 제자리·제이름이면 전부 기계 확정")
    T, th = ready()
    out = R.review(panel(), FakeRun(TRUTH), T, th)
    check(out["nvis"] == 5, "보이는 버튼 5")
    check(all(not b["why"] for b in out["boxes"]), f"이유 {[b['why'] for b in out['boxes']]}")


def test_B3를_EMO로_잡으면_넘김():
    print("[6] 분홍 B3 를 EMO 로 잡은 초벌 → 배치·무늬가 반대 → 사람에게")
    T, th = ready()
    truth = [("EMO" if n == "B3" else n, 0.9, loose(n)) for n in POS]
    out = R.review(panel(), FakeRun(truth), T, th)
    bad = [b for b in out["boxes"] if b["layout"] == "B3"]
    check(len(bad) == 1 and "배치≠초벌" in bad[0]["why"], f"B3 자리 박스 이유 {bad[0]['why'] if bad else None}")


def test_장갑은_버튼_아님():
    print("[7] 판 밖 흰 덩어리를 B2 로 잡은 초벌 → 배치 틀은 그것을 「버튼 아님」에 배정 · 그 사진은 하나도 기계 확정하지 않는다")
    # 조사판 그대로의 보수적 동작 — 「버튼 아님」 벌점(0.5)이 비용 상한(0.5)을 넘겨 사진 전체가 「배치 불확실」이 된다.
    # 표본 검사를 통과한 동작이라 이 계획에서는 바꾸지 않는다(개선은 다음 계획 — 사람 검토가 늘 뿐 틀린 확정은 없다).
    # 🔑 버튼 위치를 몇 px 흔든다 — 실제 사진처럼 배치 틀과 완전히 같지 않게. 완전히 같으면 비용이 정확히
    #    「버튼 아님」 벌점(0.5)과 같아져 상한(0.5)을 넘지 않는, 실제 사진에서는 생기지 않는 경우가 된다.
    T, th = ready()
    glove = (640, 950)
    jit = {"B1": (3, -2), "B3": (-2, 3), "EMO": (2, 2)}
    img = panel(extra=(glove, 28, (235, 235, 235)), jitter=jit)
    moved = {n: (POS[n][0] + jit.get(n, (0, 0))[0], POS[n][1] + jit.get(n, (0, 0))[1]) for n in POS}
    truth = [(n, 0.9, loose(n, moved[n])) for n in POS] + [("B2", 0.7, loose("B2", glove))]
    out = R.review(img, FakeRun(truth), T, th)
    g = [b for b in out["boxes"] if abs((b["pre"][0] + b["pre"][2]) / 2 - glove[0]) < 5]
    check(len(g) == 1 and g[0]["layout"] is None, f"장갑 박스 배정 {g[0]['layout'] if g else '없음'}")
    check(all(b["why"] for b in out["boxes"]), "그 사진의 박스는 모두 사람에게")


def test_버튼_하나면_사람():
    print("[8] 버튼이 1개만 보이면 사람에게")
    T, th = ready()
    out = R.review(panel(names=("B1",)), FakeRun([("B1", 0.9, loose("B1"))]), T, th)
    check(out["nvis"] == 1 and "버튼 1개" in out["boxes"][0]["why"], f"이유 {out['boxes'][0]['why']}")


def test_빠진_자리_제안():
    print("[9] 4개가 보이면 빠진 B4 자리를 제안한다")
    T, th = ready()
    names = ("B1", "B2", "B3", "EMO")
    out = R.review(panel(names=names), FakeRun([(n, 0.9, loose(n)) for n in names]), T, th)
    m = [b for s, b in out["missing"] if s == "B4"]
    ok = len(m) == 1 and abs((m[0][0] + m[0][2]) / 2 - POS["B4"][0]) < 8 and abs((m[0][1] + m[0][3]) / 2 - POS["B4"][1]) < 8
    check(ok, f"B4 제안 {m}")


def test_흐리면_사람():
    print("[10] 흐린 사진은 박스마다 「흐림」")
    T, th = ready()
    out = R.review(panel(blur=4.0), FakeRun(TRUTH), T, th)
    check(all("흐림" in b["why"] for b in out["boxes"]), f"이유 {[b['why'] for b in out['boxes']]}")


def test_조각_경계_합치기():
    print("[11] 조각 경계에 걸린 버튼 — 잘린 박스는 버리고 온전한 박스 하나만")
    th_ = W * 3 // 4; bottom = H - th_
    calls = [
        [("B4", 0.8, [500, 540, 560, th_]), ("B4", 0.6, [500, th_ - 6, 560, th_])],     # 위 조각: 잘린 박스 둘
        [("B4", 0.9, [500, 540 - bottom, 560, 600 - bottom])],                           # 아래 조각: 온전
    ]
    k = [0]

    def run(crop):
        out = calls[k[0]]; k[0] += 1
        return out

    got = R.tile_detect(np.zeros((H, W, 3), np.uint8), run)
    check(len(got) == 1 and got[0][2] == [500, 540, 560, 600], f"결과 {got}")


def test_가로_사진은_한_번():
    print("[12] 조각을 낼 만큼 세로가 길지 않은 사진은 통째로 한 번만 검출")
    k = [0]

    def run(crop):
        k[0] += 1
        return [("B1", 0.9, [10, 10, 40, 40])]

    got = R.tile_detect(np.zeros((480, 640, 3), np.uint8), run)
    check(k[0] == 1 and got == [("B1", 0.9, [10, 10, 40, 40])], f"호출 {k[0]} · 결과 {got}")


def test_결과는_JSON_으로_쓸_수_있다():
    print("[13] 🔴 검토 결과(박스 좌표)를 묶음 기록(JSON)에 그대로 쓸 수 있다 — numpy 정수가 섞이면 안 된다")
    import json
    T, th = ready()
    out = R.review(panel(), FakeRun(TRUTH), T, th)
    try:
        json.dumps({"boxes": [{k: b[k] for k in ("name", "score", "pre", "box", "why", "layout")} for b in out["boxes"]],
                    "missing": out["missing"]})
        ok = True
    except TypeError as e:
        ok = False; print("   ", e)
    check(ok, "json.dumps 성공")


def test_샌_박스는_검출기_박스로():
    print("[14] 🔴 박스 맞추기가 배경으로 새면 사람에게 넘기는 박스는 검출기 박스 — 샌 사각형(잘라낸 영역 끝까지)을 보여 주지 않는다")
    T, th = ready()
    img = panel()
    cx, cy = POS["B2"]
    cv2.rectangle(img, (cx, cy - 10), (cx + 200, cy + 10), COL["B2"], -1)     # 버튼에 붙은 같은 색 띠 → 배경으로 샌다
    check(R.snap(img, loose("B2"))["leak"], "준비: B2 맞추기가 샌다")
    out = R.review(img, FakeRun(TRUTH), T, th)
    b = [x for x in out["boxes"] if x["name"] == "B2"][0]
    check("박스 맞추기 실패" in b["why"], f"사람에게 {b['why']}")
    check(b["box"] == b["pre"], f"박스 {b['box']} = 검출기 박스 {b['pre']}")


if __name__ == "__main__":
    test_박스_맞추기()
    test_색_계열()
    test_EMO_무늬()
    test_배치_틀_정답()
    test_전부_맞으면_기계_확정()
    test_B3를_EMO로_잡으면_넘김()
    test_장갑은_버튼_아님()
    test_버튼_하나면_사람()
    test_빠진_자리_제안()
    test_흐리면_사람()
    test_조각_경계_합치기()
    test_가로_사진은_한_번()
    test_결과는_JSON_으로_쓸_수_있다()
    test_샌_박스는_검출기_박스로()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 버튼 기계 검토 판정 검증 통과")
