"""관객 소리(TV) — 안경에서 나는 소리를 TV 스피커로도 낸다(상위 specs/2026-10-21-관객소리TV-design.md).

🔑 안경으로 가는 소리는 모두 음성비서 `Speaker` 를 지난다 — 거기에 이 「거울」을 붙여 같은 소리를 TV 로 흘린다.
   이 파일 = 소리 재료(프레임 풀기 · 크기 맞춤 · 레이트 바꾸기 · 띠링)와 TV 통로(`AudienceSpeaker`).
🔴 거울은 안경 쪽을 절대 흔들지 않는다 — 여기 실패는 여기서 끝난다(설계 4장 8).
"""
import fcntl
import os
import struct
import subprocess
import sys
import threading
import time

import numpy as np

import config

_VOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice")


# ── 소리 재료(순수 함수) ─────────────────────────────────────────────────
def parse_frame(payload):
    """안경 전송 프레임(「W n rate\\n」 + int16LE n개 + uint32LE 체크섬 + 「P\\n」 — `voice_assistant.wav_payload` ·
    `voice_tts.frame`) → `(샘플 int16 배열, 레이트)`. 모양 · 체크섬이 틀리면 None(소리 프레임이 아님)."""
    if not payload or not payload.startswith(b"W "):
        return None
    head, _, rest = payload.partition(b"\n")
    try:
        _, n, rate = head.split()
        n, rate = int(n), int(rate)
    except ValueError:
        return None
    if n < 0 or rate <= 0 or len(rest) != 2 * n + 6 or not rest.endswith(b"P\n"):
        return None
    pcm = np.frombuffer(rest[:2 * n], dtype="<i2")
    (chk,) = struct.unpack("<I", rest[2 * n:2 * n + 4])
    if int((pcm.astype(np.int64) & 0xFFFF).sum()) & 0xFFFFFFFF != chk:
        return None
    return pcm.astype(np.int16), rate


def normalize(pcm, peak):
    """최고 진폭을 `peak` 로 — 안경 펌웨어 play() 가 소리마다 목표 진폭으로 맞추는 것과 같은 방식. 무음은 그대로."""
    a = np.asarray(pcm)
    m = int(np.abs(a.astype(np.int32)).max()) if a.size else 0
    if m == 0:
        return a.astype(np.int16)
    return np.clip(np.round(a.astype(np.float64) * (peak / m)), -32768, 32767).astype(np.int16)


def resample(pcm, src, dst):
    """레이트를 바꾼다(선형 보간 · int16) — 말소리 · 띠링에는 충분하다."""
    a = np.asarray(pcm, dtype=np.int16)
    if src == dst or a.size == 0:
        return a.copy()
    n_out = int(round(a.size * dst / src))
    x = np.arange(n_out) * (src / dst)
    return np.round(np.interp(x, np.arange(a.size), a.astype(np.float64))).astype(np.int16)


def chime_pcm(kind, rate, peak):
    """띠링("open") · 닫힘음("close") — 안경 펌웨어와 같은 모양(`voice/make_guide.chime` 재사용 · 그 값은
    selftest 가 펌웨어 소스와 대조한다). 모르는 종류 · 못 만들면 None."""
    try:
        if _VOICE_DIR not in sys.path:
            sys.path.insert(0, _VOICE_DIR)
        import make_guide as mg
        segs = {"open": mg.CHIME_SEGS, "close": mg.CLOSE_SEGS}.get(kind)
        if segs is None:
            return None
        return np.clip(np.round(mg.chime(rate, peak, segs)), -32768, 32767).astype(np.int16)
    except Exception:                           # noqa: BLE001 — 띠링만 빠진다(설계 4장 5)
        return None


