"""관객 소리(TV) — 안경에서 나는 소리를 TV 스피커로도 낸다(상위 specs/2026-10-21-관객소리TV-design.md).

🔑 안경으로 가는 소리는 모두 음성비서 `Speaker` 를 지난다 — 거기에 이 「거울」을 붙여 같은 소리를 TV 로 흘린다.
   이 파일 = 소리 재료(프레임 풀기 · 크기 맞춤 · 레이트 바꾸기 · 띠링)와 TV 통로(`AudienceSpeaker`).
🔴 거울은 안경 쪽을 절대 흔들지 않는다 — 여기 실패는 여기서 끝난다(설계 4장 8).
"""
import os
import struct
import sys

import numpy as np

_VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice")


# ── 소리 재료(순수 함수) ─────────────────────────────────────────────────
def parse_frame(payload):
    """안경 전송 프레임(「W n rate\\n」 + int16LE n개 + uint32LE 체크섬 + 「P\\n」 — `voice_assistant.wav_payload` ·
    `voice_tts.frame`) → `(샘플 int16 배열, 레이트)`. 모양 · 체크섬이 틀리면 None(소리 프레임이 아님)."""
    if not payload or not payload.startswith(b"W "):
        return None
    head, _, rest = payload.partition(b"\n")
    try:
        _, n, rate = head.split()
        n, rate = int(n), int(rate)
    except ValueError:
        return None
    if n < 0 or rate <= 0 or len(rest) != 2 * n + 6 or not rest.endswith(b"P\n"):
        return None
    pcm = np.frombuffer(rest[:2 * n], dtype="<i2")
    (chk,) = struct.unpack("<I", rest[2 * n:2 * n + 4])
    if int((pcm.astype(np.int64) & 0xFFFF).sum()) & 0xFFFFFFFF != chk:
        return None
    return pcm.astype(np.int16), rate


def normalize(pcm, peak):
    """최고 진폭을 `peak` 로 — 안경 펌웨어 play() 가 소리마다 목표 진폭으로 맞추는 것과 같은 방식. 무음은 그대로."""
    a = np.asarray(pcm)
    m = int(np.abs(a.astype(np.int32)).max()) if a.size else 0
    if m == 0:
        return a.astype(np.int16)
    return np.clip(np.round(a.astype(np.float64) * (peak / m)), -32768, 32767).astype(np.int16)


def resample(pcm, src, dst):
    """레이트를 바꾼다(선형 보간 · int16) — 말소리 · 띠링에는 충분하다."""
    a = np.asarray(pcm, dtype=np.int16)
    if src == dst or a.size == 0:
        return a.copy()
    n_out = int(round(a.size * dst / src))
    x = np.arange(n_out) * (src / dst)
    return np.round(np.interp(x, np.arange(a.size), a.astype(np.float64))).astype(np.int16)


def chime_pcm(kind, rate, peak):
    """띠링("open") · 닫힘음("close") — 안경 펌웨어와 같은 모양(`voice/make_guide.chime` 재사용 · 그 값은
    selftest 가 펌웨어 소스와 대조한다). 모르는 종류 · 못 만들면 None."""
    try:
        if _VOICE_DIR not in sys.path:
            sys.path.insert(0, _VOICE_DIR)
        import make_guide as mg
        segs = {"open": mg.CHIME_SEGS, "close": mg.CLOSE_SEGS}.get(kind)
        if segs is None:
            return None
        return np.clip(np.round(mg.chime(rate, peak, segs)), -32768, 32767).astype(np.int16)
    except Exception:                           # noqa: BLE001 — 띠링만 빠진다(설계 4장 5)
        return None
