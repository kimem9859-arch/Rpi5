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


# =============================================================================
# 지금 할 일 · 공구 상황 — 설계 2026-10-04 §4.2(통역사 재설계)
# 🔑 판단은 여기 한 곳이다 — 카드 · 대체 문장 · 그물 · 알림이 모두 이것만 쓴다(재구현 금지).
#    내용은 화면 문구·판정기 동작에서 가져온다(화면과 음성이 같은 말을 한다).
# 🔴 조사(를·가·로·는)는 공구 이름이 모음으로 끝난다고 본다 — TOOL_KO(드라이버·렌치·플라이어)가 전부 그렇다.
# =============================================================================
ALERT_KINDS = ("비상정지", "차단", "경고")


def _seen_tools(dets, fresh):
    """카메라에 지금 보이는 공구들의 한글 이름 — 점수 높은 순 · 중복 없음. 낡았으면 빈 목록."""
    if not fresh:
        return []
    best = {}
    for d in dets or []:
        key = str(d[0]).split("-in-hand")[0].strip()
        if key in TOOL_KO:
            best[key] = max(best.get(key, -1.0), float(d[1]))
    return [TOOL_KO[k] for k in sorted(best, key=lambda k: -best[k])]


def tool_phase(state, dets, fresh, now=None):
    """공구가 필요한 서브 작업이 시작된 뒤의 공구 상황 · 아니면 None(설계 2026-10-04 §4.2-나).

    🔑 「보임」 = 요구 공구가 검출 목록에 **있느냐**다 — 점수 최고 하나를 고르면 3종이 함께 보일 때(정상)
       렌치가 가려진다. 🔑 검출이 없거나 낡았으면 「찾는중」 — 부재를 단정하지 않는다(tool_state 원칙).
    """
    p = sub_progress(state, now)
    if not p or not p["공구"] or p["상태"] == "시작 전":
        return None
    seen = _seen_tools(dets, fresh)
    wrong = ((state or {}).get("서브진행") or {}).get("공구오답") or None
    if p["공구충족"]:
        kind = "쥠"
    elif wrong:
        kind = "다른공구"
    elif p["공구"] in seen:
        kind = "보임"
    else:
        kind = "찾는중"
    return {"상황": kind, "요구": p["공구"], "보이는": seen, "쥔오답": wrong}


def tool_sentence(tp):
    """공구 상황을 말할 한 문장 — 대체 문장·공구 질문 폴백이 쓴다."""
    want = tp["요구"]
    if tp["상황"] == "쥠":
        return f"{want}를 쥐었습니다."
    if tp["상황"] == "다른공구":
        return f"{tp['쥔오답']}를 쥐고 있으니 {want}로 바꿔 쥐세요."
    if tp["상황"] == "보임":
        return f"앞에 {want}가 보이니 손으로 쥐면 확인됩니다."
    return f"{want}를 찾아 손으로 쥐세요."


def _act(kind, btn, allow, card, say):
    return {"종류": kind, "버튼": btn, "허용": tuple(b for b in allow if b), "카드": card, "말": say}


def in_emergency(state):
    """비상 상황인가 — 비상정지 또는 위반 차단·순서 경고, **해제 버튼을 누르기 전까지**(설계 2026-10-04 §4.7).

    🔑 EMO 를 풀었어도 「차단 해제」 전이면 `비상정지`·BLOCK 이 남는다(fsm.emo_active 는 해제 때 꺼진다).
    🔑 알림이 나갔는지가 아니라 **상태로** 본다 — 켤 때 EMO 신호 없음 · 작업 전 EMO 도 비상 상황이다.
    """
    st = state or {}
    return bool(st.get("비상정지")) or st.get("상태") in ("BLOCK", "WARNING")


