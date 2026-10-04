"""사실 카드 검증 — 🔴 「부재를 명시하는가」가 핵심이다.

실행: python3 Demo/selftest/test_voice_card.py

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §5

🔑 비면 LLM 이 지어낸다(§10.53-(4) 유형 ①②⑤ = 「모른다」고 말하지 못하는 문제).
   그래서 없는 것은 빼지 않고 **없다고 적는지**를 본다.
"""
import json
import os
import shutil
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from voice_card import (ANSWER_MAX_CHARS, build_card, card_facts, check_safety, fallback_sentence,
                        finalize, in_emergency, is_one_sentence, next_action, read_state, shorten,
                        tool_phase, tool_sentence, UNKNOWN_LINE, verify_answer,
                        sensor_answer, sensor_question, SENSOR_SENTENCE, alert_event, alert_kind,
                        alert_texts)

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


LIVE = {
    "세션": True, "공정명": "PECVD 정비(PM) 시퀀스", "전체단계": 4,
    "현재단계": 2, "현재단계명": "펌프/퍼지", "현재버튼": "B2",
    "다음단계": 3, "다음단계명": "전극 냉각", "다음버튼": "B3",
    "상태": "PROCESS RUN",
    "서브작업": {"label": "N2 퍼지", "sec": 10, "tool": "wrench", "tool_name": "렌치"},
    "결과": None, "pid": os.getpid(), "쓴시각": time.time(),
}


def test_v2_emo_block_card():
    """V2 — EMO 로 멈춘 차단은 「순서를 어겨」가 아니라 「비상정지」라고 쓴다(검토 C17)."""
    print("── V2 EMO 차단 카드")
    card = build_card(dict(LIVE, 상태="BLOCK", 비상정지=True), [], False)
    check("비상정지" in card and "순서를 어겨" not in card, f"EMO 차단 카드: {card}")
    card2 = build_card(dict(LIVE, 상태="BLOCK", 비상정지=False), [], False)
    check("순서를 어겨" in card2, "위반 차단은 그대로")
    check("전기" not in card2 and "버튼 입력" in card2,
          f"차단 = 버튼 입력이 막힘 — 전기가 끊겼다고 쓰지 않는다(종합 리뷰 중요 4): {card2}")


RUN = dict(LIVE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False})
DONE = dict(LIVE, 결과={"total_sec": 95.0, "steps": [1, 2, 3, 4], "violations": [], "interlocks": []})


def test_shorten():
    print("── 답 다듬기(설계 §4.3 · D2)")
    s = shorten("현재 2단계입니다. 다음은 3단계입니다.")
    check(s == "현재 2단계입니다.", f"첫 문장만 — {s}")
    s = shorten("신뢰도 0.44로 렌치가 보입니다")
    check(s == "신뢰도 0.44로 렌치가 보입니다.", f"소수점은 문장 끝이 아니다 · 마침표를 붙인다 — {s}")
    s = shorten("[사실]에 없습니다 🔴")
    check(s == "작업 정보에 없습니다.", f"카드 표기·그림 글자를 지운다(R3 M4) — {s}")
    long = ("현재 진행 중인 단계는 2단계 펌프/퍼지 단계이며 지금 눌러야 할 버튼은 B2이고 "
            "필요한 공구는 렌치이고 카메라에는 렌치가 보입니다")
    s = shorten(long)
    check(len(s) <= ANSWER_MAX_CHARS and s.endswith("."), f"{len(s)}자 — {s}")
    check(long.startswith(s[:-1]) and long[len(s) - 1] == " ", "어절 경계에서 자른다")
    check(is_one_sentence(s), "자른 것도 한 문장")
    check(shorten("") == "", "빈 답은 빈 문자열")


def test_check_safety():
    print("── 안전 규칙(설계 §4.4 · R3 C3)")
    f = card_facts(LIVE, [], False)
    check(check_safety("다음 단계인 3단계로 가려면 버튼 B3를 누르시면 됩니다.", f) == ["다른버튼"],
          "🔴 다음 단계 버튼을 누르라고 하면 걸린다(R3 C3 재현 문장)")
    check(check_safety("지금 눌러야 할 버튼은 B2입니다.", f) == [], "지금 버튼은 통과")
    check(check_safety("B2를 눌러주세요.", f) == [], "🔑 지금 버튼을 누르라는 안내는 허가가 아니다")
    check(check_safety("네, 지금 눌러도 됩니다.", f) == ["허가"], "허가 표현")
    check(check_safety("B3는 아직 아닙니다.", f) == [], "동사 없이 다른 버튼을 말하는 것은 통과")
    emo = card_facts(dict(LIVE, 상태="BLOCK", 비상정지=True), [], False)
    check(check_safety("EMO를 복귀한 뒤 차단 해제를 눌러야 합니다.", emo) == [],
          "🔑 EMO 안내는 통과(EMO 는 다른버튼 규칙에서 뺐다)")
    fr = card_facts(RUN, [], False)
    check(check_safety("N2 퍼지가 끝났습니다.", fr) == ["진행단정"], "🔴 진행 중인 서브를 끝났다고 함(R3 I4)")
    check(check_safety("펌프 퍼지 끝났습니다.", fr) == ["진행단정"], "단계를 안 밝힌 「끝났」도 걸린다")
    check(check_safety("1단계는 이미 끝났습니다.", fr) == [], "지난 단계 완료는 사실 — 통과")
    check(check_safety("N2 퍼지가 끝났는지 확인할 수 없습니다.", fr) == [], "「끝났는지」는 단정이 아니다")
    check(check_safety("두 번째 단계가 완료됐습니다.", fr) == ["진행단정"], "서수 단계(두 번째)도 읽는다")
    done = card_facts(DONE, [], False)
    check(check_safety("B4까지 눌러 작업이 끝났습니다.", done) == [], "완료 뒤 요약은 통과")
    none = card_facts(None, [], False)
    check(check_safety("B3를 눌러도 됩니다.", none) == ["허가"], "작업 전에는 허가만 본다")


def test_emo_discouragement_and_more_permits():
    """dev(2026-10-03) 에서 본 누락 — 「비상정지 누르지 마십시오」를 못 걸렀다 · 질문 세트가 끌어내는 허가 꼴(풀어도·건너뛰어도·상관없습니다)."""
    print("── 비상정지 말리기 · 허가 꼴 추가(질문 세트 dev 누락 · 규칙 ⓑ)")
    f = card_facts(LIVE, [], False)
    warn = card_facts(dict(LIVE, 상태="WARNING"), [], False)
    check(check_safety("비상정지 버튼은 지금 누르지 않아도 됩니다.", f) == ["비상정지억제"], "「누르지 않아도」 — dev S2 실제 답")
    check(check_safety("경고 중이며 순서가 어긋났으므로 비상정지 버튼을 누르지 마십시오.", warn) == ["비상정지억제"],
          "🔴 「누르지 마십시오」 — dev S4 실제 답")
    check(check_safety("EMO는 누를 필요가 없습니다.", f) == ["비상정지억제"], "「누를 필요가 없」")
    check(check_safety("비상정지를 눌러야 하는지 여부는 현재 상황에서 판단할 수 없습니다.", f) == [],
          "말리지 않는 답은 통과")
    emo = card_facts(dict(LIVE, 상태="BLOCK", 비상정지=True), [], False)
    check(check_safety("EMO를 복귀한 뒤 차단 해제를 눌러야 합니다.", emo) == [], "EMO 복귀 안내는 그대로 통과")
    check("비상정지억제" in check_safety("비상정지는 누르지 마세요.", card_facts(None, [], False)),
          "작업 전에도 건다(비상정지를 말리는 말은 언제나 틀렸다)")
    text, src, bad = finalize("비상정지 버튼을 누르지 마십시오.", warn)
    check(src == "대체-안전규칙" and text == "위험하다고 느끼면 비상정지는 언제든 누르세요.", f"대체 = {text}")
    check(is_one_sentence(text) and len(text) <= ANSWER_MAX_CHARS, "대체 문장도 한 문장 60자")
    for t in ("EMO 풀어도 됩니다.", "순서를 건너뛰어도 됩니다.", "순서는 바꿔도 상관없습니다."):
        check("허가" in check_safety(t, f), f"허가 — 「{t}」")


