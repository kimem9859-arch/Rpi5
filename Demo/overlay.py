"""글라스 UI 오버레이 위젯 — 영상 위에 반투명으로 얹히는 정보 패널.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §1·§4

배치 규칙:
    🔴 **고정 픽셀을 쓰지 않는다.** 창 크기가 바뀌므로 부모 크기에 **%를 곱해** 계산한다.
    % 값은 design §1 표가 정본이다. 여기 상수(_POS)가 그 사본이며, 바꿀 때는
    문서를 먼저 고친다.

색·글꼴:
    색은 `theme.py`, 글꼴은 `config.font()`. 이 파일에 색 코드를 직접 쓰지 않는다.

🔴 글자 그림자는 넣지 않는다 (2026-08-03 실기동에서 폐기):
    Qt 스타일시트에 text-shadow 가 없어 QGraphicsDropShadowEffect 로 대신했더니
    "QPainter::begin: A paint device can only be painted by one painter at a time" 가
    끝없이 나면서 **화면이 안 그려지고 클릭도 안 먹었다**(CPU 60%).
    효과가 걸린 위젯 안에 또 효과가 걸린 자식이 있으면 페인터가 충돌한다.
    → 대비는 **색으로만** 낸다. design §3 의 색 대비가 원래 주된 수단이었다.
"""

from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
)

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
    """글자 후광 — 🔴 **쓰지 않는다.** (2026-08-03 실기동에서 폐기)

    QGraphicsDropShadowEffect 를 패널 안 QLabel 마다 걸었더니 Qt 가
        "QPainter::begin: A paint device can only be painted by one painter at a time"
    를 끝없이 뱉으며 **화면이 안 그려지고 클릭도 안 먹었다.** CPU 도 60%를 태웠다.
    효과가 걸린 위젯 안에 또 효과가 걸린 자식이 있으면 페인터가 충돌한다.

    → 대비는 **색으로만** 낸다. design §3 이 정한 색 대비(순검정 판 60% + 예정단계
      #c3c9cf 상향 등)가 원래 주된 수단이고 그림자는 보조였다. 보조를 뺀다.

    함수는 호출부를 건드리지 않으려고 남겨 둔다 — 아무 일도 하지 않는다.
    """
    return


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


# =============================================================================
# [경고·차단] design §4.5·§4.6
# =============================================================================

_BANNER_POS = {"width": 0.44, "bottom": 0.13}
_BLOCK_POS  = {"width": 0.46}