def next_action(state, dets=(), fresh=False, now=None):
    """「지금 할 일」 — 우선순위 표(설계 2026-10-04 §4.2-가)의 위에서 처음 맞는 하나.

    돌려주는 것 = {"종류", "버튼"(지금 단계 버튼|None), "허용"(누르라고 말해도 되는 버튼), "카드"(카드 줄), "말"(한 문장|None)}
    🔑 비상정지가 완료보다 앞이다 — 완료 뒤에 눌러도 차단은 실제로 걸려 있다.
    🔑 비상 상황(비상정지·차단·경고)의 「말」은 알림·대체 문장이 쓴다 — 그때 LLM 은 답하지 않는다(§4.7).
    """
    st = state or {}
    btn = st.get("현재버튼")
    if not state or not st.get("세션"):
        return _act("작업전", None, (), "「작업 시작」을 누른다", None)
    if st.get("비상정지"):
        return _act("비상정지", btn, (),
                    "EMO 를 복귀한 뒤 「차단 해제」를 누른다 — 그 뒤 「작업 시작」부터 다시 한다",
                    "비상정지 중이니 EMO를 복귀한 뒤 차단 해제를 누르세요.")
    if st.get("결과"):
        return _act("완료", None, (), "할 일 없음 — 작업이 끝났다", "작업은 이미 완료됐습니다.")
    s = st.get("상태")
    if s == "BLOCK":
        return _act("차단", btn, (),
                    f"「차단 해제」를 누른 뒤 {btn} 부터 다시 누른다",
                    f"차단 중이니 차단 해제를 누른 뒤 {btn} 버튼부터 다시 누르세요.")
    p = sub_progress(state, now)
    if s == "WARNING":
        tail = f" — 멈춘 「{p['라벨']}」가 이어진다" if p and p["상태"] == "멈춤" else ""
        return _act("경고", btn, (btn,), f"손을 뗀 뒤 {btn} 를 누른다{tail}",
                    f"순서가 다르니 손을 떼고 {btn} 버튼을 누르세요.")
    if p and p["상태"] == "진행 중":
        nxt = st.get("다음단계")
        go = f"{nxt}단계로" if nxt else "다음으로"
        left = p["남은초"] or 0
        tp = tool_phase(state, dets, fresh, now)
        if tp and tp["상황"] != "쥠":
            grab = {"찾는중": f"{tp['요구']}를 찾아 쥔다", "보임": f"앞의 {tp['요구']}를 쥔다",
                    "다른공구": f"{tp['요구']}로 바꿔 쥔다"}[tp["상황"]]
            when = (f"시간은 다 됐고 {tp['요구']}만 쥐면 바로 {go} 넘어간다" if left <= 0
                    else f"쥐고 약 {left}초가 지나면 자동으로 {go} 넘어간다")
            return _act("공구", btn, (), f"{grab} — {when}", tool_sentence(tp))
        ok = f"{tp['요구']}는 확인됐고 " if tp else ""
        return _act("대기", btn, (), f"기다린다 — {ok}약 {left}초 뒤 자동으로 {go} 넘어간다",
                    f"지금은 「{p['라벨']}」 작업 중이며 끝나면 다음 단계로 넘어갑니다.")
    return _act("누름", btn, (btn,), f"{btn} 를 누른다", f"지금은 {btn} 차례입니다.")


def alert_kind(state):
    """알림 종류 — "비상정지"|"차단"|"경고"|None(설계 2026-10-04 §4.3).

    🔑 켤 때부터 EMO 가 HIGH(`EMO신호없음`)면 배선 끊김일 수 있어 「비상정지」로 알리지 않는다.
    """
    st = state or {}
    if st.get("비상정지"):
        return None if st.get("EMO신호없음") else "비상정지"
    if not st.get("세션"):
        return None
    return {"BLOCK": "차단", "WARNING": "경고"}.get(st.get("상태"))


def alert_key(kind, button=None):
    """미리 합성한 알림 소리의 키(= wav 파일 이름)."""
    if kind == "비상정지":
        return "alert_emo"
    return f"alert_{'block' if kind == '차단' else 'warn'}_{button}"


def alert_texts():
    """미리 합성할 알림 문장 9개 — 「지금 할 일」의 말 그대로(한 곳에서 만든다 · make_answers 가 쓴다)."""
    out = {"alert_emo": next_action({"세션": True, "비상정지": True})["말"]}
    for b in ("B1", "B2", "B3", "B4"):
        out[alert_key("차단", b)] = next_action({"세션": True, "상태": "BLOCK", "현재버튼": b})["말"]
        out[alert_key("경고", b)] = next_action({"세션": True, "상태": "WARNING", "현재버튼": b})["말"]
    return out


