"""인터락 연결 관리 검증(I1~I3) — 가짜 시리얼로.

실행: python3 Demo/selftest/test_interlock.py
🔴 실제 Arduino·릴레이에 닿지 않는다 — `interlock.serial` 을 가짜 모듈로 바꾸고, 포트는
   임시 폴더의 빈 파일(뽑힘 = 파일 삭제)로 흉내 낸다.
정본 = 상위 docs/superpowers/specs/2026-09-25-런타임-문제수정-design.md §4.2
"""
import os
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import config
config.INTERLOCK_BOOT_WAIT_SEC = 0.05
config.INTERLOCK_RECONNECT_DELAY_SEC = 0.05
config.CONNECT_MAX_TRIES = 2          # 포기가 빨리 오게 — 장치가 없는 동안에는 포기하지 않아야 한다(I1)
import interlock
from fsm import Feedback

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _FakeSerial:
    opened = []
    refuse = set()
    ack = True                        # False 면 ACK 를 돌려주지 않는 장치(최종 리뷰 I-3)

    def __init__(self, port, baud, timeout=None, write_timeout=None):
        if not str(port).startswith(tempfile.gettempdir()):
            raise RuntimeError(f"🔴 시험이 실제 장치를 열려고 했다: {port}")
        if not os.path.exists(port):
            raise OSError(f"no such port {port}")
        if port in _FakeSerial.refuse:
            raise OSError(f"permission denied {port}")     # 있지만 못 여는 장치(M-4·M-10)
        self.port = port
        self.is_open = True
        self.writes = []
        self._acks = 0
        _FakeSerial.opened.append(self)

    def write(self, b):
        if not os.path.exists(self.port):
            raise OSError("device gone")
        self.writes.append(b.decode().strip())
        if _FakeSerial.ack:
            self._acks += 1

    def flush(self):
        pass

    def readline(self):
        if self._acks:
            self._acks -= 1
            return b"ACK\n"
        return b""

    def reset_input_buffer(self):
        pass

    def close(self):
        self.is_open = False


class _FakeSerialModule:
    Serial = _FakeSerial


interlock.serial = _FakeSerialModule


def _wait(cond, sec=3.0):
    end = time.time() + sec
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _ctl(port_box):
    """port_box["p"] 를 돌려주는 가짜 포트 찾기로 인터락을 만든다."""
    config.resolve_interlock_port = lambda quiet=False: port_box["p"]      # 고치기 전 경로
    config.find_interlock_port = lambda: ((port_box["p"], None) if port_box["p"]
                                          else (None, "장치를 못 찾았다(시험)"))
    config.INTERLOCK_PORT = port_box["p"]
    return interlock.InterlockController(enabled=True, log=lambda m: None)


def test_i1_device_plugged_after_start():
    """I1 — 켤 때 장치가 없어도 포기하지 않고 계속 찾다가, 나중에 꽂으면 스스로 붙는다(검토 C7)."""
    print("\n[I1] 나중에 꽂기")
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM0")
    box = {"p": None}
    c = _ctl(box)
    try:
        check(not c.connected, "시작 때 장치 없음 → 미연결")
        time.sleep(0.4)                                   # 재시도 한도(2회)를 넘길 만큼 없는 채로
        check(not c.gave_up, "장치가 없는 동안에는 포기하지 않는다")
        open(dev, "w").close()
        box["p"] = dev                                    # 꽂음
        check(_wait(lambda: c.connected), "꽂으면 재연결 스레드가 붙는다")
        check(_wait(lambda: bool(_FakeSerial.opened)
                    and _FakeSerial.opened[-1].writes[:1] == ["RUN"]),
              "붙자마자 RUN 으로 램프를 맞춘다")
    finally:
        c.close()


def test_i2_unplug_detected_and_new_number():
    """I2 — 뽑히면 쓰기 전이라도 끊김으로 보고, 다른 번호로 다시 꽂혀도 붙는다(검토 C9)."""
    print("\n[I2] 뽑힘·번호 바뀜")
    tmp = tempfile.mkdtemp()
    dev0, dev1 = os.path.join(tmp, "ttyACM0"), os.path.join(tmp, "ttyACM1")
    open(dev0, "w").close()
    box = {"p": dev0}
    c = _ctl(box)
    try:
        check(_wait(lambda: c.connected), "처음 붙음")
        os.unlink(dev0)                                   # 뽑음
        box["p"] = None                                   # 뽑힌 장치는 찾기에도 안 나온다
        check(_wait(lambda: not c.connected), "뽑히면 곧바로 끊김(녹색으로 남지 않는다)")
        time.sleep(0.3)                                   # 없는 동안 재시도 한도를 넘겨도
        open(dev1, "w").close()
        box["p"] = dev1                                   # 다른 번호로 다시 꽂힘
        check(_wait(lambda: c.connected and _FakeSerial.opened[-1].port == dev1),
              "새 번호로 다시 붙는다")
    finally:
        c.close()


