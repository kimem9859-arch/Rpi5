"""물리 인터락 컨트롤러 — 트랙 A (FSM 콜백 → Serial → Arduino 릴레이).

FSM(`fsm.py`)의 `on_interlock(bool)`·`on_feedback(Feedback)` 콜백을 받아
Arduino로 `RUN`/`WARN`/`BLOCK` 한 줄 명령을 보내고 `ACK`를 확인한다.
설계 정본: `../dev/interlock/결선도_초안.md` §5 (Serial 프로토콜).

핵심 원칙(§8 인식/판정/제어 분리, fail-safe):
  - 시리얼이 없거나 끊겨도 **예외 없이 fallback**한다(로그만). GUI·FSM은 정상 동작.
  - 시리얼 I/O(write+ACK 대기 최대 1초)는 **전용 워커 스레드**에서 수행 —
    FSM 콜백(GUI 스레드)은 큐에 넣고 즉시 반환하므로 UI가 얼지 않는다.
  - 백그라운드 스레드가 끊긴 포트를 주기적으로 재연결하고, 재연결 시
    마지막 명령을 다시 보내 릴레이 상태를 현재 FSM 상태와 일치시킨다.
  - 모든 시리얼 접근은 `threading.Lock`으로 직렬화한다.
  - **BLOCK은 ACK로 차단 실행을 확인**한다 — 무ACK면 재시도, 최종 실패 시
    `on_fault` 콜백(릴레이 미작동 가능성 알람). RUN/WARN은 경고 로그만.

명령 매핑(결선도 §5):
  feedback NONE  + interlock 해제 → "RUN"   (녹 ON, 나머지 OFF)
  feedback WARNING               → "WARN"  (황 ON, 녹 OFF)
  feedback BLOCK   + interlock ON → "BLOCK" (적+부저 ON, 녹 OFF)
EMO는 Pi GPIO로 FSM이 직접 BLOCK 전이 → 동일하게 "BLOCK" 송신(별도 메시지 없음).
"""

import queue
import threading
import time

import config

try:
    import serial  # pyserial
except ImportError:  # pyserial 미설치 환경에서도 import 자체는 통과(fallback)
    serial = None

# FSM Feedback enum 값 → 명령 문자열. import 순환을 피하려고 이름으로 매핑한다.
_FEEDBACK_TO_CMD = {
    "NONE":    "RUN",
    "WARNING": "WARN",
    "BLOCK":   "BLOCK",
}


