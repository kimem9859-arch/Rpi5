"""음성비서 답 갈래(Assistant)와 메인 루프 — 설계 2026-10-03 §4.2~§4.6 · §4.8.

실행: python3 Demo/selftest/test_voice_loop.py
⚠️ 모델을 부르지 않는다 — 스피커·합성·LLM·STT 는 가짜다. 루프 시험은 모의 글라스(FakeGlass)로 소켓까지 돈다.
"""
import math
import os
import sys
import tempfile
import threading
import time
import wave

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import config  # noqa: E402

config.LLM_ENABLED = True
import voice_assistant as va  # noqa: E402
from fake_glass import FakeGlass  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


STATE = {
    "세션": True, "공정명": "PECVD 정비(PM) 시퀀스", "전체단계": 4,
    "현재단계": 2, "현재단계명": "펌프/퍼지", "현재버튼": "B2",
    "다음단계": 3, "다음단계명": "전극 냉각", "다음버튼": "B3",
    "상태": "PROCESS RUN", "비상정지": False,
    "서브작업": {"label": "N2 퍼지", "sec": 10, "tool": "wrench", "tool_name": "렌치"},
    "서브진행": None, "결과": None, "pid": os.getpid(), "쓴시각": time.time(),
}
RUNNING = dict(STATE, 서브진행={"상태": "진행 중", "남은초": 6.0, "공구충족": False})
WRENCH = ([("wrench", 0.9, 0, 0, 9, 9)], True)


class FakeSpk:
    def __init__(self, fail_pcm=0):
        self.calls, self.fail_pcm = [], fail_pcm
        self.s = object()

    def chime(self):
        self.calls.append(("chime",))
        return True

    def play(self, key, alog=None):
        self.calls.append(("play", key))
        return True

    def send(self, payload, expect=False):
        self.calls.append(("pcm", len(payload)))
        if self.fail_pcm:
            self.fail_pcm -= 1
            return ["[FAIL] 체크섬 불일치"]
        return ["[준비]", "[적재] ok", "[재생 완료]"]

    def reset(self):
        pass

    def keys(self):
        return [c[1] for c in self.calls if c[0] == "play"]

    def pcms(self):
        return [c for c in self.calls if c[0] == "pcm"]


class FakeTts:
    def __init__(self, n=None, rate=22050):
        self.said, self.n, self.rate = [], n, rate

    def synth(self, text):
        self.said.append(text)
        n = self.n or 200 * len(text)
        return b"\x01\x00" * n, self.rate, n / self.rate


class FakeLlm:
    def __init__(self, answer="지금은 2단계입니다.", ready=True, delay=0.0):
        self.answer, self.ready, self.delay, self.asked = answer, ready, delay, []
        self.warming = False

    def start_warm(self, on_done=None):
        return False

    def available(self):
        return self.ready

    def ask(self, card, q):
        self.asked.append((card, q))
        time.sleep(self.delay)
        return (self.answer, {"LLM_ms": 1}) if self.answer else (None, {"LLM오류": "가짜 실패"})


def bot(spk=None, tts="기본", llm=None, state=STATE, tools=WRENCH, states=None):
    spk = spk or FakeSpk()
    tts = FakeTts() if tts == "기본" else tts
    llm = llm or FakeLlm()
    if states:
        seq = list(states)
        read_state = lambda: seq.pop(0) if len(seq) > 1 else seq[0]   # noqa: E731
    else:
        read_state = lambda: state                                     # noqa: E731
    return va.Assistant(spk, tts, llm, read_state=read_state, read_tools=lambda: tools)


def ask(b, text):
    m = {}
    b.awake_until = time.time() + 20
    return b.on_text(text, m), m


# ── 판단(Task 8) ─────────────────────────────────────────────────────────
def test_before_work_notready():
    print("\n[갈래] 작업 전")
    b = bot(state=None)
    ok, m = ask(b, "지금 몇 단계야")
    check(ok and b.spk.keys() == ["notready"] and b.llm.asked == [], f"notready · LLM 안 부름 · {b.spk.calls}")


def test_wake_only_chimes():
    print("\n[갈래] 호출어만")
    b = bot()
    m = {}
    check(b.on_text("가디언", m) is False, "답한 것이 아니다(소리를 버리지 않는다)")
    check(b.spk.calls == [("chime",)] and b.awake_until > time.time(), "띠링 + 깨어남")


def test_not_awake_ignored():
    print("\n[갈래] 안 깨어 있음")
    b = bot()
    check(b.on_text("지금 몇 단계야", {}) is False and b.spk.calls == [], "아무것도 안 한다")


def test_llm_answer_spoken():
    print("\n[갈래] LLM 답")
    b = bot()
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.keys() == ["checking"] and len(b.spk.pcms()) == 1, f"확인 중 + 답 1회 · {b.spk.calls}")
    check(b.tts.said == ["지금은 2단계입니다."] and m["답변출처"] == "LLM", f"그대로 말함 · {m.get('답변출처')}")


