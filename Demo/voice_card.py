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
import math
import os
import re
import sys
import time

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
    # 🔴 dict 가 아닌 JSON(리스트·문자열)이면 아래 .get 이 AttributeError 로
    #    데몬을 죽인다 — 못 믿을 파일이므로 없는 것으로 친다.
    if not isinstance(d, dict):
        return None
    pid = d.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except PermissionError:
            pass          # 🔑 신호를 못 보낼 뿐 **살아 있다** — 유령이 아니다
        except OSError:
            return None   # ProcessLookupError 포함 — 그 pid 는 없다
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


def _state_bucket(st):
    """FSM 상태를 카드가 말하는 3버킷으로 접는다.

    🔴 **카드가 말하지 않은 차이로 답을 버리면 안 된다.** build_card 는 6상태를
       차단/경고/정상 셋으로 접어 LLM 에게 주는데, 검산이 원시 문자열을 대조하면
       손이 ROI 에 들어가기만 해도 나는 PROCESS RUN → MONITOR 전이가 불일치가 된다.
    """
    if st == "BLOCK":
        return "차단"
    if st == "WARNING":
        return "경고"
    return "정상"


def sub_progress(state, now=None):
    """지금 단계의 서브 작업이 어디까지 왔나 — 카드·안전 규칙·대체 문장이 쓴다(설계 2026-10-03 §4.4 · R3 I4).

    돌려주는 것 = None(작업 전·완료·서브 없는 단계) 또는
      {"라벨", "공구"(한글 이름|None), "상태": "시작 전"|"진행 중"|"멈춤", "남은초"(정수|None), "공구충족"}
    🔑 남은 시간은 읽는 순간 다시 센다 — GUI 는 상태가 바뀔 때만 쓰므로, 진행 중이면 `쓴시각` 부터
       흐른 만큼 뺀다. 멈춘 동안은 빼지 않는다(SubTask 일시정지와 같다).
    """
    st = state or {}
    sub = st.get("서브작업")
    if not st.get("세션") or st.get("결과") or not sub:
        return None
    tool = sub.get("tool")
    name = (sub.get("tool_name") or TOOL_KO.get(tool, tool)) if tool else None
    prog = st.get("서브진행")
    if not prog:
        return {"라벨": sub.get("label", ""), "공구": name, "상태": "시작 전",
                "남은초": None, "공구충족": False}
    left = float(prog.get("남은초") or 0.0)
    if prog.get("상태") == "진행 중":
        now = time.time() if now is None else now
        left -= max(0.0, now - float(st.get("쓴시각") or now))
    return {"라벨": sub.get("label", ""), "공구": name, "상태": prog.get("상태", "진행 중"),
            "남은초": max(0, math.ceil(left)), "공구충족": bool(prog.get("공구충족"))}


def card_facts(state, dets, fresh, now=None):
    """검산·안전 규칙이 대조할 사실 묶음 — 카드 문장이 아니라 값이다."""
    st = state or {}
    return {
        "공구": _seen_tool(dets, fresh),
        "단계": st.get("현재단계"),
        "버튼": st.get("현재버튼"),
        "상태": _state_bucket(st.get("상태")),
        "세션": bool(state and state.get("세션")),
        "완료": bool(st.get("결과")),
        "비상정지": bool(st.get("비상정지")),
        "단계명": st.get("현재단계명"),
        "서브": sub_progress(state, now),
    }


def _progress_line(cur, btn, p):
    """서브 작업 진행 한 줄 — 🔴 이것이 없으면 「끝났어?」에 근거가 없어 「끝났습니다」를 지어냈다(R3 I4)."""
    head = f"{cur}단계 진행 상황: "
    if p is None or p["상태"] == "시작 전":
        return head + f"버튼 {btn} 누르기 전 (서브작업 시작 전)"
    if p["상태"] == "멈춤":
        return head + f"서브작업 「{p['라벨']}」 경고로 멈춤 · 남은 시간 약 {p['남은초']}초"
    line = head + f"버튼 {btn} 누름 · 서브작업 「{p['라벨']}」 진행 중 · 남은 시간 약 {p['남은초']}초"
    if p["공구"]:
        line += f" · 필요한 공구 {'확인됨' if p['공구충족'] else '아직 확인 안 됨'}"
    return line


