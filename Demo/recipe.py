"""공정 레시피(시퀀스) 로더 — 통합 설계문서 §6 정본을 JSON으로 외부화.

레시피 = '정답 순서'의 단일 출처(single source of truth). FSM(판정)·디스플레이
(단계 이름)·로그가 모두 이 파일을 읽는다. load_recipe()는 읽기 + 검증을 하며,
잘못된 레시피(누락·중복·순서 깨짐)는 명확한 오류로 거부해 런타임 무동작을
예방한다.
"""

import json
import os

DEFAULT_RECIPE_PATH = os.path.join(os.path.dirname(__file__), "recipe.json")


class RecipeError(ValueError):
    """레시피 파일이 없거나 형식이 잘못됐을 때."""


def load_recipe(path=None):
    """레시피 JSON을 읽고 검증해 dict로 반환. 실패 시 RecipeError."""
    path = path or DEFAULT_RECIPE_PATH
    if not os.path.exists(path):
        raise RecipeError(f"레시피 파일 없음: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RecipeError(f"레시피 JSON 파싱 실패: {e}") from e
    _validate(data)
    return data


def _validate(data):
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RecipeError("steps가 비어있거나 리스트가 아닙니다.")

    if any(not s.get("button") for s in steps):
        raise RecipeError("button이 비어있는 step이 있습니다.")

    orders  = [s.get("order") for s in steps]
    buttons = [s["button"] for s in steps]

    if orders != list(range(1, len(steps) + 1)):
        raise RecipeError(f"order는 1..N 연속이어야 합니다: {orders}")
    if len(set(buttons)) != len(buttons):
        raise RecipeError(f"button이 중복됩니다: {buttons}")
    if data.get("emo_button") in buttons:
        raise RecipeError(f"emo_button({data.get('emo_button')})이 공정 버튼과 겹칩니다.")

    thr = data.get("dwell_threshold_sec", 1.0)
    if not (isinstance(thr, (int, float)) and thr > 0):
        raise RecipeError(f"dwell_threshold_sec가 양수가 아닙니다: {thr}")

    for s in steps:
        if "sub" in s:
            _validate_sub(s["sub"], s.get("button", "?"))


# 서브 작업 종류. 늘어나면 여기만 늘린다.
SUB_TYPES = ("wait", "wait_tool")


def _validate_sub(sub, button):
    """서브 작업(sub) 검증 — 정본 = 상위 design 문서 §6.

    sub 는 **선택**이다. 없으면 그 단계는 버튼을 누르는 즉시 다음으로 간다
    (하위 호환: sub 개념이 없던 기존 레시피가 그대로 읽힌다).

    잘못된 sub 를 통과시키면 런타임에 **조용히 무동작**이 되어
    "왜 게이지가 안 뜨지"를 헤매게 되므로 여기서 거부한다.
    """
    where = f"step {button}의 sub"

    if not isinstance(sub, dict):
        raise RecipeError(f"{where}가 객체가 아닙니다: {sub!r}")

    stype = sub.get("type")
    if stype not in SUB_TYPES:
        raise RecipeError(f"{where}.type 이 {SUB_TYPES} 중 하나가 아닙니다: {stype!r}")

    sec = sub.get("sec")
    if not (isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec > 0):
        raise RecipeError(f"{where}.sec 이 양수가 아닙니다: {sec!r}")

    if not sub.get("label"):
        raise RecipeError(f"{where}.label 이 비어 있습니다 (화면에 표시할 이름)")

    if stype == "wait_tool":
        tools = sub.get("tools")
        if not isinstance(tools, list) or not tools:
            raise RecipeError(f"{where}.tools 가 비어 있습니다 (선택지 목록)")
        tool = sub.get("tool")
        if tool not in tools:
            raise RecipeError(f"{where}.tool({tool!r})이 tools{tools} 안에 없습니다")


if __name__ == "__main__":
    import sys
    try:
        r = load_recipe(sys.argv[1] if len(sys.argv) > 1 else None)
    except RecipeError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"✅ '{r['process_name']}' — {len(r['steps'])}단계, "
          f"체류임계 {r['dwell_threshold_sec']}s, EMO={r['emo_button']}")
    for s in r["steps"]:
        print(f"   {s['order']}. [{s['button']}] {s['name']}")