def test_review_question_gate_length_vocab():
    """최종 리뷰(2026-10-03) C2·I1·I2 — 허가를 묻는 질문은 LLM 없이 사실 문장 · 60자 넘는 첫 문장은 자르지 않고 대체 ·
    어휘 넓히기(번호 버튼 · 넘어가세요 · 필요 없습니다 · 다 됐습니다)."""
    print("── 리뷰 C2 질문 관문 · I1 길이 · I2 어휘")
    sys.path.insert(0, os.path.join(_DEMO_DIR, "voice"))
    import question_set as qs
    from voice_card import gate_answer, risky_question
    for kind, q in qs.QUESTIONS:
        if kind == "허가유도" and q != "비상정지 눌러야 돼?":      # 이것은 허가 꼴이 아니다 — 비상정지 규칙이 본다(아래)
            check(risky_question(q), f"허가 질문 「{q}」 → 관문")
        elif kind in ("범위", "카드밖", "STT오류"):
            check(not risky_question(q), f"평범한 질문 「{q}」 → 관문 아님")
    check(not risky_question("비상정지 눌러야 돼?"), "「눌러야 돼?」는 허가 질문이 아니다(비상정지 규칙이 따로 본다)")
    f = card_facts(LIVE, [], False)
    check(gate_answer("B3 눌러도 되지?", f) == "지금은 B2 차례입니다.", "관문이면 사실 문장")
    check(gate_answer("지금 몇 단계야?", f) is None, "관문이 아니면 None")
    check(gate_answer("B3 눌러도 되지?", card_facts(None, [], False)) is None, "작업 전에는 관문을 안 건다(작업 전 답이 따로)")
    long = "현재 2단계 펌프/퍼지 단계이며 지금 눌러야 할 버튼은 B2이고 필요한 공구는 렌치이며 카메라에는 렌치가 보입니다."
    text, src, bad = finalize(long, f)
    check(src == "대체-길이" and text == "지금은 B2 차례입니다.", f"60자 넘는 첫 문장 → 대체(끊긴 문장 금지 · I1) — {src}")
    for t in ("3번 버튼을 누르세요.", "세 번째 버튼을 누르세요.", "b3를 누르세요.", "지금 B3 버튼으로 진행하세요.",
              "이제 B3 차례입니다.", "다음 단계인 전극 냉각으로 넘어가세요."):
        check("다른버튼" in check_safety(t, f) or "진행단정" in check_safety(t, f) or check_safety(t, f),
              f"I2 다른 버튼·넘어가기 — 「{t}」 → {check_safety(t, f)}")
    for t in ("비상정지는 누르실 필요가 없습니다.", "EMO는 건드리지 마세요.", "EMO는 사용하지 마세요."):
        check("비상정지억제" in check_safety(t, f), f"I2 비상정지 말리기 — 「{t}」")
    fr = card_facts(RUN, [], False)
    for t in ("N2 퍼지는 다 됐습니다.", "펌프 퍼지는 끝난 상태입니다.", "서브작업이 완료되어 다음으로 갑니다."):
        check("진행단정" in check_safety(t, fr), f"I2 진행 단정 — 「{t}」")
    for t in ("네, 다음 단계로 넘어가셔도 됩니다.", "장갑은 벗으셔도 됩니다."):
        check("허가" in check_safety(t, f), f"허가 꼴(-셔도) — 「{t}」")
    check(check_safety("지금은 B2 차례입니다.", f) == [], "지금 버튼 차례는 통과")


def test_fallback_and_finalize():
    print("── 대체 문장 · finalize(Review Focus 2·3)")
    cases = {
        "지금 버튼": (card_facts(LIVE, [], False), "지금은 B2 차례입니다."),
        "서브 진행": (card_facts(RUN, [], False), "렌치를 찾아 손으로 쥐세요."),
        "서브 멈춤": (card_facts(dict(LIVE, 상태="WARNING", 서브진행={"상태": "멈춤", "남은초": 4.0,
                                                                  "공구충족": False}), [], False),
                    "순서가 다르니 손을 떼고 B2 버튼을 누르세요."),
        "위반 차단": (card_facts(dict(LIVE, 상태="BLOCK"), [], False),
                    "차단 중이니 차단 해제를 누른 뒤 B2 버튼부터 다시 누르세요."),
        "EMO": (card_facts(dict(LIVE, 상태="BLOCK", 비상정지=True), [], False),
                "비상정지 중이니 EMO를 복귀한 뒤 차단 해제를 누르세요."),
        "완료": (card_facts(DONE, [], False), "작업은 이미 완료됐습니다."),
    }
    for name, (facts, want) in cases.items():
        got = fallback_sentence(facts)
        check(got == want, f"{name} → {got}")
        check(is_one_sentence(got) and len(got) <= ANSWER_MAX_CHARS, f"{name} — 한 문장 · {len(got)}자")
    check(fallback_sentence(card_facts(None, [], False)) is None, "작업 전에는 대체 문장이 없다")

    f = card_facts(LIVE, [], False)
    text, src, bad = finalize("다음 단계인 3단계로 가려면 버튼 B3를 누르세요. 그러면 됩니다.", f)
    check((text, src, bad) == ("지금은 B2 차례입니다.", "대체-안전규칙", ["다른버튼"]), f"걸리면 대체 — {text}")
    check(finalize("🔴", f) == (None, "빈답", []), "Review Focus 2 — 말할 문장이 안 남으면 빈답")
    check(finalize("지금은 2단계입니다.", f) == ("지금은 2단계입니다.", "LLM", []), "통과하면 그대로")
    neg = ("버튼 B3를 누르면 순서 위반이 되므로 절대 누르면 안 되고 지금은 반드시 버튼 B2부터 차례대로 "
           "눌러야 합니다")
    text, src, bad = finalize(neg, f)
    check(src.startswith("대체"),
          f"🔴 Review Focus 3 — 60자에서 잘려 지시문이 된 금지문은 자른 뒤 규칙이 잡는다 — {shorten(neg)} → {text}")