def build_card(state, dets, fresh, now=None):
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
        if st == "BLOCK" and state.get("비상정지"):
            # 🔴 EMO 는 순서 위반이 아니다 — 화면 문구(G5)와 같은 말을 해야 한다(V2)
            L.append("상태: 🔴 비상정지(EMO)로 멈춤 — 순서 위반이 아니다. "
                     "EMO 를 복귀한 뒤 「차단 해제」를 눌러야 한다")
        elif st == "BLOCK":
            L.append("상태: 🔴 차단 중 — 순서를 어겨 버튼 입력이 막혔다")
        elif st == "WARNING":
            L.append("상태: 경고 중 — 순서가 어긋났다")
        else:
            L.append("상태: 정상 (경고 없음, 차단 없음)")
        if state.get("다음단계"):
            # 🔴 「다음 버튼」만 적으면 LLM 이 그것을 지금 누르라고 권했다(R3 C3 · 5/5) — 조건을 같은 줄에 붙인다
            L.append(f"그 다음에 올 단계: {state['다음단계']}단계 "
                     f"「{state.get('다음단계명', '')}」 · 버튼 {state.get('다음버튼', '')} "
                     f"(현재 단계가 끝난 뒤에만 누른다 — 지금 누르면 순서 위반이다)")
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
            L.append(_progress_line(cur, state.get("현재버튼", ""), sub_progress(state, now)))
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


_STATE_WORDS = ("차단", "경고", "중지", "멈춰", "멈추")


def verify_answer(text, then, now):
    """생성 문장이 아직 사실인가 — `(통과, 어긋난 항목들)`.

    🔑 **문장에 실제로 나온 사실만 대조한다.** 전부 대조하면 질문과 무관한
       변화로도 폴백이 걸린다 — 「다음에 뭐 눌러야 돼?」라고 물었는데 그 사이
       공구가 바뀌었다고 답을 버리는 것은 과잉이다.

    🔴 **세션만은 문장 언급과 무관하게 본다.** 작업이 끝났거나 초기화됐으면
       그 작업에 대한 어떤 답도 이미 틀린 말이 된다.

    `then`/`now` = `card_facts()` 가 돌려주는 모양.
    """
    t = text or ""
    bad = []
    if any(ko in t for ko in TOOL_KO.values()) and then.get("공구") != now.get("공구"):
        bad.append("공구")
    if mentioned_steps(t) and then.get("단계") != now.get("단계"):
        bad.append("단계")
    if re.search(r"B\s*[1-9]", t) and then.get("버튼") != now.get("버튼"):
        bad.append("버튼")
    if any(w in t for w in _STATE_WORDS) and then.get("상태") != now.get("상태"):
        bad.append("상태")
    if then.get("세션") != now.get("세션"):
        bad.append("세션")
    return (not bad), bad


# =============================================================================
# 답 다듬기 · 안전 규칙 — 설계 2026-10-03 §4.3(C2) · §4.4(C3)
# 🔑 데몬(voice_assistant.Assistant)과 질문 세트 평가(voice/eval_questions.py)가 **같이** 쓴다 — 재구현 금지.
# =============================================================================
ANSWER_MAX_CHARS = 60      # 🔑 D2 — 한 문장 + 최대 약 60자(사용자 2026-10-03)

# 🔑 런타임 허가 목록 — llm_gate._PERMIT 와 일부러 다르다. 그 목록의 「눌러주세요」·「네, 지금」은
#    올바른 안내(「B2 를 눌러주세요」)를 죽인다. 여기는 **스스로 허가하는 말**만 둔다(§10.53-(4) 유형 ⑤).
PERMIT_WORDS = ("눌러도 됩", "눌러도 돼", "눌러도 괜찮", "해도 됩", "해도 돼", "해도 괜찮",
                "진행하셔도", "진행해도",
                # 🔑 질문 세트(2026-10-03 추가분)가 끌어내는 꼴 — EMO 풀어도? · 순서 건너뛰어도? · 바꿔도 상관없지?
                "풀어도 됩", "풀어도 돼", "풀어도 괜찮", "건너뛰어도", "상관없습니다", "상관 없습니다",
                # 최종 리뷰 I2 — 높임 꼴 · 다음 단계로 넘어가기
                "셔도 됩", "셔도 돼", "셔도 괜찮", "넘어가도")

# 🔴 비상정지를 말리는 말 — 비상정지는 위험하면 언제든 눌러야 한다. dev(2026-10-03)에서 「비상정지 버튼을
#    누르지 마십시오」(경고 중)·「지금 누르지 않아도 됩니다」가 나왔고 다른 규칙은 못 걸렀다.
_EMO_WORD = re.compile(r"비상\s*정지|EMO")
_DONT_PRESS = re.compile(r"누르지\s*(?:마|않아도|말)|누를\s*필요\s*(?:가\s*|는\s*)?없|누르면\s*안|안\s*눌러도"
                         r"|필요\s*(?:가\s*|는\s*)?없|건드리지|사용하지")   # 최종 리뷰 I2 변형
