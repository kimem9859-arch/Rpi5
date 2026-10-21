"""관객 소리(TV) — 음성비서 `Speaker` 에 붙인 거울 검증(ESP32 없이 소켓 쌍으로 · 가짜 거울).

실행: python3 Demo/selftest/test_voice_mirror.py
정본 = 상위 docs/superpowers/specs/2026-10-21-관객소리TV-design.md 4장 1 · 2 · 3 · 8 · 12
🔒 기존 test_voice_speaker.py 는 고치지 않는다 — 소켓 쌍 방식만 같게 쓴다.
"""
import os
import socket
import sys
import threading
import time

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import numpy as np            # noqa: E402

import config                 # noqa: E402
import voice_assistant as va  # noqa: E402
import voice_tts              # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class FakeMirror:
    def __init__(self, spk_box=None):
        self.calls = []
        self.spk_box = spk_box if spk_box is not None else {}   # 🔴 빈 사전은 거짓 — `or` 로 쓰면 다른 사전이 된다
        self.io_free_at_tail = None

    def prepare(self, payload, t_send=None):
        self.calls.append("prepare")
        self.t_send = t_send

    def begin(self):
        self.calls.append("begin")

    def stop(self):
        self.calls.append("stop")

    def chime(self, kind):
        self.calls.append(f"chime:{kind}")

    def wait_tail(self, max_sec):
        self.calls.append("wait_tail")
        spk = self.spk_box.get("spk")
        if spk is not None:
            got = []

            def probe():                 # 다른 스레드(= 알림 감시)가 지금 _io 를 잡을 수 있나 — 잡았으면 그 스레드가 푼다
                ok = spk._io.acquire(blocking=False)
                if ok:
                    spk._io.release()
                got.append(ok)
            th = threading.Thread(target=probe)
            th.start()
            th.join()
            self.io_free_at_tail = bool(got and got[0])


class BoomMirror:
    def __getattr__(self, name):
        def boom(*a, **k):
            raise RuntimeError(f"거울 {name} 터짐")
        return boom


def _pair(mirror=None):
    a, b = socket.socketpair()
    spk = va.Speaker("시험", mirror=mirror)
    spk.s = a
    return spk, b


def _reply(b, parts, delay=0.05):
    def go():
        time.sleep(delay)
        for p in parts:
            if isinstance(p, float):
                time.sleep(p)
            else:
                b.sendall(p.encode())
    th = threading.Thread(target=go, daemon=True)
    th.start()
    return th


def _drain_all(b, sec=0.2):
    b.settimeout(sec)
    got = b""
    try:
        while True:
            c = b.recv(65536)
            if not c:
                break
            got += c
    except socket.timeout:
        pass
    return got


def _frame():
    return voice_tts.frame((np.sin(np.arange(800) / 3) * 2000).astype("<i2").tobytes(), 16000)


def test_play_mirrors_on_play_line():
    print("\n[거울] 「[재생]」 에 맞춰 TV 시작 · 끝나면 잠금 밖에서 꼬리 기다림")
    box = {}
    m = FakeMirror(box)
    spk, b = _pair(m)
    box["spk"] = spk
    _reply(b, ["[적재] 800샘플 ok\n", "[재생] 800샘플\n", 0.05, "[재생 완료]\n"])
    out = spk.send(_frame(), expect=True)
    check(any("재생 완료" in x for x in out), f"재생 확인 그대로 — {out}")
    check(m.calls == ["prepare", "begin", "wait_tail"], f"거울 순서 prepare → begin → wait_tail ({m.calls})")
    check(m.io_free_at_tail is True, "wait_tail 때 _io 잠금이 풀려 있다(알림이 기다리지 않음)")
    b.close()


def test_stop_cuts_mirror_then_next_plays():
    print("\n[거울] 멈춤(S)이면 TV 도 멈추고 · 다음 소리는 다시 난다")
    m = FakeMirror()
    spk, b = _pair(m)
    res = {}
    th = threading.Thread(target=lambda: res.setdefault("r", spk.send(_frame(), expect=True)))
    _reply(b, ["[적재] ok\n", "[재생] 800\n"])
    th.start()
    time.sleep(0.3)
    spk.stop()
    b.sendall(b"[\xec\x9e\xac\xec\x83\x9d \xec\xa4\x91\xeb\x8b\xa8]\n")    # 「[재생 중단]」
    th.join(3)
    check("stop" in m.calls and m.calls.index("stop") > m.calls.index("begin"), f"begin 뒤 stop ({m.calls})")
    check("wait_tail" not in m.calls, "중단이면 꼬리를 기다리지 않는다")
    m.calls.clear()
    _drain_all(b)
    _reply(b, ["[적재] ok\n", "[재생] 800\n", "[재생 완료]\n"])
    spk.send(_frame(), expect=True)
    check(m.calls[:2] == ["prepare", "begin"], f"다음 소리는 다시 begin ({m.calls})")
    b.close()


def test_mirror_stops_on_channel_reset():
    print("\n[거울] 재생 도중 채널이 끊기면 TV 도 멈춘다")
    m = FakeMirror()
    spk, b = _pair(m)
    def go():
        time.sleep(0.05)
        b.sendall("[적재] ok\n[재생] 800\n".encode())
        time.sleep(0.1)
        b.close()
    threading.Thread(target=go, daemon=True).start()
    spk.send(_frame(), expect=True)
    check("begin" in m.calls and m.calls[-1] == "stop", f"끊김 뒤 마지막 호출 = stop ({m.calls})")


