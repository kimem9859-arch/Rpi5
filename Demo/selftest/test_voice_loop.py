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

    def stop(self):
        self.calls.append(("stop",))
        return True

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


def bot(spk=None, tts="기본", llm=None, state=STATE, tools=WRENCH, states=None, alert_gen=None):
    spk = spk or FakeSpk()
    tts = FakeTts() if tts == "기본" else tts
    llm = llm or FakeLlm()
    if states:
        seq = list(states)
        read_state = lambda: seq.pop(0) if len(seq) > 1 else seq[0]   # noqa: E731
    else:
        read_state = lambda: state                                     # noqa: E731
    return va.Assistant(spk, tts, llm, read_state=read_state, read_tools=lambda: tools,
                        alert_gen=alert_gen)


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
    ok, m = ask(b, "지금 상태 어때")          # 🔑 허가를 묻지 않는 질문 — 답 쪽 규칙을 본다(허가 질문은 관문이 먼저 · 최종 리뷰 C2)
    check(m["답변출처"] == "대체-안전규칙" and "허가" in m["안전규칙"], f"{m.get('안전규칙')}")


def test_progress_claim_replaced():
    print("\n[안전] 진행 단정 → 대체(R3 I4)")
    b = bot(llm=FakeLlm("N2 퍼지가 끝났습니다."), state=RUNNING)
    ok, m = ask(b, "펌프 퍼지 끝났어")
    check(b.tts.said == ["앞에 렌치가 보이니 손으로 쥐면 확인됩니다."], f"말한 것 = {b.tts.said}")


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


def test_risky_question_skips_llm():
    """최종 리뷰 C2 — 허가를 묻는 질문은 LLM 을 안 부르고 사실 문장으로 답한다(「확인 중」도 없음)."""
    print("\n[관문] 허가 질문 → LLM 없이 사실 문장")
    b = bot(llm=FakeLlm("네, 눌러도 됩니다."))
    ok, m = ask(b, "B3 눌러도 되지?")
    check(b.llm.asked == [] and b.spk.keys() == [], f"LLM·확인 중 없음 · {b.spk.calls}")
    check(b.tts.said == ["지금은 B2 차례입니다."] and m["답변출처"] == "대체-위험질문", f"{b.tts.said} · {m.get('답변출처')}")


def test_answer_exception_falls_back():
    """최종 리뷰 M2 — 답을 만들다 예외가 나도 침묵하지 않고 고정 답(「어디서 실패해도 A」)."""
    print("\n[예외] 답하다 예외 → 고정 답")
    broken = dict(STATE, 서브진행={"상태": "진행 중", "남은초": "깨짐", "공구충족": False})
    b = bot(state=broken)
    try:
        ok, m = ask(b, "지금 몇 단계야")
        check(b.spk.keys() == ["unavailable"] and m.get("답변출처") == "고정-오류", f"{b.spk.calls} · {m.get('답변출처')}")
    except Exception as e:                           # noqa: BLE001
        check(False, f"예외가 새어 나왔다 — {type(e).__name__}: {e}")


EMO = dict(STATE, 상태="BLOCK", 비상정지=True)


def test_alert_watcher_steps():
    print("\n[알림] 감시 — 멈춤 먼저 · 알림 · 풀리면 멈춤")
    seq = [STATE, STATE, EMO, EMO, STATE]
    spk = FakeSpk()
    w = va.AlertWatcher(spk, read_state=lambda: seq.pop(0))
    evs = [w.step() for _ in range(5)]
    check(evs == [None, None, ("알림", "alert_emo"), None, ("멈춤", None)], f"사건 — {evs}")
    check(spk.calls == [("stop",), ("play", "alert_emo"), ("stop",)], f"멈춤 → 알림 → (풀림) 멈춤 — {spk.calls}")
    check(w.gen == 1 and not w.speaking.is_set(), "알림 1회 · 재생 끝")


