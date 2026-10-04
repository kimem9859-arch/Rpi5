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
    print("[3] 기본.yaml = 설계 §6 시작값 · 1-3단계 표 2(120 에폭 끝까지 · 일찍 멈춤·포화 끔) · 공통 기준 = 공구 E0c 설정")
    b = TC.load_yaml(CONF / "기본.yaml")
    t = b["train"]
    want = {"epochs": 120, "patience": 0, "batch": 16, "workers": 2, "cache": "disk", "optimizer": "AdamW",
            "lr0": 0.001, "momentum": 0.9, "warmup_bias_lr": 0.0, "deterministic": True}
    for k, v in want.items():
        check(t.get(k) == v, f"{k} = {v} — {t.get(k)}")
    check(b["입력"] == "늘리기640" and b["출발"] == "yolov8n.pt" and b["seed"] == 0, "입력 · 출발 · seed")
    m = b["멈춤"]
    check((m["포화_에폭"], m["점수0_에폭"], m["점수0_mAP50"], m["진행없음_분"], m["시간상한_배"]) == (30, 10, 0.05, 15, 2), "멈춤 조건(설계 §7)")
    check(m["포화_향상"] == 0, f"포화 멈춤 끔(포화_향상 0) — {m['포화_향상']}")
    e0c = TC.resolve(b, TC.load_yaml(CONF / "실험" / "E0c-tool-f120.yaml"), "E0c-tool-f120")
    bare = TC.resolve(b, {"id": "E99-tool-bare", "group": "tool"}, "E99-tool-bare")
    check(TC.train_kwargs(e0c) == TC.train_kwargs(bare) and e0c["멈춤"] == bare["멈춤"],
          "새 기본으로 푼 공구 E0c = 아무것도 안 바꾼 공구 실험(학습 인자 · 멈춤)")


def test_커밋된_설정():
    print("[4] 실험 65(E0b 6 · 후보 시드 4 · 조합 E7 3 · 에폭 고정 12 · 탐색 확인 E10 6 · 가설 E11·E12 6 · 흐림 E13·E14 6 · 버튼 기준 B0 E15 3 포함) · 점검 4 — 전부 읽히고 id 가 겹치지 않는다")
    b = TC.load_yaml(CONF / "기본.yaml")
    ids = []
    for sub in ("실험", "점검"):
        for p in sorted((CONF / sub).glob("*.yaml")):
            e = _try(b, p)
            if e:
                check(False, f"{p.name}: {e}")
            ids.append(p.stem)
    exp = [i for i in ids if not i.startswith("E9-")]
    check(len(exp) == 65, f"실험 65 — {len(exp)}")
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


def test_흐림_키():
    print("[10] 흐림 증강 목록 — Blur · MotionBlur · MedianBlur 만(흑백 변환 등은 막음)")
    b = TC.load_yaml(CONF / "기본.yaml")
    c = TC.resolve(b, {"id": "E14-tool-blur", "group": "tool", "흐림": ["Blur", "MotionBlur"]}, "E14-tool-blur")
    check(c["흐림"] == ["Blur", "MotionBlur"] and "흐림=" in c["바꾼것"], f"{c.get('흐림')} · {c['바꾼것']}")
    try:
        TC.resolve(b, {"id": "E14-tool-gray", "group": "tool", "흐림": ["ToGray"]}, "E14-tool-gray"); bad = False
    except ValueError:
        bad = True
    check(bad, "ToGray → ValueError")


def test_id_끝_줄바꿈():
    print("[9] 실험 id 끝 줄바꿈은 형식이 아니다(빼기 · 이어서에 그대로 셸로 들어간다 · 2차 리뷰 사소)")
    check(TC.ID_RE.match("E4-button-x\n") is None and TC.ID_RE.match("E4-button-x") is not None, "끝 줄바꿈 거부 · 정상 id 통과")


def test_새꼴():
    print("[c5] 새 꼴 id — 접두↔group · 시드 · 학습 방식이 설정과 맞아야 통과(설계 모델이름 §2.2 · 실제 기본.yaml 위에서)")
    b = TC.load_yaml(CONF / "기본.yaml")

    def err(exp):
        try:
            TC.resolve(b, exp, exp["id"])
            return None
        except ValueError as e:
            return str(e)

    check(err({"id": "B-full-color-s0", "group": "button", "train": {"hsv_s": 0.3}}) is None, "B-full-color-s0 통과")
    check(TC.resolve(b, {"id": "T-full-base-s1", "group": "tool", "seed": 1}, "T-full-base-s1")["seed"] == 1, "시드 1 통과")
    check("무리" in (err({"id": "B-full-color-s0", "group": "tool"}) or ""), "접두 B ↔ group tool → 거부")
    check("시드" in (err({"id": "B-full-color-s1", "group": "button"}) or ""), "이름 -s1 ↔ seed 0 → 거부")
    check("full" in (err({"id": "B-full-color-s0", "group": "button", "train": {"patience": 20}}) or ""), "full 인데 patience 20 → 거부")
    check("full" in (err({"id": "B-full-color-s0", "group": "button", "멈춤": {"포화_향상": 0.002}}) or ""), "full 인데 포화 멈춤 → 거부")
    check("early" in (err({"id": "B-early-color-s0", "group": "button"}) or ""), "early 인데 patience 0 → 거부")
    check(err({"id": "B-early-color-s0", "group": "button", "train": {"patience": 20}}) is None, "early + patience 20 → 통과")
    check("형식" in (err({"id": "B1-full-color-s0", "group": "button"}) or ""), "B 뒤 숫자 → 거부")


def test_옛꼴_묶음():
    print("[c6] 옛 꼴 설정 파일은 지금 수에서 늘지 않는다 — 새 실험은 새 꼴로만(Review Focus 1)")
    old = [p.stem for sub in ("실험", "점검") for p in (CONF / sub).glob("*.yaml") if p.stem.startswith("E")]
    check(len(old) == 69, f"옛 꼴 설정 69(실험 65 · 점검 4) — {len(old)}")


if __name__ == "__main__":
    test_합치기()
    test_막기()
    test_기본값()
    test_커밋된_설정()
    test_id_끝_줄바꿈()
    test_흐림_키()
    test_새꼴()
    test_옛꼴_묶음()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 학습 설정 검증 통과")