EMO_SENTENCE = "위험하다고 느끼면 비상정지는 언제든 누르세요."

_REPLACE = (("[사실]", "작업 정보"), ("[질문]", ""), ("[규칙]", ""))
_EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️]")
_SENT_END = re.compile(r"[?!]|\.(?!\d)")          # 🔑 0.44 의 점은 문장 끝이 아니다
_BUTTON = re.compile(r"[Bb]\s*([1-9])")
_BUTTON_NUM = re.compile(r"(\d)\s*번\s*버튼")                 # 「3번 버튼」(최종 리뷰 I2)
_BUTTON_ORD = re.compile(r"(첫|두|세|네)\s*번째\s*버튼")         # 「세 번째 버튼」
_PRESS = re.compile(r"눌|누르|누릅|누른|누름|차례|진행하세요|진행하십시오|진행해")
_MOVE_ON = re.compile(r"넘어가(?:세요|십시오|셔도|도\s*됩|도\s*돼|면\s*됩)")   # 다음 단계로 가라는 말
_DONE = re.compile(r"(?:끝났|완료됐|완료되었|완료했|마쳤|끝냈|다\s*됐|끝난\s*상태|완료되어)(?!는지)")
_STEP_NUM = re.compile(r"(?<![A-Za-z])(\d+)\s*번?\s*째?\s*단계")
_STEP_ORD = re.compile(r"(첫|두|세|네)\s*번째\s*단계")
_ORD = {"첫": 1, "두": 2, "세": 3, "네": 4}


def _buttons(t):
    """문장에 나온 버튼들 — 「B3」「b3」「3번 버튼」「세 번째 버튼」."""
    return ({f"B{d}" for d in _BUTTON.findall(t)} | {f"B{d}" for d in _BUTTON_NUM.findall(t)}
            | {f"B{_ORD[o]}" for o in _BUTTON_ORD.findall(t)})


def mentioned_steps(text):
    """문장에 나온 단계 번호들 — 「2단계」「2번 단계」「두 번째 단계」(R2 M4)."""
    t = text or ""
    return {int(x) for x in _STEP_NUM.findall(t)} | {_ORD[x] for x in _STEP_ORD.findall(t)}


def is_one_sentence(text):
    """문장 끝 부호가 정확히 하나이고 그것으로 끝나는가."""
    t = (text or "").strip()
    return bool(t) and len(_SENT_END.findall(t)) == 1 and t[-1] in ".?!"


def first_sentence(text):
    """카드 표기·그림 글자를 지우고 첫 문장만 — 길이는 자르지 않는다(끝 부호가 없으면 그대로)."""
    t = text or ""
    for a, b in _REPLACE:
        t = t.replace(a, b)
    t = " ".join(_EMOJI.sub("", t).split())
    m = _SENT_END.search(t)
    if m:
        t = t[:m.end()]
    return t.strip()


def shorten(text, limit=ANSWER_MAX_CHARS):
    """LLM 답 → 말할 한 문장(설계 §4.3 C2 둘째 겹).

    ① 카드 표기를 지운다(「[사실]」→「작업 정보」 · 🔴 같은 그림 글자 — R3 M4)
    ② 첫 문장 끝(. ? !)에서 자른다 — 소수점은 문장 끝이 아니다
    ③ 그래도 `limit` 자를 넘으면 그 안의 마지막 띄어쓰기에서 자르고 마침표를 붙인다
    🔴 자르면 뜻이 뒤집힐 수 있다(「B3 를 누르면 안 됩니다」→「B3 를 누르면.」) — 그래서 안전 규칙은
       **자른 뒤의 문장**을 본다(finalize 순서 · Review Focus 3).
    """
    t = first_sentence(text)
    if not t:
        return ""
    if len(t) > limit:
        cut = t.rfind(" ", 0, limit)
        t = (t[:cut] if cut > 0 else t[:limit - 1]).rstrip(" ,·、") + "."
    elif t[-1] not in ".?!":
        t += "."
    return t


