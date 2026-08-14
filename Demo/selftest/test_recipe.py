"""recipe.json 로더 + 레시피 구동 FSM 검증.

실행: python Demo/selftest/test_recipe.py
"""

import json
import os
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from recipe import load_recipe, RecipeError
from fsm import SafetyFSM, State


def _write(tmp, data):
    p = os.path.join(tmp, "r.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p


GOOD = {
    "process_name": "테스트 공정",
    "dwell_threshold_sec": 1.0,
    "emo_button": "EMO",
    "steps": [
        {"order": 1, "button": "B1", "name": "1단계"},
        {"order": 2, "button": "B2", "name": "2단계"},
        {"order": 3, "button": "B3", "name": "3단계"},
    ],
}


# ----------------------------------------------------- 실제 recipe.json 로드
def test_real_recipe_loads():
    r = load_recipe()                       # Demo/recipe.json
    assert r["process_name"]
    assert len(r["steps"]) == 4
    assert [s["button"] for s in r["steps"]] == ["B1", "B2", "B3", "B4"]
    print("  PASS  recipe.json 로드 + 4단계 B1~B4")


# ----------------------------------------------------- 검증: 나쁜 레시피 거부
def test_rejects_bad_recipes():
    cases = [
        ("order 깨짐",   {**GOOD, "steps": [{"order": 1, "button": "B1"}, {"order": 3, "button": "B2"}]}),
        ("button 중복",  {**GOOD, "steps": [{"order": 1, "button": "B1"}, {"order": 2, "button": "B1"}]}),
        ("EMO 겹침",     {**GOOD, "emo_button": "B1"}),
        ("steps 비어있음", {**GOOD, "steps": []}),
        ("임계 음수",     {**GOOD, "dwell_threshold_sec": -1}),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for label, data in cases:
            try:
                load_recipe(_write(tmp, data))
                assert False, f"{label}: 거부됐어야 함"
            except RecipeError:
                pass
    print("  PASS  잘못된 레시피 5종 모두 거부")


def test_missing_file():
    try:
        load_recipe("/nonexistent/r.json")
        assert False
    except RecipeError:
        print("  PASS  없는 파일 → RecipeError")


# ----------------------------------------------------- 레시피 구동 FSM
def test_fsm_driven_by_recipe():
    r = load_recipe()
    fsm = SafetyFSM(
        sequence=r["steps"],
        dwell_threshold=r["dwell_threshold_sec"],
        emo_button=r["emo_button"],
    )
    assert fsm.step_count == 4
    fsm.load_recipe()
    assert fsm.correct_roi == "B1"
    assert fsm.current_step_name == "클린·가스차단"
    fsm.update_vision("B1", now=0.0)
    fsm.press_button("B1")
    assert fsm.correct_roi == "B2"
    assert fsm.current_step_name == "펌프/퍼지"
    print("  PASS  레시피 구동 FSM — 단계 진행 + 이름 매핑")


# ----------------------------------------------------- 서브 작업(sub) 스키마
# 정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §6
def test_sub_backward_compatible():
    """🔴 sub 가 없는 기존 레시피가 그대로 읽혀야 한다 — 하위 호환."""
    with tempfile.TemporaryDirectory() as tmp:
        r = load_recipe(_write(tmp, GOOD))          # GOOD 에는 sub 가 없다
        assert all("sub" not in s for s in r["steps"])
    print("  PASS  sub 없는 레시피 하위 호환")


def test_sub_valid_forms():
    """wait / wait_tool 두 형태가 통과한다."""
    data = {**GOOD, "steps": [
        {"order": 1, "button": "B1", "name": "1단계",
         "sub": {"type": "wait", "sec": 30, "label": "대기"}},
        {"order": 2, "button": "B2", "name": "2단계",
         "sub": {"type": "wait_tool", "sec": 30, "label": "퍼지",
                 "tool": "spanner", "tools": ["spanner", "driver", "wrench"]}},
        {"order": 3, "button": "B3", "name": "3단계"},   # sub 없음도 섞인다
    ]}
    with tempfile.TemporaryDirectory() as tmp:
        r = load_recipe(_write(tmp, data))
        assert r["steps"][0]["sub"]["type"] == "wait"
        assert r["steps"][1]["sub"]["tool"] == "spanner"
        assert "sub" not in r["steps"][2]
    print("  PASS  sub wait / wait_tool / 없음 혼재 허용")


def test_sub_rejects_bad():
    """잘못된 sub 는 거부한다 — 런타임에 조용히 무동작이 되는 것을 막는다."""
    def step_with(sub):
        return {**GOOD, "steps": [{"order": 1, "button": "B1", "name": "1", "sub": sub}]}

    cases = [
        ("type 미지원",      {"type": "countdown", "sec": 30, "label": "x"}),
        ("type 없음",        {"sec": 30, "label": "x"}),
        ("sec 0",           {"type": "wait", "sec": 0, "label": "x"}),
        ("sec 음수",         {"type": "wait", "sec": -5, "label": "x"}),
        ("sec 비숫자",       {"type": "wait", "sec": "30", "label": "x"}),
        ("label 없음",       {"type": "wait", "sec": 30}),
        ("wait_tool 인데 tools 없음",
                            {"type": "wait_tool", "sec": 30, "label": "x", "tool": "spanner"}),
        ("wait_tool 인데 tool 이 tools 밖",
                            {"type": "wait_tool", "sec": 30, "label": "x",
                             "tool": "hammer", "tools": ["spanner", "driver"]}),
        ("sub 가 dict 가 아님", "wait"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for label, sub in cases:
            try:
                load_recipe(_write(tmp, step_with(sub)))
                assert False, f"{label}: 거부됐어야 함"
            except RecipeError:
                pass
    print(f"  PASS  잘못된 sub {len(cases)}종 모두 거부")


def test_real_recipe_has_scenario():
    """실제 recipe.json 이 확정 시나리오를 담고 있는가 (design §5).

    대기 3회(30초) + 2단계에 공구. 4단계는 서브 작업 없음.
    """
    r = load_recipe()
    steps = r["steps"]
    subs = [s.get("sub") for s in steps]

    assert subs[0] and subs[0]["type"] == "wait" and subs[0]["sec"] == 30
    assert subs[1] and subs[1]["type"] == "wait_tool" and subs[1]["sec"] == 30
    assert subs[2] and subs[2]["type"] == "wait" and subs[2]["sec"] == 30
    assert subs[3] is None, "4단계는 서브 작업이 없다(챔버 개방 = 시연 범위 밖)"
    # 🔑 A-2(2026-08-14) — tool_v3 의 클래스로 교체됐다. `spanner`(몽키)는 없어지고
    #    `pliers` 가 생겼다. 우리 오픈엔드 스패너의 정답은 `wrench`(§10.39-(6)).
    assert set(subs[1]["tools"]) == {"driver", "wrench", "pliers"}
    print("  PASS  recipe.json 시나리오 — 대기 30s×3 + 2단계 공구 3종")


def test_custom_sequence_non_b_labels():
    """버튼 라벨이 B1~B4가 아니어도(임의 라벨) 동작."""
    seq = [{"order": 1, "button": "LOAD", "name": "로딩"},
           {"order": 2, "button": "VAC", "name": "진공"}]
    fsm = SafetyFSM(sequence=seq)
    fsm.load_recipe()
    assert fsm.correct_roi == "LOAD"
    fsm.update_vision("LOAD", now=0.0)
    fsm.press_button("LOAD")
    assert fsm.correct_roi == "VAC"
    print("  PASS  임의 라벨 시퀀스(LOAD/VAC)도 동작")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} passed")
