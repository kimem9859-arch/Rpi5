"""고정 소리 만들기(make_answers) — 여러 번 만들어 또렷한 것 고르기 · 안내 소리 빠르기(2026-10-11).

실행: python3 Demo/selftest/test_make_answers.py
🔑 합성기·받아쓰기는 가짜로 — 고르는 규칙만 본다(실제 합성은 tts venv 의 test_voice_tts).
배경: 처음 만든 「비포」·「드라이버」가 거의 무음(봉우리 335 · 110)이라 안경이 39·118배로 키워 지지직거렸고,
      빠르기 1.25 에서 짧은 낱말이 자주 뭉개졌다(작업 초기화 0/6 → 1.0 에서 3/6).
"""
import os
import struct
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "voice"))

import config        # noqa: E402
import make_answers as M   # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def take(peak, tag):
    """봉우리가 peak 인 가짜 소리(태그로 구분)."""
    return struct.pack("<3h", 0, peak, -peak // 2), 22050, 0.5, tag


class FakeTts:
    def __init__(self, takes):
        self.takes, self.speeds = list(takes), []

    def synth(self, text, speed=None):
        self.speeds.append(speed)
        pcm, rate, sec, _ = self.takes.pop(0)
        return pcm, rate, sec


def test_pick():
    print("\n[고르기] 또렷하면 바로 멈춤 · 너무 작은 소리는 버림 · 다 모자라면 가장 나은 것")
    judge = lambda pcm, rate: {5000: 1.0, 4000: 0.5}.get(max(struct.unpack("<3h", pcm)), 0.0)   # noqa: E731
    f = FakeTts([take(5000, "a"), take(5000, "b")])
    got = M.pick(f, "비원", judge=judge)
    check(got[0] == take(5000, "a")[0] and len(f.speeds) == 1, "첫 소리가 또렷하면 한 번만 만든다")
    f = FakeTts([take(300, "작음"), take(5000, "좋음")])
    check(M.pick(f, "비포", judge=lambda p, r: 1.0)[0] == take(5000, "")[0], "봉우리가 너무 작은 소리(거의 무음)는 고르지 않는다")
    f = FakeTts([take(4000, "")] * 3 + [take(300, "")] * 3)
    got = M.pick(f, "작업 초기화", judge=judge, tries=6)
    check(got[0] == take(4000, "")[0] and len(f.speeds) == 6, "끝까지 또렷한 것이 없으면 가장 나은 것")
    f = FakeTts([take(5000, "")])
    check(M.pick(f, "렌치")[0] == take(5000, "")[0], "받아쓰기 없이도 된다(봉우리만 본다)")


def test_speed():
    print("\n[빠르기] 안내 소리(cue_) = TTS_CUE_SPEED · 문장(알림·답) = 엔진 기본(정한 1.25)")
    check(M.speed_for("cue_B4") == config.TTS_CUE_SPEED == 1.0, f"안내 = {M.speed_for('cue_B4')}")
    check(M.speed_for("alert_block_B2") is None and M.speed_for("wrench") is None, "문장 = None(엔진 기본)")


def main():
    test_pick()
    test_speed()
    print()
    if _fails:
        print(f"❌ {len(_fails)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
