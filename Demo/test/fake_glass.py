#!/usr/bin/env python3
"""모의 ESP32 — HW 없이 음성비서 전 구간을 돌려 보기 위한 대역품.

실행: ~/env/tts/.venv/bin/python Demo/test/fake_glass.py [옵션] <wav...>
      옵션: --burst 초 · --stall 초 · --vanish · --out 경로 · --mic-port · --cmd-port
            · --play-speed 배율 · --noise-rms 크기
시험: `from fake_glass import FakeGlass` — 포트 0 이면 빈 포트를 고른다(selftest 가 쓴다).

무엇을 흉내 내나 (펌웨어 `arduino/glass_voice/glass_voice.ino` 와 같게 · 설계 2026-10-03 §4.8):
    8889  마이크 업링크 — 무음엔 실제 수준의 잡음, 클립은 제 평균을 빼고 **PDM DC 오프셋 1400**을
          얹어 512샘플씩 실시간 속도로 흘린다(2026-08-26 실측). 끊고 다시 붙으면 받아 준다.
          쓰기가 `write_block_sec` 넘게 막히면 펌웨어처럼 끊는다(c.write 실패 → c.stop()).
    8890  명령/스피커 — 펌웨어와 **같은 응답 줄**:
          W → `[준비] …` · 2048바이트마다 `[다음]` · `[적재] … ok` / `[FAIL] …`
          P → `[재생] …` · (재생 시간) · `[재생 완료]`   B → 띠링(응답 없음)   1~5 → 음량(응답 없음)
          S → 재생 중이면 `[재생 중단]`(2단계 펌웨어 · 설계 2026-10-04 §4.3) · 아니면 그냥 지나감
              (`supports_stop=False` = 옛 펌웨어 — 재생을 끝까지 하고 S 는 뒤에 그냥 지나감)
          새 손님이 오면 옛 손님을 끊고 갈아탄다(펌웨어 규칙).

🔴 범위 밖 `W`(샘플 수 1~240,000 · 레이트 8,000~24,000)는 `[FAIL]` 뒤 **본문을 읽어 버린다** —
   2단계 펌웨어 동작이다. 현행 펌웨어는 안 읽어 남은 바이트가 명령으로 실행된다(설계 P4).
   시험은 파이가 그런 크기를 **아예 안 보내는지**를 `("oversize", n, rate)` 사건으로 본다.

🔴 이 도구가 답하는 것과 아닌 것을 섞지 말 것.
   ✅ 답한다 — 소켓 배선·프로토콜·VAD·호출어 판정·답변 선택·재생 확인·재접속
   ❌ 답하지 않는다 — ESP32 마이크 음질 · 실제 스피커 명료도 · 무선 링크 · 카메라와의 동시 가동
"""
import argparse
import array
import os
import random
import select
import socket
import struct
import tempfile
import threading
import time
import wave

RATE = 16000
DC = 1400            # 🔴 PDM 이 함께 내보내는 오프셋(1000~1600 실측)
CHUNK = 512          # 펌웨어 micUplinkTask 의 조각
MAX_SAMPLE = 240000  # 펌웨어 MAX_SAMPLE(MAX_SEC 10 × MAX_RATE 24000)
RATE_MIN, RATE_MAX = 8000, 24000
W_CHUNK = 2048       # 펌웨어 cmdWrite 흐름 제어 조각


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


def _listen(host, port):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)
    srv.settimeout(0.2)
    return srv