def alert_event(prev, cur):
    """직전·지금 상태 → None | ("알림", 소리 키) | ("멈춤", None).

    🔑 같은 GUI(pid) 안에서 바뀐 것만 본다 — 직전을 모르거나 GUI 가 새로 떴으면 알리지 않는다.
    """
    if not prev or not cur or prev.get("pid") != cur.get("pid"):
        return None
    pk, ck = alert_kind(prev), alert_kind(cur)
    if ck and ck != pk:
        return ("알림", alert_key(ck, cur.get("현재버튼")))
    if pk and not ck:
        return ("멈춤", None)
    return None


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
        "할일": next_action(state, dets, fresh, now),
        "공구상황": tool_phase(state, dets, fresh, now),
    }


def _progress_line(cur, btn, p):
    """서브 작업 진행 한 줄 — 🔴 이것이 없으면 「끝났어?」에 근거가 없어 「끝났습니다」를 지어냈다(R3 I4).

    공구 쪽은 「공구 상황」 줄이 따로 말한다(설계 2026-10-04 §4.1-6).
    """
    head = f"{cur}단계 진행 상황: "
    if p is None or p["상태"] == "시작 전":
        return head + f"버튼 {btn} 누르기 전 (서브작업 시작 전)"
    if p["상태"] == "멈춤":
        return head + f"서브작업 「{p['라벨']}」 경고로 멈춤 · 남은 시간 약 {p['남은초']}초"
    return head + f"버튼 {btn} 누름 · 서브작업 「{p['라벨']}」 진행 중 · 남은 시간 약 {p['남은초']}초"


_TOOL_LINE = {"찾는중": "{요구}를 찾아야 한다", "보임": "{요구}가 보인다 — 아직 쥐지 않았다(쥐면 확인된다)",
              "쥠": "{요구}를 쥐었다(확인됨)", "다른공구": "{쥔오답}를 쥐었다 — {요구}로 바꿔야 한다"}
# 🔑 「상태: 정상」을 장비 안전으로 읽어 「가스 누출 없어?」에 「정상」이라 답했다 — 순서 판정임을 밝힌다(§4.1-4)
_STATE_LINE = {"차단": "순서 판정: 🔴 차단 중 — 순서를 어겨 버튼 입력이 막혔다",
               "경고": "순서 판정: 경고 중 — 순서가 어긋났다",
               "정상": "순서 판정: 정상 (경고·차단 없음)"}
UNKNOWN_LINE = "이 시스템이 모르는 것: 가스·압력·온도 같은 장비 센서 값 · 다른 작업자"