def test_i3_resync_sends_latest():
    """I3 — 붙는 동안(부팅 대기) 들어온 해제가 옛 BLOCK 에 덮이지 않는다(검토 C8)."""
    print("\n[I3] 재연결 동기화")
    old_wait = config.INTERLOCK_BOOT_WAIT_SEC
    config.INTERLOCK_BOOT_WAIT_SEC = 0.4               # 부팅 대기 중에 명령이 들어오게
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM0")
    box = {"p": None}
    c = _ctl(box)
    try:
        c.set_interlock(True)                          # 미연결 중 BLOCK (보류)
        open(dev, "w").close()
        box["p"] = dev                                 # 꽂음 → 재연결 시작
        time.sleep(0.2)                                # 부팅 대기 중에
        c.set_feedback(Feedback.NONE)                  # 해제 → RUN
        ok = _wait(lambda: len(_FakeSerial.opened[-1].writes) >= 2, 3.0)
        writes = _FakeSerial.opened[-1].writes
        check(ok and writes[-1] == "RUN", f"마지막으로 나간 명령 = RUN — {writes}")
    finally:
        c.close()
        config.INTERLOCK_BOOT_WAIT_SEC = old_wait

def test_i2_no_ack_device_not_green():
    """I2 — 열리기만 하고 ACK 가 없는 장치는 연결(녹색)로 보지 않는다(설계 I2 「쓰기·ACK 결과로」 · 최종 리뷰 I-3)."""
    print("\n[I2] 무응답 장치")
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM0")
    open(dev, "w").close()
    box = {"p": dev}
    _FakeSerial.ack = False
    c = _ctl(box)
    try:
        ok = _wait(lambda: bool(_FakeSerial.opened) and _FakeSerial.opened[-1].port == dev
                   and _FakeSerial.opened[-1].writes[:1] == ["RUN"])
        check(ok, "장치는 열려 동기화 RUN 을 보냈다")
        time.sleep(0.2)
        check(not c.connected, "ACK 가 없으면 연결로 보지 않는다(녹색 아님)")
    finally:
        c.close()
        _FakeSerial.ack = True

class _LateAckSerial(_FakeSerial):
    """WARN 의 ACK 가 한도(1초)를 넘겨 늦게 오고, BLOCK 에는 응답이 없는 장치(릴레이 고장)."""

    def __init__(self, port):
        super().__init__(port, 115200)
        self._buf = []
        self._late = 0

    def write(self, b):
        self.writes.append(b.decode().strip())
        if self.writes[-1] == "WARN":
            self._late += 1                              # 한도 안에는 안 온다

    def readline(self):
        if self._buf:
            return self._buf.pop(0)
        if self._late:                                   # 기다림이 끝난 **뒤에** 도착
            self._buf += [b"ACK\n"] * self._late
            self._late = 0
        return b""

    def reset_input_buffer(self):
        self._buf.clear()


def test_c15_late_ack_not_taken_for_block():
    """C15 — 늦게 온 WARN 의 ACK 를 BLOCK 의 ACK 로 읽지 않는다(검토 C15 — 차단 확인이 거짓이 됐다)."""
    print("\n[C15] 늦은 ACK")
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM0")
    open(dev, "w").close()
    box = {"p": dev}
    c = _ctl(box)
    faults = []
    try:
        check(_wait(lambda: c.connected), "처음 붙음")
        with c._lock:
            c._ser = _LateAckSerial(dev)
        c._on_fault = faults.append
        c._write_now("WARN")
        c._write_now("BLOCK")
        check(bool(faults), "BLOCK 차단 확인 실패를 알린다(늦은 WARN-ACK 로 속지 않는다)")
        check(not c.connected, "응답 없는 장치를 「연결됨」으로 두지 않는다")
    finally:
        c.close()

_REAL_FIND = getattr(config, "find_interlock_port", None)   # _ctl 이 바꿔 끼우기 전 원본(M-6)


def test_m4_open_failure_logs_tried_port():
    """M-4 — 열기 실패 로그는 **시도한** 포트를 찍는다(③ 리뷰 M-4 — 옛 값을 찍었다)."""
    print("\n[M-4] 실패 로그의 포트")
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM1")
    open(dev, "w").close()
    _FakeSerial.refuse.add(dev)
    config.resolve_interlock_port = lambda quiet=False: dev      # 고치기 전 경로
    config.find_interlock_port = lambda: (dev, None)
    config.INTERLOCK_PORT = None                                   # 기동 때는 못 찾았다
    logs = []
    c = interlock.InterlockController(enabled=True, log=logs.append)
    try:
        fails = [m for m in logs if "연결 실패" in m]
        check(bool(fails) and f"연결 실패({dev})" in fails[0], "연결 실패 로그에 시도한 포트가 찍힌다")
    finally:
        _FakeSerial.refuse.discard(dev)
        c.close()


