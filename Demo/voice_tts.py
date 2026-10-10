"""런타임 TTS — LLM 이 만든 문장을 그때그때 합성한다 · 고정 소리(make_answers)도 이것으로 만든다.

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §4 · 엔진 교체 = 2026-10-11-측정진행도우미-안내소리-design.md D11

🔑 A 갈래의 사전 합성(make_answers.py)을 되돌리는 자리다. 문장이 매번 다르니
   미리 만들어 둘 수 없다.

🔴 **말하는 시간이 지연의 지배 항목이다** — LLM 문장은 A 갈래 답변(1.48초)의
   3.2~3.6배인 4.77~5.34초를 말한다(§10.62-(9)). 합성 자체는 0.4~1.05초다.

⚠️ 모델은 상주시킨다 — 적재가 약 0.93초라 매번 올리면 그만큼 늘어난다(§10.49).
🔑 엔진 = config.TTS_ENGINE — supertonic2(기본 · F1 · 4단계 · 1.25 · 22050Hz 로 낮춤) · kss(되돌리기).
"""
import array
import os
import re
import struct

import config

_D = os.path.expanduser("~/env/tts/vits-mimic3-ko_KO-kss_low")
# 🔑 영문 버튼 이름은 한글 읽기로 — Supertonic 은 영문을 영어로 읽는다(저널 §12.94-(8))
_READ = {"EMO": "비상정지", "B1": "비원", "B2": "비투", "B3": "비쓰리", "B4": "비포"}
_READ_RE = re.compile("|".join(_READ))
TRIM_REL = 0.02         # 앞뒤 무음 = 최고점의 2% 미만(저널 §12.94 말소리 길이 기준과 같다)
TRIM_PAD_SEC = 0.02     # 자른 뒤 남기는 여유


def read_out(text):
    """버튼 이름(B1~B4 · EMO)을 한글 읽기로 — 모든 합성이 지난다(고정 wav · LLM 답 · 안내)."""
    return _READ_RE.sub(lambda m: _READ[m.group(0)], text or "")


def downsample(x, src, dst):
    """정수배로 레이트를 낮춘다 — 창 씌운 sinc 저역 거름(새 나이퀴스트의 90%) 뒤 솎기."""
    import numpy as np
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if src == dst:
        return x
    if src % dst:
        raise ValueError(f"정수배가 아니다: {src} → {dst}")
    f = src // dst
    n = 63
    m = np.arange(n) - (n - 1) / 2
    fc = 0.45 / f
    h = 2 * fc * np.sinc(2 * fc * m) * np.hamming(n)
    h /= h.sum()
    return np.convolve(x, h, mode="same")[::f].astype(np.float32)


def trim(x, rate):
    """앞뒤 무음을 자른다 — 안내 소리의 「재생 시작」이 들리기 시작한 때와 같아야 한다(설계 D14)."""
    import numpy as np
    x = np.asarray(x, dtype=np.float32)
    a = np.abs(x)
    if a.size == 0 or a.max() <= 0:
        return x
    on = np.nonzero(a >= a.max() * TRIM_REL)[0]
    pad = int(rate * TRIM_PAD_SEC)
    return x[max(0, on[0] - pad): min(a.size, on[-1] + 1 + pad)]


def to_pcm(x):
    import numpy as np
    return (np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2").tobytes()


class Tts:
    """합성기 — 만들 때 모델을 올리고 계속 들고 있는다. engine = "supertonic2" · "kss"(없으면 config)."""

    def __init__(self, model_dir=None, threads=2, engine=None):
        self.engine = engine or config.TTS_ENGINE
        if self.engine == "kss":
            import sherpa_onnx
            d = model_dir or _D
            self._tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=f"{d}/ko_KO-kss_low.onnx",
                        tokens=f"{d}/tokens.txt",
                        data_dir=f"{d}/espeak-ng-data"),
                    num_threads=threads, provider="cpu"),
                max_num_sentences=1))
        elif self.engine == "supertonic2":
            from supertonic import TTS
            self._st = TTS(model="supertonic-2", model_dir=model_dir or config.TTS_ST_DIR, auto_download=False,
                           intra_op_num_threads=threads, inter_op_num_threads=1)
            self._style = self._st.get_voice_style(voice_name=config.TTS_ST_VOICE)
        else:
            raise ValueError(f"알 수 없는 TTS_ENGINE: {self.engine!r}(\"supertonic2\" 또는 \"kss\")")

    def synth(self, text, speed=None):
        """`(pcm bytes, 레이트, 말하는 시간초)` — 실패하면 None. speed 없음 = 엔진 기본(kss 1.0 · supertonic2 config)."""
        text = read_out(text)
        if not text.strip():
            return None
        try:
            if self.engine == "kss":
                a = self._tts.generate(text, sid=0, speed=1.0 if speed is None else speed)
                pcm = array.array("h", [int(max(-1.0, min(1.0, x)) * 32767) for x in a.samples])
                if not pcm:
                    return None
                return pcm.tobytes(), a.sample_rate, len(pcm) / a.sample_rate
            wav, _ = self._st.synthesize(text, voice_style=self._style, lang="ko", total_steps=config.TTS_ST_STEPS,
                                         speed=config.TTS_ST_SPEED if speed is None else speed)
            x = trim(downsample(wav, self._st.sample_rate, config.TTS_OUT_RATE), config.TTS_OUT_RATE)
            if x.size == 0:
                return None
            return to_pcm(x), config.TTS_OUT_RATE, x.size / config.TTS_OUT_RATE
        except Exception:                      # noqa: BLE001 — 데몬은 살아야 한다
            return None


def frame(pcm, rate):
    """전송 프레임을 만든다.

    🔴 모양이 `voice_assistant.wav_payload()` 와 **똑같아야 한다.** 펌웨어
       `checksum()` 과 어긋나면 재생이 통째로 버려진다.
    """
    a = array.array("h")
    a.frombytes(pcm)
    chk = sum(v & 0xFFFF for v in a) & 0xFFFFFFFF
    return (f"W {len(a)} {rate}\n".encode() + pcm
            + struct.pack("<I", chk) + b"P\n")


def fits(n_samples, rate):
    """펌웨어가 받아 주는 크기인가(설계 2026-10-03 §4.3 C2 셋째 겹 · R3 I1).

    🔴 넘으면 보내지 않는다 — 펌웨어가 본문을 안 읽고 거절해 남은 바이트가 명령으로 실행된다(P4).
    """
    import config
    return (0 < n_samples <= config.VOICE_FW_MAX_SAMPLE
            and config.VOICE_FW_RATE_MIN <= rate <= config.VOICE_FW_RATE_MAX)