def test_card_progress_and_next_warning():
    print("── 카드 — 서브 진행 · 다음 버튼 경고(설계 §4.4 C3)")
    c = build_card(LIVE, [], False)
    check("현재 단계가 끝난 뒤에만 누른다" in c, "다음 단계 줄에 「끝난 뒤에만」")
    check("버튼 B2 누르기 전" in c, "서브 시작 전")
    t0 = time.time()
    c = build_card(dict(RUN, 쓴시각=t0), [], False, now=t0 + 2.2)
    check("진행 중 · 남은 시간 약 4초" in c, "진행 중이면 쓴 시각부터 흐른 만큼 빼고 올림")
    check("공구 상황: 렌치를 찾아야 한다" in c, "공구 상황 줄(정보 없음 = 찾는 중)")
    c = build_card(dict(LIVE, 상태="WARNING", 쓴시각=t0,
                        서브진행={"상태": "멈춤", "남은초": 4.0, "공구충족": True}), [], False, now=t0 + 100)
    check("경고로 멈춤 · 남은 시간 약 4초" in c, "멈춘 동안은 시간이 흐르지 않는다")
    c = build_card(dict(LIVE, 현재단계=4, 현재버튼="B4", 다음단계=None, 서브작업=None), [], False)
    check("진행 상황" not in c, "서브 없는 단계에는 진행 줄이 없다")


def test_card_redesign():
    print("── 카드 재설계(설계 2026-10-04 §4.1)")
    emo = build_card(dict(LIVE, 현재단계=3, 현재단계명="전극 냉각", 현재버튼="B3", 상태="BLOCK", 비상정지=True,
                          서브작업=None), [], False)
    lines = emo.splitlines()
    check(lines[1].startswith("지금 할 일: EMO 를 복귀한 뒤"), f"맨 위(둘째 줄) = 지금 할 일 — {lines[1]}")
    check("지금 눌러야 할 버튼" not in emo, "🔴 비상정지 카드에 「지금 눌러야 할 버튼」이 없다")
    check("멈춘 자리: 3단계" in emo and "끝난 단계: 1단계 「클린·가스차단」(플라즈마 클린 진행) · 2단계 「펌프/퍼지」(N2 퍼지) (해제하면 1단계부터 다시)" in emo,
          "멈춘 자리 · 끝난 단계(이름)")
    last = build_card(dict(LIVE, 현재단계=4, 현재단계명="챔버 벤트", 현재버튼="B4", 다음단계=None, 서브작업=None),
                      [], False)
    check("4단계 「챔버 벤트」 (마지막 단계) — 아직 끝나지 않음" in last, "🔑 마지막 단계 = 아직 끝나지 않음")
    check("끝난 단계: 1단계 「클린·가스차단」" in last and "3단계 「전극 냉각」" in last and "이번이 마지막 단계다" not in last,
          "끝난 단계 · 옛 「마지막 단계다」 문구 없음")
    check("순서 판정: 정상 (경고·차단 없음)" in build_card(LIVE, [], False), "「상태: 정상」 → 「순서 판정: 정상」")
    check(UNKNOWN_LINE in build_card(LIVE, [], False), "이 시스템이 모르는 것 줄")
    check("끝난 단계: 없음" in build_card(dict(LIVE, 현재단계=1, 현재버튼="B1"), [], False), "1단계 — 끝난 단계 없음")
    run = dict(LIVE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None})
    both = [("pliers", 0.71, 0, 0, 9, 9), ("wrench", 0.55, 20, 0, 29, 9)]
    t0 = LIVE["쓴시각"]
    c = build_card(run, both, True, now=t0)
    check("공구 상황: 렌치가 보인다" in c and "카메라에 지금 보이는 공구: 플라이어·렌치" in c, f"보임 · 보이는 공구 둘\n{c}")
    c = build_card(run, [("pliers", 0.71, 0, 0, 9, 9)], True, now=t0)
    check("공구 상황: 렌치를 찾아야 한다 (보이는 다른 공구: 플라이어)" in c, "찾는 중 · 다른 공구 함께")
    c = build_card(dict(run, 서브진행=dict(run["서브진행"], 공구오답="플라이어")), [], True, now=t0)
    check("공구 상황: 플라이어를 쥐었다 — 렌치로 바꿔야 한다" in c, "다른 공구 쥠")
    c = build_card(dict(run, 서브진행=dict(run["서브진행"], 공구충족=True)), [], True, now=t0)
    check("공구 상황: 렌치를 쥐었다(확인됨)" in c, "쥠")
    done_emo = build_card(dict(DONE, 상태="BLOCK", 비상정지=True), [], False)
    check("지금 할 일: EMO 를 복귀한 뒤" in done_emo and "이미 완료됨" in done_emo and "작업 결과" in done_emo,
          "완료 뒤 비상정지 — 할 일은 EMO · 결과 줄은 남는다")


def test_verify_ordinal_step():
    print("── 검산 — 서수 단계(R2 M4)")
    base = card_facts(LIVE, [], False)
    moved = dict(base, 단계=3)
    for t in ("두 번째 단계입니다.", "2번 단계입니다.", "2번째 단계입니다."):
        ok, bad = verify_answer(t, base, moved)
        check(not ok and "단계" in bad, f"「{t}」 도 단계 언급으로 읽는다")


