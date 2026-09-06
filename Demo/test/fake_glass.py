#!/usr/bin/env python3
"""모의 ESP32 — HW 없이 음성비서 전 구간을 돌려 보기 위한 대역품.

실행: ~/env/tts/.venv/bin/python Demo/test/fake_glass.py <wav...>

무엇을 흉내 내나:
    8889  마이크 업링크 — 준 wav 를 16kHz int16LE 로, **PDM DC 오프셋 1400 을 얹어**
          흘려보낸다. 실제 마이크가 그렇게 내보내기 때문이다(2026-08-26 실측).
    8890  명령/스피커 — 펌웨어와 **같은 방식으로** `W`/`P`/`B` 를 파싱하고
          **체크섬을 검증**한다. 받은 소리는 /tmp/fake_glass_out.wav 로 남긴다.

🔴 이 도구가 답하는 것과 아닌 것을 섞지 말 것.
   ✅ 답한다 — 소켓 배선·프로토콜 프레이밍·VAD·호출어 판정·답변 선택·재생 명령
   ❌ 답하지 않는다 — ESP32 마이크 음질 · 실제 스피커 명료도 · 링크 안정성 ·
      카메라와의 동시 가동. 그것들은 실HW 관문이다.
"""
import array
import os
import socket
import struct
import sys
import threading
import time
import wave

RATE = 16000
DC = 1400          # 🔴 PDM 이 함께 내보내는 오프셋(1000~1600 실측)
OUT = "/tmp/fake_glass_out.wav"

_events = []


def log(m):
    print(f"  [glass] {m}", flush=True)


def load_16k(path):
    """wav 를 16kHz 모노 int16 으로 읽는다(정수배 다운샘플만 지원)."""
    with wave.open(path) as w:
        rate, n, ch, width = (w.getframerate(), w.getnframes(),
                              w.getnchannels(), w.getsampwidth())
        raw = w.readframes(n)
    if width != 2:
        raise SystemExit(f"🔴 16비트만 된다 — {path}")
    a = array.array("h")
    a.frombytes(raw)
    if ch == 2:
        a = array.array("h", a[0::2])
    if rate != RATE:
        if rate % RATE:
            raise SystemExit(f"🔴 {rate}Hz 는 16k 의 정수배가 아니다 — {path}")
        a = array.array("h", a[::rate // RATE])
    return a


def mic_server(clips, gap_sec=1.2):
    """접속하면 무음 → 클립 → 무음 … 순으로 실시간 속도로 흘린다."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 8889))
    srv.listen(1)
    c, _ = srv.accept()
    log("마이크 업링크 연결됨 (8889)")
    chunk = 512

    def push(samples):
        for i in range(0, len(samples), chunk):
            part = samples[i:i + chunk]
            c.sendall(array.array("h", [max(-32768, min(32767, v + DC))
                                        for v in part]).tobytes())
            time.sleep(len(part) / RATE)

    try:
        push(array.array("h", [0] * int(RATE * gap_sec)))
        for path in clips:
            a = load_16k(path)
            log(f"흘림 → {os.path.basename(path)} ({len(a)/RATE:.1f}초)")
            push(a)
            push(array.array("h", [0] * int(RATE * gap_sec)))
        push(array.array("h", [0] * int(RATE * 2.0)))
    except OSError as e:
        log(f"업링크 종료: {e}")
    finally:
        try:
            c.close()
        except OSError:
            pass
        srv.close()
        log("업링크 닫음")


def _readline(f):
    return f.readline().decode("utf-8", "replace").strip()


def cmd_server():
    """펌웨어와 같은 방식으로 명령을 파싱한다."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 8890))
    srv.listen(1)
    c, _ = srv.accept()
    log("명령 채널 연결됨 (8890)")
    f = c.makefile("rb")
    held = None
    try:
        while True:
            ch = f.read(1)
            if not ch:
                break
            ch = ch.decode()
            if ch == "B":
                _readline(f)
                _events.append(("chime", time.time()))
                log("🔔 띠링")
            elif ch == "W":
                n, rate = (int(x) for x in _readline(f).split())
                raw = f.read(n * 2)
                got = struct.unpack("<I", f.read(4))[0]
                a = array.array("h")
                a.frombytes(raw)
                want = sum(v & 0xFFFF for v in a) & 0xFFFFFFFF
                ok = want == got
                _events.append(("write", n, rate, ok))
                log(f"적재 n={n} rate={rate} 체크섬 {'ok' if ok else '🔴 불일치'}")
                held = (a, rate)
            elif ch == "P":
                _readline(f)
                if held:
                    a, rate = held
                    with wave.open(OUT, "w") as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(rate)
                        w.writeframes(a.tobytes())
                    _events.append(("play", len(a) / rate))
                    log(f"▶ 재생 {len(a)/rate:.1f}초 → {OUT}")
            else:
                _readline(f)
    except (OSError, ValueError, struct.error) as e:
        log(f"명령 채널 종료: {e}")
    finally:
        try:
            c.close()
        except OSError:
            pass
        srv.close()


def main():
    clips = sys.argv[1:]
    if not clips:
        raise SystemExit(__doc__)
    t1 = threading.Thread(target=cmd_server, daemon=True)
    t2 = threading.Thread(target=mic_server, args=(clips,), daemon=True)
    t1.start()
    t2.start()
    t2.join()
    time.sleep(1.0)
    print("\n=== 모의 글라스가 받은 것 ===")
    for e in _events:
        print("  ", e)
    if not _events:
        print("   (없음)")


if __name__ == "__main__":
    main()
