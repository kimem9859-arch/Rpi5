"""오버레이 애니메이션 관문 — 「끌 수 있는가 · 재시작하지 않는가 · 멈추는가」.

실행: python3 Demo/selftest/test_anim.py   (offscreen)

정본: 상위 docs/superpowers/specs/2026-08-16-ui-애니메이션-design.md §5

⚠️ 이 테스트는 **모양을 검사하지 않는다.** 움직임이 예쁜지는 실기동에서 눈으로 본다.
   여기서 잡는 것은 세 가지 사고다:
     ① 끕 스위치를 껐는데 최종 상태가 적용되지 않는 것
     ② _sub_timer 의 200ms 주기 반복 호출에 애니메이션이 매번 재시작되는 것
     ③ 무한 반복 맥박이 멈추지 않아 QSS 재적용으로 CPU 를 태우는 것
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget, QLabel

import config
import theme
import anim
from overlay import StatusPanel, GaugePanel, AlertBanner

_app = QApplication.instance() or QApplication([])
_w = QWidget()
_fails = []

SCREEN = QRect(0, 0, 1920, 1080)
STEPS = [
    {"order": 1, "button": "B1", "name": "클린·가스차단"},
    {"order": 2, "button": "B2", "name": "펌프/퍼지"},
    {"order": 3, "button": "B3", "name": "전극 냉각"},
    {"order": 4, "button": "B4", "name": "챔버 벤트"},
]


class _FakeSub:
    """GaugePanel.update_view 가 읽는 속성만 갖는 더미 — 시간을 실제로 흘리지 않는다."""

    def __init__(self, progress, tool_ok, wrong_tool, needs_tool=False):
        self.is_active, self.label = True, "테스트"
        self.total_sec, self.elapsed_sec = 30, 30 * progress
        self.progress, self.time_done = progress, progress >= 1.0
        self.needs_tool, self.want_tool_name = needs_tool, "렌치"
        self.tool_ok, self.wrong_tool = tool_ok, wrong_tool


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_gate_off_applies_final_state():
    """🔴 관문 ① — 꺼져 있으면 애니메이션 없이 최종 상태가 즉시 적용된다."""
    print("\n[게이트 OFF]")
    config.UI_ANIMATION = False
    seen = []
    a = anim.tween(_w, 300, lambda t: seen.append(float(t)))
    check(a is None, "꺼짐: 애니메이션 객체를 만들지 않는다")
    check(seen == [1.0], f"꺼짐: 최종값 1.0 만 한 번 적용된다 (실제 {seen})")

    lbl = QLabel(_w)
    lbl.setStyleSheet("color: red;")
    anim.slide_in(lbl, QRect(10, 20, 30, 40))
    check(lbl.geometry() == QRect(10, 20, 30, 40),
          "꺼짐: slide_in 이 목표 위치에 즉시 놓는다")
    config.UI_ANIMATION = True


def test_pulse_stops():
    """🔴 관문 ③ — 맥박은 멈춘다. 안 멈추면 QSS 재적용으로 CPU 를 태운다."""
    print("\n[맥박 정지]")
    p = anim.Pulse(_w, lambda: "", theme.C("danger"))
    p.start()
    check(p.active(), "start 후 active")
    p.stop()
    check(not p.active(), "stop 후 정지")
    p.stop()
    check(not p.active(), "두 번 stop 해도 예외 없이 정지 상태")


def test_busy_flag():
    """relayout 회피의 근거 — 슬라이드 중에는 busy 가 True."""
    print("\n[busy 표시]")
    lbl = QLabel(_w)
    anim.slide_in(lbl, QRect(0, 0, 10, 10))
    check(anim.busy(lbl), "슬라이드 중 busy")


def test_gauge_no_restart_on_same_value():
    """🔴 관문 ② — _sub_timer 가 200ms 마다 같은 값을 다시 넣어도 재시작하지 않는다."""
    print("\n[게이지 재시작 방지]")
    g = GaugePanel(_w)
    sub = _FakeSub(progress=0.5, tool_ok=False, wrong_tool=None)
    g.update_view(sub)
    first = g._gauge_anim
    for _ in range(5):
        g.update_view(sub)                      # 같은 값 반복 — 실제 런타임의 5Hz 호출
    check(g._gauge_anim is first, "같은 값 반복 호출은 애니메이션을 재시작하지 않는다")


def test_gauge_flashes_only_on_tool_change():
    """공구 상태가 바뀐 순간에만 번진다."""
    print("\n[공구 상태 변화 감지]")
    g = GaugePanel(_w)
    sub = _FakeSub(progress=0.3, tool_ok=False, wrong_tool=None, needs_tool=True)
    g.update_view(sub)
    check(g._prev_tool == (False, None), "직전 공구 상태를 기억한다")
    sub.tool_ok = True
    g.update_view(sub)
    check(g._prev_tool == (True, None), "바뀐 값으로 갱신된다")


def test_status_step_change_gate():
    """단계가 바뀐 순간에만 전환 연출을 건다."""
    print("\n[단계 전환 감지]")
    s = StatusPanel(STEPS, _w)
    s.update_view("PROCESS_RUN", 1)
    check(s._prev_step == 1, "직전 단계를 기억한다")
    for _ in range(3):
        s.update_view("PROCESS_RUN", 1)         # 같은 단계 반복
    check(s._prev_step == 1, "같은 단계 반복은 상태를 바꾸지 않는다")
    s.update_view("PROCESS_RUN", 2)
    check(s._prev_step == 2, "단계가 바뀌면 갱신된다")


def test_alert_pulse_lifecycle():
    """🔴 차단에서만 맥박하고, 벗어나면 반드시 멈춘다."""
    print("\n[배너 맥박 수명]")
    a = AlertBanner(_w)
    a.show_order_violation("B2", "펌프/퍼지")
    check(not a._pulse.active(), "경고에서는 맥박하지 않는다")
    a.show_block()
    check(a._pulse.active(), "차단에서 맥박한다")
    a.show_order_violation("B2", "펌프/퍼지")
    check(not a._pulse.active(), "차단을 벗어나면 멈춘다")
    a.show_block()
    a.hide_all()
    check(not a._pulse.active(), "숨기면 멈춘다")


def test_alert_entrance_happens_at_relayout():
    """등장은 위치를 정하는 relayout 이 실행한다 — _paint 는 예약만."""
    print("\n[배너 등장 시점]")
    a = AlertBanner(_w)
    a.show_order_violation("B2", "펌프/퍼지")
    check(a._needs_entrance, "_paint 는 등장을 예약만 한다")
    a.relayout(SCREEN)
    check(not a._needs_entrance, "relayout 이 등장을 실행하고 예약을 지운다")


def test_alert_relayout_skips_while_sliding():
    """슬라이드 중 relayout 이 geometry 를 덮어쓰면 위치가 튄다."""
    print("\n[슬라이드 중 relayout 회피]")
    a = AlertBanner(_w)
    a.show_block()
    anim.slide_in(a, QRect(0, 0, 100, 50))
    before = a.geometry()
    a.relayout(SCREEN)
    check(a.geometry() == before, "슬라이드 중에는 relayout 이 geometry 를 건드리지 않는다")
    a.hide_all()


def test_status_label_is_korean_and_consistent():
    """🔴 상태 표시명 — 기동 직후와 작업 초기화 후가 **같아야 한다**.

    2026-08-16: 종전에는 기동 직후 화면에 `STANDBY`(FSM 에 없는 하드코딩)가 뜨고
    초기화 후에는 `IDLE` 이 떠서, 같은 상태가 두 이름으로 보였다.
    표시명 정본 = 상위 specs/2026-08-03-uiux-글라스-design.md §4.1 표.
    """
    print("\n[상태 표시명]")
    s = StatusPanel(STEPS, _w)
    boot_text = s._state.text()                 # 만들자마자 = 기동 직후 화면
    check("대기 중" in boot_text, f"기동 직후 「대기 중」 (실제 {boot_text!r})")

    s.update_view("PROCESS RUN", 2)
    s.update_view("IDLE", 1)                    # 작업 초기화가 넣는 값
    check(s._state.text() == boot_text,
          f"초기화 후가 기동 직후와 같다 ({s._state.text()!r} vs {boot_text!r})")

    for value, label in (("PROCESS RUN", "작업 진행 중"), ("WARNING", "경고"),
                         ("BLOCK", "차단됨"), ("MONITOR", "감시 중"), ("READY", "준비")):
        s.update_view(value, 1)
        check(label in s._state.text(), f"{value} → {label} (실제 {s._state.text()!r})")


def test_status_steps_all_pending_before_start():
    """🔴 작업 시작 전에는 어느 단계도 「현재」로 강조되지 않는다(design §4.1).

    종전 STANDBY 하드코딩 탓에 기동 직후 1단계가 ▶ 로 강조돼 있었다.
    """
    print("\n[시작 전 단계 표시]")
    s = StatusPanel(STEPS, _w)
    marks = [r.text()[0] for r in s._rows]
    check(all(m == "○" for m in marks), f"전부 ○ (실제 {marks})")

    s.update_view("IDLE", 1)
    marks = [r.text()[0] for r in s._rows]
    check(all(m == "○" for m in marks), f"초기화 후에도 전부 ○ (실제 {marks})")


def test_text_pulse():
    """🔴 글자 맥박 — 시작·정지가 되고, 꺼져 있으면 최종값만 먹는가."""
    print("\n[글자 맥박]")
    from PyQt6.QtWidgets import QLabel
    lbl = QLabel("렌치가 필요합니다")

    config.UI_ANIMATION = True
    p = anim.TextPulse(lbl, lambda: "#ffffff")
    p.start()
    check(p.active(), "start() → 돈다")
    p.start()
    check(p.active(), "두 번 불러도 재시작하지 않는다")
    p.stop()
    check(not p.active(), "stop() → 멈춘다")

    config.UI_ANIMATION = False
    p2 = anim.TextPulse(lbl, lambda: "#ffffff")
    p2.start()
    check(not p2.active(), "애니메이션 OFF → 애니메이션을 만들지 않는다")
    check("255,255,255" in lbl.styleSheet().replace(" ", ""),
          "OFF 여도 최종 색은 적용된다")
    config.UI_ANIMATION = True


def test_fps_from_intervals():
    """도착 간격 목록에서 FPS 를 낸다. 카메라가 없으면 None."""
    print("\n[FPS 계산]")
    # 🔴 safety_console 이 아니라 fps 모듈에서 가져온다 — GUI 모듈을 import 하면
    #    Hailo 백엔드가 함께 열리고 종료 시 죽어서(기존 현상) exit code 판정이 막힌다.
    from fps import fps_from_intervals
    check(fps_from_intervals([]) is None, "표본 없음 → None (카메라 없을 때)")
    check(abs(fps_from_intervals([0.1] * 10) - 10.0) < 0.01, "0.1초 간격 → 10.0fps")
    check(abs(fps_from_intervals([0.1, 0.1, 5.0]) - 10.0) < 0.01,
          "중앙값이라 멈춤 구간 하나에 흔들리지 않는다")


def test_fps_stale():
    """프레임이 끊겼는지 판정한다 — 🔴 중앙값이 끊김을 감추기 때문에 필요하다."""
    print("\n[FPS 신선도]")
    from fps import fps_stale
    check(fps_stale(0.0, now=100.0), "프레임을 한 번도 못 받았다 → 끊김")
    check(not fps_stale(99.5, now=100.0), "0.5초 전 프레임 → 정상")
    check(not fps_stale(98.5, now=100.0), "1.5초 전 프레임 → 아직 정상(임계 2.0)")
    check(fps_stale(97.0, now=100.0), "3초 전 프레임 → 끊김")
    check(fps_stale(99.0, now=100.0, stale_after=0.5), "임계를 좁히면 끊김으로 본다")


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
    print("✅ 애니메이션 관문 통과")