class GlowFrame(QWidget):
    """상태 발광 테두리.

    🔴 **영상 영역(가운데 75%)에만** 걸린다 — 검정 레터박스는 빛나지 않는다(design §4.5).
       그래서 부모 전체가 아니라 영상 사각형에 맞춰 배치한다.
    """

    _SPEC = {
        "warn":  ("warn",   9, 60),    # (색 토큰, 테두리 두께 px, 안쪽 번짐 px)
        "block": ("danger", 12, 90),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._level = None
        self.hide()

    def set_level(self, level):
        """level: None | "warn" | "block"."""
        self._level = level
        if level is None:
            self.hide()
            return
        token, border, spread = self._SPEC[level]
        c = theme.C(token)
        self.setStyleSheet(
            f"background: transparent;"
            f"border: {border}px solid {c};"
            f"border-radius: 6px;")
        self.raise_()
        self.show()

    @property
    def level(self):
        return self._level

    def relayout(self, parent_rect):
        """영상 영역 = 가운데 75%. 좌우 12.5%씩 검정."""
        pw, ph = parent_rect.width(), parent_rect.height()
        self.setGeometry(QRect(int(pw * VIDEO_LEFT_RATIO), 0,
                               int(pw * VIDEO_WIDTH_RATIO), ph))


class AlertBanner(_Panel):
    """경고·차단 배너.

    두 종류의 경고가 있고 **해제 버튼 유무가 다르다**(design §4.3·§4.5):
      - 순서 위반: 손을 뗐는지 시스템이 알 수 없어 **사람이 해제**해야 한다 → 버튼 있음
      - 공구 오선택: 다시 보면 안다 → **버튼 없음.** 올바른 공구로 바꾸면 스스로 풀린다
        (버튼을 두면 잘못된 공구를 든 채 넘어갈 수 있다)
    """

    release_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._mode = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self._icon = QLabel("⚠")
        self._icon.setFont(config.font("cta", 800))
        lay.addWidget(self._icon)

        col = QVBoxLayout()
        col.setSpacing(3)
        self._title = QLabel("")
        self._title.setFont(config.font("banner", 800))
        self._line1 = QLabel("")
        self._line1.setFont(config.font("body", 600))
        self._line1.setWordWrap(True)
        self._line2 = QLabel("")
        self._line2.setFont(config.font("body", 600))
        self._line2.setWordWrap(True)
        col.addWidget(self._title)
        col.addWidget(self._line1)
        col.addWidget(self._line2)
        lay.addLayout(col, 1)

        self._release = QPushButton("해제")
        self._release.setFont(config.font("body", 700))
        self._release.setCursor(Qt.CursorShape.PointingHandCursor)
        self._release.clicked.connect(self.release_clicked.emit)
        lay.addWidget(self._release)

        self.hide()

    # --------------------------------------------------------------- 표시
    def show_order_violation(self, expected_button, expected_name):
        """순서 위반 — 해제 버튼 있음. 안내 2줄(2번째 줄 들여쓰기)."""
        self._mode = "order"
        self._paint("warn", "⚠", "순서가 다릅니다",
                    f"지금은 {expected_button} {expected_name} 차례입니다",
                    f"— 손을 뗀 뒤 {expected_button}를 누르세요",
                    release_text="경고 해제", indent2=True)

    def show_wrong_tool(self, wrong_name, want_name):
        """공구 오선택 — 🔴 해제 버튼 없음. 문장이 짧아 들여쓰기도 하지 않는다."""
        self._mode = "tool"
        self._paint("warn", "⚠", "다른 공구입니다",
                    f"가져온 것: {wrong_name} — {want_name}로 바꿔 주세요",
                    "", release_text=None, indent2=False)

    def show_block(self, reason="순서 위반이 계속되어 인터락이 작동했습니다"):
        """차단 — 해제 버튼 있음(EMO 미복귀 거부는 기존 _release_block 이 담당)."""
        self._mode = "block"
        self._paint("danger", "⛔", "전기 입력 차단됨", reason, "",
                    release_text="차단 해제", indent2=False)

    def _paint(self, token, mark, title, line1, line2, release_text, indent2):
        c = theme.C(token)
        self._icon.setText(mark)
        self._icon.setStyleSheet(theme.text_qss(token, 800))
        self._title.setText(title)
        self._title.setStyleSheet(theme.text_qss(token, 800))
        for lbl, text in ((self._line1, line1), (self._line2, line2)):
            lbl.setText(text)
            lbl.setStyleSheet(theme.text_qss("text", 600))
            lbl.setVisible(bool(text))
        self._line2.setStyleSheet(
            theme.text_qss("text", 600) + ("padding-left: 14px;" if indent2 else ""))

        if release_text:
            self._release.setText(release_text)
            self._release.setStyleSheet(
                f"QPushButton {{ background-color: {c}; color: {theme.C('cta_text')};"
                f" border: 1px solid {c}; border-radius: 6px; padding: 10px 18px; }}")
            self._release.show()
        else:
            self._release.hide()

        self.setStyleSheet(theme.panel_qss("sheet", padding="14px 18px")
                           + f"border-color: {c};")
        for lbl in (self._icon, self._title, self._line1, self._line2):
            _glow(lbl)
        self.raise_()
        self.show()

    @property
    def mode(self):
        return self._mode

    def hide_all(self):
        self._mode = None
        self.hide()

    def relayout(self, parent_rect):
        if self._mode == "block":
            place(self, parent_rect, width=_BLOCK_POS["width"])       # 중앙을 가린다
        else:
            place(self, parent_rect, width=_BANNER_POS["width"],
                  bottom=_BANNER_POS["bottom"])
