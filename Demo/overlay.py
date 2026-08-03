"""글라스 UI 오버레이 위젯 — 영상 위에 반투명으로 얹히는 정보 패널.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §1·§4

배치 규칙:
    🔴 **고정 픽셀을 쓰지 않는다.** 창 크기가 바뀌므로 부모 크기에 **%를 곱해** 계산한다.
    % 값은 design §1 표가 정본이다. 여기 상수(_POS)가 그 사본이며, 바꿀 때는
    문서를 먼저 고친다.

색·글꼴:
    색은 `theme.py`, 글꼴은 `config.font()`. 이 파일에 색 코드를 직접 쓰지 않는다.

글자 그림자:
    Qt 스타일시트에는 text-shadow 가 없다. `QGraphicsDropShadowEffect` 로 대신하는데,
    **위젯 하나에 효과 하나만** 걸 수 있어 3겹을 그대로 재현할 수는 없다.
    → 가장 큰 효과 하나(퍼지는 후광)를 걸고, 색 대비(design §3)가 나머지를 맡는다.
"""

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGraphicsDropShadowEffect
from PyQt6.QtGui import QColor

import config
import theme


# design §1 「오버레이 배치」 표의 사본 — (left, top, width) 비율. None = 계산으로 정함
_POS = {
    "status":  {"left": 0.14, "top": 0.05, "width": 0.24},
    "gauge":   {"left": 0.41, "top": 0.05, "width": 0.17},   # wait_tool 이면 0.24 로 넓어진다
    "gauge_w_tool": 0.24,
    "menu_btn":  {"right": 0.14, "top": 0.05},
    "notify_btn": {"left": 0.14, "bottom": 0.05},
}

# 영상 영역 = 화면 가운데 75% (1440/1920). 좌우 12.5%씩 검정 레터박스.
VIDEO_LEFT_RATIO = 0.125
VIDEO_WIDTH_RATIO = 0.75


def place(widget, parent_rect, left=None, top=None, width=None,
          right=None, bottom=None, height=None):
    """부모 사각형 안에 비율로 배치한다. 픽셀 계산을 한 곳에 모은다."""
    pw, ph = parent_rect.width(), parent_rect.height()
    w = int(pw * width) if width is not None else widget.sizeHint().width()
    h = int(ph * height) if height is not None else widget.sizeHint().height()
    if left is not None:
        x = int(pw * left)
    elif right is not None:
        x = pw - int(pw * right) - w
    else:
        x = (pw - w) // 2
    if top is not None:
        y = int(ph * top)
    elif bottom is not None:
        y = ph - int(ph * bottom) - h
    else:
        y = (ph - h) // 2
    widget.setGeometry(QRect(x, y, w, h))