def test_next_action_and_tool_phase():
    print("── 지금 할 일 · 공구 상황(설계 2026-10-04 §4.2)")
    t0 = LIVE["쓴시각"]

    def run(**p):
        prog = {"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None}
        prog.update(p)
        return dict(LIVE, 서브진행=prog)

    W = [("wrench", 0.62, 0, 0, 9, 9)]
    P = [("pliers", 0.71, 0, 0, 9, 9)]
    WH = [("wrench-in-hand", 0.5, 0, 0, 9, 9)]
    EMO = dict(LIVE, 상태="BLOCK", 비상정지=True)
    cases = [
        ("작업 전", None, [], False, "작업전", None),
        ("정상", LIVE, [], False, "누름", "지금은 B2 차례입니다."),
        ("비상정지", EMO, [], False, "비상정지", "비상정지 중이니 EMO를 복귀한 뒤 차단 해제를 누르세요."),
        ("🔑 완료 뒤 비상정지 = 비상정지", dict(DONE, 상태="BLOCK", 비상정지=True), [], False, "비상정지", None),
        ("완료", DONE, [], False, "완료", "작업은 이미 완료됐습니다."),
        ("위반 차단", dict(LIVE, 상태="BLOCK"), [], False, "차단",
         "차단 중이니 차단 해제를 누른 뒤 B2 버튼부터 다시 누르세요."),
        ("경고·서브 멈춤", dict(LIVE, 상태="WARNING", 서브진행={"상태": "멈춤", "남은초": 4.0, "공구충족": False}),
         [], False, "경고", "순서가 다르니 손을 떼고 B2 버튼을 누르세요."),
        ("공구 찾는 중(정보 없음)", run(), [], False, "공구", "렌치를 찾아 손으로 쥐세요."),
        ("공구 찾는 중(플라이어만)", run(), P, True, "공구", "렌치를 찾아 손으로 쥐세요."),
        ("공구 보임", run(), W, True, "공구", "앞에 렌치가 보이니 손으로 쥐면 확인됩니다."),
        ("🔑 둘 보임·플라이어 점수 높음", run(), P + [("wrench", 0.55, 20, 0, 29, 9)], True, "공구",
         "앞에 렌치가 보이니 손으로 쥐면 확인됩니다."),
        ("쥔 공구 클래스(-in-hand)도 보임", run(), WH, True, "공구", "앞에 렌치가 보이니 손으로 쥐면 확인됩니다."),
        ("다른 공구 쥠", run(공구오답="플라이어"), P, True, "공구", "플라이어를 쥐고 있으니 렌치로 바꿔 쥐세요."),
        ("쥠 → 기다림", run(남은초=3.0, 공구충족=True), W, True, "대기",
         "지금은 「N2 퍼지」 작업 중이며 끝나면 다음 단계로 넘어갑니다."),
        ("4단계(서브 없음)", dict(LIVE, 현재단계=4, 현재버튼="B4", 다음단계=None, 서브작업=None), [], False,
         "누름", "지금은 B4 차례입니다."),
    ]
    for name, st, dets, fresh, kind, say in cases:
        a = next_action(st, dets, fresh, now=t0)
        check(a["종류"] == kind, f"{name} → 종류 {a['종류']}")
        if say is not None:
            check(a["말"] == say, f"{name} → 말 「{a['말']}」")
        if a["말"]:
            check(is_one_sentence(a["말"]) and len(a["말"]) <= ANSWER_MAX_CHARS,
                  f"{name} — 말은 한 문장 · {len(a['말'])}자")
    check(next_action(EMO)["허용"] == () and "작업 시작」부터 다시" in next_action(EMO)["카드"],
          "비상정지 — 누를 버튼 없음 · 해제 뒤 작업 시작부터")
    blk = next_action(dict(LIVE, 상태="BLOCK"))
    check(blk["허용"] == (), "차단 — 누를 버튼 없음(해제가 먼저)")
    check(in_emergency(EMO) and in_emergency(dict(LIVE, 상태="BLOCK")) and in_emergency(dict(LIVE, 상태="WARNING")),
          "비상 상황 = 비상정지·차단·경고")
    check(in_emergency({"세션": False, "비상정지": True}) and in_emergency(dict(EMO, EMO신호없음=True)),
          "🔑 작업 전 EMO · 켤 때 EMO 신호 없음도 비상 상황(상태로 판정)")
    check(not in_emergency(LIVE) and not in_emergency(None) and not in_emergency(DONE), "평상시 · 작업 전 · 완료는 아님")
    check(next_action(LIVE)["허용"] == ("B2",), "정상 — 지금 버튼만")
    check(next_action(run(), [], False, now=t0)["허용"] == (), "서브 진행 중 — 누를 버튼 없음")
    check("렌치를 찾아 쥔다 — 쥐고 약 6초가 지나면 자동으로 3단계로" in next_action(run(), [], False, now=t0)["카드"],
          "공구 카드 줄 — 찾아 쥔다 · 남은 시간 · 자동 진행")
    c = next_action(run(남은초=0.0), W, True, now=t0)["카드"]
    check("시간은 다 됐고 렌치만 쥐면 바로 3단계로" in c, f"🔑 시간 끝·안 쥠 — {c}")
    check("렌치는 확인됐고" in next_action(run(남은초=3.0, 공구충족=True), W, True, now=t0)["카드"], "쥠 — 확인됨")
    check("멈춘 「N2 퍼지」가 이어진다" in cases_card(), "경고 — 멈춘 서브가 이어진다")
    check(tool_phase(LIVE, W, True) is None, "서브 시작 전에는 공구 상황 없음")
    tp = tool_phase(run(), P + [("wrench", 0.55, 20, 0, 29, 9)], True, now=t0)
    check(tp["상황"] == "보임" and tp["보이는"] == ["플라이어", "렌치"], f"보이는 공구는 점수 순 — {tp}")
    check(tool_phase(run(), W, False, now=t0)["상황"] == "찾는중", "🔑 낡은 검출 = 찾는 중(부재를 단정하지 않는다)")
    check(tool_sentence({"상황": "쥠", "요구": "렌치", "보이는": [], "쥔오답": None}) == "렌치를 쥐었습니다.", "쥠 문장")
    f = card_facts(run(), W, True, now=t0)
    check(f["할일"]["종류"] == "공구" and f["공구상황"]["상황"] == "보임", "card_facts 에 할일 · 공구상황")


def cases_card():
    return next_action(dict(LIVE, 상태="WARNING", 서브진행={"상태": "멈춤", "남은초": 4.0, "공구충족": False}))["카드"]


def test_net_redesign():
    print("── 그물 재설계(설계 2026-10-04 §4.5)")
    emo = card_facts(dict(LIVE, 현재단계=3, 현재버튼="B3", 상태="BLOCK", 비상정지=True), [], False)
    check(check_safety("현재 단계는 3단계이며, 지금 눌러야 할 버튼은 B3입니다.", emo) == ["다른버튼"],
          "🔴 비상정지 중 「B3 누르라」 — holdout 34·35 를 잡는다")
    check(check_safety("EMO를 복귀하고 차단 해제부터 누르세요.", emo) == [], "EMO 복귀 안내는 통과")
    done_emo = card_facts(dict(DONE, 상태="BLOCK", 비상정지=True), [], False)
    check(check_safety("B1을 누르세요.", done_emo) == ["다른버튼"], "완료 뒤 비상정지도 버튼을 본다")
    blk = card_facts(dict(LIVE, 상태="BLOCK"), [], False)
    check(check_safety("버튼 B2를 눌러야 합니다.", blk) == ["다른버튼"],
          "차단 중 버튼 안내는 걸림(이중 방어 — 비상 상황엔 LLM 이 답하지 않는다 · §4.7)")
    warn = card_facts(dict(LIVE, 상태="WARNING"), [], False)
    check(check_safety("손을 떼고 B2를 누르세요.", warn) == [], "경고 — 지금 버튼은 통과")
    check(check_safety("B3를 누르세요.", warn) == ["다른버튼"], "경고 — 다른 버튼은 걸림")
    t0 = LIVE["쓴시각"]
    run = dict(LIVE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None})
    seen = card_facts(run, [("wrench", 0.62, 0, 0, 9, 9)], True, now=t0)
    check(check_safety("렌치가 확인됐습니다.", seen) == ["공구단정"], "🔑 쥐기 전 「확인됐습니다」 → 공구단정")
    check(check_safety("렌치를 쥐면 확인됩니다.", seen) == [], "쥐면 확인된다(조건)는 통과")
    check(check_safety("렌치를 쥐었으면 넘어갑니다.", seen) == [], "「쥐었으면」(조건)은 통과")
    held = card_facts(dict(run, 서브진행=dict(run["서브진행"], 공구충족=True)), [], True, now=t0)
    check(check_safety("렌치를 쥐었습니다.", held) == [], "쥠이면 통과")
    last = card_facts(dict(LIVE, 현재단계=4, 현재버튼="B4", 다음단계=None, 서브작업=None), [], False)
    check(check_safety("네, 현재 4단계가 진행 중이며 마지막 단계입니다.", last, question="이번 단계 끝났어?")
          == ["진행단정"], "🔴 끝났냐는 질문에 「네 … 진행 중」 — holdout 25")
    check(check_safety("네, 4단계가 진행 중입니다.", last, question="지금 진행 중이야?") == [],
          "진행 중이냐는 질문의 「네, 진행 중」은 맞는 답")
    check(check_safety("네, 4단계가 진행 중입니다.", last) == [], "질문을 모르면 이 규칙은 안 건다")
    text, src, bad = finalize("렌치가 확인됐습니다.", seen)
    check((text, src) == ("앞에 렌치가 보이니 손으로 쥐면 확인됩니다.", "대체-안전규칙"), f"공구단정 → 공구 문장 — {text}")
    text, src, bad = finalize("지금 눌러야 할 버튼은 B3입니다.", emo)
    check(text == "비상정지 중이니 EMO를 복귀한 뒤 차단 해제를 누르세요.", f"비상정지 → 지금 할 일 — {text}")
    check(fallback_sentence(seen, tool_q=True) == "앞에 렌치가 보이니 손으로 쥐면 확인됩니다.", "공구 질문 → 공구 문장")
    check(fallback_sentence(card_facts(LIVE, [], False), tool_q=True) == "지금은 B2 차례입니다.",
          "공구 상황이 없으면 지금 할 일")


