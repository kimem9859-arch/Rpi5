"""관객 소리(TV) — 안경에서 나는 소리를 TV 스피커로도 낸다(상위 specs/2026-10-21-관객소리TV-design.md).

🔑 안경으로 가는 소리는 모두 음성비서 `Speaker` 를 지난다 — 거기에 이 「거울」을 붙여 같은 소리를 TV 로 흘린다.
   이 파일 = 소리 재료(프레임 풀기 · 크기 맞춤 · 레이트 바꾸기 · 띠링)와 TV 통로(`AudienceSpeaker`).
🔴 거울은 안경 쪽을 절대 흔들지 않는다 — 여기 실패는 여기서 끝난다(설계 4장 8).
"""
import array
import fcntl
import os
import struct
import subprocess
import sys
import termios
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
       잘라 먹는다. 1024샘플씩 넣되 관(파이프)에 쌓인 소리를 직접 재서(FIONREAD) AHEAD_MAX_SEC 분을 넘으면 기다린다 →
       쌓인 소리가 그만큼뿐이라 멈춤이 바로 듣고 TV 가 덜 늦는다. ⚠️ 관 크기는 줄여 봐야 페이지 크기까지다(파이5 커널 = 16KB ≈
       0.17초). 🔴 공급 쪽 시계로만 재면 재생기가 늦게 읽기 시작한 뒤 회복하지 못해 관이 가득 찼다(검토 I1 · 0.3초 늦은 시작 →
       약 0.27초 적체) — 시간 규칙은 FIONREAD 가 안 될 때의 대체로만 남긴다.
    🔑 순서 = `prepare(프레임, t_send)`(보내기 시작할 때 · 따로 도는 스레드가 풀어 둠) → 안경이 「[재생]」을 알리면 `begin()` ·
       띠링은 `chime(kind)` · `stop()`.
    🔑 앞당겨 틀기(설계 11장) — 안경은 파일을 다 받은 뒤 재생한다. 그래서 `t_send + 받는 시간(spb × 바이트) − TV 지연` 에
       미리 튼다(`_pending`) · 「[재생]」이 먼저 오면 그때 바로 · 이미 틀었으면 다시 시작하지 않는다 · 「[재생]」이 온 때로
       받는 시간을 고쳐 간다(spb). 끄기 = advance=False(config.AUDIENCE_ADVANCE).
    🔴 어떤 메서드도 예외를 밖으로 내지 않는다 — 재생기가 없거나 죽으면 TV 만 조용히 빠진다(로그는 종류마다 한 줄).
    """

    CHUNK = 1024                 # 한 번에 넣는 샘플 수(48kHz 에서 약 21ms)
    PIPE_BYTES = 4096            # 관 크기 요청 — 커널이 페이지 크기(파이5 = 16KB)로 올린다
    AHEAD_MAX_SEC = 0.1          # 관에 이만큼 넘게 쌓아 두지 않는다 = 쌓인 소리 · 멈춤 지연의 상한(GIL 에 밀려도 끊기지 않을 여유)

    def __init__(self, enabled, cmd=None, rate=None, peak=None, log=print, retry_sec=10.0, flag_ttl=0.3,
                 advance=None, tv_lag=None, spb=None):
        self.advance = config.AUDIENCE_ADVANCE if advance is None else advance
        self.tv_lag = config.AUDIENCE_TV_LAG_SEC if tv_lag is None else tv_lag
        self.spb = 1 / 500_000 if spb is None else spb      # 안경이 받는 데 드는 초/바이트 — 처음 값 = 초당 500KB 가정 · 학습
        self.rate = rate or config.AUDIENCE_RATE
        self.peak = peak or config.AUDIENCE_PEAK
        self.cmd = cmd or ["pw-cat", "--playback", "--raw", "--format", "s16", "--rate", str(self.rate),
                           "--channels", "1", "--latency", "40ms", "-"]
        self._enabled_fn, self._log = enabled, log
        self.retry_sec, self.flag_ttl = retry_sec, flag_ttl
        self._lock = threading.Lock()
        self._cur, self._pos, self._prepared = None, 0, None
        self._pending = None                 # 앞당겨 틀 예약 (pcm, 틀 때, t_send, 바이트)
        self._started = None                 # 앞당겨 틀어 이미 나가는 소리의 (t_send, 바이트) — 「[재생]」 때 학습만
        self._begin_at = None                # 아직 풀고 있는데 「[재생]」이 먼저 온 때
        self._job = 0                        # 풀기 작업 번호 — 낡은 작업 결과를 버린다
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
        self._last_write = 0.0               # 재생기에 마지막으로 써 넣은 때 — 막혔는지 본다(검토 Minor 2)

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
        self._last_write = time.monotonic()
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
            self._clear()
        now = time.monotonic()
        quick = self._died_at is not None and now - self._died_at < 5.0
        self._died_at = now
        if quick:
            self._next_try = now + self.retry_sec
            self._warn("died2", f"⚠️ 관객 소리(TV) 재생기가 연달아 멈췄다 — {self.retry_sec:.0f}초 쉬고 다시 띄운다")
        else:
            self._next_try = now
            self._warn("died", "⚠️ 관객 소리(TV) 재생기가 멈췄다 — 다시 띄운다")

    def _clear(self):
        """(잠금 안에서) 지금 소리 · 준비 · 예약을 모두 버린다."""
        self._cur = self._prepared = self._pending = self._started = self._begin_at = None
        self._job += 1

    def _learn(self, t_send, nbytes, t_play):
        """(잠금 안에서) 보내기 시작 → 「[재생]」 까지 실제로 걸린 시간으로 초/바이트를 고친다."""
        if t_send is None or nbytes <= 0:
            return
        obs = t_play - t_send
        if 0 < obs < 5.0:
            self.spb = 0.7 * self.spb + 0.3 * (obs / nbytes)

    def _next_chunk(self):
        on = self.enabled()                  # 🔑 잠금 밖에서 — 상태 파일 읽기가 begin · stop 을 붙잡지 않게(검토 Minor 3)
        now = time.monotonic()
        with self._lock:
            if self._cur is None and self._pending is not None and now >= self._pending[1]:
                pcm, _, ts, n = self._pending
                self._pending = None
                if on:
                    self._cur, self._pos, self._started = pcm, 0, (ts, n)    # 앞당겨 틀기 — 「[재생]」 전에
            if self._cur is None:
                return None
            if not on:
                self._cur, self._last_end = None, time.monotonic()
                return None
            c = self._cur[self._pos:self._pos + self.CHUNK]
            self._pos += self.CHUNK
            if self._pos >= len(self._cur):
                self._cur, self._last_end = None, time.monotonic()
        if len(c) < self.CHUNK:
            c = np.concatenate([c, np.zeros(self.CHUNK - len(c), np.int16)])
        return c.tobytes()

    @staticmethod
    def _queued(p):
        """관에 쌓여 아직 재생기가 읽지 않은 바이트 — 못 재면 None."""
        try:
            buf = array.array("i", [0])
            fcntl.ioctl(p.stdin.fileno(), termios.FIONREAD, buf)
            return buf[0]
        except (OSError, ValueError, AttributeError):
            return None

    def _wait_room(self, p):
        """관에 AHEAD_MAX_SEC 분 넘게 쌓였으면 줄 때까지 기다린다(못 재면 공급 쪽 시계 규칙)."""
        limit = int(self.AHEAD_MAX_SEC * self.rate) * 2
        while not self._closed.is_set():
            if p.poll() is not None:
                return                       # 🔴 재생기가 죽었다 — 관은 영영 안 준다 · 바로 써 보게 해 죽음을 알아챈다(_died)
            q = self._queued(p)
            if q is None:
                ahead = self._written / self.rate - (time.monotonic() - self._t_base)
                if ahead > self.AHEAD_MAX_SEC:
                    time.sleep(ahead - self.AHEAD_MAX_SEC)
                return
            if q <= limit:
                return
            time.sleep(0.005)

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
            self._wait_room(p)                   # 🔑 덩어리를 꺼내기 전에 — 멈춤 · 시작이 곧바로 다음 덩어리에 걸리게
            buf = self._next_chunk() or silence
            try:
                p.stdin.write(buf)
                self._written += len(buf) // 2
                self._last_write = time.monotonic()
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

    def prepare(self, payload, t_send=None):
        """안경으로 보낼 프레임 — 따로 도는 스레드가 풀어 둔다(🔑 곧바로 돌아온다 · 안경 전송을 늦추지 않음).
        `t_send` = 보내기 시작한 때(단조 시계) — 있고 앞당기기 켬이면 예약해 「[재생]」 전에 튼다. 끔 · 재생기 없음이면 풀지 않는다."""
        with self._lock:
            self._clear()
            job = self._job
        if not (self.enabled() and self._proc is not None):
            return
        threading.Thread(target=self._prep_job, args=(payload, t_send, job), name="audience-prep", daemon=True).start()

    def _prep_job(self, payload, t_send, job):
        try:
            got = parse_frame(payload)
            pcm = None if got is None else resample(normalize(got[0], self.peak), got[1], self.rate)
        except Exception as e:                  # noqa: BLE001
            pcm = None
            self._warn("prepare", f"⚠️ 관객 소리(TV) 프레임을 못 풀었다: {e}")
        n = len(payload or b"")
        with self._lock:
            if job != self._job or pcm is None:
                return                           # 그사이 멈춤 · 다음 소리 — 낡은 결과
            if self._begin_at is not None:       # 「[재생]」이 먼저 왔다 — 바로
                self._cur, self._pos = pcm, 0
                self._learn(t_send, n, self._begin_at)
                self._begin_at = None
            elif self.advance and t_send is not None:
                self._pending = (pcm, t_send + self.spb * n - self.tv_lag, t_send, n)
            else:
                self._prepared = (pcm, t_send, n)

    def begin(self):
        """안경이 「[재생]」을 알렸다 — 예약 · 준비한 소리를 지금 튼다 · 앞당겨 이미 틀었으면 다시 시작하지 않고 학습만
        (끔 · 재생기 없음이면 버린다)."""
        on = self.enabled() and self._proc is not None
        now = time.monotonic()
        with self._lock:
            if not on:
                self._clear()
                return
            if self._pending is not None:
                pcm, _, ts, n = self._pending
                self._pending = None
                self._cur, self._pos = pcm, 0
                self._learn(ts, n, now)
            elif self._started is not None:
                ts, n = self._started
                self._started = None
                self._learn(ts, n, now)
            elif self._prepared is not None:
                pcm, ts, n = self._prepared
                self._prepared = None
                self._cur, self._pos = pcm, 0
                self._learn(ts, n, now)
            else:
                self._begin_at = now             # 아직 풀고 있다 — 다 풀면 바로 튼다(_prep_job)

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
            self._clear()

    @property
    def busy(self):
        """TV 로 낼 소리가 남았나 — 나가는 중 · 예약됨 · 「[재생]」 뒤 아직 풀고 있음을 모두 센다(꼬리 기다림이 짧은 소리를 놓치지 않게)."""
        return self._cur is not None or self._pending is not None or self._begin_at is not None

    def wait_tail(self, max_sec):
        """TV 가 남은 소리를 다 낼 때까지(+ AUDIENCE_TAIL_PAD_SEC) 기다린다 — 상한 max_sec · 소리 없으면 바로."""
        try:
            t0 = time.monotonic()
            end = t0 + max(0.0, max_sec)
            pad = config.AUDIENCE_TAIL_PAD_SEC
            if not self.busy and t0 - self._last_end >= pad:
                return
            while self.busy and time.monotonic() < end:
                if time.monotonic() - self._last_write > 0.3:
                    return                       # 재생기가 읽지 않고 막혔다 — 기다려도 TV 는 안 난다(검토 Minor 2)
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
