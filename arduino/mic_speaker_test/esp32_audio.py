#!/usr/bin/env python3
"""파이 ↔ ESP32 오디오 다리 — 펌웨어 mic_speaker_test 의 짝.

🔴 이 파일과 펌웨어는 프로토콜을 공유한다. 한쪽만 고치면 조용히 어긋난다.
설계 정본 = docs/superpowers/specs/2026-09-01-글라스-오디오다리-design.md

  play <wav>            wav 를 ESP32 로 보내 FQ 스피커로 재생
  rec <초> <out.wav>    ESP32 로 녹음시키고 회수해 wav 로 저장
  tone <Hz> <초> <wav>  검증용 순음 wav 생성 (ESP32 불필요)
"""
import argparse
import os
import socket
import struct
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Demo"))
from serial_ports import ESP32_S3, describe, resolve  # noqa: E402


class Link:
    """전송 계층 — 펌웨어의 Stream* 에 대응한다(설계 §4.1).

    유선(SerialLink)과 무선(TcpLink)이 같은 얼굴을 하므로, 아래 프로토콜
    코드는 어느 쪽인지 모른 채 동작한다.
    """

    def write(self, b):
        raise NotImplementedError

    def read(self, n):
        raise NotImplementedError

    def readline(self):
        raise NotImplementedError

    def close(self):
        pass


class SerialLink(Link):
    def __init__(self, path, baud=115200, timeout=15):
        import serial

        self.s = serial.Serial(path, baud, timeout=timeout)
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def write(self, b):
        self.s.write(b)
        self.s.flush()

    def read(self, n):
        out = b""
        while len(out) < n:
            chunk = self.s.read(n - len(out))
            if not chunk:
                raise IOError(f"읽기 중단 — {len(out)}/{n} 바이트만 받았다")
            out += chunk
        return out

    def readline(self):
        return self.s.readline().decode("utf-8", "replace").strip()

    def close(self):
        self.s.close()


class TcpLink(Link):
    """무선 이행용. 🔴 아직 펌웨어 쪽 WiFiClient 결선이 없다(설계 §7)."""

    def __init__(self, host, port, timeout=15):
        self.s = socket.create_connection((host, port), timeout)
        self.s.settimeout(timeout)
        self.f = self.s.makefile("rb")

    def write(self, b):
        self.s.sendall(b)

    def read(self, n):
        out = self.f.read(n)
        if out is None or len(out) < n:
            raise IOError(f"읽기 중단 — {len(out or b'')}/{n} 바이트만 받았다")
        return out

    def readline(self):
        return self.f.readline().decode("utf-8", "replace").strip()

    def close(self):
        self.s.close()


def checksum(samples):
    """펌웨어의 checksum() 과 같아야 한다 — uint16 으로 본 값의 32비트 합."""
    return sum(s & 0xFFFF for s in samples) & 0xFFFFFFFF


def read_wav(path):
    with wave.open(path) as w:
        if w.getnchannels() != 1:
            raise SystemExit(f"🔴 모노만 된다 — {path} 는 {w.getnchannels()}채널")
        if w.getsampwidth() != 2:
            raise SystemExit(f"🔴 16비트만 된다 — {path} 는 {w.getsampwidth() * 8}비트")
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    return list(struct.unpack(f"<{len(raw) // 2}h", raw)), rate


def write_wav(path, samples, rate):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def wait_for(link, marker, timeout=30):
    """marker 로 시작하는 줄이 나올 때까지 로그를 흘려보며 기다린다."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        line = link.readline()
        if not line:
            continue
        print("  " + line)
        if line.startswith(marker):
            return line
        if line.startswith("[FAIL]"):
            raise SystemExit(f"🔴 ESP32 가 실패를 보고했다: {line}")
    raise SystemExit(f"🔴 '{marker}' 응답이 {timeout}초 안에 안 왔다")


def cmd_play(link, path):
    samples, rate = read_wav(path)
    cs = checksum(samples)
    print(f"▶ 보냄: {os.path.basename(path)} — {len(samples)}샘플 · {rate}Hz "
          f"· {len(samples) / rate:.2f}초 · sum={cs}")
    link.write(f"W {len(samples)} {rate}\n".encode())
    link.write(struct.pack(f"<{len(samples)}h", *samples))
    link.write(struct.pack("<I", cs))
    wait_for(link, "[적재]")
    link.write(b"P\n")
    wait_for(link, "[재생 완료]", timeout=60)
    print("✅ 재생 완료")


def cmd_rec(link, sec, out):
    print(f"▶ {sec}초 녹음 — 신호음 뒤에 말하세요")
    link.write(f"R {sec}\n".encode())
    wait_for(link, "[녹음 완료]", timeout=sec + 30)
    link.write(b"D\n")
    header = ""
    while not header.startswith("D "):
        header = link.readline()
        if not header:
            raise SystemExit("🔴 덤프 헤더가 안 왔다")
        if header.startswith("[FAIL]"):
            raise SystemExit(f"🔴 {header}")
    _, n, rate, want = header.split()
    n, rate, want = int(n), int(rate), int(want)
    raw = link.read(n * 2)
    samples = list(struct.unpack(f"<{n}h", raw))
    got = checksum(samples)
    if got != want:
        # 🔴 여기서 멈춘다 — 잘린 녹음으로 STT 를 재면 마이크를 오해한다.
        raise SystemExit(f"🔴 체크섬 불일치 — ESP32 {want} · 파이 {got}. 측정하지 말 것.")
    write_wav(out, samples, rate)
    peak = max(abs(s) for s in samples) if samples else 0
    rms = int((sum(s * s for s in samples) / len(samples)) ** 0.5) if samples else 0
    print(f"✅ {out} — {n}샘플 · {rate}Hz · {n / rate:.2f}초 "
          f"· RMS {rms} · peak {peak} · 체크섬 일치")


def cmd_tone(hz, sec, out, rate=16000):
    import math

    n = int(rate * sec)
    samples = [int(math.sin(2 * math.pi * hz * i / rate) * 12000) for i in range(n)]
    write_wav(out, samples, rate)
    print(f"✅ {out} — {hz}Hz 순음 {sec}초 · {rate}Hz")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--port", help="시리얼 경로 (기본: USB 신원으로 자동 탐지)")
    ap.add_argument("--tcp", help="무선용 host:port (미구현 — 설계 §7)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play")
    p.add_argument("wav")
    r = sub.add_parser("rec")
    r.add_argument("sec", type=int)
    r.add_argument("out")
    t = sub.add_parser("tone")
    t.add_argument("hz", type=int)
    t.add_argument("sec", type=float)
    t.add_argument("out")
    a = ap.parse_args()

    if a.cmd == "tone":
        cmd_tone(a.hz, a.sec, a.out)
        return

    if a.tcp:
        host, port = a.tcp.split(":")
        link = TcpLink(host, int(port))
    else:
        path = a.port or resolve(*ESP32_S3)
        if not path:
            print("🔴 ESP32 를 못 찾았다. 붙어 있는 장치:", file=sys.stderr)
            for line in describe() or ["  (없음)"]:
                print("  " + line, file=sys.stderr)
            sys.exit(1)
        print(f"🔌 {path}")
        link = SerialLink(path)

    try:
        if a.cmd == "play":
            cmd_play(link, a.wav)
        else:
            cmd_rec(link, a.sec, a.out)
    finally:
        link.close()


if __name__ == "__main__":
    main()
