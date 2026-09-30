"""GPIO 입력 — 켤 때 EMO 신호가 없으면(HIGH) 따로 알린다(2026-09-30 실HW).

실행: python3 Demo/selftest/test_gpio_input.py

왜 필요한가:
    EMO 는 NC 쌍 + 풀업이라 **누름과 배선 끊김이 같은 HIGH** 다. 켤 때 이미 HIGH 면
    대개 배선 문제인데(2026-09-30 EMO 선이 35번 핀에 꽂혀 있었다) 화면은 「비상정지」라고
    단정했다. 콘솔이 문구를 가르려면 GPIO 쪽이 「켤 때부터 HIGH」를 알려 줘야 한다.

⚠️ gpiozero 가짜 핀(MockFactory)으로 돈다 — 실제 핀을 건드리지 않는다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from gpiozero import Device
from gpiozero.pins.mock import MockFactory, MockPin

import config
from gpio_input import GpioInputController

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _GroundedPin(MockPin):
    """NC 가 닫혀 GND 로 당긴 핀 — 풀업을 걸어도 LOW(정상)다.

    🔴 기본 가짜 핀은 풀업을 거는 순간 HIGH 로 바뀐다 — 미리 drive_low() 해 두면 덮인다.
    """

    def _set_pull(self, value):
        super()._set_pull(value)
        self.drive_low()


def _controller(calls, emo_low):
    Device.pin_factory = MockFactory()
    if emo_low:
        Device.pin_factory.pin(config.GPIO_EMO_PIN, pin_class=_GroundedPin)
    return GpioInputController(on_button=calls.append, log=lambda m: None, enabled=True,
                               on_emo_at_start=lambda: calls.append("시작 신호 없음"))


def test_emo_high_at_start_is_reported_before_emo():
    print("\n[켤 때 EMO HIGH]")
    calls = []
    c = _controller(calls, emo_low=False)
    check(calls == ["시작 신호 없음", "EMO"],
          f"「시작 신호 없음」을 EMO 보다 먼저 알린다 (실제 {calls})")
    c.close()


def test_emo_low_at_start_is_not_reported():
    print("\n[켤 때 EMO 정상]")
    calls = []
    c = _controller(calls, emo_low=True)
    check(calls == [], f"정상이면 아무것도 알리지 않는다 (실제 {calls})")
    c.close()


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
    print("✅ GPIO 입력 관문 통과")
