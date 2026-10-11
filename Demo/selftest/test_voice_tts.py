"""런타임 합성 검증 — 프레임이 wav_payload 와 같은 모양인지 본다.

실행: ~/env/tts/.venv/bin/python Demo/selftest/test_voice_tts.py

🔴 시스템 python3 에는 sherpa_onnx 가 없다 — 반드시 tts venv 로 돌린다.
정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §7
"""
import os
import struct
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from voice_assistant import wav_payload
from voice_tts import Tts, frame

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    t = Tts()
    got = t.synth("앞에 렌치가 보입니다.")
    check(got is not None, "합성이 된다")
    pcm, rate0, sec = got
    body = frame(pcm, rate0)
    check(body.startswith(b"W "), "W 프레임으로 시작한다")
    check(body.endswith(b"P\n"), "P 로 끝난다")
    check(0.5 < sec < 5.0, f"말하는 시간이 그럴듯하다 ({sec:.2f}초)")

    head, rest = body.split(b"\n", 1)
    n, rate = int(head.split()[1]), int(head.split()[2])
    check(len(rest) == n * 2 + 4 + 2, "본문 길이 = 샘플*2 + 체크섬4 + P\\n2")
    import array
    a = array.array("h")
    a.frombytes(rest[:n * 2])
    chk = struct.unpack("<I", rest[n * 2:n * 2 + 4])[0]
    check(chk == (sum(v & 0xFFFF for v in a) & 0xFFFFFFFF),
          "🔴 체크섬 계산이 펌웨어·wav_payload 와 같다")

    # 🔴 두 프레임 생성기가 같은 PCM 에 대해 **바이트 단위로 같은 것**을 내야 한다.
    #    어긋나면 펌웨어 checksum() 이 재생을 통째로 버린다.
    ref_path = os.path.join(_DEMO_DIR, "voice", "wav", "wrench.wav")
    ref, _ = wav_payload(ref_path)
    import wave as _wave
    with _wave.open(ref_path) as w:
        ref_pcm, ref_rate = w.readframes(w.getnframes()), w.getframerate()
    check(frame(ref_pcm, ref_rate) == ref,
          "🔴 voice_tts.frame() 이 wav_payload() 와 바이트 단위로 일치한다")

    check(t.synth("") is None, "빈 문자열이면 None")

    # ── 엔진 갈래 · 한글 읽기 · 레이트(측정 진행 도우미 설계 2026-10-11 D11) ──
    import numpy as np
    import config
    import voice_tts as V
    check(V.read_out("B1 다음 B4 · EMO 해제") == "비원 다음 비포 · 비상정지 해제", "버튼 이름 → 한글 읽기")
    sr = 44100
    tt = np.arange(sr) / sr
    lo = V.downsample(np.sin(2 * np.pi * 1000 * tt) * 0.5, 44100, 22050)
    hi = V.downsample(np.sin(2 * np.pi * 15000 * tt) * 0.5, 44100, 22050)
    check(len(lo) == 22050, f"44100 → 22050 길이 절반 ({len(lo)})")
    check(abs(np.abs(lo[1000:-1000]).max() - 0.5) < 0.03, "1kHz 진폭이 그대로다")
    check(np.abs(hi[1000:-1000]).max() < 0.5 * 10 ** (-30 / 20), "15kHz(새 나이퀴스트 위)는 30dB 넘게 깎인다")
    x = np.r_[np.zeros(1000), np.full(10, 0.5), np.zeros(1000)].astype(np.float32)
    check(len(V.trim(x, 22050)) == 10 + 2 * int(22050 * V.TRIM_PAD_SEC), "앞뒤 무음을 자르고 여유만 남긴다")
    check(t.engine == config.TTS_ENGINE == "supertonic2", f"기본 엔진 = supertonic2 ({t.engine})")
    check(rate0 == config.TTS_OUT_RATE == 22050, f"출력 레이트 = 22050 ({rate0})")
    check(Tts(engine="kss").synth("앞에 렌치가 보입니다.") is not None, "되돌리기 갈래(kss)도 합성된다")

    # ── 센 소리 줄이기(2026-10-11 · 사용자 「센 발음(고음)만 깍아 낼 순 없나」 · 「조금 줄인 쪽」) ──
    r = 22050
    seg = lambda f, s: (np.sin(2 * np.pi * f * np.arange(int(r * s)) / r) * 0.5).astype(np.float32)   # noqa: E731
    x = np.r_[seg(500, 0.3), seg(7000, 0.2), seg(500, 0.3)]
    try:
        y = V.deess(x, r)
    except AttributeError:
        check(False, "deess 가 없다")
        y = None
    if y is not None:
        a, b = int(r * 0.25), int(r * 0.55)          # 바뀐 곳에서 50ms 떨어진 모음(500Hz) 자리
        check(np.abs(y[:a] - x[:a]).max() < 1e-4 and np.abs(y[b:] - x[b:]).max() < 1e-4,
              "센 소리가 아닌 곳(500Hz)은 손대지 않는다 — 소리 전체를 깎지 않는다")
        mid = slice(int(r * 0.35), int(r * 0.45))
        got = np.abs(y[mid]).max()
        check(abs(got - 0.5 * config.TTS_DEESS_GAIN) < 0.03, f"센 소리(7kHz) 순간만 {config.TTS_DEESS_GAIN} 배로 ({got:.3f})")
        check(np.abs(V.deess(x, r, gain=1.0) - x).max() < 1e-4, "gain 1.0 = 끔")
        called = []
        orig = V.deess
        V.deess = lambda x, rate, **k: (called.append(rate), orig(x, rate, **k))[1]
        try:
            t.synth("다시")
        finally:
            V.deess = orig
        check(called == [config.TTS_OUT_RATE], "supertonic2 합성이 센 소리 줄이기를 지난다")
    import voice_assistant as va
    check(va.build_stt() is not None, f"받아쓰기가 저장소 핫워드 목록(「가디언 :8.0」 꼴)을 읽는다 — {os.path.basename(va.HOTWORDS)}")
    try:
        Tts(engine="없음")
        check(False, "모르는 엔진을 못 잡음")
    except ValueError:
        check(True, "모르는 엔진 = ValueError")

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