def _glow(widget):
    """글자를 배경에서 떼어내는 후광. 테마에 따라 어둡게/밝게 뒤집는다."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(12)
    eff.setOffset(0, 1)
    eff.setColor(QColor(0, 0, 0, 230) if theme.current() == "dark"
                 else QColor(255, 255, 255, 240))
    widget.setGraphicsEffect(eff)


class _Panel(QWidget):
    """반투명 오버레이 패널의 공통 뼈대."""

    KIND = "panel"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def apply_theme(self):
        self.setStyleSheet(theme.panel_qss(self.KIND))
        for lbl in self.findChildren(QLabel):
            _glow(lbl)


class StatusPanel(_Panel):
    """좌상단 — FSM 상태 + 공정 단계 목록. 기존 StepFlowWidget 을 대체한다."""

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self._steps = list(steps)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._state = QLabel("● STANDBY")
        self._state.setFont(config.font("state", 800))
        lay.addWidget(self._state)

        self._caption = QLabel("공정 단계")
        self._caption.setFont(config.font("small"))
        lay.addWidget(self._caption)

        self._rows = []
        for _ in self._steps:
            row = QLabel()
            row.setFont(config.font("body"))
            row.setWordWrap(True)
            lay.addWidget(row)
            self._rows.append(row)

        self.update_view("STANDBY", 1)

    def update_view(self, state_value, expected_step, sub_running=False):
        """state_value = FSM State.value 문자열. sub_running 이면 현재 단계를 '진행 중'으로."""
        started = state_value != "IDLE"
        if state_value == "WARNING":
            cur_token, mark = "warn", "⚠"
        elif state_value == "BLOCK":
            cur_token, mark = "danger", "⛔"
        else:
            cur_token, mark = "current", "▶"

        self._state.setText(f"● {state_value}")
        self._state.setStyleSheet(theme.text_qss(
            "warn" if state_value == "WARNING" else
            "danger" if state_value == "BLOCK" else "done", 800))
        self._caption.setStyleSheet(theme.text_qss("label", 600))

        for i, (s, row) in enumerate(zip(self._steps, self._rows)):
            order = i + 1
            text = f"{s['button']} {s.get('name', '')}"
            if not started:
                row.setText(f"○ {text}")
                row.setStyleSheet(theme.text_qss("todo", 600))
            elif order < expected_step:
                row.setText(f"✓ {text}")
                row.setStyleSheet(theme.text_qss("done", 600))
            elif order == expected_step:
                row.setText(f"{mark} {text}")
                row.setStyleSheet(theme.text_qss(cur_token, 800)
                                  + f"border-left: 3px solid {theme.C(cur_token)}; padding-left: 7px;")
            else:
                row.setText(f"○ {text}")
                row.setStyleSheet(theme.text_qss("todo", 600))

    def relayout(self, parent_rect):
        p = _POS["status"]
        place(self, parent_rect, left=p["left"], top=p["top"], width=p["width"])


class GaugePanel(_Panel):
    """상단 중앙 — 서브 작업 대기 게이지(+ 공구 지시).

    `wait_tool` 이면 폭이 17% → 24% 로 넓어지고 아래 칸이 생긴다(design §4.3).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._needs_tool = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        head = QHBoxLayout()
        self._label = QLabel("")
        self._label.setFont(config.font("small"))
        self._time = QLabel("")
        self._time.setFont(config.font("small", 700))
        self._time.setAlignment(Qt.AlignmentFlag.AlignRight)
        head.addWidget(self._label)
        head.addWidget(self._time)
        lay.addLayout(head)

        self._track = QWidget()
        self._track.setFixedHeight(8)
        self._fill = QWidget(self._track)
        lay.addWidget(self._track)

        # 공구 칸 — wait_tool 일 때만 보인다
        self._tool_box = QWidget()
        tb = QHBoxLayout(self._tool_box)
        tb.setContentsMargins(0, 8, 0, 0)
        tb.setSpacing(8)
        self._tool_icon = QLabel("🔧")
        self._tool_icon.setFont(config.font("banner"))
        self._tool_text = QLabel("")
        self._tool_text.setFont(config.font("body", 800))
        self._tool_state = QLabel("")
        self._tool_state.setFont(config.font("small"))
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(self._tool_text)
        col.addWidget(self._tool_state)
        tb.addWidget(self._tool_icon)
        tb.addLayout(col)
        lay.addWidget(self._tool_box)
        self._tool_box.hide()

        self.hide()

    def update_view(self, sub):
        """sub = SubTask 또는 None. None 이면 패널을 숨긴다."""
        if sub is None or not sub.is_active:
            self.hide()
            return

        self._needs_tool = sub.needs_tool
        self._label.setText(sub.label)
        self._label.setStyleSheet(theme.text_qss("label", 600))

        remain_token = "done" if sub.time_done else "current"
        self._time.setText("완료" if sub.time_done
                           else f"{int(sub.elapsed_sec)}/{int(sub.total_sec)}s")
        self._time.setStyleSheet(theme.text_qss(remain_token, 700))

        self._track.setStyleSheet(theme.gauge_qss())
        w = int(self._track.width() * sub.progress)
        self._fill.setGeometry(0, 0, w, 8)
        fill_color = theme.C("done") if sub.time_done else theme.C("gauge_to")
        self._fill.setStyleSheet(
            f"background-color: {fill_color}; border-radius: 4px;")

        if sub.needs_tool:
            self._tool_box.show()
            self._tool_text.setText(f"{sub.want_tool_name}를 가져오세요")
            self._tool_text.setStyleSheet(theme.text_qss("text", 800))
            if sub.tool_ok:
                self._tool_state.setText(f"✓ {sub.want_tool_name} 확인됨")
                self._tool_state.setStyleSheet(theme.text_qss("done", 600))
            else:
                self._tool_state.setText("○ 콘솔 앞에 놓으면 확인됩니다")
                self._tool_state.setStyleSheet(theme.text_qss("label", 600))
        else:
            self._tool_box.hide()

        self.show()

    def relayout(self, parent_rect):
        p = _POS["gauge"]
        width = _POS["gauge_w_tool"] if self._needs_tool else p["width"]
        place(self, parent_rect, left=p["left"], top=p["top"], width=width)
