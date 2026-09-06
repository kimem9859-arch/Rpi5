#!/usr/bin/env python3
"""답변 wav 사전 합성 — 시연용 정형 답변은 문장이 유한하다.

실행: ~/env/tts/.venv/bin/python Demo/voice/make_answers.py

🔑 미리 만들어 두는 이유 세 가지:
   ① 응답이 0.4초 빨라진다(런타임 합성 시간이 사라진다 — §10.49 = 0.37~1.05초)
   ② **명료도를 미리 들어보고 나쁘면 다시 만들 수 있다** — ⛔ 미판정으로 남은
      §10.49 위험을 시연 범위에서만 덮는다. 런타임 합성에는 그 기회가 없다.
   ③ 런타임 TTS 를 안 띄워도 되어 메모리·CPU 가 빈다

⚠️ 이것은 「유연한 LLM 답변」 방향을 바꾸는 것이 아니다. 템플릿 답변(A안)에서만
   성립하는 최적화이고, LLM(B안)으로 갈 때 런타임 TTS 로 되돌린다.
"""
import array
import os
import time
import wave

import sherpa_onnx

D = os.path.expanduser("~/env/tts/vits-mimic3-ko_KO-kss_low")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wav")

# 🔴 키는 voice_lib.answer_key() 가 돌려주는 값과 정확히 같아야 한다.
ANSWERS = {
    "driver":  "앞에 드라이버가 보입니다.",
    "wrench":  "앞에 렌치가 보입니다.",
    "pliers":  "앞에 플라이어가 보입니다.",
    "none":    "지금은 공구가 보이지 않습니다.",
    "notstep": "지금은 공구를 확인하는 단계가 아닙니다.",
    # 이번 흐름에서는 안 쓴다(호출 응답은 띠링이므로). LLM 갈래에서
    # 「생각 중」 표시로 쓸 자리라 미리 만들어 둔다.
    "ack":     "네, 말씀하세요.",
}


def main():
    os.makedirs(OUT, exist_ok=True)
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=f"{D}/ko_KO-kss_low.onnx",
                tokens=f"{D}/tokens.txt",
                data_dir=f"{D}/espeak-ng-data",
            ),
            num_threads=2, provider="cpu",
        ),
        max_num_sentences=1,
    )
    t0 = time.time()
    tts = sherpa_onnx.OfflineTts(cfg)
    print(f"모델 적재 {time.time() - t0:.2f}s")

    for k, text in ANSWERS.items():
        t = time.time()
        a = tts.generate(text, sid=0, speed=1.0)
        el = time.time() - t
        path = os.path.join(OUT, f"{k}.wav")
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(a.sample_rate)
            w.writeframes(array.array(
                "h", [int(max(-1, min(1, x)) * 32767) for x in a.samples]).tobytes())
        print(f"  {k:8s} {len(text):2d}자 · 합성 {el:.2f}s · "
              f"{len(a.samples) / a.sample_rate:.2f}초 · {a.sample_rate}Hz → {path}")


if __name__ == "__main__":
    main()
