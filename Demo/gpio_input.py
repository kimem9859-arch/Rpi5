"""물리 입력 (버튼 B1~B4 · EMO) → Pi GPIO → FSM. 트랙 A 입력부.

설계 정본: `../dev/interlock/결선도_초안.md` §3.1
  - B1~B4 = GPIO5/6/13/19. active-low 모멘터리(INPUT_PULLUP, 눌림=LOW).
  - EMO   = GPIO26. **NC쌍 + INPUT_PULLUP**, 평소 LOW=정상 / 누름·단선=HIGH=비상.
    → NC가 닫혀 있으면(정상) 핀이 GND로 당겨져 LOW, 누르거나 선이 끊기면(비상)
      풀업으로 HIGH. **단선도 비상으로 잡는 fail-safe.**
  - 해제 버튼(WARNING/BLOCK 해제)은 터치 UI(release_warning/release_block)라 GPIO 불필요.

설계 원칙(인터락 `interlock.py`와 동일):
  - gpiozero 미설치·핀 초기화 실패·비-Pi 환경에서도 **예외 없이 fallback**(로그만).
    GUI·FSM·키보드 시뮬 입력은 정상 동작.
  - gpiozero 콜백은 **내부 스레드**에서 불린다. 이 모듈은 콜백을 그대로 전달만 하고,
    호출부(safety_console)가 Qt 시그널로 GUI 스레드에 마샬링한다(여기서 GUI 접근 금지).

gpiozero `Button(pin, pull_up=True)` 의미:
  - is_pressed=True ⇔ 핀 LOW. when_pressed=LOW 전이, when_released=HIGH 전이.
  - B1~B4: 눌림=LOW이므로 when_pressed → 해당 버튼 발사.
  - EMO  : 비상=HIGH이므로 when_released → "EMO" 발사 (정상복귀 LOW는 UI가 처리).
"""

import config

try:
    from gpiozero import Button
except Exception:  # 비-Pi/미설치 환경에서도 import는 통과(fallback)
    Button = None


class GpioInputController:
    """물리 버튼·EMO의 GPIO 엣지를 받아 `on_button(button_id)` 콜백으로 전달.

    button_id 는 "B1".."B4" 또는 "EMO". 콜백은 gpiozero 스레드에서 호출되므로
    호출부에서 GUI 스레드로 마샬링할 것(예: pyqtSignal.emit 를 on_button 으로 주입).
    """

    def __init__(self, on_button, log=None, enabled=None):
        self._on_button = on_button
        self._log = log or (lambda m: print(m))
        self._enabled = config.GPIO_INPUT_ENABLED if enabled is None else enabled
        self._devices = []
        self._emo_device = None

        if not self._enabled:
            self._log("[입력] GPIO 입력 비활성(GPIO_INPUT_ENABLED=False) — 키보드 시뮬만")
            return
        if Button is None:
            self._log("[입력] gpiozero 미설치 — fallback(키보드 시뮬만), GUI 정상")
            return

        bounce = getattr(config, "GPIO_BOUNCE_SEC", 0.05)

        # B1~B4: active-low 모멘터리. 눌림(LOW) → press_button("Bn")
        for bid, pin in config.GPIO_BUTTON_PINS.items():
            try:
                btn = Button(pin, pull_up=True, bounce_time=bounce)
                btn.when_pressed = (lambda b=bid: self._fire(b))   # b 캡처(루프 클로저)
                self._devices.append(btn)
            except Exception as e:
                self._log(f"[입력] {bid}(GPIO{pin}) 초기화 실패: {e} — fallback")

        # EMO: NC + INPUT_PULLUP. 비상=HIGH=gpiozero 'released'. (정상 닫힘=LOW=pressed)
        try:
            emo_pin = config.GPIO_EMO_PIN
            emo = Button(emo_pin, pull_up=True, bounce_time=bounce)
            emo.when_released = (lambda: self._fire("EMO"))        # HIGH 전이 = 비상
            self._devices.append(emo)
            self._emo_device = emo
            # 시작 시 이미 HIGH(비상 눌림/단선/미배선)면 즉시 EMO 발사 — fail-safe.
            # NC+풀업 배선의 취지가 "단선도 비상"인데 엣지 전용이면 부팅 시 상태를
            # 놓쳐 무방비 기동한다. 미배선 콘솔은 GPIO_INPUT_ENABLED=False 로 끌 것.
            if not emo.is_pressed:
                self._log(f"[입력] 🚨 EMO(GPIO{emo_pin}) 시작 시 HIGH(비상/단선/미배선) — 즉시 BLOCK")
                self._fire("EMO")
        except Exception as e:
            self._log(f"[입력] EMO 초기화 실패: {e} — fallback")

        if self._devices:
            self._log(f"[입력] GPIO 입력 활성 — 버튼 {list(config.GPIO_BUTTON_PINS)} + EMO(GPIO{config.GPIO_EMO_PIN})")

    def emo_active(self):
        """EMO가 현재 비상 레벨(HIGH = 눌림/단선)인지. GPIO 미사용 환경은 False.

        엣지 콜백과 별개의 **레벨 조회** — BLOCK 해제 시 "EMO가 물리적으로
        복귀되지 않으면 해제 거부"에 쓴다(엣지만 보면 비상 유지 중 해제가 통과).
        """
        if self._emo_device is None:
            return False
        try:
            return not self._emo_device.is_pressed  # HIGH(released) = 비상
        except Exception:
            return False

    def _fire(self, button_id):
        """엣지 콜백 → 호출부로 전달(GUI 마샬링은 호출부 책임). 예외는 흡수."""
        try:
            self._on_button(button_id)
        except Exception as e:
            self._log(f"[입력] 콜백 오류({button_id}): {e}")

    def close(self):
        """모든 GPIO 디바이스 해제(핀 반환)."""
        for d in self._devices:
            try:
                d.close()
            except Exception:
                pass
        self._devices = []
