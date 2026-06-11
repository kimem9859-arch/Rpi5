"""recipe.json 로더 + 레시피 구동 FSM 검증.

실행: python Demo/test_recipe.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

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