class FakeGlass:
    """펌웨어 glass_voice 의 8889·8890 흉내. `start()` 뒤 배경 스레드로 돈다."""

    def __init__(self, clips, mic_port=8889, cmd_port=8890, host="127.0.0.1",
                 lead_sec=1.2, gap_sec=1.2, tail_sec=2.0, burst_sec=0.0,
                 stall_sec=0.0, vanish=False, noise_rms=150.0, play_speed=1.0,
                 write_block_sec=10.0, out=None, seed=1, quiet=False, supports_stop=True):
        self.clips = [load_16k(c) if isinstance(c, str) else array.array("h", c) for c in clips]
        self.lead_sec, self.gap_sec, self.tail_sec = lead_sec, gap_sec, tail_sec
        self.burst_sec, self.stall_sec, self.vanish = burst_sec, stall_sec, vanish
        self.noise_rms, self.play_speed = noise_rms, play_speed
        self.write_block_sec, self.out = write_block_sec, out
        self.supports_stop = supports_stop
        self._rng = random.Random(seed)
        self._log = (lambda m: None) if quiet else log
        self.events = []
        self.mic_done = threading.Event()
        self._stop = threading.Event()
        self._mic_srv = _listen(host, mic_port)
        self._cmd_srv = _listen(host, cmd_port)
        self.mic_port = self._mic_srv.getsockname()[1]
        self.cmd_port = self._cmd_srv.getsockname()[1]
        self._cmd_conn = None
        self._abandoned = []          # 반열림으로 버린 연결 — 🔴 닫지 않아야 FIN 이 안 간다

    def start(self):
        for fn in (self._mic_loop, self._cmd_accept_loop):
            threading.Thread(target=fn, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        for s in [self._mic_srv, self._cmd_srv, self._cmd_conn] + self._abandoned:
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass

    def count(self, kind):
        return sum(1 for e in self.events if e[0] == kind)

    def _event(self, *e):
        self.events.append(e)

    def _accept(self, srv):
        while not self._stop.is_set():
            try:
                c, _ = srv.accept()
                return c
            except socket.timeout:
                continue
            except OSError:
                return None
        return None

    # ── 8889 마이크 ───────────────────────────────────────────────────────
    def _noise(self, n):
        g = self._rng.gauss
        return [int(g(0.0, self.noise_rms)) for _ in range(n)] if self.noise_rms > 0 else [0] * n

    @staticmethod
    def _clip(a):
        """클립 제 평균을 뺀다 — DC 가 이미 실린 녹음에 DC 를 또 얹지 않게(R3 도구 한계)."""
        if not len(a):
            return []
        m = sum(a) / len(a)
        return [int(v - m) for v in a]

    def _script(self):
        """흘릴 순서 — (이름, 표본들). 무음 = 잡음만."""
        parts = [("무음", self._noise(int(RATE * self.lead_sec)))]
        for i, a in enumerate(self.clips):
            parts.append((f"클립{i + 1}", self._clip(a)))
            parts.append(("무음", self._noise(int(RATE * self.gap_sec))))
        parts.append(("꼬리", self._noise(int(RATE * self.tail_sec))))
        return parts

    def _push(self, c, samples, realtime=True):
        """DC 를 얹어 보낸다. 끊기거나 막히면 False."""
        for i in range(0, len(samples), CHUNK):
            if self._stop.is_set():
                return False
            part = samples[i:i + CHUNK]
            body = array.array("h", [max(-32768, min(32767, v + DC)) for v in part]).tobytes()
            try:
                c.sendall(body)
            except socket.timeout:
                self._log(f"업링크 끊김 — 쓰기가 {self.write_block_sec:.1f}초 막혔다(펌웨어처럼 끊는다)")
                self._event("mic_drop", "막힘")
                return False
            except OSError as e:
                self._log(f"업링크 종료: {e}")
                return False
            if realtime:
                time.sleep(len(part) / RATE)
        return True

    def _mic_loop(self):
        script = self._script()
        pos = n_conn = 0
        burst_done = first_clip_done = False
        while not self._stop.is_set():
            c = self._accept(self._mic_srv)
            if c is None:
                return
            n_conn += 1
            self._event("mic_conn", n_conn)
            self._log(f"마이크 업링크 연결됨 (8889 · {n_conn}번째)")
            # 🔑 lwIP 송신 버퍼 근사(R3) — 파이가 안 읽으면 막힘이 빨리 드러난다
            c.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 5760)
            c.settimeout(self.write_block_sec)
            keep_open = False
            if pos >= len(script):                      # 다 흘린 뒤 다시 붙은 손님 — 꼬리 잡음만
                self._push(c, self._noise(int(RATE * self.tail_sec)))
            while pos < len(script):
                name, samples = script[pos]
                if pos == 1 and self.burst_sec > 0 and not burst_done and self.clips:
                    burst_done = True
                    self._log(f"⏸ {self.burst_sec:.0f}초간 막혔다가 한꺼번에 터뜨린다(최신 우선 유발)")
                    self._stop.wait(self.burst_sec)
                    # 🔴 밀린 것이 **말소리**여야 한다 — 무음이면 데몬의 「무음 정리」가 먼저 걸려
                    #    최신 우선 분기를 못 밟는다(2026-09-06 확인).
                    src = self._clip(self.clips[0])
                    need = int(RATE * self.burst_sec)
                    if not self._push(c, (src * (need // len(src) + 1))[:need], realtime=False):
                        break
                if not self._push(c, samples):
                    break                               # 끊김 — 같은 조각부터 다음 손님에게
                pos += 1
                if name.startswith("클립") and not first_clip_done:
                    first_clip_done = True
                    if self.stall_sec > 0:
                        self._log(f"⏸ {self.stall_sec:.1f}초 동안 아무것도 안 보낸다(정체 · 연결 유지)")
                        self._event("stall", self.stall_sec)
                        self._stop.wait(self.stall_sec)
                    if self.vanish:
                        self._log("👻 이 연결을 닫지 않고 버린다(반열림) — 새 손님을 기다린다")
                        self._event("vanish")
                        self._abandoned.append(c)
                        keep_open = True
                        break
            if not keep_open:
                try:
                    c.close()
                except OSError:
                    pass
            if pos >= len(script) and not self.mic_done.is_set():
                self._log("업링크 닫음(흘릴 것을 다 흘렸다)")
                self.mic_done.set()

    # ── 8890 명령 ─────────────────────────────────────────────────────────
    def _cmd_accept_loop(self):
        n = 0
        while not self._stop.is_set():
            c = self._accept(self._cmd_srv)
            if c is None:
                return
            n += 1
            old, self._cmd_conn = self._cmd_conn, c
            if old is not None:                         # 🔑 펌웨어처럼 새 손님으로 갈아탄다
                try:
                    old.shutdown(socket.SHUT_RDWR)
                    old.close()
                except OSError:
                    pass
            self._event("cmd_conn", n)
            self._log(f"명령 채널 연결됨 (8890 · {n}번째)")
            threading.Thread(target=self._serve_cmd, args=(c,), daemon=True).start()

    def _serve_cmd(self, c):
        f = c.makefile("rb")
        held = None

        def say(line):
            try:
                c.sendall((line + "\n").encode())
            except OSError:
                pass

        try:
            while not self._stop.is_set():
                ch = f.read(1)
                if not ch:
                    break
                if ch == b"B":
                    f.readline()
                    self._event("chime", time.time())
                    self._log("🔔 띠링")
                    time.sleep(0.43 * self.play_speed)
                elif ch == b"W":
                    held = self._cmd_write(f, say)
                elif ch == b"P":
                    f.readline()
                    self._cmd_play(held, say, c, f)
                elif ch == b"S":
                    self._event("stop_idle")            # 재생 중이 아닐 때의 S — 펌웨어처럼 그냥 지나간다
                elif ch in b"12345":
                    self._event("volume", int(ch))
                # 그 밖의 글자는 펌웨어처럼 그냥 넘긴다(줄을 읽지 않는다)
        except (OSError, ValueError) as e:
            self._log(f"명령 채널 종료: {e}")
        finally:
            try:
                c.close()
            except OSError:
                pass

    def _cmd_write(self, f, say):
        try:
            n, rate = (int(x) for x in f.readline().decode("utf-8", "replace").split())
        except ValueError:
            say("[FAIL] W 인자를 못 읽었다. 형식: W <샘플수> <레이트>")
            return None
        bad = None
        if n <= 0 or n > MAX_SAMPLE:
            bad = f"[FAIL] 샘플수 {n} — 1~{MAX_SAMPLE} 범위를 벗어났다."
        elif rate < RATE_MIN or rate > RATE_MAX:
            bad = f"[FAIL] 레이트 {rate} — {RATE_MIN}~{RATE_MAX} 범위를 벗어났다."
        if bad:
            say(bad)
            self._event("oversize", n, rate)
            f.read(max(0, n) * 2 + 4)                  # 🔴 2단계 펌웨어처럼 본문을 버린다(머리말)
            return None
        total = n * 2
        say(f"[준비] chunk={W_CHUNK} total={total}")
        raw = b""
        while len(raw) < total:
            part = f.read(min(W_CHUNK, total - len(raw)))
            if not part:
                say(f"[FAIL] 페이로드가 도중에 끊겼다 — {len(raw)}/{total} 바이트")
                return None
            raw += part
            say("[다음]")
        cs = f.read(4)
        if len(cs) < 4:
            say("[FAIL] 체크섬 4바이트가 안 왔다.")
            return None
        sent = struct.unpack("<I", cs)[0]
        a = array.array("h")
        a.frombytes(raw)
        got = sum(v & 0xFFFF for v in a) & 0xFFFFFFFF
        ok = sent == got
        self._event("write", n, rate, ok)
        if not ok:
            say(f"[FAIL] 체크섬 불일치 — 보낸 값 {sent} · 받은 값 {got}")
            return None
        say(f"[적재] n={n} rate={rate} sum={got} ok")
        self._log(f"적재 n={n} rate={rate} 체크섬 ok")
        return (a, rate)

    def _cmd_play(self, held, say, c=None, f=None):
        if not held:
            say("[재생] 담긴 것이 없다. 먼저 r 또는 W 를 쓰라.")
            return
        a, rate = held
        sec = len(a) / rate
        say(f"[재생] {len(a)}샘플 · {rate}Hz · 목표 진폭 13000 · 배율 1.0배")
        if self.out:
            with wave.open(self.out, "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(a.tobytes())
        end = time.time() + sec * self.play_speed
        while time.time() < end:
            if self.supports_stop and c is not None and self._stop_requested(c, f):
                self._event("stop", round(sec, 2))
                self._log(f"■ 재생 중단 ({sec:.1f}초 중)")
                say("[재생 중단]")
                return
            time.sleep(0.01)
        self._event("play", round(sec, 2))
        self._log(f"▶ 재생 {sec:.1f}초" + (f" → {self.out}" if self.out else ""))
        say("[재생 완료]")

    @staticmethod
    def _stop_requested(c, f):
        """다음 글자가 S 면 읽고 True — 펌웨어 play() 의 peek 흉내(설계 2026-10-04 §4.3).

        ⚠️ 이미 버퍼에 들어온 글자는 소켓이 「읽기 가능」으로 안 보일 수 있다 — 시험은 S 를 따로 보낸다.
        """
        r, _, _ = select.select([c], [], [], 0)
        if not r:
            return False
        if f.peek(1)[:1] == b"S":
            f.read(1)
            return True
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+", help="흘릴 wav(16비트 · 16kHz 정수배)")
    ap.add_argument("--burst", type=float, default=0.0, help="첫 클립 앞에서 이만큼 막혔다가 한꺼번에 터뜨린다")
    ap.add_argument("--stall", type=float, default=0.0, help="첫 클립 뒤 이만큼 아무것도 안 보낸다(연결 유지)")
    ap.add_argument("--vanish", action="store_true", help="첫 클립 뒤 연결을 닫지 않고 버린다(반열림)")
    ap.add_argument("--out", default=os.path.join(tempfile.gettempdir(), f"fake_glass_out_{os.getpid()}.wav"),
                    help="재생한 소리를 남길 곳(실행마다 다른 이름 — 공유 경로를 덮어쓰지 않게)")
    ap.add_argument("--mic-port", type=int, default=8889)
    ap.add_argument("--cmd-port", type=int, default=8890)
    ap.add_argument("--play-speed", type=float, default=1.0, help="재생 대기 배율(1 = 실제 길이)")
    ap.add_argument("--noise-rms", type=float, default=150.0, help="무음 구간 잡음 크기(0 = 종전처럼 무음)")
    ap.add_argument("--no-stop", action="store_true", help="옛 펌웨어 흉내 — 재생 중 S(멈춤)를 무시한다")
    a = ap.parse_args()
    g = FakeGlass(a.clips, mic_port=a.mic_port, cmd_port=a.cmd_port, burst_sec=a.burst,
                  stall_sec=a.stall, vanish=a.vanish, out=a.out, play_speed=a.play_speed,
                  noise_rms=a.noise_rms, supports_stop=not a.no_stop).start()
    try:
        g.mic_done.wait()
    except KeyboardInterrupt:
        pass
    time.sleep(1.0)
    g.stop()
    print("\n=== 모의 글라스가 받은 것 ===")
    for e in g.events:
        print("  ", e)
    if not g.events:
        print("   (없음)")


if __name__ == "__main__":
    main()