def build_card(state, dets, fresh, now=None, question=None):
    """LLM 프롬프트에 붙일 `[사실]` 블록 — 맨 위가 코드가 정한 「지금 할 일」이다(설계 2026-10-04 §4.1).

    🔴 「지금 눌러야 할 버튼」 줄을 두지 않는다 — 비상정지 중에도 그 줄이 있어 모델이 「B3 를 누르세요」를
       옮겼다(holdout 2026-10-04). 누르라는 말은 「지금 할 일」에만 있다.
    """
    act = next_action(state, dets, fresh, now)
    L = ["[사실]", f"지금 할 일: {act['카드']}"]
    ask = asked_progress(question, card_facts(state, dets, fresh, now)) if question else None
    if ask:
        L.append(f"질문한 일: {ask['대상']} — {_ASK_STATE[ask['상태']]}")      # 🔑 끝남은 코드가 판단(§3-1 · 판 2 45번)
    st = state or {}
    emo = bool(st.get("비상정지"))
    if not state or not st.get("세션"):
        L.append("작업: 시작되지 않음 (작업자가 아직 「작업 시작」을 누르지 않았다)")
    elif st.get("결과"):
        # 🔴 완주 뒤에도 세션은 살려 둔다 — 「작업 결과 어때?」에 답해야 하기 때문이다.
        #    다만 「진행 중」이라고 쓰면 결과와 모순되므로 여기서 갈라 쓴다.
        L.append(f"작업: {st.get('공정명', '')} · 전체 {st.get('전체단계')}단계 · "
                 f"🔴 이미 완료됨 (더 누를 버튼이 없다)")
        if emo:
            L.append("멈춘 이유: 🔴 비상정지(EMO) — 순서 위반이 아니다")
    else:
        total, cur = st.get("전체단계"), st.get("현재단계")
        L.append(f"작업: {st.get('공정명', '')} · 전체 {total}단계 · 진행 중")
        last = " (마지막 단계)" if cur == total else ""
        label = "멈춘 자리" if emo else "현재 진행 중인 단계"
        L.append(f"{label}: {cur}단계 「{st.get('현재단계명', '')}」{last} — 아직 끝나지 않음 · "
                 f"이 단계의 버튼: {st.get('현재버튼', '')}")
        again = " (해제하면 1단계부터 다시)" if emo else ""
        L.append(f"끝난 단계: {_done_steps(cur)}{again}")
        if emo:
            # 🔴 EMO 는 순서 위반이 아니다 — 화면 문구(G5)와 같은 말을 해야 한다(V2)
            L.append("멈춘 이유: 🔴 비상정지(EMO) — 순서 위반이 아니다")
        else:
            L.append(_STATE_LINE[_state_bucket(st.get("상태"))])
        if st.get("다음단계"):
            # 🔴 「다음 버튼」만 적으면 LLM 이 그것을 지금 누르라고 권했다(R3 C3 · 5/5) — 조건을 같은 줄에 붙인다
            L.append(f"그 다음에 올 단계: {st['다음단계']}단계 「{st.get('다음단계명', '')}」 · "
                     f"버튼 {st.get('다음버튼', '')} (현재 단계가 끝난 뒤에만 누른다 — 지금 누르면 순서 위반이다)")
        else:
            L.append("그 다음에 올 단계: 없음")
        sub = st.get("서브작업")
        if sub:
            tool = sub.get("tool")
            name = sub.get("tool_name") or TOOL_KO.get(tool, tool)
            L.append(f"{cur}단계의 서브작업: {sub.get('label', '')} {sub.get('sec')}초 · "
                     f"{cur}단계에 필요한 공구 = {name if tool else '없음'}")
            L.append(_progress_line(cur, st.get("현재버튼", ""), sub_progress(state, now)))
        else:
            L.append(f"{cur}단계의 서브작업: 없음")
    tp = tool_phase(state, dets, fresh, now)
    if tp:
        others = [n for n in tp["보이는"] if n != tp["요구"]]
        extra = f" (보이는 다른 공구: {'·'.join(others)})" if tp["상황"] == "찾는중" and others else ""
        L.append("공구 상황: " + _TOOL_LINE[tp["상황"]].format(**tp) + extra)
    seen = _seen_tools(dets, fresh)
    if seen:
        L.append(f"카메라에 지금 보이는 공구: {'·'.join(seen)}")
    elif fresh:
        L.append("카메라에 지금 보이는 공구: 없음 (보고 있지만 아무 공구도 안 보인다)")
    else:
        L.append("카메라에 지금 보이는 공구: 확인 중이 아님 (지금은 공구를 인식하는 단계가 아니다)")
    L.append(UNKNOWN_LINE)
    res = st.get("결과")
    if res:
        L.append(f"작업 결과: 총 {res.get('total_sec', 0):.0f}초 · "
                 f"완료 {len(res.get('steps') or [])}단계 · "
                 f"순서 위반 {len(res.get('violations') or [])}회 · "
                 f"차단 {len(res.get('interlocks') or [])}회")
    return "\n".join(L) + "\n"


_STATE_WORDS = ("차단", "경고", "중지", "멈춰", "멈추")