# ── TV 통로 ──────────────────────────────────────────────────────────────
class AudienceSpeaker:
    """계속 열어 둔 재생기(`pw-cat` · PipeWire 기본 출력) 하나로 TV 에 소리를 흘린다(설계 4장 6).

    🔑 쉴 때도 무음을 흘린다 — 소리마다 재생기를 띄우면 시작이 늦고, HDMI 는 쉬다가 다시 열릴 때 TV 가 앞소리를
       잘라 먹는다. 1024샘플씩 넣되 실제 시간보다 AHEAD_MAX_SEC 넘게 앞서 넣지 않는다 → 쌓인 소리가 그만큼뿐이라
       멈춤이 바로 듣는다. ⚠️ 관(파이프) 크기는 줄여 봐야 페이지 크기까지다(파이5 커널 = 16KB ≈ 0.17초) — 상한은 이 규칙이 정한다.
    🔑 순서 = `prepare(프레임)`(풀어 두기만) → 안경이 「[재생]」을 알리면 `begin()` · 띠링은 `chime(kind)` · `stop()`.
    🔴 어떤 메서드도 예외를 밖으로 내지 않는다 — 재생기가 없거나 죽으면 TV 만 조용히 빠진다(로그는 종류마다 한 줄).
    """

    CHUNK = 1024                 # 한 번에 넣는 샘플 수(48kHz 에서 약 21ms)
    PIPE_BYTES = 4096            # 관 크기 요청 — 커널이 페이지 크기(파이5 = 16KB)로 올린다
    AHEAD_MAX_SEC = 0.1          # 실제 시간보다 이만큼 넘게 앞서 넣지 않는다 = 쌓인 소리 · 멈춤 지연의 상한(GIL 에 밀려도 끊기지 않을 여유)

    def __init__(self, enabled, cmd=None, rate=None, peak=None, log=print, retry_sec=10.0, flag_ttl=0.3):
        self.rate = rate or config.AUDIENCE_RATE
        self.peak = peak or config.AUDIENCE_PEAK
        self.cmd = cmd or ["pw-cat", "--playback", "--raw", "--format", "s16", "--rate", str(self.rate),
                           "--channels", "1", "--latency", "40ms", "-"]
        self._enabled_fn, self._log = enabled, log
        self.retry_sec, self.flag_ttl = retry_sec, flag_ttl
        self._lock = threading.Lock()
        self._cur, self._pos, self._prepared = None, 0, None
        self._last_end = 0.0                 # 지금 소리의 마지막 덩어리를 넘긴 때(단조 시계)
        self._proc = None
        self._closed = threading.Event()
        self._thread = None
        self._died_at = None
        self._next_try = 0.0
        self._warned = set()
        self._flag_at, self._flag = None, False
        self._chimes = {}
        self._t_base, self._written = time.monotonic(), 0

    # ---------------------------------------------------------------- 안쪽
    def _warn(self, key, msg):
        if key in self._warned:
            return
        self._warned.add(key)
        try:
            self._log(msg)
        except Exception:                       # noqa: BLE001
            pass

    def enabled(self):
        """켬/끔(설정 「TV 소리」) — flag_ttl 초 묶어 읽는다 · 읽다 실패하면 끔."""
        now = time.monotonic()
        if self._flag_at is None or now - self._flag_at >= self.flag_ttl:
            try:
                self._flag = bool(self._enabled_fn())
            except Exception:                   # noqa: BLE001
                self._flag = False
            self._flag_at = now
        return self._flag

    def _spawn(self):
        try:
            p = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as e:
            self._proc = None
            self._next_try = time.monotonic() + self.retry_sec
            self._warn("spawn", f"⚠️ 관객 소리(TV) 재생기를 못 띄웠다 — TV 소리 없이 계속한다: {e}")
            return False
        try:
            fcntl.fcntl(p.stdin.fileno(), fcntl.F_SETPIPE_SZ, self.PIPE_BYTES)
        except (OSError, AttributeError):
            pass
        self._t_base, self._written = time.monotonic(), 0
        self._proc = p
        return True

    def _died(self, p):
        try:
            p.kill()
            p.wait(timeout=1)
        except Exception:                       # noqa: BLE001
            pass
        self._proc = None
        with self._lock:
            self._cur, self._prepared = None, None
        now = time.monotonic()
        quick = self._died_at is not None and now - self._died_at < 5.0
        self._died_at = now
        if quick:
            self._next_try = now + self.retry_sec
            self._warn("died2", f"⚠️ 관객 소리(TV) 재생기가 연달아 멈췄다 — {self.retry_sec:.0f}초 쉬고 다시 띄운다")
        else:
            self._next_try = now
            self._warn("died", "⚠️ 관객 소리(TV) 재생기가 멈췄다 — 다시 띄운다")

    def _next_chunk(self):
        with self._lock:
            if self._cur is None:
                return None
            if not self.enabled():
                self._cur, self._last_end = None, time.monotonic()
                return None
            c = self._cur[self._pos:self._pos + self.CHUNK]
            self._pos += self.CHUNK
            if self._pos >= len(self._cur):
                self._cur, self._last_end = None, time.monotonic()
        if len(c) < self.CHUNK:
            c = np.concatenate([c, np.zeros(self.CHUNK - len(c), np.int16)])
        return c.tobytes()

    def _run(self):
        silence = np.zeros(self.CHUNK, np.int16).tobytes()
        while not self._closed.is_set():
            p = self._proc
            if p is None:
                if time.monotonic() >= self._next_try:
                    self._spawn()
                if self._proc is None:
                    time.sleep(0.05)
                    continue
                p = self._proc
            buf = self._next_chunk() or silence
            ahead = self._written / self.rate - (time.monotonic() - self._t_base)
            if ahead > self.AHEAD_MAX_SEC:
                time.sleep(ahead - self.AHEAD_MAX_SEC)
            try:
                p.stdin.write(buf)
                self._written += len(buf) // 2
            except (OSError, ValueError, AttributeError):
                if not self._closed.is_set():
                    self._died(p)

    # ---------------------------------------------------------------- 밖에서 부르는 것
    def start(self):
        """재생기 + 공급 스레드를 띄운다(음성비서가 켜질 때 한 번)."""
        try:
            self._spawn()
            self._thread = threading.Thread(target=self._run, name="audience-speaker", daemon=True)
            self._thread.start()
        except Exception as e:                  # noqa: BLE001
            self._warn("start", f"⚠️ 관객 소리(TV) 시작 실패 — TV 소리 없이 계속한다: {e}")

    def prepare(self, payload):
        """안경으로 보낼 프레임을 풀어 둔다(아직 소리 아님) — 소리 프레임이 아니면 비운다."""
        try:
            got = parse_frame(payload)
            pcm = None if got is None else resample(normalize(got[0], self.peak), got[1], self.rate)
        except Exception as e:                  # noqa: BLE001
            pcm = None
            self._warn("prepare", f"⚠️ 관객 소리(TV) 프레임을 못 풀었다: {e}")
        with self._lock:
            self._prepared = pcm

    def begin(self):
        """안경이 「[재생]」을 알렸다 — 준비한 소리를 흘리기 시작한다(끔 · 재생기 없음이면 버린다)."""
        on = self.enabled() and self._proc is not None
        with self._lock:
            if on and self._prepared is not None:
                self._cur, self._pos = self._prepared, 0
            self._prepared = None

    def chime(self, kind):
        """띠링("open") · 닫힘음("close") — 안경에 B · C 를 보낸 직후."""
        if not (self.enabled() and self._proc is not None):
            return
        try:
            if kind not in self._chimes:
                self._chimes[kind] = chime_pcm(kind, self.rate, self.peak)
            c = self._chimes[kind]
        except Exception:                       # noqa: BLE001
            c = None
        if c is not None:
            with self._lock:
                self._cur, self._pos = c, 0

    def stop(self):
        """지금 소리 · 준비한 것을 버린다 → 다음 덩어리부터 무음."""
        with self._lock:
            if self._cur is not None:
                self._last_end = time.monotonic()
            self._cur, self._prepared = None, None

    @property
    def busy(self):
        return self._cur is not None

    def wait_tail(self, max_sec):
        """TV 가 남은 소리를 다 낼 때까지(+ AUDIENCE_TAIL_PAD_SEC) 기다린다 — 상한 max_sec · 소리 없으면 바로."""
        try:
            t0 = time.monotonic()
            end = t0 + max(0.0, max_sec)
            pad = config.AUDIENCE_TAIL_PAD_SEC
            if not self.busy and t0 - self._last_end >= pad:
                return
            while self.busy and time.monotonic() < end:
                time.sleep(0.01)
            rest = min(end, self._last_end + pad) - time.monotonic()
            if rest > 0:
                time.sleep(rest)
        except Exception:                       # noqa: BLE001
            pass

    def close(self):
        self._closed.set()
        self.stop()
        p = self._proc
        self._proc = None
        if p is not None:
            try:
                p.stdin.close()
                p.terminate()
                p.wait(timeout=1)
            except Exception:                   # noqa: BLE001
                pass