def test_chime_only_on_success():
    print("\n[거울] 띠링 · 닫힘음은 보낸 게 확인될 때만")
    m = FakeMirror()
    spk, b = _pair(m)
    check(spk.chime() is True and m.calls == ["chime:open"], f"띠링 성공 → chime:open ({m.calls})")
    m.calls.clear()
    r = spk.close_chime(still_valid=lambda: False)
    check(r is va.DROPPED and m.calls == [], f"낡아서 안 보냄 → 거울 안 부름 ({m.calls})")
    r = spk.close_chime()
    check(r is True and m.calls == ["chime:close"], f"닫힘음 성공 → chime:close ({m.calls})")
    b.close()
    dead = va.Speaker(lambda: (_ for _ in ()).throw(OSError("주소 없음")), mirror=m)
    m.calls.clear()
    check(dead.chime() is False and not any(c.startswith("chime") for c in m.calls),
          f"전송 실패 → 거울 띠링 안 부름(채널을 버릴 때 stop 은 설계대로 · {m.calls})")


def _session(mirror):
    """같은 대화를 거울만 바꿔 돌린다 → (안경이 받은 바이트, 반환값들)."""
    spk, b = _pair(mirror)
    rets = []
    _reply(b, ["[적재] ok\n", "[재생] 800\n", "[재생 완료]\n"])
    rets.append(spk.send(_frame(), expect=True))
    rets.append(spk.chime())
    rets.append(spk.close_chime())
    rets.append(spk.stop())
    got = _drain_all(b)
    b.close()
    return got, rets


def test_mirror_exception_isolated_and_holdout():
    print("\n[거울] 🔒 거울 없음 · 가짜 · 터지는 거울 — 안경이 받는 바이트와 반환값이 같다")
    base = _session(None)
    fake = _session(FakeMirror())
    boom = _session(BoomMirror())
    check(base[0] == fake[0] == boom[0], f"안경이 받은 바이트 같음({len(base[0])} · {len(fake[0])} · {len(boom[0])})")
    check(base[1] == fake[1] == boom[1], f"반환값 같음({base[1]})")


def test_audience_flag():
    print("\n[거울] 설정 「TV 소리」 칸 읽기")
    check(va.AudienceFlag(read_state=lambda: {"관객소리": False})() is False, "칸 = 끔 → False")
    check(va.AudienceFlag(read_state=lambda: {"관객소리": True})() is True, "칸 = 켬 → True")
    check(va.AudienceFlag(read_state=lambda: {})() is config.AUDIENCE_SPEAKER, "칸 없음 → config 값")
    check(va.AudienceFlag(read_state=lambda: None)() is config.AUDIENCE_SPEAKER, "상태 파일 없음 → config 값")


def test_make_mirror_off():
    print("\n[거울] SOP_AUDIENCE_SPEAKER=0 이면 통로를 만들지 않는다")
    old = config.AUDIENCE_SPEAKER
    config.AUDIENCE_SPEAKER = False
    try:
        check(va.make_mirror() is None, "config 끔 → None")
    finally:
        config.AUDIENCE_SPEAKER = old


def test_run_makes_no_real_mirror_by_itself():
    print("\n[거울] 🔴 시험이 부르는 run() 은 진짜 TV 재생기를 띄우지 않는다 — 실행 입구(main)만 만든다")
    import inspect
    sig = inspect.signature(va.run)
    check("mirror" in sig.parameters and sig.parameters["mirror"].default is None, "run(mirror=None) — 기본 = 거울 없음")
    check("make_mirror(" not in inspect.getsource(va.run), "run() 안에서 make_mirror 를 부르지 않는다")
    check("make_mirror(" in inspect.getsource(va.main), "main() 이 거울을 만들어 넘긴다")

def test_prepare_nonblocking_before_send():
    print("\n[거울] 검토 Minor 1 · 설계 11장 — 보내기 시작할 때 넘기되 거울은 곧바로 돌아온다(안경 쪽 지연 0)")
    import inspect
    src = inspect.getsource(va.Speaker._send)
    check(src.index('_mirror("prepare"') < src.index("sendall(payload)"), "보내기 시작 전에 prepare(t_send)")
    import audience_speaker as aus
    sp = aus.AudienceSpeaker(lambda: True, cmd=[sys.executable, "-c", "import time;time.sleep(5)"], log=lambda m: None)
    sp.start()
    big = voice_tts.frame((np.sin(np.arange(8 * 24000) / 3) * 3000).astype("<i2").tobytes(), 24000)
    t0 = time.monotonic()
    sp.prepare(big, t_send=t0)
    dt = time.monotonic() - t0
    sp.close()
    check(dt < 0.005, f"8초 소리도 prepare 가 곧바로 돌아온다({dt * 1000:.1f}ms)")

def test_send_passes_t_send():
    print("\n[거울] 앞당겨 틀기 — 보내기 시작한 때(t_send)를 거울에 넘긴다(설계 11장)")
    m = FakeMirror()
    spk, b = _pair(m)
    _reply(b, ["[적재] ok\n", "[재생] 800\n", "[재생 완료]\n"])
    t_before = time.monotonic()
    spk.send(_frame(), expect=True)
    check(isinstance(m.t_send, float) and t_before <= m.t_send <= time.monotonic(), f"t_send = 단조 시계 · 보내기 전후 사이({m.t_send})")
    b.close()

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:      # noqa: BLE001
                check(False, f"{name} 예외 — {type(e).__name__}: {e}")
    print(f"\n{'❌ 실패 ' + str(len(_fails)) + '건' if _fails else '✅ 모두 통과'}")
    sys.exit(1 if _fails else 0)
