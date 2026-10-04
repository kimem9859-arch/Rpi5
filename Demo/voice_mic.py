"""마이크 업링크(8889) 수신 스레드 — 메인 루프가 막혀도 소켓을 늘 비운다.

정본: ../docs/superpowers/specs/2026-10-03-음성비서-시연안정화-design.md §4.1 (P1·P5·Q7)

🔴 왜 따로 도나 — 메인 루프는 LLM 대기·합성·재생으로 10~20초 막힌다. 그동안 소켓을 안 읽으면
   커널 수신 창이 차고, 펌웨어 쓰기가 막혀 펌웨어가 업링크를 끊는다(R3 C1 — 펌웨어 흉내로 재현).
   여기서 늘 읽어 두면 끊길 일이 없고, 대답 중 들어온 소리는 메인 루프가 `clear()` 로 버린다(G11).
🔴 반열림 — 상대가 사라졌는데 FIN/RST 가 안 오면 recv 는 영원히 타임아웃만 낸다(R2 C1). 펌웨어는
   접속 중 쉬지 않고 보내므로 `stall_sec` 동안 0바이트면 죽은 연결로 보고 다시 붙는다.
🔑 주소는 붙을 때마다 다시 읽는다 — 통신경로 폴백(iptime→폰→파이AP)을 따라간다(mDNS 미사용).
🔑 밀림 = **도착 시각** 기준이다(R2 M3) — 꺼낼 때 도착한 지 `lag_limit` 초 넘은 소리는 메인 루프가
   늦어 밀린 것이므로 버린다(최신 우선). 종전 LAG_LIMIT 는 표본 수만 봐 실제 지연을 재지 않았다.
"""
import collections
import socket
import threading
import time

import numpy as np


class MicReceiver:
    """업링크 하나를 붙들고 읽어 (도착 시각, 표본) 줄에 쌓는다. 스레드 하나."""

    def __init__(self, ip_getter, port, rate=16000, stall_sec=3.0, retry_sec=3.0,
                 lag_limit=2.0, max_queue_sec=8.0, on_chunk=None, log=print, once=False):
        self._ip = ip_getter
        self.port = port
        self.rate = rate
        self.stall_sec = stall_sec
        self.retry_sec = retry_sec
        self.lag_limit = lag_limit
        self._max_q = int(rate * max_queue_sec)
        self._on_chunk = on_chunk
        self._log = log
        self.once = once
        self._q = collections.deque()       # (도착 시각 monotonic, int16 배열)
        self._queued = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.generation = 0                 # 붙을 때마다 +1 — 메인 루프가 재접속을 알아챈다
        self.connected = False              # 지금 붙어 있나 — 준비 줄이 본다(1단계 M11)
        self.connected_ip = None
        self.closed = False                 # once 모드에서 상대가 닫았다
        self.dropped = 0                    # 밀려서 버린 표본 수(누적)
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._guarded, name="mic-uplink", daemon=True)
        self._thread.start()
        return self

    def alive(self):
        """수신 스레드가 살아 있는가 — 🔴 죽은 채 프로세스만 살아 있으면 감시가 다시 띄우지 않아 영구히 귀가 먹는다
        (최종 리뷰 M1). 메인 루프가 이것을 보고 데몬을 끝낸다."""
        return self._thread is not None and self._thread.is_alive()

    def _guarded(self):
        try:
            self._run()
        except Exception as e:             # noqa: BLE001 — 죽은 이유를 남기고 끝낸다(메인 루프가 alive() 로 안다)
            self._log(f"🔴 마이크 수신 스레드가 죽었다 — {type(e).__name__}: {e}")

    def stop(self):
        self._stop.set()

    def pull(self, now=None):
        """새로 들어온 소리. 도착한 지 lag_limit 초 넘은 것은 밀린 것이라 버린다."""
        now = time.monotonic() if now is None else now
        with self._lock:
            items = list(self._q)
            self._q.clear()
            self._queued = 0
        late = sum(len(a) for t, a in items if now - t > self.lag_limit)
        fresh = [a for t, a in items if now - t <= self.lag_limit]
        if late:
            with self._lock:                # 🔑 수신 스레드도 더한다 — 잠금 밖이면 겹쳐 빠진다(1단계 M6)
                self.dropped += late
            self._log(f"⚠️ 오디오가 {self.lag_limit:.0f}초 넘게 밀려 {late / self.rate:.1f}초를 버렸다(최신 우선)")
        return np.concatenate(fresh) if fresh else np.zeros(0, dtype=np.int16)

    def clear(self):
        """쌓인 소리를 모두 버린다 — 대답하는 동안 들어온 소리(G11). 버린 표본 수."""
        with self._lock:
            n = self._queued
            self._q.clear()
            self._queued = 0
        return n

    def _run(self):
        while not self._stop.is_set():
            s = self._connect()
            if s is None:
                return
            why = self._read(s)
            self.connected = False
            try:
                s.close()
            except OSError:
                pass
            if why == "멈춤":
                return
            if self.once and why == "끊김(EOF)":
                self._log("업링크 종료 — 리허설 끝")
                self.closed = True
                return
            self._log(f"🔴 업링크 {why} — {self.retry_sec:.0f}초 뒤 다시 붙는다")
            self._stop.wait(self.retry_sec)

    def _connect(self):
        while not self._stop.is_set():
            ip = None
            try:
                ip = self._ip()
                s = socket.create_connection((ip, self.port), 10)
            except (OSError, ValueError, SystemExit) as e:
                # 🔑 SystemExit 도 잡는다 — esp_ip() 는 주소 파일이 없으면 그것을 올린다. 스레드가 조용히
                #    죽으면 영구히 귀가 먹는다(파일이 생기면 다음 시도에 붙는다).
                self._log(f"🔴 업링크 연결 실패 ({ip}:{self.port}) {e} — {self.retry_sec:.0f}초 뒤 재시도")
                self._stop.wait(self.retry_sec)
                continue
            s.settimeout(0.5)
            self.connected_ip = ip
            self.generation += 1
            self.connected = True
            self._log(f"마이크 업링크 연결됨 ({ip}:{self.port})")
            return s
        return None

    def _read(self, s):
        last = time.monotonic()
        rest = b""
        while not self._stop.is_set():
            try:
                b = s.recv(16384)
            except socket.timeout:
                if time.monotonic() - last >= self.stall_sec:
                    return f"무수신 {self.stall_sec:.1f}초(반열림으로 본다)"
                continue
            except OSError as e:
                return f"오류: {e}"
            if not b:
                return "끊김(EOF)"
            last = time.monotonic()
            data = rest + b
            cut = len(data) // 2 * 2
            rest = data[cut:]
            a = np.frombuffer(data[:cut], dtype="<i2")
            if self._on_chunk is not None:
                try:
                    self._on_chunk(a)
                except Exception:              # noqa: BLE001 — 기록 실패로 귀가 먹으면 안 된다
                    pass
            with self._lock:
                self._q.append((last, a))
                self._queued += len(a)
                while self._queued > self._max_q:    # 🔴 메인 루프가 오래 막혀도 기억은 한정
                    _, old = self._q.popleft()
                    self._queued -= len(old)
                    self.dropped += len(old)
        return "멈춤"
