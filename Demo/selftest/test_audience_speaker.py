"""관객 소리(TV) 거울 검증 — 소리 재료(프레임 풀기 · 크기 맞춤 · 레이트 · 띠링)와 통로(AudienceSpeaker).

실행: python3 Demo/selftest/test_audience_speaker.py
정본 = 상위 docs/superpowers/specs/2026-10-21-관객소리TV-design.md 4장
"""
import os
import re
import sys
import wave

import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "voice"))

import audience_speaker as aus   # noqa: E402
import config                    # noqa: E402
import voice_assistant as va     # noqa: E402
import voice_tts                 # noqa: E402

FW = os.path.join(_DEMO, "..", "arduino", "glass_voice", "glass_voice.ino")
WAV = os.path.join(_DEMO, "voice", "wav", "cue_g1_0a.wav")
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _peak_hz(seg, rate):
    seg = np.asarray(seg, dtype=np.float64)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    return float(np.fft.rfftfreq(len(seg), 1 / rate)[int(np.argmax(spec))])


def test_parse_frame_roundtrip():
    print("\n[재료] 프레임 풀기 — 합성 답 · 고정 wav")
    pcm = (np.sin(np.arange(1600) / 5) * 3000).astype("<i2")
    got = aus.parse_frame(voice_tts.frame(pcm.tobytes(), 16000))
    check(got is not None and got[1] == 16000 and np.array_equal(got[0], pcm), "합성 답 프레임 = 원래 샘플 · 16000Hz")
    body, _ = va.wav_payload(WAV)
    with wave.open(WAV) as w:
        rate, raw = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2")
    got = aus.parse_frame(body)
    check(got is not None and got[1] == rate and np.array_equal(got[0], raw), f"고정 wav 프레임 = 원래 샘플 · {rate}Hz")


def test_parse_frame_rejects_bad():
    print("\n[재료] 잘못된 프레임은 None")
    body = voice_tts.frame((np.ones(100) * 5).astype("<i2").tobytes(), 16000)
    bad_chk = body[:-6] + bytes([body[-6] ^ 1]) + body[-5:]
    check(aus.parse_frame(bad_chk) is None, "체크섬이 다르면 None")
    check(aus.parse_frame(body[:-2]) is None, "꼬리(P) 없으면 None")
    check(aus.parse_frame(b"") is None, "빈 바이트는 None")
    check(aus.parse_frame(b"B\n") is None, "한 글자 명령은 None")


def test_normalize_peak():
    print("\n[재료] 크기 맞춤")
    a = np.array([0, 1000, -3394, 200], dtype=np.int16)
    out = aus.normalize(a, 29162)
    check(int(np.abs(out).max()) == 29162 and out.dtype == np.int16, f"최고 3394 → 29162 ({int(np.abs(out).max())})")
    z = aus.normalize(np.zeros(10, np.int16), 29162)
    check(int(np.abs(z).max()) == 0, "무음은 그대로 0")


def test_resample_length():
    print("\n[재료] 레이트 바꾸기")
    a = (np.sin(np.arange(24000) / 7) * 1000).astype(np.int16)
    out = aus.resample(a, 24000, 48000)
    check(abs(len(out) - 48000) <= 1 and out.dtype == np.int16, f"24000 → 48000 길이 2배 ({len(out)})")
    check(len(aus.resample(a, 48000, 48000)) == len(a), "같은 레이트면 길이 그대로")


def test_chime_shape():
    print("\n[재료] 띠링 · 닫힘음 — 펌웨어와 같은 모양(make_guide.chime 재사용)")
    rate, peak = 48000, 29162
    for kind, first, second in (("open", 1568, 2093), ("close", 2093, 1568)):
        c = aus.chime_pcm(kind, rate, peak)
        check(abs(len(c) - int(0.43 * rate)) <= 2, f"{kind} 길이 0.43초({len(c) / rate:.3f})")
        check(0 < int(np.abs(c).max()) <= peak, f"{kind} 최고 진폭 ≤ {peak}")
        f1 = _peak_hz(c[int(0.040 * rate):int(0.140 * rate)], rate)
        f2 = _peak_hz(c[int(0.200 * rate):int(0.380 * rate)], rate)
        check(abs(f1 - first) <= 20 and abs(f2 - second) <= 20, f"{kind} 높이 {first}→{second} ({f1:.0f}→{f2:.0f})")
    check(aus.chime_pcm("없음", rate, peak) is None, "모르는 종류는 None")


def test_close_chime_matches_firmware():
    print("\n[재료] 닫힘음 순서 = 펌웨어 closeChime()")
    src = open(FW, encoding="utf-8").read()
    body = src[src.index("static void closeChime()"):]
    body = body[:body.index("}")]
    tones = re.findall(r"toneSeg\((CHIME_\w+), \1, (\d+)", body)
    check(tones == [("CHIME_HI", "120"), ("CHIME_LO", "180")], f"펌웨어 닫힘음 = HI 120ms → LO 180ms ({tones})")


def test_config_values():
    print("\n[설정] 관객 소리 값")
    check(config.AUDIENCE_PEAK == 29162 and config.AUDIENCE_RATE == 48000, "기준 진폭 29162 · 48000Hz")
    check(config.AUDIENCE_TAIL_MAX_SEC == 0.5 and config.AUDIENCE_TAIL_PAD_SEC == 0.15, "꼬리 상한 0.5 · 여유 0.15")
    check(isinstance(config.AUDIENCE_SPEAKER, bool), "켬/끔 = bool")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:      # noqa: BLE001 — 하나가 터져도 나머지를 본다
                check(False, f"{name} 예외 — {type(e).__name__}: {e}")
    print(f"\n{'❌ 실패 ' + str(len(_fails)) + '건' if _fails else '✅ 모두 통과'}")
    sys.exit(1 if _fails else 0)