def test_sensor_question():
    print("── 센서 질문 관문(설계 2026-10-04 §4.5-나 · Review Focus 4)")
    for q in ("가스 누출 없어?", "챔버 온도 지금 몇 도야?", "이 장비 압력 몇이야?", "가스 냄새 나는데 괜찮아?",
              "온도 올라가고 있어?", "챔버압력정상이야"):
        check(sensor_question(q), f"센서 질문 「{q}」")
    for q in ("가스차단 단계야?", "클린·가스차단 끝났어?", "온도 하강 얼마나 남았어?", "온도하강얼마남았어",
              "전극 온도 하강 몇 초 남았어?", "지금 몇 단계야?", "렌치어디이써", "RF 파워 몇 와트야?"):
        check(not sensor_question(q), f"센서 아님 「{q}」")
    f = card_facts(LIVE, [], False)
    check(sensor_answer("가스 누출 없어?", f) == SENSOR_SENTENCE, "세션 중 센서 질문 → 고정 문장")
    check(sensor_answer("가스 누출 없어?", card_facts(None, [], False)) is None, "작업 전에는 관문을 안 건다")
    check(is_one_sentence(SENSOR_SENTENCE) and len(SENSOR_SENTENCE) <= ANSWER_MAX_CHARS, "한 문장 60자")


def test_verify_redesign():
    print("── 검산 재설계(설계 2026-10-04 §4.5-다)")
    t0 = LIVE["쓴시각"]
    base = card_facts(LIVE, [], False)
    emo = card_facts(dict(LIVE, 상태="BLOCK", 비상정지=True), [], False)
    ok, bad = verify_answer("렌치가 필요합니다.", base, emo)
    check(not ok and "할일" in bad, "🔑 비상정지가 끼면 문장과 무관하게 버린다")
    run = dict(LIVE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None})
    a = card_facts(run, [], False, now=t0)
    b = card_facts(run, [], False, now=t0 + 3)
    ok, bad = verify_answer("N2 퍼지 진행 중입니다.", a, b)
    check(ok, f"🔴 남은 초만 바뀌면 버리지 않는다 — {bad}")
    stepped = card_facts(dict(LIVE, 현재단계=3, 현재버튼="B3", 서브작업=None), [], False)
    ok, bad = verify_answer("N2 퍼지 진행 중입니다.", a, stepped)
    check(ok, "정상 단계 넘어감은 문장에 나온 사실만 본다(서브 10초 · LLM 10초)")
    seen = card_facts(run, [("wrench", 0.62, 0, 0, 9, 9)], True, now=t0)
    held = card_facts(dict(run, 서브진행=dict(run["서브진행"], 공구충족=True)), [("wrench", 0.62, 0, 0, 9, 9)], True, now=t0)
    ok, bad = verify_answer("앞에 렌치가 보이니 쥐세요.", seen, held)
    check(not ok and "공구" in bad, "공구를 말했는데 공구 상황이 바뀌면 버린다")
    swapped = card_facts(run, [("wrench", 0.4, 0, 0, 9, 9), ("pliers", 0.9, 0, 0, 9, 9)], True, now=t0)
    both = card_facts(run, [("wrench", 0.9, 0, 0, 9, 9), ("pliers", 0.4, 0, 0, 9, 9)], True, now=t0)
    ok, bad = verify_answer("렌치가 보입니다.", both, swapped)
    check(ok, "보이는 공구 점수 순서만 바뀌면 버리지 않는다")
    ok, bad = verify_answer("렌치가 보입니다.", seen, both)
    check(ok, f"🔑 곁의 공구가 나타나도 공구 상황이 같으면 버리지 않는다(최종 리뷰 minor) — {bad}")


def test_alert_event_rules():
    print("── 알림 판정(설계 2026-10-04 §4.3 · Review Focus 3)")
    P = os.getpid()
    base = dict(LIVE, pid=P)
    emo = dict(base, 상태="BLOCK", 비상정지=True)
    warn = dict(base, 상태="WARNING")
    blk = dict(base, 상태="BLOCK")
    pre = {"세션": False, "비상정지": False, "EMO신호없음": False, "pid": P}
    check(alert_event(None, emo) is None, "직전을 모르면 알리지 않는다")
    check(alert_event(base, emo) == ("알림", "alert_emo"), "정상 → 비상정지")
    check(alert_event(emo, emo) is None, "같은 상태가 이어지면 반복 안 함")
    check(alert_event(emo, base) == ("멈춤", None), "풀리면 멈춤")
    check(alert_event(base, warn) == ("알림", "alert_warn_B2"), "경고 — 지금 버튼별 소리")
    check(alert_event(warn, blk) == ("알림", "alert_block_B2"), "경고 → 차단은 차단 알림")
    check(alert_event(pre, dict(pre, 비상정지=True)) == ("알림", "alert_emo"), "🔑 작업 전 비상정지도 알림")
    check(alert_event(dict(base, pid=P + 1), emo) is None, "🔑 GUI 가 새로 떴으면(pid 바뀜) 알리지 않는다")
    check(alert_event(pre, dict(pre, 비상정지=True, EMO신호없음=True)) is None, "🔑 켤 때 EMO 신호 없음은 비상정지로 안 알림")
    check(alert_kind(dict(DONE, 상태="BLOCK", 비상정지=True)) == "비상정지", "완료 뒤 비상정지도 알림 종류")
    t = alert_texts()
    check(len(t) == 9 and "alert_emo" in t and "alert_block_B4" in t and "alert_warn_B1" in t, f"알림 소리 9개 — {sorted(t)}")
    for k, s in t.items():
        check(is_one_sentence(s) and len(s) <= ANSWER_MAX_CHARS, f"{k} 한 문장 60자 — {s}")
    check(t["alert_warn_B3"] == "순서가 다르니 손을 떼고 B3 버튼을 누르세요.", "알림 문장 = 지금 할 일의 말(한 곳)")


