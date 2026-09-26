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


def test_v4_audio_log_closed_at_exit():
    """V4 — 오디오 기록(마이크_전체.wav)을 프로그램이 끝날 때 닫도록 등록한다(함수목록 §4.1-8)."""
    print("\n[V4] 녹음 파일 닫기")
    reg = []
    atx = getattr(va, "atexit", None)
    old = atx.register if atx else None
    if atx:
        atx.register = lambda fn, *a, **k: reg.append(fn)
    try:
        opener = getattr(va, "open_audio_log", None)
        check(opener is not None, "open_audio_log 가 있다")
        if opener is not None:
            alog = opener(tempfile.mkdtemp())
            check(any(getattr(f, "__self__", None) is alog and f.__name__ == "close" for f in reg),
                  "종료 때 alog.close 가 불리도록 등록된다")
            alog.close()
    finally:
        if atx:
            atx.register = old

def test_c20_missing_wav_does_not_kill():
    """C20 — 재생 파일이 없으면 그 재생만 실패 — 음성비서가 죽지 않는다(검토 C20)."""
    print("\n[C20] wav 없음")
    spk, b = _speaker_pair()
    old = va.WAV_DIR
    va.WAV_DIR = tempfile.mkdtemp()
    try:
        ok = spk.play("없는소리")
        check(ok is False, "그 재생만 실패로 돌려준다")
    except Exception as e:                           # noqa: BLE001
        check(False, f"예외로 끝났다 — {type(e).__name__}")
    finally:
        va.WAV_DIR = old
        b.close()


def test_m2_timeout_drops_channel():
    """M-2 — 한도 안에 「재생 완료」가 없으면 명령 채널을 버린다 — 늦은 응답이 다음 재생에 섞이지 않게(③ 리뷰 M-2)."""
    print("\n[M-2] 재생 확인 한도 초과")
    spk, b = _speaker_pair()
    _send_later(b, ["[적재] ok\n"])
    out = spk._drain(wait=0.5)
    check(out == ["[적재] ok"], "한도 안에 받은 응답은 돌려준다")
    check(spk.s is None, "명령 채널을 버린다(다음 전송이 새로 붙는다)")
    b.close()
    spk2, b2 = _speaker_pair()
    _send_later(b2, ["[재생 완료]\n"])
    spk2._drain(wait=3.0)
    check(spk2.s is not None, "제때 끝나면 채널을 그대로 쓴다")
    b2.close()

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
