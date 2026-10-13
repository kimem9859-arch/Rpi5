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


# 🔴 Supertonic 2 가 받지 않는 글자(2026-10-11 실물 — 「클린·가스차단」 「펌프/퍼지」 가 든 답이 ValueError 로 합성 실패 →
#    「지금은 답변할 수 없습니다」) · 옛 kss 는 넘겼다. 괄호·따옴표는 지우고 가운뎃점은 띄어쓰기로.
_DROP = str.maketrans({c: "" for c in "「」『』“”‘’\"'〈〉《》"})
_SPACE = re.compile(r"[·ㆍ・]+")
_UNSUPPORTED = re.compile(r"'(.)'")


def read_out(text):
    """합성 전 글 다듬기 — 버튼 이름(B1~B4 · EMO)을 한글 읽기로 · 엔진이 안 받는 글자를 정리(모든 합성이 지난다)."""
    t = _READ_RE.sub(lambda m: _READ[m.group(0)], text or "").translate(_DROP).replace("…", ".")
    return re.sub(r"\s{2,}", " ", _SPACE.sub(" ", t)).strip()


_BREATH = re.compile(r"(?<=[,?!])\s+|(?<=\D\.)\s+")    # 🔑 숫자 바로 뒤 마침표(「1. 렌치」)는 안 나눈다 — 「1.」 홀로는 뭉개진다


def breath_parts(text):
    """숨 고르기 조각 — `[(조각, 뒤에 둘 쉼초), …]` · 쉼표·문장 끝 뒤 띄어쓰기에서만 나눈다(소수점 · 번호 목록은 안 나뉜다)."""
    parts = [p for p in _BREATH.split(text) if p.strip()]
    return [(p, 0.0 if i == len(parts) - 1 else
             (config.TTS_PAUSE_COMMA_SEC if p.endswith(",") else config.TTS_PAUSE_END_SEC))
            for i, p in enumerate(parts)]


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


def deess(x, rate, hz=None, ratio=None, gain=None, win=0.02, hop=0.01, ramp=0.005):
    """센 소리(쓰·시·초) 순간만 높은 성분을 줄인다 — 20ms 조각의 hz 위 성분 비율이 ratio 를 넘으면 그 조각의 높은 성분 × gain.
    나머지(모음 등)는 원본 그대로 · 바뀌는 곳은 ramp 로 부드럽게(딸깍 없게) · 값 = config.TTS_DEESS_*."""
    import numpy as np
    hz = config.TTS_DEESS_HZ if hz is None else hz
    ratio = config.TTS_DEESS_RATIO if ratio is None else ratio
    gain = config.TTS_DEESS_GAIN if gain is None else gain
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if gain >= 1.0 or x.size == 0:
        return x
    n = 101
    m = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * hz / rate * m) * np.hamming(n)
    lo = np.convolve(x, h / h.sum(), mode="same")
    hi = x - lo
    w, step = max(1, int(rate * win)), max(1, int(rate * hop))
    g = np.ones(x.size)
    for i in range(0, max(1, x.size - w + 1), step):
        e = float((x[i:i + w] ** 2).sum())
        if e > 0 and float((hi[i:i + w] ** 2).sum()) / e > ratio:
            g[i:i + w] = gain
    k = max(1, int(rate * ramp))
    g = np.convolve(np.pad(g, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, mode="valid")   # 🔑 끝을 0 으로 채우면 앞뒤가 깎인다
    return (lo + g * hi).astype(np.float32)


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

    last_error = ""

    def synth(self, text, speed=None):
        """`(pcm bytes, 레이트, 말하는 시간초)` — 실패하면 None. speed 없음 = 엔진 기본(kss 1.0 · supertonic2 config)."""
        self.last_error = ""                      # 앞선 실패 이유가 남지 않게(최종 리뷰 M5)
        text = read_out(text)
        if not text.strip():
            self.last_error = "빈 글"
            return None
        try:
            if self.engine == "kss":
                a = self._tts.generate(text, sid=0, speed=1.0 if speed is None else speed)
                pcm = array.array("h", [int(max(-1.0, min(1.0, x)) * 32767) for x in a.samples])
                if not pcm:
                    return None
                return pcm.tobytes(), a.sample_rate, len(pcm) / a.sample_rate
            import numpy as np
            sp = config.TTS_ST_SPEED if speed is None else speed
            xs = []
            for part, pause in breath_parts(text):        # 🔑 숨 고르기 — 쉼표·문장 끝에서 나눠 만들고 무음을 넣는다
                xs.append(self._st_part(part, sp))
                if pause:
                    xs.append(np.zeros(int(config.TTS_OUT_RATE * pause), dtype=np.float32))
            x = np.concatenate(xs)
            if x.size == 0:
                self.last_error = "빈 소리"
                return None
            return to_pcm(x), config.TTS_OUT_RATE, x.size / config.TTS_OUT_RATE
        except Exception as e:                 # noqa: BLE001 — 데몬은 살아야 한다
            self.last_error = f"{type(e).__name__}: {e}"[:200]      # 🔑 부른 쪽이 로그에 남긴다(조용히 None 이던 것)
            return None

    def _st_part(self, text, sp):
        """supertonic2 한 조각 → 22050Hz float — 글자 수에 비해 너무 짧으면(깨짐) 다시 만들어 가장 긴 것."""
        syl = len(re.findall(r"[가-힣]", text))
        best = None
        for _ in range(1 + (config.TTS_REDO if syl >= config.TTS_MIN_SYL else 0)):
            x = self._st_once(text, sp)
            if best is None or x.size > best.size:
                best = x
            if syl < config.TTS_MIN_SYL or x.size / config.TTS_OUT_RATE >= syl * config.TTS_MIN_SEC_PER_SYL:
                break
        return best

    def _st_once(self, text, sp):
        """supertonic2 한 번 → 22050Hz float(앞뒤 무음 자름 · 센 소리 줄임)."""
        try:
            wav, _ = self._st.synthesize(text, voice_style=self._style, lang="ko", total_steps=config.TTS_ST_STEPS,
                                         speed=sp)
        except ValueError as e:                  # 🔑 그래도 안 받는 글자가 있으면 그 글자만 빼고 한 번 더
            bad = set(_UNSUPPORTED.findall(str(e)))
            if not bad:
                raise
            text = re.sub(r"\s{2,}", " ", "".join(" " if c in bad else c for c in text)).strip()
            wav, _ = self._st.synthesize(text, voice_style=self._style, lang="ko", total_steps=config.TTS_ST_STEPS,
                                         speed=sp)
        return deess(trim(downsample(wav, self._st.sample_rate, config.TTS_OUT_RATE), config.TTS_OUT_RATE),
                     config.TTS_OUT_RATE)


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
