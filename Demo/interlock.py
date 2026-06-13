"""물리 인터락 컨트롤러 — 트랙 A (FSM 콜백 → Serial → Arduino 릴레이).

FSM(`fsm.py`)의 `on_interlock(bool)`·`on_feedback(Feedback)` 콜백을 받아
Arduino로 `RUN`/`WARN`/`BLOCK` 한 줄 명령을 보내고 `ACK`를 확인한다.
설계 정본: `../dev/interlock/결선도_초안.md` §5 (Serial 프로토콜).

핵심 원칙(§8 인식/판정/제어 분리, fail-safe):
  - 시리얼이 없거나 끊겨도 **예외 없이 fallback**한다(로그만). GUI·FSM은 정상 동작.
  - 백그라운드 스레드가 끊긴 포트를 주기적으로 재연결하고, 재연결 시
    마지막 명령을 다시 보내 릴레이 상태를 현재 FSM 상태와 일치시킨다.
  - 모든 시리얼 접근은 `threading.Lock`으로 직렬화한다.

명령 매핑(결선도 §5):
  feedback NONE  + interlock 해제 → "RUN"   (녹 ON, 나머지 OFF)
  feedback WARNING               → "WARN"  (황 ON, 녹 OFF)
  feedback BLOCK   + interlock ON → "BLOCK" (적+부저 ON, 녹 OFF)
EMO는 Pi GPIO로 FSM이 직접 BLOCK 전이 → 동일하게 "BLOCK" 송신(별도 메시지 없음).
"""

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
                 enabled=None, log=None):
        self._port    = port if port is not None else config.INTERLOCK_PORT
        self._baud    = baud if baud is not None else config.INTERLOCK_BAUD
        self._timeout = timeout if timeout is not None else config.INTERLOCK_TIMEOUT
        self._reconnect_delay = getattr(config, "INTERLOCK_RECONNECT_DELAY_SEC", 3.0)
        self._enabled = config.INTERLOCK_ENABLED if enabled is None else enabled

        # 로그 싱크(없으면 print). safety_console 의 _append_log 를 주입받는다.
        self._log = log or (lambda msg: print(msg))

        self._lock   = threading.Lock()
        self._ser    = None
        self._closing = False
        self._last_cmd = None     # 재연결 시 재전송용 마지막 명령

        if not self._enabled:
            self._log("[인터락] 비활성(INTERLOCK_ENABLED=False) — 명령 전송 안 함")
            self._reconnect_thread = None
            return

        if serial is None:
            self._log("[인터락] pyserial 미설치 — fallback(로그만), GUI 정상")

        # 최초 연결 시도(실패해도 예외 없이 진행)
        self._open()

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

    def _reconnect_loop(self):
        """연결이 없을 때 주기적으로 재연결을 시도하는 백그라운드 루프."""
        while not self._closing:
            connected = self._ser is not None and getattr(self._ser, "is_open", False)
            if not connected and serial is not None:
                if self._open() and self._last_cmd is not None:
                    # 재연결 성공 → 현재 FSM 상태를 릴레이에 다시 반영
                    self._write(self._last_cmd, force=True)
            time.sleep(self._reconnect_delay)

    # -------------------------------------------------------------- 전송 코어
    def _write(self, cmd, force=False):
        """명령 한 줄 전송 + ACK 확인. 직전과 같은 명령이면 생략(force 제외).

        모든 실패(미연결·write 오류)는 로그만 남기고 흡수한다.
        """
        if not self._enabled:
            return
        with self._lock:
            if not force and cmd == self._last_cmd:
                self._last_cmd = cmd
                return
            self._last_cmd = cmd
            ser = self._ser
            if ser is None or not getattr(ser, "is_open", False):
                self._log(f"[인터락] (미연결) 명령 보류: {cmd}")
                return
            try:
                ser.write((cmd + "\n").encode("ascii"))
                ser.flush()
            except Exception as e:
                self._log(f"[인터락] 송신 실패({cmd}): {e} — 재연결 대기")
                self._drop()
                return
            # ACK 확인(타임아웃이면 경고만, 동작은 계속)
            try:
                ack = ser.readline().decode("ascii", "replace").strip()
            except Exception:
                ack = ""
            if ack == "ACK":
                self._log(f"[인터락] → {cmd} (ACK)")
            else:
                self._log(f"[인터락] → {cmd} (ACK 없음: '{ack}')")

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
        """재연결 스레드 정지 + 시리얼 닫기. 종료 전 안전상태(RUN) 시도."""
        self._closing = True
        if self._reconnect_thread is not None:
            self._reconnect_thread.join(timeout=self._reconnect_delay + 1.0)
        with self._lock:
            self._drop()
        self._log("[인터락] 종료")