def test_m5_fixed_port_missing_is_absent():
    """M-5 — 지정한 포트가 없으면 「못 찾음」 — 포기하지 않고, 나중에 생기면 붙는다(③ 리뷰 M-5)."""
    print("\n[M-5] 지정 포트 없음")
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM9")
    logs = []
    c = interlock.InterlockController(port=dev, enabled=True, log=logs.append)
    try:
        time.sleep(0.4)                                    # 재시도 한도(2회)를 넘길 만큼
        check(not c.gave_up, "지정 포트가 없는 동안에는 포기하지 않는다")
        check(any("지정한 포트가 없다" in m for m in logs), "로그 = 「지정한 포트가 없다」")
        open(dev, "w").close()
        check(_wait(lambda: c.connected), "나중에 생기면 붙는다")
    finally:
        c.close()


def test_m6_many_candidates_says_so():
    """M-6 — 후보가 여럿이면 「꽂히면 붙는다」가 아니라 「여럿이라 고를 수 없다」고 안내한다(③ 리뷰 M-6)."""
    print("\n[M-6] 후보 여럿")
    check(_REAL_FIND is not None, "config.find_interlock_port 가 있다(사유를 함께 돌려준다)")
    if _REAL_FIND is None:
        return
    import types
    from serial.tools import list_ports
    fake = [types.SimpleNamespace(device="/dev/시험A", vid=0x2341, pid=0x0069),
            types.SimpleNamespace(device="/dev/시험B", vid=0x1a86, pid=0x7523)]
    old, old_env = list_ports.comports, os.environ.pop("SOP_INTERLOCK_PORT", None)
    try:
        list_ports.comports = lambda: fake
        port, why = _REAL_FIND()
        check(port is None, "고르지 않는다")
        check("여럿" in (why or "") and "SOP_INTERLOCK_PORT" in (why or ""),
              "사유 = 후보가 여럿 · 직접 지정 안내")
        list_ports.comports = lambda: fake[:1]
        check(_REAL_FIND() == ("/dev/시험A", None), "하나면 그것")
        list_ports.comports = lambda: []
        port, why = _REAL_FIND()
        check(port is None and "못 찾았다" in (why or ""), "없으면 「못 찾았다」")
    finally:
        list_ports.comports = old
        if old_env is not None:
            os.environ["SOP_INTERLOCK_PORT"] = old_env


def test_m10_found_but_unopenable_gives_up():
    """M-10(가드) — 찾았지만 열리지 않는 장치는 몇 번 뒤 포기하고 알린다(③ Review Focus 1 의 나머지 절반)."""
    print("\n[M-10] 못 여는 장치 → 포기")
    tmp = tempfile.mkdtemp()
    dev = os.path.join(tmp, "ttyACM2")
    open(dev, "w").close()
    _FakeSerial.refuse.add(dev)
    config.resolve_interlock_port = lambda quiet=False: dev
    config.find_interlock_port = lambda: (dev, None)
    gave = []
    c = interlock.InterlockController(enabled=True, log=lambda m: None, on_give_up=gave.append)
    try:
        check(_wait(lambda: c.gave_up), "포기한다")
        check(gave == [config.CONNECT_MAX_TRIES], "포기 알림(시도 횟수와 함께)")
        check(not c.connected, "미연결")
    finally:
        _FakeSerial.refuse.discard(dev)
        c.close()

_REAL_RESOLVE = config.resolve_interlock_port          # _ctl 이 바꿔 끼우기 전 원본(④ 사소 5)


def test_final_minor_startup_message_many_candidates():
    """④ 미룬 사소 5 — 후보가 여럿이면 기동 안내가 「꽂히면 붙는다」가 아니라 지정하라고 한다 · 장치 없음 문구는 그대로."""
    print("\n[④ 사소 5] 기동 안내")
    import contextlib
    import io
    import types
    from serial.tools import list_ports
    fake = [types.SimpleNamespace(device="/dev/시험A", vid=0x2341, pid=0x0069),
            types.SimpleNamespace(device="/dev/시험B", vid=0x1a86, pid=0x7523)]
    old, old_env = list_ports.comports, os.environ.pop("SOP_INTERLOCK_PORT", None)
    patched = config.find_interlock_port
    config.find_interlock_port = _REAL_FIND             # 앞 시험의 _ctl 이 바꿔 끼운 것을 원본으로(감싸개가 부른다)

    def said(cands):
        list_ports.comports = lambda: cands
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _REAL_RESOLVE()
        return buf.getvalue().splitlines()

    try:
        many = said(fake)
        check(not any("꽂히면 자동으로 붙는다" in ln for ln in many), "여럿이면 「꽂히면 붙는다」라고 하지 않는다")
        check(any("SOP_INTERLOCK_PORT" in ln and "지정" in ln for ln in many), "직접 지정하라고 안내한다")
        check(said([]) == ["[config] ⚠️ 인터록 장치를 못 찾았다 (ESP32 는 인터록이 아니다)",
                           "[config] → 찾을 때까지 연결하지 않는다(꽂히면 자동으로 붙는다). "
                           "강제하려면 SOP_INTERLOCK_PORT=/dev/ttyACMx"],
              "장치 없음 문구는 글자 그대로(관문 출력이 담는다)")
    finally:
        list_ports.comports = old
        config.find_interlock_port = patched
        if old_env is not None:
            os.environ["SOP_INTERLOCK_PORT"] = old_env

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
    print("✅ 인터락 검증 통과")