def _tool_changed(then, now):
    """공구 사실이 바뀌었나 — 공구 상황이 있으면 (상황, 보이는 공구 집합) · 없으면 점수 최고 공구(종전)."""
    ta, tb = then.get("공구상황"), now.get("공구상황")
    if ta or tb:
        sig = lambda x: ((x or {}).get("상황"), tuple(sorted((x or {}).get("보이는") or ())))  # noqa: E731
        return sig(ta) != sig(tb)
    return then.get("공구") != now.get("공구")


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
    if any(ko in t for ko in TOOL_KO.values()) and _tool_changed(then, now):
        bad.append("공구")
    if mentioned_steps(t) and then.get("단계") != now.get("단계"):
        bad.append("단계")
    if re.search(r"B\s*[1-9]", t) and then.get("버튼") != now.get("버튼"):
        bad.append("버튼")
    if any(w in t for w in _STATE_WORDS) and then.get("상태") != now.get("상태"):
        bad.append("상태")
    if then.get("세션") != now.get("세션"):
        bad.append("세션")
    # 🔑 비상정지·차단·경고가 끼면 문장과 무관하게 버린다 — 그 사이 알림이 나갔거나 할 일이 뒤집혔다.
    #    그 밖의 넘어감은 문장에 나온 사실만 본다(서브 10초 · LLM 10초 — 무조건 비교하면 답이 매번 버려진다).
    a, b = then.get("할일") or {}, now.get("할일") or {}
    if ({a.get("종류"), b.get("종류")} & set(ALERT_KINDS)
            and (a.get("종류"), a.get("버튼")) != (b.get("종류"), b.get("버튼"))):
        bad.append("할일")
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

_REPLACE = (("[사실]", "작업 정보"), ("[질문]", ""), ("[규칙]", ""), ("[예시]", ""))
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
_YES = re.compile(r"^\s*(?:네|예)(?![가-힣])")
_DONE_Q = re.compile(r"끝났|끝난|끝냈|됐|완료|마쳤|다\s*했|다\s*된|끈났|끈난")  # 끝났냐는 질문
_NOT_DONE = re.compile(r"아직|안\s*끝|끝나지\s*않|않았|진행\s*중|시작\s*전")       # 안 끝났다는 말
_TOOL_ASK = re.compile(r"(?:렌치|드라이버|플라이어|공구).*(?:확인|인식|쥐|잡)|(?:확인|인식).*(?:렌치|드라이버|플라이어|공구)")
_CUR_ASK = re.compile(r"이번|이단계|지금단계")
_ALL_ASK = re.compile(r"작업|전부|전체|모두")
_STEP_NUM_ASK = re.compile(r"(\d)단계")
_ASK_STATE = {"끝남": "이미 끝남", "진행 중": "아직 끝나지 않음", "시작 전": "아직 시작 전"}
_YES_LEAD = re.compile(r"^\s*(?:네|예)(?![가-힣])[\s,.!]*")                   # 맨 앞 「네,」·「예.」
_GRIP = re.compile(r"(?:쥐었|쥐셨)(?!으면)|쥔\s*것으로\s*확인|확인됐|확인되었|확인\s*완료")
_SENSOR = re.compile(r"가스|압력|온도|누출|누설|진공도|유량")
SENSOR_SENTENCE = "그 정보는 이 시스템이 확인할 수 없습니다."
_RECIPE_PATH = os.path.join(_DEMO_DIR, "recipe.json")
_names_cache = None


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


