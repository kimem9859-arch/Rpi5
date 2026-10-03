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
import re

import config
import voice_tts

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
    _send_later(b2, ["[적재] ok\n", "[재생 완료]\n"])
    spk2._drain(wait=3.0)
    check(spk2.s is not None, "제때 끝나면 채널을 그대로 쓴다")
    b2.close()

def test_final_minor_bad_wav_does_not_kill():
    """④ 미룬 사소 4 — 16비트가 아닌 wav(8비트·홀수 길이)도 그 재생만 실패 — 음성비서가 죽지 않는다."""
    print("\n[④ 사소 4] 16비트가 아닌 wav")
    import wave
    spk, b = _speaker_pair()
    old = va.WAV_DIR
    va.WAV_DIR = tempfile.mkdtemp()
    try:
        with wave.open(os.path.join(va.WAV_DIR, "8비트.wav"), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(16000)
            w.writeframes(bytes(range(101)))         # 홀수 바이트 — 16비트 배열로 못 읽는다
        ok = spk.play("8비트")
        check(ok is False, "그 재생만 실패로 돌려준다")
    except Exception as e:                           # noqa: BLE001
        check(False, f"예외로 끝났다 — {type(e).__name__}")
    finally:
        va.WAV_DIR = old
        b.close()

def _capture_log():
    logs = []
    old = va.log
    va.log = lambda m: (logs.append(m), old(m))
    return logs, lambda: setattr(va, "log", old)


def test_fw_limits_match_firmware():
    """§4.3 C2 — 파이 쪽 한도 상수가 펌웨어 소스와 같다(어긋나면 한도 검사가 무의미하다)."""
    print("\n[한도] 펌웨어 대조")
    src = open(os.path.join(_DEMO_DIR, "..", "arduino", "glass_voice", "glass_voice.ino"),
               encoding="utf-8").read()
    sec = int(re.search(r"MAX_SEC\s*=\s*(\d+)", src).group(1))
    rmax = int(re.search(r"MAX_RATE\s*=\s*(\d+)", src).group(1))
    rmin = int(re.search(r"r\s*<\s*(\d+)\s*\|\|", src).group(1))
    check(config.VOICE_FW_MAX_SAMPLE == sec * rmax, f"샘플 한도 {config.VOICE_FW_MAX_SAMPLE} = {sec}×{rmax}")
    check((config.VOICE_FW_RATE_MIN, config.VOICE_FW_RATE_MAX) == (rmin, rmax), "레이트 범위")
    check(voice_tts.fits(240000, 24000), "한도 끝은 들어간다")
    check(not voice_tts.fits(240001, 24000), "한도 넘으면 안 된다")
    check(not voice_tts.fits(1000, 7999) and not voice_tts.fits(1000, 24001), "레이트 범위 밖")
    check(not voice_tts.fits(0, 16000), "빈 소리는 안 된다")


def test_stale_complete_ignored():
    """§4.5 — 적재 확인 전에 온 「재생 완료」는 지난 재생의 늦은 응답이다 — 이번 확인으로 쓰지 않는다(R3 I1)."""
    print("\n[확인] 이번 요청의 응답만")
    spk, b = _speaker_pair()
    _send_later(b, ["[재생 완료]\n", 0.2, "[준비]\n", "[적재] ok\n", 0.2, "[재생 완료]\n"])
    t0 = time.time()
    out = spk._drain(wait=3.0)
    check(out.count("[재생 완료]") == 1 and out[-1] == "[재생 완료]", f"응답 = {out}")
    check(time.time() - t0 >= 0.35, "앞선 「재생 완료」에서 멈추지 않았다")
    b.close()


def test_fail_resets_channel():
    """§4.5 — 펌웨어 FAIL 이면 채널을 버린다 — 거절된 본문이 한 글자 명령으로 읽히는 것을 끊는다(P4)."""
    print("\n[FAIL] 채널을 버린다")
    spk, b = _speaker_pair()
    _send_later(b, ["[FAIL] 샘플수 300000 — 1~240000 범위를 벗어났다.\n"])
    out = spk._drain(wait=2.0)
    check(any("FAIL" in x for x in out) and spk.s is None, f"FAIL → 채널 버림 · {out}")
    b.close()


def test_eof_logged_as_eof():
    """R3 M3 — 명령 채널 EOF 를 「15초 안에 안 끝남」으로 적지 않는다."""
    print("\n[EOF] 사실대로 적는다")
    logs, restore = _capture_log()
    try:
        spk, b = _speaker_pair()
        b.close()
        spk._drain(wait=3.0)
        check(spk.s is None, "채널을 버린다")
        check(any("닫혔다" in l for l in logs) and not any("안에 끝나지 않았다" in l for l in logs),
              f"로그 = {logs[-1:]}")
    finally:
        restore()


def test_peer_closed_reconnects_before_send():
    """R3 M1 · R2 C2 — 상대가 닫은 채널에 띠링을 보내면 오류 없이 사라졌다 — 보내기 전에 알아채고 다시 붙는다.
    붙을 때마다 주소를 다시 읽는다(Review Focus 4)."""
    print("\n[닫힘] 보내기 전에 다시 붙는다")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)
    srv.settimeout(3)
    calls = []

    def getter():
        calls.append(1)
        return "127.0.0.1"

    spk = va.Speaker(getter, port=srv.getsockname()[1])
    try:
        spk.send(b"")
        c1, _ = srv.accept()
        c1.close()
        time.sleep(0.1)
        spk.chime()
        c2, _ = srv.accept()
        c2.settimeout(2)
        got, end = b"", time.time() + 2
        while b"B\n" not in got and time.time() < end:
            try:
                got += c2.recv(64)
            except socket.timeout:
                break
        check(b"B\n" in got, f"띠링이 새 연결로 갔다 — {got!r}")
        check(len(calls) == 2, f"붙을 때마다 주소를 다시 읽었다 — {len(calls)}회")
        c2.close()
    finally:
        spk.reset()
        srv.close()


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
