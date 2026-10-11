#!/usr/bin/env python3
"""답변 wav 사전 합성 — 시연용 정형 답변은 문장이 유한하다.

실행: ~/env/tts/.venv/bin/python Demo/voice/make_answers.py [키 …]
      소리마다 최대 TRIES 번 만들어 받아쓰기로 가장 또렷한 것을 고른다 · 안내 소리(cue_)는 빠르기 config.TTS_CUE_SPEED
      키를 주면 그것만 만든다(예: cue_reset) — 안 주면 전부 다시 만든다(이미 들어 본 소리도 바뀐다)

🔑 미리 만들어 두는 이유 세 가지:
   ① 응답이 0.4초 빨라진다(런타임 합성 시간이 사라진다 — §10.49 = 0.37~1.05초)
   ② **명료도를 미리 들어보고 나쁘면 다시 만들 수 있다** — ⛔ 미판정으로 남은
      §10.49 위험을 시연 범위에서만 덮는다. 런타임 합성에는 그 기회가 없다.
   ③ 런타임 TTS 를 안 띄워도 되어 메모리·CPU 가 빈다

⚠️ 이것은 「유연한 LLM 답변」 방향을 바꾸는 것이 아니다. 템플릿 답변(A안)에서만
   성립하는 최적화이고, LLM(B안)으로 갈 때 런타임 TTS 로 되돌린다.
"""
import os
import shutil
import time
import wave
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config      # noqa: E402 — TTS 엔진 갈래(측정 진행 도우미 설계 D11)
import voice_card  # noqa: E402  — 알림 문장은 「지금 할 일」의 말 그대로(설계 2026-10-04 §4.3 · 한 곳)
import voice_tts   # noqa: E402 — 런타임과 같은 합성기(엔진 · 한글 읽기 · 레이트)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wav")

# 🔴 키는 voice_lib.answer_key() 가 돌려주는 값과 정확히 같아야 한다.
ANSWERS = {
    "driver":  "앞에 드라이버가 보입니다.",
    "wrench":  "앞에 렌치가 보입니다.",
    "pliers":  "앞에 플라이어가 보입니다.",
    "none":    "지금은 공구가 보이지 않습니다.",
    "notstep": "지금은 공구를 확인하는 단계가 아닙니다.",
    # 🔴 B 갈래 폴백 4종 — 「모든 실패의 착지점이 A 갈래」를 성립시키는 부품이다
    #    (설계 2026-09-07-음성비서-LLM-design.md §10).
    #    ⚠️ 종전 "ack"(「네, 말씀하세요」)는 뺐다 — 그것은 **호출에 대한 응답**이지
    #       생각 중 표시가 아니다. 질문을 이미 받은 뒤에 쓰면 말이 어긋난다.
    "checking":    "확인해 보겠습니다.",
    "notready":    "아직 작업이 시작되지 않았습니다.",
    "changed":     "상태가 바뀌었습니다. 다시 말씀해 주세요.",
    "unavailable": "지금은 답변할 수 없습니다.",
}
ANSWERS.update(voice_card.alert_texts())    # 🔔 알림 9개 — alert_emo · alert_block_B1~4 · alert_warn_B1~4

# 📣 측정 안내 소리(측정 진행 도우미 설계 2026-10-11 D7) — 짧게 · 최종 문구는 안경으로 들어 보고 정한다(Task 12)
CUES = {"cue_B1": "비원", "cue_B2": "비투", "cue_B3": "비쓰리", "cue_B4": "비포", "cue_EMO": "비상정지",
        "cue_hover_B1": "비원 머물기", "cue_hover_B2": "비투 머물기", "cue_hover_B3": "비쓰리 머물기",
        "cue_hover_B4": "비포 머물기",
        "cue_tool_wrench": "렌치", "cue_tool_driver": "드라이버", "cue_tool_pliers": "플라이어", "cue_ng": "다시",
        "cue_reset": "작업 초기화"}      # 틀린 공구 판 끝(설계 D17)
