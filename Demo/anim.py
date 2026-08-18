"""오버레이 애니메이션 도우미 — 정본: 상위 specs/2026-08-16-ui-애니메이션-design.md

🔴 QGraphicsEffect(DropShadow·Opacity)를 쓰지 않는다 — overlay.py `_glow()` 참조.
   페인터 충돌로 화면이 안 그려지고 클릭도 안 먹었다(CPU 60%).
   투명도는 QSS 색의 알파를 QVariantAnimation 으로 굴려서 낸다.
🔴 테두리 **두께**를 애니메이션하지 않는다 — 레이아웃이 밀려 글자가 흔들린다.

끄는 법: config.UI_ANIMATION = False (환경변수 SOP_UI_ANIM=0).
   꺼지면 **여기서** 최종 상태를 즉시 적용한다. 호출부에 if 를 흩지 않는다 —
   분기가 위젯마다 퍼지면 끄는 경로를 검증할 수 없다.

🔴 호출부는 「직전 상태와 달라졌을 때만」 이 도우미를 부른다 — safety_console 의
   _sub_timer 가 200ms 주기로 갱신 함수를 반복 호출하므로, 비교 없이 걸면
   초당 5번 재시작돼 끝나지 않는 애니메이션이 된다.
"""

from PyQt6.QtCore import QVariantAnimation, QEasingCurve
from PyQt6.QtGui import QColor

import config

# 지속시간(ms) — 값의 단일 출처. 실기동에서 눈으로 보고 조정한다.
D_FLASH = 520      # 줄 반짝
D_SLIDE = 260      # 배너 등장
D_BAR   = 300      # 현재 단계 막대
D_GAUGE = 200      # 게이지 따라가기 (_sub_timer 주기와 같게 — 끊기지 않는다)
D_PULSE = 620      # 차단 맥박 반주기
D_TEXT_PULSE = 1600   # 글자 맥박 한 바퀴(ms) — 실기동 목업에서 정한 값
SLIDE_DY = 40      # 배너가 아래에서 올라오는 거리(px)

_BUSY = "_anim_busy"


def enabled():
    return bool(getattr(config, "UI_ANIMATION", True))


def tween(parent, ms, on_step, curve=QEasingCurve.Type.OutCubic, on_done=None, loops=1):
    """0.0 → 1.0 보간. 꺼져 있으면 최종값만 적용하고 None 을 준다."""
    if not enabled():
        on_step(1.0)
        if on_done:
            on_done()
        return None
    a = QVariantAnimation(parent)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    a.setLoopCount(loops)
    a.valueChanged.connect(on_step)
    if on_done:
        a.finished.connect(on_done)
    a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return a


def flash(widget, color_hex, ms=D_FLASH):
    """한 줄을 잠깐 반짝. 원래 QSS 를 기억했다가 그대로 되돌린다."""
    if not enabled():
        return
    base = widget.styleSheet()

    def step(t):
        c = QColor(color_hex)
        alpha = 0.45 * (1.0 - float(t))
        widget.setStyleSheet(
            base + f"background-color: rgba({c.red()},{c.green()},{c.blue()},{alpha:.3f});")

    tween(widget, ms, step, curve=QEasingCurve.Type.OutQuad,
          on_done=lambda: widget.setStyleSheet(base))


def slide_in(widget, target, ms=D_SLIDE, dy=SLIDE_DY):
    """아래(dy>0)에서 미끄러져 목표 사각형에 앉는다. geometry 만 움직인다."""
    if not enabled():
        widget.setGeometry(target)
        widget.show()
        return
    widget.setGeometry(target.translated(0, dy))
    widget.show()
    setattr(widget, _BUSY, True)
    tween(widget, ms,
          lambda t: widget.setGeometry(target.translated(0, int(dy * (1 - float(t))))),
          on_done=lambda: setattr(widget, _BUSY, False))


def busy(widget):
    """위치 애니메이션이 진행 중인가 — relayout 이 geometry 를 덮어쓰지 않게 확인한다."""
    return bool(getattr(widget, _BUSY, False))


class Pulse:
    """테두리 색이 천천히 맥박한다(차단 배너).

    🔴 반드시 stop() 으로 멈춘다 — 살아남으면 QSS 를 계속 재적용해 CPU 를 태운다.
    base_qss_fn: 맥박이 덧씌울 바탕 QSS 를 그때그때 만들어 주는 함수(테마 전환 대응).
    """

    def __init__(self, widget, base_qss_fn, color_hex):
        self._w = widget
        self._base = base_qss_fn
        self._c = color_hex
        self._anim = None

    def start(self):
        if self._anim is not None:
            return                      # 이미 뛰고 있으면 재시작하지 않는다
        base = self._base()
        c = QColor(self._c)

        def step(t):
            a = 0.30 + 0.70 * float(t)
            self._w.setStyleSheet(
                base + f"border: 1px solid rgba({c.red()},{c.green()},{c.blue()},{a:.2f});")

        if not enabled():
            step(1.0)
            return
        self._anim = tween(self._w, D_PULSE, step,
                           curve=QEasingCurve.Type.InOutSine, loops=-1)

    def stop(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def active(self):
        return self._anim is not None


class TextPulse:
    """글자색 알파가 천천히 오르내린다(공구 문구).

    🔴 반드시 stop() 으로 멈춘다 — 살아남으면 QSS 를 계속 재적용해 CPU 를 태운다.
    🔴 크기·두께가 아니라 **색만** 흔든다 — 굵기를 흔들면 레이아웃이 밀린다.
    color_fn: 그때그때 색(#RRGGBB)을 주는 함수(테마 전환 대응).
    """

    def __init__(self, widget, color_fn, weight=800, floor=0.40, ms=D_TEXT_PULSE):
        self._w = widget
        self._color = color_fn
        self._weight = weight
        self._floor = floor
        self._ms = ms
        self._anim = None

    def _apply(self, a):
        c = QColor(self._color())
        self._w.setStyleSheet(
            f"color: rgba({c.red()},{c.green()},{c.blue()},{a:.3f});"
            f"font-weight: {self._weight}; border: none; background: transparent;")

    def start(self):
        if self._anim is not None:
            return                      # 이미 뛰고 있으면 재시작하지 않는다
        if not enabled():
            self._apply(1.0)
            return
        floor = self._floor

        def step(t):
            # 0→1 을 삼각파로 접어 한 바퀴에 밝아졌다 어두워진다
            u = 1.0 - abs(2.0 * float(t) - 1.0)
            self._apply(floor + (1.0 - floor) * u)

        self._anim = tween(self._w, self._ms, step,
                           curve=QEasingCurve.Type.InOutSine, loops=-1)

    def stop(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._apply(1.0)               # 멈추면 또렷한 상태로 남는다

    def active(self):
        return self._anim is not None