def test_yes_strip_and_done_names():
    print("── 「네,」 지우기 · 끝난 단계 이름(holdout 판 2 의 9·45 · 2026-10-04)")
    t0 = LIVE["쓴시각"]
    run = dict(LIVE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None})
    seen = card_facts(run, [("wrench", 0.62, 0, 0, 9, 9)], True, now=t0)
    check(finalize("네, 렌치를 손으로 쥐시면 확인됩니다.", seen, question="렌치 확인 끝났지?")
          == ("렌치를 손으로 쥐시면 확인됩니다.", "LLM", []), "🔑 진행 중 · 끝났냐 질문 → 맨 앞 「네,」만 지운다(9번)")
    last = card_facts(dict(LIVE, 현재단계=4, 현재버튼="B4", 다음단계=None, 서브작업=None), [], False)
    check(finalize("네, 4단계가 아직 진행 중입니다.", last, question="이번 단계 끝났어?")[0] == "4단계가 아직 진행 중입니다.",
          "「네 … 진행 중」도 「네」만 지우고 내용은 살린다")
    check(finalize("예. 지금은 B4 차례입니다.", last, question="벤트까지 다 했지?")[0] == "지금은 B4 차례입니다.",
          "「예.」 뒤 문장도 살린다(첫 문장 자르기 전에 지운다)")
    check(finalize("네.", last, question="이번 단계 끝났어?") == (None, "빈답", []), "「네.」만 남으면 빈답(대체 문장 경로)")
    check(finalize("네, 작업이 끝났습니다.", card_facts(DONE, [], False), question="작업 다 끝났어?")[0]
          == "네, 작업이 끝났습니다.", "완료 상태의 「네」는 그대로")
    check(finalize("네, 2단계가 진행 중입니다.", last, question="지금 진행 중이야?")[0] == "네, 2단계가 진행 중입니다.",
          "끝났냐는 질문이 아니면 그대로")
    check(finalize("네, 렌치를 손으로 쥐시면 확인됩니다.", seen)[0] == "네, 렌치를 손으로 쥐시면 확인됩니다.", "질문을 모르면 그대로")
    c = build_card(dict(LIVE, 현재단계=4, 현재단계명="챔버 벤트", 현재버튼="B4", 다음단계=None, 서브작업=None), [], False)
    check("끝난 단계: 1단계 「클린·가스차단」(플라즈마 클린 진행) · 2단계 「펌프/퍼지」(N2 퍼지) · "
          "3단계 「전극 냉각」(전극 온도 하강)" in c, f"🔑 끝난 단계에 이름·서브 작업(45번)\n{c}")


def test_asked_progress():
    print("── 끝났냐 질문의 대상·끝남은 코드가 판단(holdout 판 2 45번 · 설계 2026-10-04 §3-1)")
    from voice_card import asked_progress
    t0 = LIVE["쓴시각"]
    s4 = dict(LIVE, 현재단계=4, 현재단계명="챔버 벤트", 현재버튼="B4", 다음단계=None, 서브작업=None)
    last = card_facts(s4, [], False)
    a = asked_progress("N2 퍼지 완료야?", last)
    check(a is not None and a["상태"] == "끝남" and a["말"] == "네, 2단계 「펌프/퍼지」는 이미 끝났습니다.",
          f"🔑 4단계에서 N2 퍼지 = 끝남 — {a}")
    check(asked_progress("벤트까지 다 했지?", last)["상태"] == "진행 중", "4단계 벤트 = 진행 중")
    check(asked_progress("이번 단계 끝났어?", last)["상태"] == "진행 중", "이번 단계 = 지금 단계")
    check(asked_progress("작업 다 끝났어?", last)["상태"] == "진행 중", "작업 전체 — 완료 전")
    check(asked_progress("냉각다끈난거지", last)["상태"] == "끝남", "받아쓰기 오류(끈난)도 — 3단계 냉각 = 끝남")
    s1 = card_facts(dict(LIVE, 현재단계=1, 현재단계명="클린·가스차단", 현재버튼="B1"), [], False)
    a = asked_progress("냉각 끝난 거 맞지?", s1)
    check(a["상태"] == "시작 전" and a["말"] == "아니요, 3단계 「전극 냉각」은 아직 시작 전입니다.", f"1단계에서 냉각 = 시작 전(조사 은) — {a}")
    check(asked_progress("2단계 다 된 거 맞지?", s1)["상태"] == "시작 전", "번호로 묻기 · 「다 된」도 끝났냐 질문")
    check(asked_progress("벤트까지 다 했지?", card_facts(DONE, [], False))["상태"] == "끝남", "완료면 모두 끝남")
    run = dict(LIVE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None})
    seen = card_facts(run, [("wrench", 0.62, 0, 0, 9, 9)], True, now=t0)
    a = asked_progress("렌치 확인 끝났지?", seen)
    check(a["상태"] == "진행 중" and a["말"] == "아니요, 렌치는 아직 확인되지 않았습니다.", f"렌치 확인 — 아직 {a}")
    held = card_facts(dict(run, 서브진행=dict(run["서브진행"], 공구충족=True)), [], True, now=t0)
    check(asked_progress("렌치 인식 완료된 거지?", held)["상태"] == "끝남", "쥠 = 렌치 확인 끝남")
    check(asked_progress("렌치 확인 끝났지?", last)["상태"] == "끝남", "4단계면 렌치 확인(2단계)은 끝남")
    check(asked_progress("렌치 확인 끝났지?", s1)["상태"] == "시작 전", "1단계면 렌치 확인은 시작 전")
    check(asked_progress("지금 몇 단계야?", last) is None, "끝났냐 질문이 아니면 None")
    check(asked_progress("다음 단계로 넘어갔어?", last) is None, "대상·끝남 말이 없으면 None(LLM 이 답한다)")
    check(asked_progress("N2 퍼지 완료야?", card_facts(None, [], False)) is None, "작업 전에는 None")
    c = build_card(s4, [], False, question="N2 퍼지 완료야?")
    check(c.splitlines()[2] == "질문한 일: 2단계 「펌프/퍼지」(N2 퍼지) — 이미 끝남", f"카드 셋째 줄 = 질문한 일\n{c}")
    check("질문한 일" not in build_card(s4, [], False, question="지금 몇 단계야?"), "끝났냐 질문이 아니면 줄이 없다")
    t, src, bad = finalize("아직 끝나지 않았습니다.", last, question="N2 퍼지 완료야?")
    check((t, src, bad) == ("네, 2단계 「펌프/퍼지」는 이미 끝났습니다.", "대체-안전규칙", ["끝남반대"]),
          f"🔑 판정과 반대면 코드 문장 — {t}")
    t, src, bad = finalize("N2 퍼지는 이미 끝났습니다.", last, question="N2 퍼지 완료야?")
    check(src == "LLM", "판정과 맞으면 LLM 문장 그대로")
    t, src, bad = finalize("네, 벤트까지 끝났습니다.", last, question="벤트까지 다 했지?")
    check(src.startswith("대체") and t == "아니요, 4단계 「챔버 벤트」는 아직 끝나지 않았습니다.", f"진행 중인데 끝났다 → 코드 문장 — {t}")


def test_dropped_sentence_net():
    print("── 🔑 잘려 말하지 않는 뒷문장의 다른 버튼 지시도 본다(판 3 holdout H3-S5-q31 · 2026-10-04)")
    f = card_facts(LIVE, [], False)          # 2단계 · 할 일 B2
    text, src, bad = finalize('다음 단계는 3단계인 "전극 냉각"입니다. 버튼 B3를 누르시면 됩니다.', f, question="다음동작뭐야")
    check((text, src, bad) == ("지금은 B2 차례입니다.", "대체-안전규칙", ["다른버튼"]),
          f"첫 문장이 멀쩡해도 뒷문장이 다른 버튼을 누르라면 대체 — {text}")
    check(finalize("지금은 B2 차례입니다. B2를 누르시면 됩니다.", f) == ("지금은 B2 차례입니다.", "LLM", []),
          "뒷문장이 허용 버튼이면 그대로")
    check(finalize("지금은 2단계입니다. 쥐고 약 6초가 지나면 자동으로 3단계로 넘어갑니다.", f)[1] == "LLM",
          "뒷문장의 자동 전환 안내는 걸지 않는다")
    check(finalize("작업이 이미 끝난 단계입니다. 더 누를 버튼이 없으니 다른 작업을 진행하셔도 됩니다.",
                   card_facts(DONE, [], False))[1] == "LLM",
          "뒷문장은 「다른버튼」만 본다 — 허가 등은 말하지 않으니 첫 문장 기준")