def test_alert_hold():
    """Review Focus 1 — 알림 동안·직후 소리는 버린다(알림을 질문으로 받아쓰지 않게 · 루프가 깨어남도 푼다)."""
    print("\n[알림] 메인 루프가 소리를 버림")

    class A:
        def __init__(self):
            self.speaking = threading.Event()
            self.gen = 0

    a = A()
    check(va.alert_hold(None, 0) == (False, 0), "알림 끄면 아무 일 없음")
    check(va.alert_hold(a, 0) == (False, 0), "평소")
    a.speaking.set()
    a.gen = 1
    check(va.alert_hold(a, 0) == (True, 0), "재생 중 — 버림 · 아직 따라잡지 않음")
    a.speaking.clear()
    check(va.alert_hold(a, 0) == (True, 1), "끝난 직후 한 번 더 버리고 따라잡음")
    check(va.alert_hold(a, 1) == (False, 1), "그다음은 평소")


def test_answer_dropped_after_alert():
    """Review Focus 2 — 질문을 받은 뒤 알림이 나갔으면 만들던 답을 조용히 버린다(「상태가 바뀌었습니다」 없음)."""
    print("\n[알림] 답 버림")
    g = [0]

    class AlertDuringLlm(FakeLlm):
        def ask(self, card, q):
            g[0] = 1                                 # LLM 을 기다리는 동안 알림이 나갔다
            return super().ask(card, q)

    b = bot(llm=AlertDuringLlm("지금은 2단계입니다."), alert_gen=lambda: g[0])
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.pcms() == [] and "changed" not in b.spk.keys(), f"답·「상태가 바뀌었습니다」 없음 — {b.spk.calls}")
    check(m.get("답변출처") == "알림으로버림", f"출처 — {m.get('답변출처')}")
    check(b.awake_until == 0.0, "🔑 대화창은 닫힌다 — 버린 답을 다시 말하지도, 대화창을 이어 주지도 않는다(사용자 2026-10-04)")


def test_stopped_answer_no_fallback():
    print("\n[알림] 멈춘 답은 실패가 아니다")

    class StopSpk(FakeSpk):
        def send(self, payload, expect=False):
            self.calls.append(("pcm", len(payload)))
            return ["[적재] ok", "[재생] 1샘플", "[재생 중단]"]

    b = bot(spk=StopSpk())
    ok, m = ask(b, "지금 몇 단계야")
    check(b.spk.keys() == ["checking"] and m.get("재생중단") is True, f"A 갈래로 다시 말하지 않는다 — {b.spk.calls}")


def test_loop_alert_plays_during_stt():
    """설계 2026-10-04 §4.3 — 루프 전체: 받아쓰기(STT)가 메인 루프를 3초 막고 있어도 알림은 그동안 나간다."""
    print("\n[루프] STT 중 알림")
    va.WAV_DIR = _wavdir()
    fg = FakeGlass([tone(0.8)], mic_port=0, cmd_port=0, lead_sec=0.5, tail_sec=6.0, play_speed=0.05,
                   quiet=True).start()
    busy = {}

    def slow_stt(samples):
        busy["start"] = time.time()
        time.sleep(3.0)
        busy["end"] = time.time()
        return ""

    seen = []
    old = va.log
    va.log = lambda m: (seen.append((time.time(), m)), old(m))
    th, stop = _run_bg(fg, slow_stt, FakeLlm(), FakeTts(),
                       read_state=lambda: EMO if busy.get("start") and time.time() > busy["start"] + 0.3 else STATE)
    try:
        end = time.time() + 12
        while time.time() < end and "end" not in busy:
            time.sleep(0.1)
    finally:
        stop.set()
        th.join(5)
        fg.stop()
        va.log = old
    t_alert = next((t for t, m in seen if "🔔 알림 → alert_emo" in m), None)
    check(t_alert is not None and "end" in busy and t_alert < busy["end"],
          f"🔑 STT 가 끝나기 전에 알림이 나갔다(메인 루프와 따로) — 알림 {t_alert} · STT 끝 {busy.get('end')}")
    check(fg.count("play") >= 1, f"모의 글라스가 재생했다 — {fg.count('play')}")