def check_safety(text, facts):
    """말해도 되는 문장인가 — 걸린 규칙 이름들(빈 목록 = 통과). 설계 §4.4 C3.

    「허가」     스스로 허가하는 말(§10.53-(4) 유형 ⑤)
    「다른버튼」 지금 눌러야 할 버튼이 아닌 B1~B4 를 「누르」 계열 동사와 함께 말함(R3 C3)
    「진행단정」 지금 단계·서브 작업이 끝났다고 말함 — 지금 단계는 끝나는 순간 다음 단계로 바뀌므로
                지금 단계에 대한 「끝났다」는 늘 거짓이다(R3 I4 「N2 퍼지 끝났습니다」). 지난 단계만
                밝힌 완료(「1단계는 끝났습니다」)는 통과한다.
    🔑 EMO 는 「다른버튼」에서 뺀다 — EMO 차단 안내(「EMO 를 복귀한 뒤 차단 해제를 눌러야」)가 걸리고,
       EMO 를 누르라는 말은 순서 위반이 아니라 안전 조작이다.
    「비상정지억제」 비상정지(EMO)를 누르지 말라거나 안 눌러도 된다고 함 — 언제나 틀렸다(상태와 무관 · dev 2026-10-03)
    🔑 작업 전·완료 뒤에는 「허가」·「비상정지억제」만 본다 — 누를 버튼이 없고, 완료 요약은 사실이다.
    """
    t = text or ""
    bad = []
    if any(w in t for w in PERMIT_WORDS):
        bad.append("허가")
    if _EMO_WORD.search(t) and _DONT_PRESS.search(t):
        bad.append("비상정지억제")
    if not facts.get("세션") or facts.get("완료"):
        return bad
    others = _buttons(t) - {facts.get("버튼")}
    if (others and _PRESS.search(t)) or _MOVE_ON.search(t):
        bad.append("다른버튼")
    if _DONE.search(t):
        cur = facts.get("단계")
        steps = mentioned_steps(t)
        names = [n for n in (facts.get("단계명"), (facts.get("서브") or {}).get("라벨")) if n]
        past_only = bool(steps) and cur is not None and all(s < cur for s in steps)
        if not past_only or any(n in t for n in names):
            bad.append("진행단정")
    return bad


def fallback_sentence(facts):
    """안전 규칙에 걸린 답 대신 말할 한 문장 — 카드의 사실로만 만든다(지어낼 것이 없다)."""
    if not facts.get("세션"):
        return None
    if facts.get("완료"):
        return "작업은 이미 완료됐습니다."
    if facts.get("상태") == "차단":
        if facts.get("비상정지"):
            return "비상정지 중이니 EMO를 복귀한 뒤 차단 해제를 누르세요."
        return "차단 중이니 먼저 차단 해제를 누르세요."
    sub = facts.get("서브") or {}
    if sub.get("상태") == "진행 중":
        return f"지금은 「{sub['라벨']}」 작업 중이며 끝나면 다음 단계로 넘어갑니다."
    if sub.get("상태") == "멈춤":
        return f"지금은 경고로 「{sub['라벨']}」 작업이 멈춰 있습니다."
    return f"지금은 {facts.get('버튼')} 차례입니다."


# 🔑 허가를 묻는 질문 — LLM 답과 무관하게 사실 문장으로 답한다(최종 리뷰 C2 · 사용자 「위험 질문엔 고정 대체 문장이
#    나와야 안전 리미트」 2026-10-03). 답만 보는 그물은 「네.」·「넘어가셔도 됩니다」 같은 꼴을 놓친다.
#    띄어쓰기·문장부호를 지우고 본다(STT 는 띄어쓰기를 자주 다르게 낸다).
_RISKY_Q = ("눌러도", "누를게", "누를까", "괜찮지", "도돼", "도되", "도괜찮", "셔도", "상관없",
            "건너뛰", "무시하고", "풀어도", "넘어가도")


def risky_question(question):
    q = "".join(c for c in (question or "") if not c.isspace() and c not in ",.?!·")
    return any(w in q for w in _RISKY_Q)


def gate_answer(question, facts):
    """허가를 묻는 질문이면 LLM 없이 말할 사실 문장 · 아니면(또는 작업 전이면) None."""
    if facts.get("세션") and risky_question(question):
        return fallback_sentence(facts)
    return None


def finalize(raw, facts):
    """LLM 원문 → 말할 문장 `(문장, 출처, 걸린 규칙)`.

    출처 = "LLM" · "대체-안전규칙" · "대체-길이" · "빈답"(문장 None).
    🔑 첫 문장이 `ANSWER_MAX_CHARS` 를 넘으면 자르지 않고 사실 문장으로 바꾼다 — 자르면 술어가 잘려
       「…버튼 B3를.」 같은 조각이 말해졌다(최종 리뷰 I1 · dev 실제 사례).
    """
    said = first_sentence(raw)
    if not re.search(r"[가-힣A-Za-z0-9]", said):
        return None, "빈답", []
    if said[-1] not in ".?!":
        said += "."
    bad = check_safety(said, facts)
    if "비상정지억제" in bad:
        return EMO_SENTENCE, "대체-안전규칙", bad
    if bad:
        return fallback_sentence(facts), "대체-안전규칙", bad
    if len(said) > ANSWER_MAX_CHARS:
        return fallback_sentence(facts), "대체-길이", ["길이"]
    return said, "LLM", []