class InterlockController:
    """FSM 판정을 Arduino 릴레이 명령으로 변환·전송하는 시리얼 매니저.

    스레드 안전. 시리얼 미연결·끊김 시에도 예외를 던지지 않고 로그만 남긴다.
    """

    def __init__(self, port=None, baud=None, timeout=None,
                 enabled=None, log=None, on_fault=None, on_give_up=None):
        self._port    = port if port is not None else config.INTERLOCK_PORT
        self._baud    = baud if baud is not None else config.INTERLOCK_BAUD
        self._timeout = timeout if timeout is not None else config.INTERLOCK_TIMEOUT
        self._reconnect_delay = getattr(config, "INTERLOCK_RECONNECT_DELAY_SEC", 3.0)
        # 재연결 제한 — 무한 재시도로 로그가 쌓이는 것을 막는다.
        self._fail_count = 0
        self._give_up = False
        self._on_give_up = on_give_up
        self._block_retries = getattr(config, "INTERLOCK_BLOCK_ACK_RETRIES", 2)
        self._enabled = config.INTERLOCK_ENABLED if enabled is None else enabled

        # 로그 싱크(없으면 print). 워커 스레드에서 호출되므로 GUI 위젯 직접 접근 금지
        # — safety_console 은 pyqtSignal.emit 를 주입한다.
        self._log = log or (lambda msg: print(msg))
        # BLOCK 차단 미확인 알람(무ACK·미연결). 역시 워커 스레드에서 호출됨.
        self._on_fault = on_fault

        self._lock   = threading.Lock()
        self._ser    = None
        self._closing = False
        self._last_cmd = None     # 재연결 시 재전송용 마지막 명령
        self._queue = queue.Queue()   # (cmd, force) — GUI 스레드 비블로킹용

        if not self._enabled:
            self._log("[인터락] 비활성(INTERLOCK_ENABLED=False) — 명령 전송 안 함")
            self._reconnect_thread = None
            self._writer_thread = None
            return

        if serial is None:
            self._log("[인터락] pyserial 미설치 — fallback(로그만), GUI 정상")

        # 전송 워커 스레드 — 시리얼 write+ACK 대기를 GUI 스레드 밖에서 처리
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="interlock-writer", daemon=True)
        self._writer_thread.start()

        # 최초 연결 시도(실패해도 예외 없이 진행). 성공 시 램프 상태 동기화.
        if self._open():
            self._sync_after_open()

        # 백그라운드 재연결 스레드(연결 안 됐을 때만 실제로 동작)
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, name="interlock-reconnect", daemon=True)
        self._reconnect_thread.start()

    # ------------------------------------------------------------------ 연결
    def _open(self):
        """시리얼 포트 열기 시도. 실패는 로그만 남기고 False 반환."""
        if serial is None:
            return False
        with self._lock:
            if self._ser is not None and getattr(self._ser, "is_open", False):
                return True
            try:
                self._ser = serial.Serial(
                    self._port, self._baud, timeout=self._timeout,
                    write_timeout=self._timeout)
                # UNO R4 는 연결 직후 리셋 → 부팅 대기. 짧게 비운다.
                time.sleep(2.0)
                self._ser.reset_input_buffer()
                self._log(f"[인터락] 연결됨 — {self._port} @ {self._baud}")
                return True
            except Exception as e:  # SerialException 외 권한/장치없음 모두 흡수
                self._ser = None
                self._log(f"[인터락] 연결 실패({self._port}): {e} — fallback")
                return False

    def _sync_after_open(self):
        """연결 직후 램프 상태를 Pi 기준으로 강제 동기화한다(_open 락 밖에서 호출).

        - 최초 연결(_last_cmd None): "RUN" 을 명시 송신 → 시작 램프를 Arduino
          부팅값 우연이 아니라 Pi 가 결정한 정상(녹)으로 확정.
        - 재연결(_last_cmd 있음): 마지막 명령을 다시 보내 끊기기 전 상태 복원
          (BLOCK 중 케이블이 빠졌다 붙어도 차단이 풀리지 않음).
        """
        cmd = self._last_cmd if self._last_cmd is not None else "RUN"
        self._write(cmd, force=True)

    def _reconnect_loop(self):
        """연결이 없을 때 주기적으로 재연결을 시도하는 백그라운드 루프.

        🔴 무한 재시도 금지 — 3초마다 영원히 돌면 "연결 실패" 로그가 계속 쌓인다.
           CONNECT_MAX_TRIES 회 실패하면 멈추고 on_give_up 을 부른다.
           다시 붙이려면 메뉴 → 점검(연결) 에서 retry_connect() 를 부른다.
        """
        max_tries = getattr(config, "CONNECT_MAX_TRIES", 5)
        while not self._closing:
            if self.connected:
                self._fail_count = 0
                self._give_up = False
            elif self._give_up:
                pass                       # 포기 상태 — 수동 재시도를 기다린다
            elif serial is not None:
                if self._open():
                    self._fail_count = 0
                    self._sync_after_open()
                else:
                    self._fail_count += 1
                    if self._fail_count >= max_tries:
                        self._give_up = True
                        self._log(f"[인터락] 🔴 {max_tries}회 연결 실패 — 자동 재시도를 멈춥니다. "
                                  f"메뉴 → 점검(연결) 에서 다시 시도하세요.")
                        if self._on_give_up:
                            try:
                                self._on_give_up(max_tries)
                            except Exception:
                                pass
            time.sleep(self._reconnect_delay)

    def retry_connect(self):
        """수동 재연결 — 메뉴 → 점검(연결) 에서 부른다."""
        self._fail_count = 0
        self._give_up = False
        self._log("[인터락] 수동 재연결 시도")

    @property
    def gave_up(self):
        return self._give_up

    @property
    def connected(self):
        """시리얼이 실제로 열려 있는가.

        🔴 **상태바 색이 이 값으로 칠해진다** — `precheck.run_stage1` 이
           `getattr(itl, "connected", False)` 로 읽으므로, 속성이 없으면 기본값
           False 가 되어 **연결돼 있어도 언제나 빨강**이다.
        ⚠️ 2026-09-05 에 실제로 물렸다 — 인터락이 붙어 ACK 까지 오는데
           오른쪽 아래 「인터락 연결」만 빨갛게 떠 있었다. 시연 영상에 그대로
           찍힐 뻔했다.
        """
        return self._ser is not None and getattr(self._ser, "is_open", False)

    # -------------------------------------------------------------- 전송 코어
    def _write(self, cmd, force=False):
        """명령을 전송 큐에 넣고 즉시 반환(비블로킹 — GUI 스레드에서 안전).

        실제 시리얼 write+ACK 대기는 _writer_loop(워커 스레드)가 수행한다.
        """
        if not self._enabled:
            return
        self._queue.put((cmd, force))

    def _writer_loop(self):
        """전송 큐를 소비하는 워커. None 센티널이면 종료."""
        while True:
            item = self._queue.get()
            if item is None:
                return
            cmd, force = item
            try:
                self._write_now(cmd, force)
            except Exception as e:  # 어떤 실패도 워커를 죽이지 않는다
                self._log(f"[인터락] 전송 스레드 오류({cmd}): {e}")

    def _write_now(self, cmd, force=False):
        """명령 한 줄 전송 + ACK 확인. 직전과 같은 명령이면 생략(force 제외).

        모든 실패(미연결·write 오류)는 로그만 남기고 흡수한다. 단 BLOCK 은
        차단이 실제 실행됐는지 ACK 로 확인해야 하므로, 무ACK 시 재시도 후
        최종 실패면 _fault(알람) — 릴레이가 안 움직였을 수 있다.
        """
        with self._lock:
            if not force and cmd == self._last_cmd:
                self._last_cmd = cmd
                return
            self._last_cmd = cmd
            ser = self._ser
            if ser is None or not getattr(ser, "is_open", False):
                self._log(f"[인터락] (미연결) 명령 보류: {cmd}")
                if cmd == "BLOCK":
                    self._fault("BLOCK 송신 불가(시리얼 미연결) — 릴레이 차단 미확인")
                return
            attempts = 1 + (self._block_retries if cmd == "BLOCK" else 0)
            for i in range(attempts):
                try:
                    ser.write((cmd + "\n").encode("ascii"))
                    ser.flush()
                except Exception as e:
                    self._log(f"[인터락] 송신 실패({cmd}): {e} — 재연결 대기")
                    self._drop()
                    if cmd == "BLOCK":
                        self._fault(f"BLOCK 송신 실패({e}) — 릴레이 차단 미확인")
                    return
                try:
                    ack = ser.readline().decode("ascii", "replace").strip()
                except Exception:
                    ack = ""
                if ack == "ACK":
                    tag = f" (재시도 {i}회 후)" if i else ""
                    self._log(f"[인터락] → {cmd} (ACK){tag}")
                    return
                if cmd != "BLOCK":
                    self._log(f"[인터락] → {cmd} (ACK 없음: '{ack}')")
                    return
                self._log(f"[인터락] → BLOCK ACK 없음('{ack}') — 재시도 {i + 1}/{attempts - 1}"
                          if i < attempts - 1 else
                          f"[인터락] → BLOCK ACK 없음('{ack}')")
            self._fault(f"BLOCK ACK {attempts}회 미수신 — 릴레이 차단 미확인, 배선·Arduino 점검")

    def _fault(self, msg):
        """차단 미확인 등 안전 폴트 통지. 로그 + on_fault 콜백(예외 흡수)."""
        self._log(f"[인터락] 🚨 {msg}")
        if self._on_fault is not None:
            try:
                self._on_fault(msg)
            except Exception as e:
                self._log(f"[인터락] 폴트 콜백 오류: {e}")

    def _drop(self):
        """현재 시리얼 핸들을 닫고 None 으로. (호출자가 _lock 보유 중)"""
        try:
            if self._ser is not None:
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    # ---------------------------------------------------------- FSM 콜백 연결
    def set_interlock(self, engaged):
        """FSM on_interlock(bool). BLOCK 진입 시 가장 빠른 차단 경로.

        engaged=True → 즉시 BLOCK 송신(해제는 뒤따르는 feedback NONE→RUN 이 처리).
        FSM._goto 는 BLOCK 시 on_interlock(True)→on_feedback(BLOCK) 순서로 부르며,
        _write 의 중복 제거로 BLOCK 이 두 번 전송되지 않는다.
        """
        if engaged:
            self._write("BLOCK")

    def set_feedback(self, level):
        """FSM on_feedback(Feedback). 램프 명령의 권위 소스.

        level 은 fsm.Feedback enum. import 순환을 피하려 `.name` 으로 매핑한다.
        """
        name = getattr(level, "name", str(level))
        cmd = _FEEDBACK_TO_CMD.get(name)
        if cmd is None:
            self._log(f"[인터락] 알 수 없는 피드백 레벨: {level}")
            return
        self._write(cmd)

    # ------------------------------------------------------------------ 종료
    def close(self):
        """워커·재연결 스레드 정지 + 시리얼 닫기."""
        self._closing = True
        if self._writer_thread is not None:
            self._queue.put(None)   # 워커 종료 센티널
            self._writer_thread.join(timeout=self._timeout * 4 + 1.0)
        if self._reconnect_thread is not None:
            self._reconnect_thread.join(timeout=self._reconnect_delay + 1.0)
        with self._lock:
            self._drop()
        self._log("[인터락] 종료")
