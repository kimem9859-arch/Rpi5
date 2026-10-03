"""마이크 수신 스레드 — 설계 2026-10-03 §4.1 (P1 귀먹음 · P5 반열림 · G11 대답 중 소리).

실행: python3 Demo/selftest/test_voice_mic.py
"""
import math
import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

from fake_glass import FakeGlass  # noqa: E402
from voice_mic import MicReceiver  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def tone(sec, amp=4000):
    return [int(amp * math.sin(i / 5)) for i in range(int(16000 * sec))]


def wait_for(cond, sec):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def receiver(g, logs, **kw):
    kw.setdefault("stall_sec", 0.6)
    kw.setdefault("retry_sec", 0.1)
    return MicReceiver(lambda: "127.0.0.1", g.mic_port, log=logs.append, **kw).start()


def test_receives_continuously():
    print("\n[수신] 늘 읽어 쌓는다")
    g = FakeGlass([tone(0.5)], mic_port=0, cmd_port=0, tail_sec=10, quiet=True).start()
    logs = []
    mr = receiver(g, logs)
    try:
        check(wait_for(lambda: mr.generation == 1, 3), "붙었다(generation 1)")
        time.sleep(1.0)
        a = mr.pull()
        check(len(a) >= 9600, f"1초 동안 쌓인 표본 {len(a)}개(≥ 0.6초 분량)")
        check(abs(int(a.mean()) - 1400) < 300, "DC 가 실린 원래 값 그대로(파이가 DC 를 뺀다)")
    finally:
        mr.stop()
        g.stop()


def test_halfopen_reconnects():
    """🔴 반열림 — FIN 없이 조용해지면 stall_sec 뒤 다시 붙는다(종전: 5초 타임아웃을 영원히 삼켰다 · R2 C1)."""
    print("\n[반열림] 무수신 → 재접속")
    g = FakeGlass([tone(0.3), tone(0.3)], mic_port=0, cmd_port=0, lead_sec=0.2, gap_sec=0.2,
                  tail_sec=5, vanish=True, quiet=True).start()
    logs = []
    mr = receiver(g, logs)
    try:
        check(wait_for(lambda: mr.generation >= 2, 5), f"다시 붙었다(generation {mr.generation})")
        check(any("무수신" in l for l in logs), "로그에 무수신 이유가 남는다")
        check(g.count("mic_conn") >= 2, "모의 글라스도 두 번째 연결을 받았다")
    finally:
        mr.stop()
        g.stop()


def test_eof_reconnects_and_reads_address_each_time():
    print("\n[끊김] EOF → 재접속 · 주소를 매번 다시 읽는다")
    g = FakeGlass([], mic_port=0, cmd_port=0, lead_sec=0.3, tail_sec=0.3, quiet=True).start()
    calls, logs = [], []

    def getter():
        calls.append(1)
        return "127.0.0.1"

    mr = MicReceiver(getter, g.mic_port, stall_sec=0.6, retry_sec=0.1, log=logs.append).start()
    try:
        check(wait_for(lambda: mr.generation >= 2, 5), f"끊긴 뒤 다시 붙었다(generation {mr.generation})")
        check(len(calls) >= 2, f"붙을 때마다 주소를 다시 읽는다 — {len(calls)}회")
    finally:
        mr.stop()
        g.stop()


def test_reads_address_each_time():
    """Review Focus 4 — 주소 읽기가 실패해도(파일 없음 = SystemExit) 스레드가 죽지 않고 다시 읽는다."""
    print("\n[주소] 읽기 실패에도 산다")
    g = FakeGlass([], mic_port=0, cmd_port=0, tail_sec=5, quiet=True).start()
    n = []

    def getter():
        n.append(1)
        if len(n) == 1:
            raise SystemExit("🔴 보드 주소를 못 찾았다(시험)")
        return "127.0.0.1"

    logs = []
    mr = MicReceiver(getter, g.mic_port, retry_sec=0.1, log=logs.append).start()
    try:
        check(wait_for(lambda: mr.generation == 1, 3), "두 번째 읽기로 붙었다")
    finally:
        mr.stop()
        g.stop()


def test_clear_drops_queued():
    """G11 — 대답하는 동안 쌓인 소리는 clear() 로 버린다(종전 del buf[:] 는 커널에 쌓인 소리를 못 버렸다)."""
    print("\n[버림] clear")
    g = FakeGlass([], mic_port=0, cmd_port=0, tail_sec=10, quiet=True).start()
    logs = []
    mr = receiver(g, logs)
    try:
        wait_for(lambda: mr.generation == 1, 3)
        time.sleep(1.0)
        n = mr.clear()
        check(n >= 9600, f"쌓인 {n}표본을 버렸다")
        check(len(mr.pull()) < 3200, "버린 직후에는 거의 없다")
    finally:
        mr.stop()
        g.stop()


def test_late_chunks_dropped():
    """M3 — 도착한 지 lag_limit 초 넘은 소리는 밀린 것이다(메인 루프가 늦었다) — 버리고 센다."""
    print("\n[밀림] 도착 시각 기준")
    g = FakeGlass([], mic_port=0, cmd_port=0, tail_sec=10, quiet=True).start()
    logs = []
    mr = receiver(g, logs, lag_limit=2.0)
    try:
        wait_for(lambda: mr.generation == 1, 3)
        time.sleep(0.5)
        a = mr.pull(now=time.monotonic() + 5.0)
        check(len(a) == 0 and mr.dropped > 0, f"모두 밀린 것으로 보고 버렸다({mr.dropped}표본)")
        check(any("밀려" in l for l in logs), "버린 사실을 로그에 남긴다")
    finally:
        mr.stop()
        g.stop()


def test_once_mode_closes():
    print("\n[리허설] once — 상대가 닫으면 끝")
    g = FakeGlass([], mic_port=0, cmd_port=0, lead_sec=0.3, tail_sec=0.3, quiet=True).start()
    logs = []
    mr = receiver(g, logs, once=True)
    try:
        check(wait_for(lambda: mr.closed, 5), "closed 가 켜진다")
        time.sleep(0.5)
        check(mr.generation == 1, "다시 붙지 않는다")
    finally:
        mr.stop()
        g.stop()


def test_thread_death_is_visible():
    """최종 리뷰 M1 — 수신 스레드가 예외로 죽으면 alive() 가 거짓이고 로그가 남는다(메인 루프가 알아챈다)."""
    print("\n[죽음] 수신 스레드 예외")
    g = FakeGlass([], mic_port=0, cmd_port=0, tail_sec=5, quiet=True).start()
    logs = []
    mr = MicReceiver(lambda: "127.0.0.1", g.mic_port, retry_sec=0.1, log=logs.append)
    mr._read = lambda s: (_ for _ in ()).throw(RuntimeError("시험"))
    mr.start()
    try:
        check(wait_for(lambda: not mr.alive(), 3), "alive() 가 거짓이 된다")
        check(any("죽었다" in l for l in logs), "로그에 남는다")
    finally:
        mr.stop()
        g.stop()


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
    print("✅ 마이크 수신 스레드 검증 통과")