def check_safety(text, facts, question=None):
    """말해도 되는 문장인가 — 걸린 규칙 이름들(빈 목록 = 통과). 설계 §4.4 C3 · 2026-10-04 §4.5.

    「허가」     스스로 허가하는 말(§10.53-(4) 유형 ⑤)
    「다른버튼」 「지금 할 일」의 허용 버튼이 아닌 B1~B4 를 「누르」 계열 동사와 함께 말함(R3 C3 ·
                2026-10-04 — 비상정지 중 「B3 누르세요」는 종전 「현재 버튼」 기준을 통과했다)
    「진행단정」 지금 단계·서브 작업이 끝났다고 말함 · 끝났냐는 질문에 「네」로 받고 「진행 중」이라 함(모순)
    「공구단정」 쥠 확정 전에 「쥐었다·확인됐다」
    🔑 EMO 는 버튼 검사에서 뺀다 — EMO 를 누르라는 말은 순서 위반이 아니라 안전 조작이다.
    「비상정지억제」 비상정지(EMO)를 누르지 말라거나 안 눌러도 된다고 함 — 언제나 틀렸다(상태와 무관 · dev 2026-10-03)
    🔑 작업 전·완료 뒤(비상정지가 아닐 때)는 「허가」·「비상정지억제」만 본다.
    """
    t = text or ""
    bad = []
    if any(w in t for w in PERMIT_WORDS):
        bad.append("허가")
    if _EMO_WORD.search(t) and _DONT_PRESS.search(t):
        bad.append("비상정지억제")
    if not facts.get("세션") or (facts.get("완료") and not facts.get("비상정지")):
        return bad
    act = facts.get("할일") or {"허용": (facts.get("버튼"),)}
    said = _buttons(t)
    if said and _PRESS.search(t) and said - set(act.get("허용") or ()):
        bad.append("다른버튼")
    if _MOVE_ON.search(t) and "다른버튼" not in bad:
        bad.append("다른버튼")
    if _DONE.search(t):
        cur = facts.get("단계")
        steps = mentioned_steps(t)
        names = [n for n in (facts.get("단계명"), (facts.get("서브") or {}).get("라벨")) if n]
        past_only = bool(steps) and cur is not None and all(s < cur for s in steps)
        if not past_only or any(n in t for n in names):
            bad.append("진행단정")
    if (question and _DONE_Q.search(question) and _YES.search(t) and "진행 중" in t
            and "진행단정" not in bad):
        bad.append("진행단정")
    tp = facts.get("공구상황")
    if tp and tp["상황"] != "쥠" and _GRIP.search(t) and (tp["요구"] in t or "공구" in t):
        bad.append("공구단정")
    return bad


def fallback_sentence(facts, tool_q=False):
    """안전 규칙에 걸린 답·LLM 이 못 낸 답 대신 말할 한 문장 — 「지금 할 일」의 말(설계 2026-10-04 §4.2·§4.6).

    공구를 물었고 공구 상황이 있으면 공구 문장. 작업 전이면 None(답 경로가 따로 있다).
    """
    if not facts.get("세션"):
        return None
    tp = facts.get("공구상황")
    if tool_q and tp:
        return tool_sentence(tp)
    act = facts.get("할일")
    if act and act.get("말"):
        return act["말"]
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


def _recipe_names(path=_RECIPE_PATH):
    """질문에서 지울 레시피 이름들(공백 없앤 꼴 · 긴 것부터) — 단계 이름과 그 조각 · 서브 작업 이름과 뒤쪽 어절 묶음."""
    global _names_cache
    if _names_cache is None:
        out = set()
        try:
            with open(path, encoding="utf-8") as f:
                steps = json.load(f).get("steps", [])
        except (OSError, ValueError):
            steps = []
        for s in steps:
            name = s.get("name") or ""
            out.add(name)
            out.update(re.split(r"[·/]", name))
            words = ((s.get("sub") or {}).get("label") or "").split()
            for k in range(len(words) - 1):            # 「전극 온도 하강」 → 전체 · 「온도 하강」
                out.add("".join(words[k:]))
        _names_cache = sorted({w.replace(" ", "") for w in out if len(w.replace(" ", "")) >= 2},
                              key=len, reverse=True)
    return _names_cache


_steps_cache = None


def _recipe_steps(path=_RECIPE_PATH):
    """레시피 단계 {번호: (이름, 서브 작업 이름|None)} — 카드의 「끝난 단계」가 쓴다."""
    global _steps_cache
    if _steps_cache is None:
        try:
            with open(path, encoding="utf-8") as f:
                steps = json.load(f).get("steps", [])
        except (OSError, ValueError):
            steps = []
        _steps_cache = {}
        for s in steps:
            sub = s.get("sub") or {}
            tool = sub.get("tool") if sub.get("type") == "wait_tool" else None
            tool_name = ((sub.get("tool_names") or {}).get(tool) or TOOL_KO.get(tool, tool)) if tool else None
            _steps_cache[s.get("order")] = (s.get("name") or "", sub.get("label"), tool_name)
    return _steps_cache


