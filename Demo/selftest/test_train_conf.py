"""학습 설정(학습/trainconf.py)과 커밋된 설정 파일을 고정한다 — 합치기 · 오타·함정 막기 · 시작값(설계 §6) · 실험 44(E0b 6 = 최종 리뷰 C1 · 후보 시드 4 · 조합 E7 3 · 에폭 고정 12).

실행: python3 Demo/selftest/test_train_conf.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §6 · §9
"""
import os
import sys
from pathlib import Path

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import trainconf as TC

_fails = []
CONF = Path(_RPI5) / "학습" / "설정"


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


BASE = {"나눔": "place1_v1", "입력": "늘리기640", "출발": "yolov8n.pt", "seed": 0,
        "train": {"epochs": 200, "patience": 20, "optimizer": "AdamW", "lr0": 0.001},
        "멈춤": {k: 1 for k in TC.STOP_KEYS}}


def _err(exp, stem=None):
    try:
        TC.resolve(BASE, exp, stem)
        return None
    except ValueError as e:
        return str(e)


def test_합치기():
    print("[1] 기본 + 바꾼 것만")
    c = TC.resolve(BASE, {"id": "E3-tool-mosaic05", "group": "tool", "train": {"mosaic": 0.5}}, "E3-tool-mosaic05")
    check(c["train"]["mosaic"] == 0.5 and c["train"]["lr0"] == 0.001, "mosaic 만 바뀌고 lr0 는 기본")
    check(c["바꾼것"] == "mosaic=0.5", f"바꾼것 — {c['바꾼것']}")
    k = TC.train_kwargs(c)
    check(k["imgsz"] == 640 and k["seed"] == 0 and k["optimizer"] == "AdamW", "학습 인자 = imgsz 640 · seed 0")
    c2 = TC.resolve(BASE, {"id": "E1-tool-in1024", "group": "tool", "입력": "원본768x1024", "seed": 2})
    check(TC.train_kwargs(c2)["imgsz"] == 1024 and c2["바꾼것"] == "입력=원본768x1024 · seed=2", f"원본 입력 — {c2['바꾼것']}")
    check(TC.INPUT_MODES["원본768x1024"]["predict_imgsz"] == [1024, 768], "채점 = [세로 1024, 가로 768]")


def test_막기():
    print("[2] 오타·함정·형식")
    cases = [({"id": "E3-tool-x", "group": "tool", "train": {"hsvh": 0}}, None, "모르는 train 키"),
             ({"id": "E3-tool-x", "group": "tool", "train": {"imgsz": 320}}, None, "체계가 정하는 키"),
             ({"id": "E3-tool-x", "group": "tool", "train": {"optimizer": "auto"}}, None, "optimizer auto"),
             ({"id": "E3-tool-x", "group": "tool"}, "E3-tool-y", "id 와 파일 이름 다름"),
             ({"id": "E3-button-x", "group": "tool"}, None, "id 의 무리 ≠ group"),
             ({"id": "X3-tool-x", "group": "tool"}, None, "id 형식"),
             ({"id": "E3-tool-x", "group": "tool", "입력": "늘리기320"}, None, "모르는 입력 방식"),
             ({"id": "E3-tool-x", "group": "tool", "학습률": 1}, None, "모르는 최상위 키"),
             ({"id": "E3-tool-x", "group": "tool", "멈춤": {"포화": 1}}, None, "모르는 멈춤 키")]
    for exp, stem, why in cases:
        check(_err(exp, stem) is not None, f"{why} → ValueError")
    base2 = {**BASE, "멈춤": {"포화_에폭": 30}}
    try:
        TC.resolve(base2, {"id": "E3-tool-x", "group": "tool"})
        check(False, "멈춤 키 빠진 기본 → ValueError")
    except ValueError:
        check(True, "멈춤 키 빠진 기본 → ValueError")


def test_기본값():
    print("[3] 기본.yaml = 설계 §6 시작값")
    b = TC.load_yaml(CONF / "기본.yaml")
    t = b["train"]
    want = {"epochs": 200, "patience": 20, "batch": 16, "workers": 2, "cache": "disk", "optimizer": "AdamW",
            "lr0": 0.001, "momentum": 0.9, "warmup_bias_lr": 0.0, "deterministic": True}
    for k, v in want.items():
        check(t.get(k) == v, f"{k} = {v} — {t.get(k)}")
    check(b["입력"] == "늘리기640" and b["출발"] == "yolov8n.pt" and b["seed"] == 0, "입력 · 출발 · seed")
    m = b["멈춤"]
    check((m["포화_에폭"], m["점수0_에폭"], m["점수0_mAP50"], m["진행없음_분"], m["시간상한_배"]) == (30, 10, 0.05, 15, 2), "멈춤 조건(설계 §7)")


def test_커밋된_설정():
    print("[4] 실험 56(E0b 6 · 후보 시드 4 · 조합 E7 3 · 에폭 고정 12 · 탐색 확인 E10 6 · 가설 E11·E12 6 포함) · 점검 4 — 전부 읽히고 id 가 겹치지 않는다")
    b = TC.load_yaml(CONF / "기본.yaml")
    ids = []
    for sub in ("실험", "점검"):
        for p in sorted((CONF / sub).glob("*.yaml")):
            e = _try(b, p)
            if e:
                check(False, f"{p.name}: {e}")
            ids.append(p.stem)
    exp = [i for i in ids if not i.startswith("E9-")]
    check(len(exp) == 56, f"실험 56 — {len(exp)}")
    check(len([i for i in ids if i.startswith("E9-")]) == 4, "점검 4")
    check(len(ids) == len(set(ids)), "id 겹침 없음")
    for e0 in ("E0", "E0b"):
        for g in ("button", "tool"):
            seeds = sorted(TC.resolve(b, TC.load_yaml(CONF / "실험" / f"{e0}-{g}-s{s}.yaml"), f"{e0}-{g}-s{s}")["seed"] for s in range(3))
            check(seeds == [0, 1, 2], f"{e0} {g} 시드 0·1·2")


def _try(b, p):
    try:
        TC.resolve(b, TC.load_yaml(p), p.stem)
        return None
    except ValueError as e:
        return str(e)


def test_id_끝_줄바꿈():
    print("[9] 실험 id 끝 줄바꿈은 형식이 아니다(빼기 · 이어서에 그대로 셸로 들어간다 · 2차 리뷰 사소)")
    check(TC.ID_RE.match("E4-button-x\n") is None and TC.ID_RE.match("E4-button-x") is not None, "끝 줄바꿈 거부 · 정상 id 통과")


if __name__ == "__main__":
    test_합치기()
    test_막기()
    test_기본값()
    test_커밋된_설정()
    test_id_끝_줄바꿈()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 학습 설정 검증 통과")