# ── 메인 루프(Task 9) ─────────────────────────────────────────────────────
def tone(sec, amp=4000):
    return [int(amp * math.sin(i / 5)) for i in range(int(16000 * sec))]


def _wavdir():
    d = tempfile.mkdtemp(prefix="sop_wav_")
    for k in ("checking", "notready", "unavailable", "changed", "wrench", "driver", "pliers",
              "none", "notstep") + tuple(va.voice_card.alert_texts()):
        with wave.open(os.path.join(d, f"{k}.wav"), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 1600)
    return d


def _run_bg(fg, stt, llm, tts, read_state=lambda: STATE):
    stop = threading.Event()
    th = threading.Thread(target=va.run, daemon=True, kwargs=dict(
        get_ip=lambda: "127.0.0.1", mic_port=fg.mic_port, cmd_port=fg.cmd_port, stt=stt, tts=tts,
        llm=llm, read_state=read_state, read_tools=lambda: WRENCH, stop=stop))
    th.start()
    return th, stop


def _capture_log():
    logs = []
    old = va.log
    va.log = lambda m: (logs.append(m), old(m))
    return logs, lambda: setattr(va, "log", old)


def test_loop_discards_speech_during_answer():
    """G11 · P1 — 대답하는 동안 들어온 둘째 발화는 버리고, 그동안에도 업링크는 안 끊긴다(Review Focus 1)."""
    print("\n[루프] 대답 중 소리 버림 · 업링크 유지")
    va.WAV_DIR = _wavdir()
    fg = FakeGlass([tone(0.8), tone(0.8)], mic_port=0, cmd_port=0, lead_sec=1.0, gap_sec=1.0,
                   tail_sec=4.0, play_speed=0.05, quiet=True).start()
    texts = []

    def stt(samples):
        texts.append(len(samples))
        return "가디언 지금 몇 단계야" if len(texts) == 1 else "가디언"

    logs, restore = _capture_log()
    th, stop = _run_bg(fg, stt, FakeLlm("지금은 2단계입니다.", delay=2.5), FakeTts())
    try:
        fg.mic_done.wait(20)
        time.sleep(0.5)
    finally:
        stop.set()
        th.join(5)
        fg.stop()
        restore()
    check(len(texts) == 1, f"STT 는 첫 발화 한 번만 — 대답 중 들어온 둘째는 버렸다 · {len(texts)}회")
    # 🔑 clear() 가 실제로 버렸는지 직접 본다 — 밀림 버림(lag_limit)에 가려 통과하지 않게(최종 리뷰 I6)
    import re as _re
    dropped = [float(m.group(1)) for l in logs for m in [_re.search(r"대답하는 동안 들어온 소리 ([\d.]+)초", l)] if m]
    check(bool(dropped) and max(dropped) >= 1.0, f"대답 중 소리 버림 로그 · {dropped}")
    check(fg.count("chime") == 1, f"띠링 1번 · {fg.count('chime')}")
    check(fg.count("write") >= 2, "확인 중 + 답이 실제로 갔다")
    check(fg.count("mic_drop") == 0 and fg.count("mic_conn") == 1, "대답하는 동안에도 업링크가 끊기지 않았다(P1)")


