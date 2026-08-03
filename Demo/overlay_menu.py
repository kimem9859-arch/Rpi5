"""글라스 UI — 메뉴 · 알림 · 설정 패널.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §4.4·§4.7·§4.8

세 패널의 공통 성격:
    상시 노출이 아니라 **열었을 때만** 나온다. 그래서 배경을 진하게(`sheet`) 두어
    가독성을 우선한다 — 시야를 막는 시간이 짧기 때문이다.

로그와 알림은 역할이 다르다:
    로그(메뉴 안)는 **전부**를 시간순으로 담고, 알림은 **알려야 할 것만** 골라 띄운다.
    둘 다 유지한다.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QRadioButton, QButtonGroup, QFrame,
)

import config
import theme
from overlay import place, _glow


# 알림 종류 — design §4.8. (기호, 색 토큰)
NOTIFY_KINDS = {
    "check": ("✓", "done"),      # 점검
    "work":  ("▶", "info"),      # 이벤트 — 작업
    "warn":  ("⚠", "warn"),      # 이벤트 — 경고
    "danger": ("⛔", "danger"),   # 이벤트 — 위험
}

_MENU_POS = {"right": 0.14, "top": 0.05, "width": 0.13, "bottom": 0.05}
_NOTIFY_POS = {"left": 0.14, "top": 0.48, "width": 0.27, "bottom": 0.05}
_SETTINGS_W = 0.34


class _Sheet(QWidget):
    """열었을 때만 나오는 진한 패널."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()

    def apply_theme(self):
        self.setStyleSheet(theme.panel_qss("sheet", padding="10px 12px"))
        for lbl in self.findChildren(QLabel):
            _glow(lbl)


def _row_button(text, token="text"):
    b = QPushButton(text)
    b.setFont(config.font("body", 600))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFlat(True)
    b.setStyleSheet(
        f"QPushButton {{ color: {theme.C(token)}; background: transparent; border: none;"
        f" text-align: left; padding: 9px 2px; }}"
        f"QPushButton:hover {{ color: {theme.C('info')}; }}")
    return b


class MenuPanel(_Sheet):
    """우상단 세로 메뉴 — design §4.7.

    🔴 시스템 종료는 맨 아래로 분리 + 구분선. 비가역 동작이라 다른 항목과 섞지 않는다.
       (확인창은 기존 `_on_shutdown_clicked` 가 그대로 담당한다.)
    """

    log_clicked = pyqtSignal()
    calibrate_clicked = pyqtSignal()
    cctv_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    shutdown_clicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        self._title = QLabel("메뉴")
        self._title.setFont(config.font("small", 700))
        close = QPushButton("✕")
        close.setFont(config.font("body"))
        close.setFlat(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet("background: transparent; border: none;")
        close.clicked.connect(self.closed.emit)
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(close)
        lay.addLayout(head)
        lay.addWidget(self._hline())

        self._items = []
        for text, sig in (("📜  로그", self.log_clicked),
                          ("🎯  캘리브레이션", self.calibrate_clicked),
                          ("📹  CCTV 전환", self.cctv_clicked),
                          ("⚙  설정", self.settings_clicked)):
            b = _row_button(text)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
            self._items.append(b)

        # 추후 항목 자리 3칸 — design §4.7
        self._free = []
        for _ in range(3):
            f = QLabel("＋")
            f.setFont(config.font("small"))
            f.setStyleSheet(f"color: {theme.C('todo')}; padding: 9px 2px;")
            lay.addWidget(f)
            self._free.append(f)

        lay.addStretch()
        lay.addWidget(self._hline())
        self._shutdown = _row_button("⏻  시스템 종료", "danger")
        self._shutdown.clicked.connect(self.shutdown_clicked.emit)
        lay.addWidget(self._shutdown)

    @staticmethod
    def _hline():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("label", 700))
        for b in self._items:
            b.setStyleSheet(
                f"QPushButton {{ color: {theme.C('text')}; background: transparent;"
                f" border: none; text-align: left; padding: 9px 2px; }}"
                f"QPushButton:hover {{ color: {theme.C('info')}; }}")
        self._shutdown.setStyleSheet(
            f"QPushButton {{ color: {theme.C('danger')}; background: transparent;"
            f" border: none; text-align: left; padding: 9px 2px; font-weight: 700; }}")
        for f in self._free:
            f.setStyleSheet(f"color: {theme.C('todo')}; padding: 9px 2px; background: transparent;")
        for line in self.findChildren(QFrame):
            line.setStyleSheet(f"background-color: {theme.C('panel_border')}; border: none;")

    def relayout(self, parent_rect):
        p = _MENU_POS
        h = 1.0 - p["top"] - p["bottom"]
        place(self, parent_rect, right=p["right"], top=p["top"],
              width=p["width"], height=h)