def test_other_button_replaced():
    print("\n[안전] 다른 버튼 권함 → 대체(R3 C3)")
    b = bot(llm=FakeLlm("다음 단계인 3단계로 가려면 버튼 B3를 누르세요."))
    ok, m = ask(b, "지금 다음 순서 뭐야")
    check(b.tts.said == ["지금은 B2 차례입니다."], f"말한 것 = {b.tts.said}")
    check(m["답변출처"] == "대체-안전규칙" and "다른버튼" in m["안전규칙"], f"{m.get('안전규칙')}")


def test_permission_replaced():
    print("\n[안전] 허가 → 대체")
    b = bot(llm=FakeLlm("네, 지금 눌러도 됩니다."))
    ok, m = ask(b, "지금 눌러도 돼")
    check(m["답변출처"] == "대체-안전규칙" and "허가" in m["안전규칙"], f"{m.get('안전규칙')}")


def test_progress_claim_replaced():
    print("\n[안전] 진행 단정 → 대체(R3 I4)")
    b = bot(llm=FakeLlm("N2 퍼지가 끝났습니다."), state=RUNNING)
    ok, m = ask(b, "펌프 퍼지 끝났어")
    check(b.tts.said and b.tts.said[0].startswith("지금은 「N2 퍼지」 작업 중"), f"말한 것 = {b.tts.said}")


def test_long_answer_shortened():
    print("\n[다듬기] 첫 문장 · 60자(D2)")
    b = bot(llm=FakeLlm("현재 2단계 펌프/퍼지 단계이고 지금 눌러야 할 버튼은 B2입니다. 필요한 공구는 렌치입니다."))
    ask(b, "지금 뭐 해야 돼")
    check(b.tts.said == ["현재 2단계 펌프/퍼지 단계이고 지금 눌러야 할 버튼은 B2입니다."], f"{b.tts.said}")


def test_oversize_not_sent():
    print("\n[한도] 펌웨어 한도 초과 → 안 보내고 A(P4)")
    b = bot(tts=FakeTts(n=240001, rate=24000))
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.pcms() == [], "답 PCM 을 보내지 않았다")
    check(b.spk.keys() == ["checking", "unavailable"] and m["답변출처"] == "고정-한도초과", f"{b.spk.calls}")


def test_play_failure_falls_back_to_a():
    print("\n[재생 실패] → A 갈래 한 번(R2 I2)")
    b = bot(spk=FakeSpk(fail_pcm=1), llm=FakeLlm("앞에 렌치가 보입니다."))
    ok, m = ask(b, "앞에 보이는 게 뭐야")
    check(b.spk.keys() == ["checking", "wrench"], f"공구 질문이라 공구 답 · {b.spk.calls}")
    check(m["답변출처"] == "고정-재생실패대체" and m.get("답변재생실패"), f"{m.get('답변출처')}")


def test_cold_goes_straight_to_a():
    print("\n[콜드] 예열 전 → 확인 중 없이 바로 A(설계 §4.2)")
    b = bot(llm=FakeLlm(ready=False))
    ok, m = ask(b, "앞에 보이는 게 뭐야")
    check(b.spk.keys() == ["wrench"] and b.llm.asked == [], f"공구 답 · LLM 안 부름 · {b.spk.calls}")
    b2 = bot(llm=FakeLlm(ready=False))
    ask(b2, "지금 몇 단계야")
    check(b2.spk.keys() == ["unavailable"], f"공구 질문이 아니면 unavailable · {b2.spk.calls}")


def test_llm_failure_falls_back():
    print("\n[LLM 실패] → A")
    b = bot(llm=FakeLlm(answer=None))
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.keys() == ["checking", "unavailable"] and m["답변출처"] == "고정-폴백", f"{b.spk.calls}")


def test_empty_answer_falls_back():
    print("\n[빈답] 그림 글자뿐인 답 → A(Review Focus 2)")
    b = bot(llm=FakeLlm("🔴"))
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.keys() == ["checking", "unavailable"] and m["답변출처"] == "고정-빈답", f"{b.spk.calls}")


def test_verify_mismatch_changed():
    print("\n[검산] 그 사이 버튼이 바뀜 → changed")
    moved = dict(STATE, 현재단계=3, 현재버튼="B3")
    b = bot(llm=FakeLlm("지금 눌러야 할 버튼은 B2입니다."), states=[STATE, moved])
    ok, m = ask(b, "뭐 눌러야 돼")
    check(b.spk.keys() == ["checking", "changed"] and m["답변출처"] == "고정-검산불일치", f"{b.spk.calls}")


def test_llm_off_answers_a_for_any_question():
    print("\n[LLM 미사용] TTS 없음 → 어떤 질문이든 A(종전 결정)")
    b = bot(tts=None)
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.keys() == ["wrench"] and m["답변출처"] == "고정-LLM미사용", f"{b.spk.calls}")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 음성비서 갈래·루프 검증 통과")
