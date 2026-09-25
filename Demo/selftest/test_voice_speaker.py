"""음성비서 명령 채널 검증(V1·V4) — ESP32 없이 소켓 쌍으로.

실행: python3 Demo/selftest/test_voice_speaker.py
정본 = 상위 docs/superpowers/specs/2026-09-25-런타임-문제수정-design.md §4.3
"""
import os
import socket
import sys
import tempfile
import threading
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import voice_assistant as va

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _speaker_pair():
    a, b = socket.socketpair()
    spk = va.Speaker("시험")
    spk.s = a
    spk.f = a.makefile("rb")          # 종전 코드가 읽던 통로(고친 뒤에는 쓰지 않는다)
    return spk, b


def _send_later(b, parts):
    def go():
        for p in parts:
            if isinstance(p, float):
                time.sleep(p)
            else:
                b.sendall(p.encode())
    threading.Thread(target=go, daemon=True).start()


def test_v1_silence_during_playback_is_waited():
    """V1 — 재생 중 1초 넘는 무음 뒤의 「재생 완료」를 받고, 다음 재생도 확인된다(검토 C6)."""
    print("\n[V1] 재생 확인")
    spk, b = _speaker_pair()
    _send_later(b, ["[준비]\n", "[적재] ok\n", 1.4, "[재생 완료]\n"])
    out = spk._drain(wait=5.0)
    check(any("재생 완료" in x for x in out), f"첫 재생 확인 — {out}")
    _send_later(b, ["[적재] ok\n", 0.2, "[재생 완료]\n"])
    out2 = spk._drain(wait=5.0)
    check(any("재생 완료" in x for x in out2), f"두 번째 재생도 확인 — {out2}")
    b.close()


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 음성 명령 채널 검증 통과")
