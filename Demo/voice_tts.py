"""런타임 TTS — LLM 이 만든 문장을 그때그때 합성한다.

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §4

🔑 A 갈래의 사전 합성(make_answers.py)을 되돌리는 자리다. 문장이 매번 다르니
   미리 만들어 둘 수 없다.

🔴 **말하는 시간이 지연의 지배 항목이다** — LLM 문장은 A 갈래 답변(1.48초)의
   3.2~3.6배인 4.77~5.34초를 말한다(§10.62-(9)). 합성 자체는 0.4~1.05초다.

⚠️ 모델은 상주시킨다 — 적재가 약 0.93초라 매번 올리면 그만큼 늘어난다(§10.49).
"""
import array
import os
import struct

_D = os.path.expanduser("~/env/tts/vits-mimic3-ko_KO-kss_low")


class Tts:
    """sherpa VITS 합성기. 만들 때 모델을 올리고 계속 들고 있는다."""

    def __init__(self, model_dir=None, threads=2):
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

    def synth(self, text, speed=1.0):
        """`(pcm bytes, 레이트, 말하는 시간초)` — 실패하면 None."""
        if not (text or "").strip():
            return None
        try:
            a = self._tts.generate(text, sid=0, speed=speed)
        except Exception:                      # noqa: BLE001 — 데몬은 살아야 한다
            return None
        pcm = array.array("h", [int(max(-1.0, min(1.0, x)) * 32767) for x in a.samples])
        if not pcm:
            return None
        return pcm.tobytes(), a.sample_rate, len(pcm) / a.sample_rate


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