def test_loop_halfopen_reattaches_speaker():
    """P5 · Q3 — 반열림이면 다시 붙고, 붙은 뒤 명령 채널도 미리 다시 붙인다(첫 띠링 유실 방지)."""
    print("\n[루프] 반열림 → 재접속 + 명령 채널 미리 붙임")
    va.WAV_DIR = _wavdir()
    old = (va.STALL_SEC, va.RETRY_SEC)
    va.STALL_SEC, va.RETRY_SEC = 0.8, 0.2
    fg = FakeGlass([tone(0.3)], mic_port=0, cmd_port=0, lead_sec=0.5, tail_sec=5.0, vanish=True,
                   play_speed=0.05, quiet=True).start()
    th, stop = _run_bg(fg, lambda s: "", FakeLlm(), FakeTts())
    try:
        end = time.time() + 8
        while time.time() < end and not (fg.count("mic_conn") >= 2 and fg.count("cmd_conn") >= 2):
            time.sleep(0.1)
    finally:
        stop.set()
        th.join(5)
        fg.stop()
        va.STALL_SEC, va.RETRY_SEC = old
    check(fg.count("mic_conn") >= 2, f"업링크 재접속 · {fg.count('mic_conn')}")
    check(fg.count("cmd_conn") >= 2, f"명령 채널도 다시 붙였다 · {fg.count('cmd_conn')}")


def test_loop_survives_exception():
    """M8 — 한 발화 처리에서 예외가 나도 루프는 산다 — 다음 발화를 처리한다."""
    print("\n[루프] 예외 보호")
    va.WAV_DIR = _wavdir()
    logs, restore = _capture_log()
    fg = FakeGlass([tone(0.8), tone(0.8)], mic_port=0, cmd_port=0, lead_sec=1.0, gap_sec=1.5,
                   tail_sec=2.5, play_speed=0.05, quiet=True).start()
    calls = []

    def stt(samples):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("시험 — STT 가 터졌다")
        return "가디언"

    th, stop = _run_bg(fg, stt, FakeLlm(), FakeTts())
    try:
        fg.mic_done.wait(20)
        time.sleep(0.5)
    finally:
        stop.set()
        th.join(5)
        fg.stop()
        restore()
    check(len(calls) == 2, f"둘째 발화도 처리했다 · {len(calls)}회")
    check(fg.count("chime") == 1, "둘째 발화(호출어)에 띠링")
    check(any("메인 루프 오류" in l for l in logs), "오류를 로그에 남겼다")


def test_loop_vad_hop():
    """Q7 — VAD 는 새 소리가 0.25초 쌓였을 때만 본다(종전: 512샘플 조각마다 · 초당 31회)."""
    print("\n[루프] VAD 간격")
    va.WAV_DIR = _wavdir()
    n = []
    orig = va.find_utterance
    va.find_utterance = lambda *a, **k: (n.append(1), orig(*a, **k))[1]
    fg = FakeGlass([], mic_port=0, cmd_port=0, lead_sec=3.0, tail_sec=0.5, quiet=True).start()
    th, stop = _run_bg(fg, lambda s: "", FakeLlm(), FakeTts())
    try:
        fg.mic_done.wait(10)
    finally:
        stop.set()
        th.join(5)
        fg.stop()
        va.find_utterance = orig
    check(0 < len(n) <= 3.5 / 0.25 + 2, f"3.5초 무음에 VAD {len(n)}회")


def _free_ports(n=2):
    import socket
    socks = [socket.socket() for _ in range(n)]
    for k in socks:
        k.bind(("127.0.0.1", 0))
    ports = [k.getsockname()[1] for k in socks]
    for k in socks:
        k.close()
    return ports


