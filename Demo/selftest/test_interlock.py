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

    def __init__(self, port, baud, timeout=None, write_timeout=None):
        if not str(port).startswith(tempfile.gettempdir()):
            raise RuntimeError(f"🔴 시험이 실제 장치를 열려고 했다: {port}")
        if not os.path.exists(port):
            raise OSError(f"no such port {port}")
        self.port = port
        self.is_open = True
        self.writes = []
        self._acks = 0
        _FakeSerial.opened.append(self)

    def write(self, b):
        if not os.path.exists(self.port):
            raise OSError("device gone")
        self.writes.append(b.decode().strip())
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
    config.resolve_interlock_port = lambda quiet=False: port_box["p"]
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