def _done_steps(cur):
    """끝난 단계를 이름·서브 작업 이름과 함께 — 🔴 번호만 적으면 「N2 퍼지 완료야?」에 근거가 없어 LLM 이
    「아직 끝나지 않았습니다」로 추측했다(holdout 판 2 45번 · 2026-10-04). 레시피가 없으면 번호만."""
    if not isinstance(cur, int) or cur <= 1:
        return "없음"
    names = _recipe_steps()
    parts = []
    for n in range(1, cur):
        name, sub, _ = names.get(n, ("", None, None))
        parts.append(f"{n}단계 「{name}」" + (f"({sub})" if sub else "") if name else f"{n}단계")
    return " · ".join(parts)


def _josa(word, with_final, without_final):
    """받침이 있으면 앞 것(은·을), 없으면 뒤 것(는·를) — 마지막 한글 글자로 본다."""
    for ch in reversed(word or ""):
        if "가" <= ch <= "힣":
            return with_final if (ord(ch) - 0xAC00) % 28 else without_final
    return without_final


def _step_words():
    """질문에서 단계를 찾을 낱말 {공백 없앤 낱말: 단계 번호} — 레시피의 이름·조각·서브 작업 이름·그 어절(긴 것부터)."""
    out = {}
    for n, (name, sub, _) in _recipe_steps().items():
        words = {name, *re.split(r"[·/\s]", name)}
        if sub:
            words |= {sub, *sub.split()}
        for w in words:
            w = w.replace(" ", "")
            if len(w) >= 2 and w != "진행":          # 「진행」은 「진행 중이야?」 같은 질문에 늘 나온다
                out.setdefault(w, n)
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


def asked_progress(question, facts):
    """끝났냐는 질문의 대상과 끝남을 코드가 정한다 → {"대상", "상태"(끝남|진행 중|시작 전), "말"} · 모르면 None.

    🔴 holdout 판 2 45번(2026-10-04) — 4단계에서 「N2 퍼지 완료야?」에 LLM 이 지금 단계 줄의 「아직 끝나지 않음」을
       옮겼다. 끝난 단계에 이름을 넣어도 그대로였다. 설계 §3-1 「끝남은 코드가 판단」을 이 질문에도 적용한다 —
       카드 맨 위에 판정을 주고(build_card), LLM 이 반대로 말하면 그물이 이 「말」로 바꾼다(finalize).
    대상 = 공구 확인(렌치 확인·인식) → 단계(번호·레시피 이름) → 이번 단계 → 작업 전체. 못 찾으면 None(LLM 이 답한다).
    """
    if not question or not facts.get("세션") or not _DONE_Q.search(question):
        return None
    q = question.replace(" ", "")
    done_all = bool(facts.get("완료"))
    cur = facts.get("단계")
    steps = _recipe_steps()
    if _TOOL_ASK.search(q):
        tool_step = next(((n, tn) for n, (_, _, tn) in sorted(steps.items()) if tn), None)
        if tool_step:
            n, want = tool_step
            tp = facts.get("공구상황")
            if done_all or (isinstance(cur, int) and cur > n) or (tp and tp["상황"] == "쥠"):
                st = "끝남"
            elif cur == n and tp:
                st = "진행 중"
            else:
                st = "시작 전"
            j = _josa(want, "은", "는")
            say = {"끝남": f"네, {want}{j} 이미 확인됐습니다.",
                   "진행 중": f"아니요, {want}{j} 아직 확인되지 않았습니다.",
                   "시작 전": f"아니요, {want} 확인은 아직 시작 전입니다."}[st]
            return {"대상": f"{want} 확인", "상태": st, "말": say, "낱말": [want]}
    n = None
    m = _STEP_NUM_ASK.search(q)
    if m:
        n = int(m.group(1))
    else:
        n = next((k for w, k in _step_words() if w in q), None)
    if n is None and _CUR_ASK.search(q):
        n = cur
    if n is not None and n in steps:
        name, sub, _ = steps[n]
        if done_all or (isinstance(cur, int) and n < cur):
            st = "끝남"
        elif n == cur:
            st = "진행 중"
        else:
            st = "시작 전"
        j = _josa(name, "은", "는")
        say = {"끝남": f"네, {n}단계 「{name}」{j} 이미 끝났습니다.",
               "진행 중": f"아니요, {n}단계 「{name}」{j} 아직 끝나지 않았습니다.",
               "시작 전": f"아니요, {n}단계 「{name}」{j} 아직 시작 전입니다."}[st]
        words = [w for w, k in _step_words() if k == n] + [f"{n}단계"]
        return {"대상": f"{n}단계 「{name}」" + (f"({sub})" if sub else ""), "상태": st, "말": say, "낱말": words}
    if _ALL_ASK.search(q):
        st = "끝남" if done_all else "진행 중"
        say = "네, 작업이 모두 끝났습니다." if done_all else "아니요, 작업은 아직 끝나지 않았습니다."
        return {"대상": "작업 전체", "상태": st, "말": say, "낱말": ["작업"]}
    return None