def test_loop_board_later_preattaches_speaker():
    """최종 리뷰 I3 — 데몬이 보드보다 먼저 켜지면(상시 가동의 기본 순서) 첫 연결 때 명령 채널을 미리 붙인다."""
    print("\n[루프] 보드가 나중에 켜짐 → 명령 채널 미리 붙임")
    va.WAV_DIR = _wavdir()
    old = va.RETRY_SEC
    va.RETRY_SEC = 0.2
    mp, cp = _free_ports()
    stop = threading.Event()
    th = threading.Thread(target=va.run, daemon=True, kwargs=dict(
        get_ip=lambda: "127.0.0.1", mic_port=mp, cmd_port=cp, stt=lambda s: "", tts=FakeTts(), llm=FakeLlm(),
        read_state=lambda: STATE, read_tools=lambda: WRENCH, stop=stop))
    th.start()
    time.sleep(1.5)                                  # 보드 없음 — 명령 채널 연결 실패
    fg = FakeGlass([], mic_port=mp, cmd_port=cp, lead_sec=10.0, quiet=True).start()
    try:
        end = time.time() + 6
        while time.time() < end and fg.count("cmd_conn") < 1:
            time.sleep(0.1)
    finally:
        stop.set()
        th.join(5)
        fg.stop()
        va.RETRY_SEC = old
    check(fg.count("mic_conn") >= 1, "업링크 연결")
    check(fg.count("cmd_conn") >= 1, f"띠링 없이도 명령 채널을 미리 붙였다 · {fg.count('cmd_conn')}")


def test_loop_exits_when_mic_thread_dies():
    """최종 리뷰 M1 — 수신 스레드가 죽으면 데몬을 끝낸다(감시가 다시 띄운다) — 조용한 영구 귀먹음 방지."""
    print("\n[루프] 수신 스레드 죽음 → 데몬 끝")
    import voice_mic
    va.WAV_DIR = _wavdir()
    logs, restore = _capture_log()
    orig = voice_mic.MicReceiver._read
    voice_mic.MicReceiver._read = lambda self, s: (_ for _ in ()).throw(RuntimeError("시험 — 수신 스레드가 터졌다"))
    fg = FakeGlass([], mic_port=0, cmd_port=0, lead_sec=10.0, quiet=True).start()
    th, stop = _run_bg(fg, lambda s: "", FakeLlm(), FakeTts())
    try:
        th.join(6)
        ended = not th.is_alive()
    finally:
        stop.set()
        th.join(3)
        fg.stop()
        voice_mic.MicReceiver._read = orig
        restore()
    check(ended, "run() 이 스스로 끝났다")
    check(any("수신 스레드" in l for l in logs), "이유를 로그에 남겼다")


def test_lock_and_exit_code():
    """§4.6 — 한 대만 돈다(명령 채널은 손님 하나) · 이미 돌면 코드 3 으로 끝난다(감시가 멈춘다)."""
    print("\n[잠금] 한 대만")
    import subprocess
    p = os.path.join(tempfile.mkdtemp(), "voice.lock")
    a = va.take_lock(p)
    check(a is not None and va.take_lock(p) is None, "둘째 잠금은 실패")
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "voice_assistant.py"), "--ip", "127.0.0.1"],
                       env=dict(os.environ, SOP_VOICE_LOCK=p), capture_output=True, text=True, timeout=60)
    check(r.returncode == va.EXIT_ALREADY_RUNNING and "이미" in r.stdout,
          f"이미 돌면 코드 {r.returncode} · {r.stdout.strip()[-80:]}")
    a.close()
    check(va.take_lock(p) is not None, "놓으면 다시 잡힌다")


def test_esp_ip_camera_ip_only():
    """§4.9 — 보드는 하나 — 주소는 .camera_ip 하나(.audio_ip 를 읽지 않는다)."""
    print("\n[주소] .camera_ip 하나")
    d = tempfile.mkdtemp()
    old = va.IP_FILE
    va.IP_FILE = os.path.join(d, ".camera_ip")
    try:
        with open(va.IP_FILE, "w") as f:
            f.write("192.168.1.16\n")
        check(va.esp_ip() == "192.168.1.16", "파일 그대로")
        os.remove(va.IP_FILE)
        try:
            va.esp_ip()
            check(False, "파일이 없으면 SystemExit")
        except SystemExit as e:
            check(".camera_ip" in str(e), f"이유와 함께 끝난다 · {e}")
    finally:
        va.IP_FILE = old
    check(not hasattr(va, "AUDIO_IP_FILE"), ".audio_ip 상수가 없다")


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