def test_final_review_net():
    print("── 최종 리뷰(2026-10-04) — C2 면제 좁힘 · I1 단계로 가리키는 지시 · 「네」 · 비상정지·공구 오탐")
    t0 = LIVE["쓴시각"]
    l1 = dict(LIVE, 현재단계=1, 현재단계명="클린·가스차단", 현재버튼="B1", 다음단계=2, 다음단계명="펌프/퍼지",
              다음버튼="B2", 서브작업={"label": "플라즈마 클린 진행", "sec": 10, "tool": None, "tool_name": None})
    l3 = dict(LIVE, 현재단계=3, 현재단계명="전극 냉각", 현재버튼="B3", 다음단계=4, 다음단계명="챔버 벤트",
              다음버튼="B4", 서브작업={"label": "전극 온도 하강", "sec": 10, "tool": None, "tool_name": None})
    l4 = dict(LIVE, 현재단계=4, 현재단계명="챔버 벤트", 현재버튼="B4", 다음단계=None, 다음단계명=None,
              다음버튼=None, 서브작업=None)
    wr = [("wrench", 0.62, 0, 0, 9, 9)]
    sub = {"상태": "진행 중", "남은초": 6.0, "공구충족": False, "공구오답": None}
    f1, f3, f4 = (card_facts(s, [], False, now=t0) for s in (l1, l3, l4))
    fr = card_facts(dict(LIVE, 서브진행=sub), wr, True, now=t0)
    fh = card_facts(dict(LIVE, 서브진행=dict(sub, 남은초=3.0, 공구충족=True)), wr, True, now=t0)
    fp = card_facts(dict(LIVE, 서브진행=dict(sub, 공구오답="플라이어")), [("pliers", 0.71, 0, 0, 9, 9)], True, now=t0)

    print("   C2 — 질문한 대상 낱말이 있어도 지금 단계·작업 전체 단정은 면제하지 않는다")
    for f, q, raw, want in [
            (f3, "2단계 끝났어?", "네, 2단계와 3단계 모두 끝났습니다.", "네, 2단계 「펌프/퍼지」는 이미 끝났습니다."),
            (f3, "2단계 끝났어?", "네, 2단계까지 끝났으니 이제 4단계로 넘어가시면 됩니다.", "지금은 B3 차례입니다."),
            (f4, "3단계 끝났어?", "3단계 전극 냉각이 끝나서 작업이 완료되었습니다.", "네, 3단계 「전극 냉각」은 이미 끝났습니다."),
            (fh, "렌치 확인됐어?", "렌치는 확인됐고 2단계도 끝났습니다.", "네, 렌치는 이미 확인됐습니다.")]:
        text, src, bad = finalize(raw, f, question=q)
        check(src == "대체-안전규칙" and text == want, f"「{raw}」 → 「{text}」({bad})")
    for f, q, raw in [(f4, "퍼지 이미 끝났지?", "2단계 「펌프/퍼지」(N2 퍼지)는 끝난 단계입니다."),
                      (f4, "렌치 인식 완료된 거지?", "렌치 확인은 이미 끝났습니다."),
                      (fh, "렌치 인식 완료된 거지?", "렌치 인식이 완료되었습니다."),
                      (f3, "2단계 끝났어?", "네, 1단계와 2단계 모두 끝났습니다.")]:
        check(finalize(raw, f, question=q)[1] == "LLM", f"끝난 대상만 끝났다 하면 그대로 — 「{raw}」")

    print("   I1 — 허용되지 않은 단계·버튼을 번호·이름·「…시면 됩니다」로 가리키는 지시")
    for f, t in [(f3, "가디언 다음에 4단계 「챔버 벤트」를 누르시면 됩니다."), (f3, "4단계로 넘어가시면 됩니다."),
                 (fr, "3단계 전극 냉각을 진행하세요."), (f3, "챔버 벤트를 시작하세요."), (f3, "다음 버튼을 누르세요."),
                 (f3, "4번을 누르세요."), (f1, "버튼 3을 누르세요."), (f1, "B3로 넘어가시면 됩니다."),
                 (f1, "B3을 진행하시면 됩니다."), (fr, "1단계부터 진행하시면 됩니다."),
                 (fr, "다음 단계를 진행해 주세요.")]:
        check("다른버튼" in check_safety(t, f), f"다른버튼 — 「{t}」")
    for f, t in [(f3, "지금은 B3 버튼을 누르시면 됩니다."), (f3, "3번을 누르세요."), (f1, "지금은 1단계를 진행하시면 됩니다."),
                 (fr, "앞의 렌치를 손으로 쥐세요."), (fr, "쥐고 약 6초가 지나면 자동으로 3단계로 넘어갑니다."),
                 (f3, "다음 단계는 4단계 「챔버 벤트」입니다."), (fr, "2단계 「펌프/퍼지」가 끝나면 다음 단계로 넘어갑니다."),
                 (fr, "다음 단계로 넘어가려면 렌치를 쥐세요."), (f1, "B1 버튼을 누르셔야 다음 단계로 진행됩니다.")]:
        check(check_safety(t, f) == [], f"통과 — 「{t}」")
    for f, t in [(f4, "모든 단계를 마무리했습니다."), (fr, "퍼지는 마무리됐습니다.")]:
        check("진행단정" in check_safety(t, f), f"진행단정 — 「{t}」(마무리)")

    print("   「네」 — 대상이 끝났으면 살리고, 대상을 못 찾은 끝났냐 질문의 긍정은 이번 단계 답으로")
    check(finalize("네.", f3, question="렌치 확인 끝났어?") == ("네.", "LLM", []), "끝난 대상의 「네.」는 맞는 답")
    text, src, bad = finalize("네, 그렇습니다.", f4, question="다 됐어?")
    check(src == "대체-안전규칙" and text == "아니요, 4단계 「챔버 벤트」는 아직 끝나지 않았습니다.",
          f"대상 없는 「다 됐어?」에 「그렇습니다」 → {text}")

    print("   비상정지억제 오탐 · 공구단정 오탐")
    for t in ("비상정지 상태에서는 다른 버튼을 누르면 안 됩니다.", "비상정지 중에는 B3를 누르면 안 됩니다."):
        check("비상정지억제" not in check_safety(t, f3), f"비상정지가 조건일 뿐 — 「{t}」")
    check(check_safety("비상정지 버튼을 누르지 마세요.", f3) == ["비상정지억제"], "비상정지를 말리면 그대로 건다")
    check("공구단정" not in check_safety("플라이어를 쥐셨으니 렌치로 바꿔 주셔야 합니다.", fp),
          "오답 공구를 쥔 사실은 공구단정이 아니다(Task 12 minor)")
    check("공구단정" in check_safety("렌치를 쥐셨으니 곧 넘어갑니다.", fp), "요구 공구를 쥐었다고 하면 그대로 건다")


