"""사실 카드 — LLM 에게 줄 「우리가 아는 것」을 한 덩어리 글로 만든다.

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §5

🔴 **없는 것은 빼지 않고 「없다」고 적는다.** 비면 LLM 이 지어낸다 —
   §10.53-(4) 의 유형 ①(수치 지어냄)·②(모르는 상태를 안다고 함)·⑤(상태
   모르면서 허가함)는 전부 **「모른다」고 말하지 못하는 문제**다.

🔴 **라벨을 축약하지 않는다.** `현재:`/`다음:` 으로 줄여 썼을 때 모델이
   「이번 단계에 무슨 공구 필요해?」에 **다음 단계를 답했다**(§10.62-(6)).
   카드 내용은 같았고 라벨 문구만 달랐다.

🔑 **소켓·모델에 의존하지 않는 순수 함수만 둔다** — voice_lib.py 와 같은 철학.
   그래야 HW 없이 1초 안에 도는 selftest 가 된다.
"""
import json
import os
import sys

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

# 🔴 한글 표시명의 정본은 recipe.json 의 sub.tool_names 다. 여기 표는
#    레시피가 그 키를 안 줄 때의 폴백이자, **클래스명 목록**이기도 하다.
#    ⚠️ voice_lib._TOOL_KEYS 를 끌어 쓰지 않는다 — 비공개 이름이라 바뀌면 조용히 깨진다.
TOOL_KO = {"driver": "드라이버", "wrench": "렌치", "pliers": "플라이어"}

_STATE_FILE = "state.json"


def _state_path(path=None):
    if path:
        return path
    import config
    return os.path.join(config.STATE_SHM_DIR, _STATE_FILE)


def read_state(path=None):
    """GUI 가 낸 상태. 없거나 못 믿을 것이면 None.

    🔑 `pid` 를 확인한다 — /dev/shm 파일은 GUI 가 죽어도 재부팅까지 남는다.
       그 프로세스가 없으면 **유령 상태**이므로 없는 것으로 친다.
    """
    try:
        with open(_state_path(path), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    pid = d.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return None
    return d


def _seen_tool(dets, fresh):
    """카메라에 지금 보이는 공구 키. 없거나 낡았으면 None."""
    if not fresh:
        return None
    best, best_score = None, -1.0
    for d in dets or []:
        name = str(d[0]).split("-in-hand")[0].strip()
        if name not in TOOL_KO:
            continue
        if float(d[1]) > best_score:
            best, best_score = name, float(d[1])
    return best


def card_facts(state, dets, fresh):
    """검산이 대조할 사실 묶음 — 카드 문장이 아니라 값이다."""
    return {
        "공구": _seen_tool(dets, fresh),
        "단계": (state or {}).get("현재단계"),
        "버튼": (state or {}).get("현재버튼"),
        "상태": (state or {}).get("상태"),
        "세션": bool(state and state.get("세션")),
    }


def build_card(state, dets, fresh):
    """LLM 프롬프트에 붙일 `[사실]` 블록."""
    L = ["[사실]"]
    if not state or not state.get("세션"):
        L.append("작업: 시작되지 않음 (작업자가 아직 「작업 시작」을 누르지 않았다)")
    elif state.get("결과"):
        # 🔴 완주 뒤에도 세션은 살려 둔다 — 「작업 결과 어때?」에 답해야 하기 때문이다.
        #    다만 「진행 중」이라고 쓰면 결과와 모순되므로 여기서 갈라 쓴다.
        L.append(f"작업: {state.get('공정명', '')} · 전체 {state.get('전체단계')}단계 · "
                 f"🔴 이미 완료됨 (더 누를 버튼이 없다)")
    else:
        L.append(f"작업: {state.get('공정명', '')} · 전체 {state.get('전체단계')}단계 · 진행 중")
        cur = state.get("현재단계")
        L.append(f"현재 진행 중인 단계: {cur}단계 「{state.get('현재단계명', '')}」 "
                 f"· 지금 눌러야 할 버튼 {state.get('현재버튼', '')}")
        st = state.get("상태") or ""
        if st == "BLOCK":
            L.append("상태: 🔴 차단 중 — 순서를 어겨 전기 입력이 끊겼다")
        elif st == "WARNING":
            L.append("상태: 경고 중 — 순서가 어긋났다")
        else:
            L.append("상태: 정상 (경고 없음, 차단 없음)")
        if state.get("다음단계"):
            L.append(f"그 다음에 올 단계: {state['다음단계']}단계 "
                     f"「{state.get('다음단계명', '')}」 · 버튼 {state.get('다음버튼', '')}")
        else:
            L.append("그 다음에 올 단계: 없음 (이번이 마지막 단계다)")
        sub = state.get("서브작업")
        if sub:
            tool = sub.get("tool")
            name = sub.get("tool_name") or TOOL_KO.get(tool, tool)
            line = f"{cur}단계의 서브작업: {sub.get('label', '')} {sub.get('sec')}초"
            if tool:
                line += f" · {cur}단계에 필요한 공구 = {name}"
            else:
                line += f" · {cur}단계에 필요한 공구 = 없음"
            L.append(line)
        else:
            L.append(f"{cur}단계의 서브작업: 없음")

    seen = _seen_tool(dets, fresh)
    if seen:
        score = max(float(d[1]) for d in dets
                    if str(d[0]).split("-in-hand")[0].strip() == seen)
        L.append(f"카메라에 지금 보이는 공구: {TOOL_KO.get(seen, seen)} (신뢰도 {score:.2f})")
    elif fresh:
        L.append("카메라에 지금 보이는 공구: 없음 (보고 있지만 아무 공구도 안 보인다)")
    else:
        L.append("카메라에 지금 보이는 공구: 확인 중이 아님 "
                 "(지금은 공구를 인식하는 단계가 아니다)")

    res = (state or {}).get("결과")
    if res:
        L.append(f"작업 결과: 총 {res.get('total_sec', 0):.0f}초 · "
                 f"완료 {len(res.get('steps') or [])}단계 · "
                 f"순서 위반 {len(res.get('violations') or [])}회 · "
                 f"차단 {len(res.get('interlocks') or [])}회")
    return "\n".join(L) + "\n"
