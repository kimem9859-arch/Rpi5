"""모의 글라스가 펌웨어 glass_voice 처럼 응답하는지 — 설계 2026-10-03 §4.8 (R2 I6 · R3 도구 한계).

실행: python3 Demo/selftest/test_fake_glass.py
"""
import array
import math
import os
import socket
import struct
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

from fake_glass import FakeGlass  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def tone(sec, amp=4000):
    return [int(amp * math.sin(i / 5)) for i in range(int(16000 * sec))]


def frame(samples, rate, bad_sum=False):
    a = array.array("h", samples)
    chk = (sum(v & 0xFFFF for v in a) + (1 if bad_sum else 0)) & 0xFFFFFFFF
    return f"W {len(a)} {rate}\n".encode() + a.tobytes() + struct.pack("<I", chk) + b"P\n"


def read_until(sock, marker, timeout=3.0):
    """`marker` 가 든 줄이 올 때까지 받은 줄들."""
    sock.settimeout(0.2)
    buf, out = b"", []
    end = time.time() + timeout
    while time.time() < end:
        try:
            b = sock.recv(4096)
        except socket.timeout:
            continue
        if not b:
            break
        buf += b
        while b"\n" in buf:
            line, _, buf = buf.partition(b"\n")
            out.append(line.decode("utf-8", "replace"))
            if marker in out[-1]:
                return out
    return out