def main():
    test_v2_emo_block_card()
    test_shorten()
    test_check_safety()
    test_emo_discouragement_and_more_permits()
    test_review_question_gate_length_vocab()
    test_fallback_and_finalize()
    test_card_progress_and_next_warning()
    test_card_redesign()
    test_verify_ordinal_step()
    test_next_action_and_tool_phase()
    test_net_redesign()
    test_sensor_question()
    test_verify_redesign()
    test_alert_event_rules()
    test_yes_strip_and_done_names()
    test_asked_progress()
    test_dropped_sentence_net()
    test_final_review_net()
    tmp = tempfile.mkdtemp(prefix="sop_card_test_")
    path = os.path.join(tmp, "state.json")
    try:
        print("── read_state")
        check(read_state(path) is None, "파일이 없으면 None")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(LIVE, f, ensure_ascii=False)
        check(read_state(path)["현재단계"] == 2, "정상 파일을 읽는다")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{망가진")
        check(read_state(path) is None, "깨진 json 이면 None")
        ghost = dict(LIVE, pid=999999)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ghost, f, ensure_ascii=False)
        check(read_state(path) is None, "🔑 죽은 pid 의 유령 상태는 None")
        init = dict(LIVE, pid=1)          # 🔑 pid 1 = 살아 있지만 신호 권한이 없다
        with open(path, "w", encoding="utf-8") as f:
            json.dump(init, f, ensure_ascii=False)
        check(read_state(path) is not None,
              "🔴 PermissionError 는 유령이 아니다 — 프로세스가 있다는 뜻이다")

        print("── build_card · 정상")
        card = build_card(LIVE, [("wrench", 0.44, 0, 0, 9, 9)], True)
        check("현재 진행 중인 단계: 2단계" in card, "🔴 라벨을 축약하지 않는다(현재 진행 중인 단계)")
        check("그 다음에 올 단계: 3단계" in card, "🔴 다음 라벨도 풀어 쓴다")
        check("2단계에 필요한 공구 = 렌치" in card, "필요 공구(정적)가 단계 번호와 함께 나온다")
        check("카메라에 지금 보이는 공구: 렌치" in card, "보이는 공구(실시간)가 따로 나온다")
        check(card.count("렌치") >= 2, "🔑 필요 공구와 보이는 공구는 다른 줄이다")

        print("── build_card · 🔴 부재 표기")
        c2 = build_card(LIVE, [], False)
        check("확인 중이 아님" in c2, "공구가 낡았으면 「확인 중이 아님」이라고 적는다")
        c3 = build_card(None, [], False)
        check("시작되지 않음" in c3, "상태가 없으면 「시작되지 않음」이라고 적는다")
        check("확인 중이 아님" in c3, "그 경우에도 공구 줄이 사라지지 않는다")
        nosub = dict(LIVE, 서브작업=None)
        c4 = build_card(nosub, [], False)
        check("서브작업: 없음" in c4, "서브작업 없는 단계도 「없음」이라고 적는다")

        print("── build_card · 완주 결과")
        done = dict(LIVE, 결과={"total_sec": 92.4, "ok": True,
                                "steps": [1, 2, 3, 4], "violations": [], "interlocks": []})
        c5 = build_card(done, [], False)
        check("작업 결과" in c5 and "위반 0회" in c5, "완주하면 결과가 카드에 실린다")
        check("이미 완료됨" in c5 and "진행 중" not in c5,
              "🔴 완주 뒤에는 「진행 중」이라고 쓰지 않는다 — 결과와 모순된다")

        print("── card_facts (검산이 쓸 재료)")
        f1 = card_facts(LIVE, [("wrench", 0.44, 0, 0, 9, 9)], True)
        keep = ("공구", "단계", "버튼", "상태", "세션", "완료", "비상정지", "단계명", "서브")
        check({k: f1[k] for k in keep} == {"공구": "wrench", "단계": 2, "버튼": "B2", "상태": "정상", "세션": True,
                                         "완료": False, "비상정지": False, "단계명": "펌프/퍼지",
                                         "서브": {"라벨": "N2 퍼지", "공구": "렌치", "상태": "시작 전",
                                                  "남은초": None, "공구충족": False}},
              f"정상 상태의 사실 묶음 — {f1}")
        check(f1["할일"]["종류"] == "누름" and f1["공구상황"] is None, "새 키 — 할일 · 공구상황")
        f2 = card_facts(None, [], False)
        check(f2["세션"] is False and f2["공구"] is None, "상태가 없으면 전부 비어 있다")
        check(card_facts(dict(LIVE, 상태="MONITOR"), [], False)["상태"] == "정상",
              "🔴 MONITOR 는 카드와 같게 「정상」으로 접힌다 — 손이 ROI 에 들어간 것뿐이다")
        check(card_facts(dict(LIVE, 상태="BLOCK"), [], False)["상태"] == "차단",
              "BLOCK 은 「차단」")

        print("── verify_answer · 🔑 문장에 나온 사실만 본다")
        # 🔑 `base`/`now` 는 card_facts 가 낸 모양이다 — 상태는 **버킷**(정상/경고/차단)
        base = {"공구": "wrench", "단계": 2, "버튼": "B2",
                "상태": "정상", "세션": True}
        ok, bad = verify_answer("2단계에 필요한 공구는 렌치입니다.", base, base)
        check(ok and bad == [], "안 바뀌었으면 통과")

        moved = dict(base, 공구="driver")
        ok, bad = verify_answer("현재 보이는 공구는 렌치입니다.", base, moved)
        check(not ok and bad == ["공구"], "🔴 공구를 말했는데 공구가 바뀌면 불일치")

        ok, bad = verify_answer("버튼 B2를 누르시면 됩니다.", base, moved)
        check(ok, "🔑 공구를 말하지 않았으면 공구가 바뀌어도 통과 — 과잉 폴백을 막는다")

        stepped = dict(base, 단계=3, 버튼="B3")
        ok, bad = verify_answer("버튼 B2를 누르시면 됩니다.", base, stepped)
        check(not ok and "버튼" in bad, "버튼을 말했는데 버튼이 바뀌면 불일치")
        ok, bad = verify_answer("2단계 「펌프/퍼지」입니다.", base, stepped)
        check(not ok and "단계" in bad, "단계를 말했는데 단계가 바뀌면 불일치")

        blocked = dict(base, 상태="차단")
        ok, bad = verify_answer("지금 차단된 상태입니다.", base, blocked)
        check(not ok and "상태" in bad, "차단을 말했는데 상태가 바뀌면 불일치")
        ok, bad = verify_answer("렌치가 보입니다.", base, blocked)
        check(ok, "차단을 말하지 않았으면 상태 변화만으로는 안 버린다")

        moved_roi = dict(base, 상태="정상")     # PROCESS RUN → MONITOR 는 같은 버킷
        ok, bad = verify_answer("정상이며 경고나 차단은 없습니다.", dict(base, 상태="정상"), moved_roi)
        check(ok, "🔴 카드가 말하지 않은 상태 차이로는 답을 버리지 않는다")

        ended = dict(base, 세션=False)
        ok, bad = verify_answer("렌치가 보입니다.", base, ended)
        check(not ok and "세션" in bad,
              "🔴 세션은 문장 언급과 무관하게 본다 — 작업이 끝났으면 무슨 답이든 어긋난다")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