def sensor_question(question):
    """장비 센서(가스·압력·온도…)를 묻나 — 🔑 레시피 이름을 지운 뒤 본다(「클린·가스차단」·「전극 온도 하강」).

    이름은 recipe.json 에서 읽는다 — 손으로 적은 예외 목록을 두지 않는다(설계 2026-10-04 §4.5-나).
    """
    q = (question or "").replace(" ", "")
    for w in _recipe_names():
        q = q.replace(w, "")
    return bool(_SENSOR.search(q))


def sensor_answer(question, facts):
    """장비 센서 질문이면 LLM 없이 말할 문장 · 아니면(또는 작업 전이면) None — 이 시스템은 센서를 보지 않는다."""
    if facts.get("세션") and sensor_question(question):
        return SENSOR_SENTENCE
    return None


def finalize(raw, facts, question=None):
    """LLM 원문 → 말할 문장 `(문장, 출처, 걸린 규칙)`.

    출처 = "LLM" · "대체-안전규칙" · "대체-길이" · "빈답"(문장 None).
    🔑 첫 문장이 `ANSWER_MAX_CHARS` 를 넘으면 자르지 않고 사실 문장으로 바꾼다 — 자르면 술어가 잘려
       「…버튼 B3를.」 같은 조각이 말해졌다(최종 리뷰 I1 · dev 실제 사례).
    """
    if question and _DONE_Q.search(question) and facts.get("세션") and not facts.get("완료"):
        # 🔑 끝났냐는 질문에 작업이 진행 중이면 맨 앞 「네,」를 지운다 — temperature 때문에 무작위로 붙어
        #    (같은 카드·질문 10회 중 2~3회) 「끝났다」로 들렸다(holdout 판 2 9번 · 2026-10-04). 내용은 그대로 —
        #    지난 단계가 정말 끝났어도 「네」만 빠진다. 첫 문장을 자르기 전에 지워야 「예. 다음 문장」이 살아난다.
        raw = _YES_LEAD.sub("", raw or "", count=1)
    said = first_sentence(raw)
    if not re.search(r"[가-힣A-Za-z0-9]", said):
        return None, "빈답", []
    if said[-1] not in ".?!":
        said += "."
    bad = check_safety(said, facts, question)
    if "비상정지억제" in bad:
        return EMO_SENTENCE, "대체-안전규칙", bad
    ask = asked_progress(question, facts)
    if ask and ask["상태"] == "끝남" and _NOT_DONE.search(said):
        return ask["말"], "대체-안전규칙", ["끝남반대"]          # 끝났는데 안 끝났다고 함(판 2 45번)
    if ask and ask["상태"] != "끝남" and _DONE.search(said) and not _NOT_DONE.search(said):
        return ask["말"], "대체-안전규칙", ["진행단정"]          # 안 끝났는데 끝났다고 함
    if (ask and ask["상태"] == "끝남" and "진행단정" in bad and not _NOT_DONE.search(said)
            and any(w in said.replace(" ", "") for w in ask["낱말"])):
        bad.remove("진행단정")          # 끝난 대상(질문한 일)을 끝났다고 한 것 — 지금 단계 단정이 아니다
    if bad == ["공구단정"]:
        return tool_sentence(facts["공구상황"]), "대체-안전규칙", bad
    if bad:
        return fallback_sentence(facts), "대체-안전규칙", bad
    if len(said) > ANSWER_MAX_CHARS:
        return fallback_sentence(facts), "대체-길이", ["길이"]
    return said, "LLM", []