def test_cmd_protocol():
    """W·P 응답 줄이 펌웨어와 같다 · 범위 밖은 FAIL 뒤 본문을 버려 흐름이 안 깨진다 · 체크섬 불일치는 FAIL."""
    print("\n[명령 채널] 펌웨어 응답 줄")
    g = FakeGlass([tone(0.2)], mic_port=0, cmd_port=0, play_speed=0.01, quiet=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", g.cmd_port), 2)
        s.sendall(frame(tone(0.2), 16000))
        got = read_until(s, "재생 완료")
        check(bool(got) and got[0].startswith("[준비]"), f"첫 줄 [준비] — {got[:1]}")
        check(got.count("[다음]") == math.ceil(3200 * 2 / 2048), f"2048바이트마다 [다음] — {got.count('[다음]')}개")
        check(any(l.startswith("[적재]") and l.endswith("ok") for l in got), "[적재] … ok")
        check(bool(got) and got[-1] == "[재생 완료]", "끝 줄 [재생 완료]")
        s.sendall(b"W 240001 16000\n" + b"\x00" * (240001 * 2 + 4) + b"P\n")
        got = read_until(s, "담긴 것이 없다")
        check(any("[FAIL] 샘플수 240001" in l for l in got), f"한도 초과 → [FAIL] — {got}")
        check(g.count("oversize") == 1, "한도 초과를 사건으로 남긴다")
        s.sendall(frame(tone(0.1), 16000))
        check(read_until(s, "재생 완료")[-1:] == ["[재생 완료]"], "🔑 FAIL 뒤에도 흐름이 맞다(본문을 버렸다)")
        s.sendall(frame(tone(0.1), 16000, bad_sum=True))
        check(any("체크섬 불일치" in l for l in read_until(s, "담긴 것이 없다")), "체크섬 불일치 → [FAIL]")
        s.sendall(b"B\n5\n")
        time.sleep(0.3)
        check(g.count("chime") == 1 and g.count("volume") == 1, "띠링·음량은 응답 없이 사건만")
        s2 = socket.create_connection(("127.0.0.1", g.cmd_port), 2)
        s.settimeout(2.0)
        try:
            old_closed = s.recv(16) == b""
        except OSError:
            old_closed = True
        check(old_closed, "새 손님이 오면 옛 손님을 끊는다(펌웨어 규칙)")
        s2.sendall(frame(tone(0.1), 16000))
        check(read_until(s2, "재생 완료")[-1:] == ["[재생 완료]"], "새 손님과 그대로 주고받는다")
    finally:
        g.stop()


def test_mic_noise_and_dc():
    """무음 = DC 1400 + 실제 수준의 잡음(종전 0 이라 VAD 가 절대 하한으로만 돌았다)."""
    print("\n[마이크] DC·잡음")
    g = FakeGlass([], mic_port=0, cmd_port=0, lead_sec=2.0, tail_sec=0.5, quiet=True).start()
    try:
        m = socket.create_connection(("127.0.0.1", g.mic_port), 2)
        m.settimeout(2.0)
        raw, end = b"", time.time() + 0.6
        while time.time() < end:
            raw += m.recv(65536)
        a = array.array("h")
        a.frombytes(raw[:len(raw) // 2 * 2])
        mean = sum(a) / len(a)
        r = math.sqrt(sum((v - mean) ** 2 for v in a) / len(a))
        check(abs(mean - 1400) < 60, f"DC ≈ 1400 — {mean:.0f}")
        check(80 < r < 250, f"잡음 RMS ≈ 150 — {r:.0f}")
    finally:
        g.stop()


def test_mic_vanish_then_new_client():
    """반열림 — 첫 클립 뒤 옛 연결은 닫지 않고 침묵(FIN 없음) · 새 손님에게 나머지를 흘린다."""
    print("\n[마이크] 반열림(--vanish)")
    g = FakeGlass([tone(0.3), tone(0.3)], mic_port=0, cmd_port=0, lead_sec=0.2, gap_sec=0.2,
                  tail_sec=1.0, vanish=True, quiet=True).start()
    try:
        m1 = socket.create_connection(("127.0.0.1", g.mic_port), 2)
        m1.settimeout(0.3)
        closed = False
        last, end = time.time(), time.time() + 2.0
        while time.time() < end:
            try:
                b = m1.recv(65536)
            except socket.timeout:
                continue
            if not b:
                closed = True
                break
            last = time.time()
        check(not closed, "옛 연결은 닫히지 않는다(FIN 없음)")
        check(time.time() - last >= 1.0, "첫 클립 뒤 옛 연결로는 아무것도 안 온다")
        check(g.count("vanish") == 1, "반열림 사건")
        m2 = socket.create_connection(("127.0.0.1", g.mic_port), 2)
        m2.settimeout(1.0)
        check(len(m2.recv(65536)) > 0, "새 손님은 받는다")
        check(g.count("mic_conn") == 2, "두 번째 연결")
    finally:
        g.stop()


def test_mic_write_block_drops():
    """쓰기가 막히면 펌웨어처럼 끊는다(c.write 실패 → c.stop) — 파이가 안 읽을 때 일어나는 일(R3 C1)."""
    print("\n[마이크] 쓰기 막힘 → 끊음")
    g = FakeGlass([], mic_port=0, cmd_port=0, lead_sec=30.0, write_block_sec=0.5, quiet=True).start()
    try:
        m = socket.socket()
        m.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2048)
        m.connect(("127.0.0.1", g.mic_port))
        end = time.time() + 5.0
        while time.time() < end and g.count("mic_drop") == 0:
            time.sleep(0.1)
        check(g.count("mic_drop") == 1, "안 읽는 손님은 끊긴다")
        m.close()
    finally:
        g.stop()



def test_fake_glass_stop():
    """설계 2026-10-04 §4.3 — 새 펌웨어 흉내: 재생 중 S → [재생 중단] · 다음 명령은 그대로."""
    print("\n[명령 채널] 멈춤 S")
    g = FakeGlass([tone(0.2)], mic_port=0, cmd_port=0, play_speed=1.0, quiet=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", g.cmd_port), 2)
        s.sendall(frame(tone(2.0), 16000))
        time.sleep(0.6)
        t0 = time.time()
        s.sendall(b"S")
        got = read_until(s, "재생 중단")
        check(bool(got) and got[-1] == "[재생 중단]" and time.time() - t0 < 0.5, f"S → 곧바로 중단 — {got[-2:]}")
        check(g.count("stop") == 1 and g.count("play") == 0, "중단 사건 · 재생 완료 사건 없음")
        s.sendall(frame(tone(0.1), 16000))
        check(read_until(s, "재생 완료")[-1:] == ["[재생 완료]"], "다음 재생은 그대로")
    finally:
        g.stop()


def test_fake_glass_old_firmware_ignores_stop():
    """Review Focus 2 — 옛 펌웨어(supports_stop=False): 재생 중 S 는 끝난 뒤 한 글자 명령으로 읽혀 무시된다."""
    print("\n[명령 채널] 옛 펌웨어는 멈춤 무시")
    g = FakeGlass([tone(0.2)], mic_port=0, cmd_port=0, play_speed=1.0, quiet=True,
                  supports_stop=False).start()
    try:
        s = socket.create_connection(("127.0.0.1", g.cmd_port), 2)
        s.sendall(frame(tone(0.8), 16000))
        time.sleep(0.3)
        s.sendall(b"S")
        got = read_until(s, "재생 완료")
        check(got[-1:] == ["[재생 완료]"] and "[재생 중단]" not in got, "끝까지 재생")
        time.sleep(0.2)
        check(g.count("stop_idle") == 1, "S 는 재생 뒤 그냥 지나간다")
    finally:
        g.stop()


def test_fake_glass_stop_already_buffered():
    """최종 리뷰 minor — S 가 재생 명령과 한 덩어리로 와서 이미 읽기 버퍼에 있어도 멈춘다(펌웨어 peek 와 같게)."""
    print("\n[명령 채널] 버퍼에 든 S")
    g = FakeGlass([tone(0.2)], mic_port=0, cmd_port=0, play_speed=1.0, quiet=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", g.cmd_port), 2)
        s.sendall(frame(tone(2.0), 16000) + b"S")
        got = read_until(s, "중단", timeout=1.5)
        check("[재생 중단]" in got and g.count("play") == 0, f"곧바로 중단 — {got[-3:]}")
    finally:
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
    print("✅ 모의 글라스 검증 통과")