ANSWERS.update(CUES)
KSS_KEEP = os.path.join(os.path.dirname(OUT), "wav_kss")     # 되돌리기 = 이 폴더를 wav 로(설계 §9)
TRIES = 6           # 🔑 새 목소리는 만들 때마다 결과가 다르다 — 처음 만든 「비포」·「드라이버」가 거의 무음(봉우리 335·110)이라
MIN_PEAK = 1500     #    안경이 39·118배로 키워 지지직거렸다(2026-10-11) → 여러 번 만들어 받아쓰기로 또렷한 것을 고른다


def speed_for(key):
    """안내 소리(cue_) = config.TTS_CUE_SPEED · 문장(알림·답) = None(엔진 기본 — 정한 빠르기)."""
    return config.TTS_CUE_SPEED if key.startswith("cue_") else None


def _peak(pcm):
    import array
    a = array.array("h")
    a.frombytes(pcm)
    return max((abs(v) for v in a), default=0)


def pick(tts, text, speed=None, judge=None, tries=TRIES):
    """여러 번 만들어 가장 또렷한 것 → `(pcm, rate, sec, 점수, 몇 번째)` · 다 실패하면 None.
    점수 = judge(pcm, rate)(0~1 · 없으면 1) · 봉우리가 MIN_PEAK 미만(거의 무음)이면 0.5 를 뺀다 · 0.99 이상이면 바로 멈춘다."""
    best = None
    for n in range(1, tries + 1):
        got = tts.synth(text, speed=speed)
        if got is None:
            continue
        pcm, rate, sec = got
        score = (judge(pcm, rate) if judge else 1.0) - (0.5 if _peak(pcm) < MIN_PEAK else 0.0)
        if best is None or score > best[3]:
            best = (pcm, rate, sec, score, n)
        if score >= 0.99:
            break
    return best


def stt_judge():
    """받아쓰기(음성비서와 같은 STT)로 뜻한 말과 얼마나 같은지 → judge(pcm, rate, text) 를 text 로 묶어 쓴다."""
    import difflib
    import re
    import numpy as np
    import voice_assistant as va
    rec = va.build_stt()
    norm = lambda s: re.sub(r"[^가-힣]", "", voice_tts.read_out(s or "")).replace("쓰", "스")   # noqa: E731 — 받아쓰기는 쓰/스를 못 가른다

    def judge(pcm, rate, text):
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        n = int(len(x) * va.RATE / rate)
        y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
        y = y / max(1.0, np.abs(y).max()) * 20000
        pad = np.zeros(int(va.RATE * 0.25))
        heard = va.transcribe(rec, [int(v) for v in np.concatenate([pad, y, pad])])
        return difflib.SequenceMatcher(None, norm(text), norm(heard)).ratio()
    return judge


def main(keys=None):
    unknown = set(keys or ()) - set(ANSWERS)
    if unknown:
        raise SystemExit(f"모르는 키: {sorted(unknown)}")
    os.makedirs(OUT, exist_ok=True)
    if config.TTS_ENGINE != "kss" and not os.path.isdir(KSS_KEEP):
        shutil.copytree(OUT, KSS_KEEP)          # 🔑 처음 바꿀 때 한 번만 — 옛 kss 소리를 덮어쓰기 전에
        print(f"옛 kss 소리 보관 → {KSS_KEEP}")
    t0 = time.time()
    tts = voice_tts.Tts()
    judge = stt_judge()
    print(f"모델 적재({tts.engine} · 받아쓰기) {time.time() - t0:.2f}s")
    for k, text in ANSWERS.items():
        if keys and k not in keys:
            continue
        t = time.time()
        got = pick(tts, text, speed=speed_for(k), judge=lambda p, r, s=text: judge(p, r, s))
        el = time.time() - t
        if got is None:
            print(f"  🔴 {k} 합성 실패 — {text}")
            continue
        pcm, rate, sec, score, n = got
        path = os.path.join(OUT, f"{k}.wav")
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        print(f"  {k:16s} {len(text):2d}자 · {n}번째 고름(받아쓰기 일치 {score:.2f}) · 합성 {el:.2f}s · {sec:.2f}초 · {rate}Hz → {path}")

if __name__ == "__main__":
    main(sys.argv[1:])