class NotifyPanel(_Sheet):
    """좌하단 알림 목록 — design §4.8.

    🔴 메신저 방식 — 최신이 맨 아래, 열면 최신이 보이는 위치에서 시작,
       과거는 위로 스크롤.
    🔴 프로그램을 종료하면 초기화 — 메모리에만 둔다(파일 저장 없음).
       파일 기록은 통합문서 §13 확장의 「작업 로그 기록」과 겹쳐 보류.
    """

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QHBoxLayout()
        self._title = QLabel("🔔  알림")
        self._title.setFont(config.font("small", 700))
        close = QPushButton("✕")
        close.setFont(config.font("body"))
        close.setFlat(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet("background: transparent; border: none;")
        close.clicked.connect(self.closed.emit)
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(close)
        lay.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QWidget()
        self._list = QVBoxLayout(self._body)
        self._list.setContentsMargins(0, 4, 4, 0)
        self._list.setSpacing(6)
        self._list.addStretch()          # 위쪽에 여백 → 항목이 아래부터 쌓인다
        self._scroll.setWidget(self._body)
        lay.addWidget(self._scroll)

        self._rows = []

    def push(self, kind, title, sub=""):
        """알림 하나 추가. 최신이 맨 아래로 간다."""
        mark, token = NOTIFY_KINDS.get(kind, NOTIFY_KINDS["work"])
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        icon = QLabel(mark)
        icon.setFont(config.font("body", 800))
        icon.setStyleSheet(theme.text_qss(token, 800))
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setFont(config.font("body", 600))
        t.setStyleSheet(theme.text_qss("text", 600))
        t.setWordWrap(True)
        col.addWidget(t)
        if sub:
            s = QLabel(sub)
            s.setFont(config.font("small"))
            s.setStyleSheet(theme.text_qss("label", 500))
            s.setWordWrap(True)
            col.addWidget(s)

        rl.addWidget(icon)
        rl.addLayout(col, 1)
        self._list.addWidget(row)         # addStretch 뒤에 넣어 아래로 쌓인다
        self._rows.append(row)
        self._scroll_to_latest()

    def _scroll_to_latest(self):
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def showEvent(self, event):
        super().showEvent(event)
        self._scroll_to_latest()          # 열면 최신이 보이는 위치에서 시작

    @property
    def count(self):
        return len(self._rows)

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("label", 700))

    def relayout(self, parent_rect):
        p = _NOTIFY_POS
        h = 1.0 - p["top"] - p["bottom"]
        place(self, parent_rect, left=p["left"], top=p["top"],
              width=p["width"], height=h)


class SettingsPanel(_Sheet):
    """중앙 설정 패널 — design §4.4.

    메뉴 폭(13%)에는 라디오 항목이 안 들어가 중앙에 띄운다.
    🔴 바꾼 값은 저장하지 않는다 — 이 세션에만. 레시피가 정답 순서의 단일 출처라
       UI 가 파일을 고치기 시작하면 정본이 흐려진다.
    """

    tool_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool_buttons = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self._title = QLabel("⚙  설정")
        self._title.setFont(config.font("title", 800))
        close = QPushButton("✕")
        close.setFont(config.font("body"))
        close.setFlat(True)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet("background: transparent; border: none;")
        close.clicked.connect(self.closed.emit)
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(close)
        lay.addLayout(head)

        self._tool_caption = QLabel("4단계 지정 공구")
        self._tool_caption.setFont(config.font("small", 700))
        lay.addWidget(self._tool_caption)

        self._tool_group = QButtonGroup(self)
        self._tool_box = QVBoxLayout()
        self._tool_box.setSpacing(2)
        lay.addLayout(self._tool_box)

        self._tool_note = QLabel("")
        self._tool_note.setFont(config.font("small"))
        self._tool_note.setWordWrap(True)
        lay.addWidget(self._tool_note)

        self._theme_caption = QLabel("화면 테마")
        self._theme_caption.setFont(config.font("small", 700))
        lay.addWidget(self._theme_caption)

        self._theme_group = QButtonGroup(self)
        for key, text in (("dark", "다크  (기본)"), ("light", "화이트")):
            rb = QRadioButton(text)
            rb.setFont(config.font("body", 600))
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setChecked(key == theme.current())
            rb.toggled.connect(lambda on, k=key: on and self.theme_changed.emit(k))
            self._theme_group.addButton(rb)
            lay.addWidget(rb)

        lay.addStretch()

    def set_tools(self, tools, current_tool, tool_names=None):
        """레시피가 준 선택지로 라디오를 만든다 — 목록을 코드에 박지 않는다."""
        names = tool_names or {}
        for b in list(self._tool_buttons.values()):
            self._tool_group.removeButton(b)
            b.setParent(None)
        self._tool_buttons.clear()

        for key in tools:
            rb = QRadioButton(names.get(key, key))
            rb.setFont(config.font("body", 600))
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setChecked(key == current_tool)
            rb.toggled.connect(lambda on, k=key: on and self.tool_changed.emit(k))
            self._tool_group.addButton(rb)
            self._tool_box.addWidget(rb)
            self._tool_buttons[key] = rb

    def set_tool_editable(self, editable):
        """🔴 작업 중에는 공구를 바꿀 수 없다 — 진행 중에 바뀌면 판정이 흔들린다."""
        for b in self._tool_buttons.values():
            b.setEnabled(editable)
        self._tool_note.setText(
            "" if editable else "ⓘ 작업 중에는 변경할 수 없습니다")
        self._tool_note.setStyleSheet(theme.text_qss("warn", 600))

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("text", 800))
        for cap in (self._tool_caption, self._theme_caption):
            cap.setStyleSheet(theme.text_qss("label", 700))
        radio_qss = (f"QRadioButton {{ color: {theme.C('text')}; background: transparent;"
                     f" padding: 3px 2px; }}"
                     f"QRadioButton:disabled {{ color: {theme.C('todo')}; }}")
        for b in list(self._tool_buttons.values()) + list(self._theme_group.buttons()):
            b.setStyleSheet(radio_qss)

    def relayout(self, parent_rect):
        place(self, parent_rect, width=_SETTINGS_W)   # 가로·세로 중앙
