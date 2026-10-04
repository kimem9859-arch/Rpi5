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
                        tool_phase, tool_sentence, UNKNOWN_LINE, verify_answer)

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
        "서브 진행": (card_facts(RUN, [], False), "지금은 「N2 퍼지」 작업 중이며 끝나면 다음 단계로 넘어갑니다."),
        "서브 멈춤": (card_facts(dict(LIVE, 상태="WARNING", 서브진행={"상태": "멈춤", "남은초": 4.0,
                                                                  "공구충족": False}), [], False),
                    "지금은 경고로 「N2 퍼지」 작업이 멈춰 있습니다."),
        "위반 차단": (card_facts(dict(LIVE, 상태="BLOCK"), [], False), "차단 중이니 먼저 차단 해제를 누르세요."),
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
    check("멈춘 자리: 3단계" in emo and "끝난 단계: 1·2단계 (해제하면 1단계부터 다시)" in emo, "멈춘 자리 · 끝난 단계")
    last = build_card(dict(LIVE, 현재단계=4, 현재단계명="챔버 벤트", 현재버튼="B4", 다음단계=None, 서브작업=None),
                      [], False)
    check("4단계 「챔버 벤트」 (마지막 단계) — 아직 끝나지 않음" in last, "🔑 마지막 단계 = 아직 끝나지 않음")
    check("끝난 단계: 1·2·3단계" in last and "이번이 마지막 단계다" not in last, "끝난 단계 · 옛 「마지막 단계다」 문구 없음")
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
