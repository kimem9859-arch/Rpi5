#!/usr/bin/env python3
"""GPIO 입력 준비 판정 시험 — `GpioInputController.available`·`reason` 과 precheck 「GPIO 입력」 행.

왜: precheck 가 `getattr(gpio, "available", True)` 로 읽는데 속성이 없어서
    GPIO 가 꺼져 있거나 핀 초기화가 실패해도 언제나 「준비됨」이었다(2026-09-11 확인,
    짝 결함 interlock.connected = fdf548b). 실HW 없이 가짜 Button 으로 확인한다.

실행: cd Demo && python3 test/test_gpio_available.py   → 「✅ 통과」 / 「❌ 실패 N건」(exit 1)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config          # noqa: E402
import gpio_input      # noqa: E402
import precheck        # noqa: E402

fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)


def fake_button(bad_pins=(), emo_high=False, emo_read_error=False):
    class FakeButton:
        def __init__(self, pin, pull_up=True, bounce_time=None):
            if pin in bad_pins:
                raise RuntimeError("pin busy")
            self.pin = pin
            self.when_pressed = None
            self.when_released = None

        @property
        def is_pressed(self):
            if self.pin == config.GPIO_EMO_PIN:
                if emo_read_error:
                    raise OSError("read failed")
                return not emo_high         # EMO 정상 = LOW = pressed · 비상/단선 = HIGH
            return True

        def close(self):
            pass
    return FakeButton


def make(button, enabled=True):
    gpio_input.Button = button
    return gpio_input.GpioInputController(on_button=lambda b: None, log=lambda m: None, enabled=enabled)


def gpio_row(ctrl):
    return next(r for r in precheck.run_stage1({"gpio_input": ctrl}) if r.key == "gpio")


def case(name, ctrl, want_ok, reason_has):
    ok = getattr(ctrl, "available", None)
    check(ok is want_ok, "%s: available=%r (기대 %r)" % (name, ok, want_ok))
    reason = getattr(ctrl, "reason", "")
    if reason_has:
        check(reason_has in (reason or ""), "%s: reason=%r 에 %r 없음" % (name, reason, reason_has))
    row = gpio_row(ctrl)
    check(row.ok is want_ok, "%s: precheck GPIO 행 ok=%r (기대 %r)" % (name, row.ok, want_ok))
    if not want_ok and reason_has:
        check(reason_has in row.detail, "%s: precheck 문구 %r 에 사유 없음" % (name, row.detail))


orig = gpio_input.Button
try:
    b3 = config.GPIO_BUTTON_PINS["B3"]
    case("비활성", make(fake_button(), enabled=False), False, "GPIO_INPUT_ENABLED")
    case("gpiozero 없음", make(None), False, "gpiozero")
    case("버튼 하나 실패", make(fake_button(bad_pins=(b3,))), False, "B3")
    case("EMO 실패", make(fake_button(bad_pins=(config.GPIO_EMO_PIN,))), False, "EMO")
    case("전부 성공", make(fake_button()), True, "")
    case("EMO 생성 뒤 읽기 예외", make(fake_button(emo_read_error=True)), False, "EMO")
    fired = []
    gpio_input.Button = fake_button(emo_high=True)
    hot = gpio_input.GpioInputController(on_button=fired.append, log=lambda m: None, enabled=True)
    check(hot.available is True and fired == ["EMO"], "시작 시 EMO 비상: 초기화는 성공(available True) · EMO 즉시 발사 — %r %r" % (hot.available, fired))
    ok = make(fake_button()); ok.close()
    check(ok.available is False and "close" in ok.reason, "close() 뒤에는 준비됨이 아니다 — %r %r" % (ok.available, ok.reason))
    check(gpio_row(make(None)).retryable is False, "GPIO 행에 동작하지 않는 「재연결」 버튼을 붙이지 않는다")
    check(not gpio_row(None).ok, "gpio_input 이 없으면(None) 준비됨이 아니다")
    check(config.GPIO_BOUNCE_SEC == 0.2, "디바운스 0.2(2026-09-11 임시 확정) — 지금 %r" % config.GPIO_BOUNCE_SEC)
finally:
    gpio_input.Button = orig

if fails:
    print("❌ 실패 %d건\n   - " % len(fails) + "\n   - ".join(fails))
    sys.exit(1)
print("✅ 통과 — GPIO 준비 판정 5경우 + None + 디바운스 0.2")
