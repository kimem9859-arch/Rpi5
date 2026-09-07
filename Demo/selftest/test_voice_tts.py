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

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
