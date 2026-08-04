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

import os

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

# 🔴 패널이 **자기 버튼을 덮지 않게** 한다 (2026-08-04 실기동 피드백).
#    버튼이 보여야 "같은 버튼을 다시 눌러 닫기"가 성립한다.
#    메뉴 패널은 ☰ **아래**에서 시작, 알림 패널은 🔔 **위**에서 끝난다.
#    폭은 2026-08-04 실기동 피드백으로 1.5배(0.13 → 0.195). 항목 글자가 오른쪽
#    경계에 닿아 답답했다. 🔴 글자 크기는 유지한다 — 멀리서 보는 화면이다.
_MENU_POS = {"right": 0.14, "top": 0.15, "width": 0.195, "bottom": 0.05}
_NOTIFY_POS = {"left": 0.14, "top": 0.42, "width": 0.27, "bottom": 0.15}
_SETTINGS_W = 0.34


class _Sheet(QWidget):
    """열었을 때만 나오는 진한 패널."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()

    def apply_theme(self):
        # 🔴 시트는 **항상 배경을 그린다** — 읽고 눌러야 하므로 가독성이 우선이다.
        #    (맨 QWidget 은 이 속성 없이는 스타일시트 배경이 무시된다.)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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


class NotifyButton(QPushButton):
    """🔔 버튼 + 우측 상단 배지 — 폰 앱 알림처럼.

    🔴 숫자를 버튼 글자에 넣지 않는다(종전 "🔔 3"). 빨강 원 안에 흰 숫자를
       **우측 상단 꼭짓점**에 겹쳐 그린다. 0 이면 배지 자체를 숨긴다.
    """

    BADGE_BG = "#e02020"
    BADGE_FG = "#ffffff"

    def __init__(self, parent=None):
        super().__init__("🔔", parent)
        self._count = 0
        self._badge = QLabel("", self)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(config.font("small", 800))
        self._badge.hide()

    def set_count(self, n):
        self._count = max(0, int(n))
        if self._count == 0:
            self._badge.hide()
            return
        self._badge.setText("99+" if self._count > 99 else str(self._count))
        self._place_badge()
        self._badge.show()
        self._badge.raise_()

    def _place_badge(self):
        # 🔴 배지는 **버튼 안**에 있어야 한다 — 밖으로 걸치면 Qt 가 부모 경계에서
        #    잘라내 반쪽만 보인다(2026-08-04 실기동에서 확인).
        #    종전: setGeometry(width - w + d//3, -d//3, ...) → 위·오른쪽 6px 잘림.
        m = 3                                            # 버튼 안쪽 여백
        d = max(16, self.height() // 3)                  # 배지 지름
        w = max(d, self._badge.fontMetrics().horizontalAdvance(self._badge.text()) + 10)
        w = min(w, self.width() - 2 * m)                 # 폭이 넘치면 버튼에 맞춘다
        self._badge.setStyleSheet(
            f"background-color: {self.BADGE_BG}; color: {self.BADGE_FG};"
            f"border-radius: {d // 2}px; border: none;")
        self._badge.setGeometry(self.width() - w - m, m, w, d)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._count:
            self._place_badge()


class MenuPanel(_Sheet):
    """우상단 세로 메뉴 — design §4.7.

    🔴 시스템 종료는 맨 아래로 분리 + 구분선. 비가역 동작이라 다른 항목과 섞지 않는다.
       (확인창은 기존 `_on_shutdown_clicked` 가 그대로 담당한다.)
    """

    log_clicked = pyqtSignal()
    check_clicked = pyqtSignal()      # 점검(연결) — 수동 재연결·재확인
    record_clicked = pyqtSignal()     # 녹화 — 필요할 때만 켠다
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
        # 🔴 ✕ 버튼을 두지 않는다 — 같은 버튼(☰/🔔)을 다시 눌러 닫는다.
        head.addWidget(self._title)
        head.addStretch()
        lay.addLayout(head)
        # 🔴 구분선은 목록으로 들고 있는다 — apply_theme 에서 findChildren(QFrame) 로
        #    찾으면 **QLabel 까지 잡힌다**(QLabel 은 QFrame 의 하위 클래스). 그래서
        #    선에 칠하려던 배경색이 제목·「＋」에 덮여 회색 박스로 보였다(2026-08-04).
        self._lines = [self._hline()]
        lay.addWidget(self._lines[0])

        self._items = []
        for text, sig in (("🔧  점검 (연결)", self.check_clicked),
                          ("⏺  녹화", self.record_clicked),
                          ("📜  로그", self.log_clicked),
                          ("🎯  캘리브레이션", self.calibrate_clicked),
                          ("📹  CCTV 전환", self.cctv_clicked),
                          ("⚙  설정", self.settings_clicked)):
            b = _row_button(text)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
            self._items.append(b)

        # 추후 항목 자리 3칸 — design §4.7
        self._free = []
        for _ in range(1):
            f = QLabel("＋")
            f.setFont(config.font("small"))
            f.setStyleSheet(f"color: {theme.C('todo')}; padding: 9px 2px;")
            lay.addWidget(f)
            self._free.append(f)

        lay.addStretch()
        self._lines.append(self._hline())
        lay.addWidget(self._lines[-1])
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
        for line in self._lines:
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
        # 🔴 ✕ 버튼을 두지 않는다 — 같은 버튼(☰/🔔)을 다시 눌러 닫는다.
        head.addWidget(self._title)
        head.addStretch()
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
    panel_bg_changed = pyqtSignal(bool)
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
        # 🔴 ✕ 버튼을 두지 않는다 — 같은 버튼(☰/🔔)을 다시 눌러 닫는다.
        head.addWidget(self._title)
        head.addStretch()
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

        self._bg_caption = QLabel("공정 단계 패널 배경")
        self._bg_caption.setFont(config.font("small", 700))
        lay.addWidget(self._bg_caption)

        self._bg_group = QButtonGroup(self)
        for on, text in ((False, "없음  (글자만 — AR 글라스 느낌)"), (True, "있음")):
            rb = QRadioButton(text)
            rb.setFont(config.font("body", 600))
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            rb.setChecked(on == getattr(theme, "PANEL_BACKGROUND", True))
            rb.toggled.connect(lambda chk, v=on: chk and self.panel_bg_changed.emit(v))
            self._bg_group.addButton(rb)
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
        for cap in (self._tool_caption, self._theme_caption, self._bg_caption):
            cap.setStyleSheet(theme.text_qss("label", 700))
        radio_qss = (f"QRadioButton {{ color: {theme.C('text')}; background: transparent;"
                     f" padding: 3px 2px; }}"
                     f"QRadioButton:disabled {{ color: {theme.C('todo')}; }}")
        for b in (list(self._tool_buttons.values()) + list(self._theme_group.buttons())
                  + list(self._bg_group.buttons())):
            b.setStyleSheet(radio_qss)

    def relayout(self, parent_rect):
        place(self, parent_rect, width=_SETTINGS_W)   # 가로·세로 중앙


class CheckPanel(_Sheet):
    """점검(연결) — 항목별 상태 + 수동 재연결 (design §4.2).

    🔴 재연결 5회 실패 후 **다시 붙일 수 있는 유일한 수단**이다.
       자동 재시도를 멈추기로 한 이상 이 화면이 없으면 프로그램을 껐다 켜야 한다.
    """

    retry_requested = pyqtSignal(str)     # 항목 key
    recheck_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._title = QLabel("🔧  점검 (연결)")
        self._title.setFont(config.font("title", 800))
        lay.addWidget(self._title)

        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        lay.addLayout(self._body)

        lay.addStretch()
        self._recheck = QPushButton("다시 점검")
        self._recheck.setFont(config.font("body", 700))
        self._recheck.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recheck.clicked.connect(lambda: self.recheck_requested.emit())
        lay.addWidget(self._recheck)

    def update_results(self, results):
        """CheckResult 목록을 그린다. 재연결 가능한 항목엔 버튼을 붙인다."""
        for w in list(self._rows.values()):
            w.setParent(None)
        self._rows.clear()

        for r in results:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)

            mark = QLabel(r.mark)
            mark.setFont(config.font("body", 800))
            mark.setStyleSheet(theme.text_qss("done" if r.ok else "danger", 800))
            mark.setFixedWidth(18)

            col = QVBoxLayout()
            col.setSpacing(1)
            name = QLabel(r.name)
            name.setFont(config.font("body", 600))
            name.setStyleSheet(theme.text_qss("text", 600))
            detail = QLabel(r.detail)
            detail.setFont(config.font("small"))
            detail.setStyleSheet(theme.text_qss("label", 500))
            col.addWidget(name)
            col.addWidget(detail)

            rl.addWidget(mark)
            rl.addLayout(col, 1)

            if r.retryable and not r.ok:
                btn = QPushButton("재연결")
                btn.setFont(config.font("small", 700))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton {{ background-color: {theme.C('cta_bg')};"
                    f" color: {theme.C('cta_text')}; border: none;"
                    f" border-radius: 5px; padding: 5px 12px; }}")
                btn.clicked.connect(lambda _=False, k=r.key: self.retry_requested.emit(k))
                rl.addWidget(btn)

            self._body.addWidget(row)
            self._rows[r.key] = row

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._recheck.setStyleSheet(
            f"QPushButton {{ background-color: {theme.C('cta_bg')};"
            f" color: {theme.C('cta_text')}; border: 1px solid {theme.C('cta_border')};"
            f" border-radius: 8px; padding: 10px 18px; }}")

    def relayout(self, parent_rect):
        place(self, parent_rect, width=0.34)


class RecordPanel(_Sheet):
    """녹화 — 필요할 때만 켠다 (design §8 갱신, 2026-08-04).

    🔴 상시 자동 녹화를 폐기한 이유: 실측에서 **전체 부하 55.6% 중 약 40%p**가
       녹화였다. GUI 스레드가 초당 15번 창 전체를 캡처하느라 화면이 버벅였다.

    모드 2종:
      Full        — GUI 전체(오버레이 포함). 시연 화면 그대로 남긴다
      카메라 영역 — 받아 둔 프레임만. **창 캡처를 안 하므로 GUI 부담이 거의 0**
    """

    start_requested = pyqtSignal(str)      # "full" | "camera"
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._title = QLabel("⏺  녹화")
        self._title.setFont(config.font("title", 800))
        lay.addWidget(self._title)

        self._state = QLabel("")
        self._state.setFont(config.font("body", 600))
        self._state.setWordWrap(True)
        lay.addWidget(self._state)

        self._btn_full = QPushButton("전체 화면 녹화 시작")
        self._btn_cam = QPushButton("카메라 영역만 녹화 시작")
        self._btn_stop = QPushButton("녹화 중지")
        for b, mode in ((self._btn_full, "full"), (self._btn_cam, "camera")):
            b.setFont(config.font("body", 700))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: self.start_requested.emit(m))
            lay.addWidget(b)
        self._btn_stop.setFont(config.font("body", 700))
        self._btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop.clicked.connect(lambda: self.stop_requested.emit())
        lay.addWidget(self._btn_stop)

        self._note = QLabel("")
        self._note.setFont(config.font("small"))
        self._note.setWordWrap(True)
        lay.addWidget(self._note)
        lay.addStretch()

        self.set_state(False, "", 0)

    def set_state(self, recording, path="", elapsed=0):
        self._recording = recording
        if recording:
            self._state.setText(f"● 녹화 중 — {int(elapsed)}초")
            self._state.setStyleSheet(theme.text_qss("danger", 700))
            self._note.setText(os.path.basename(path) if path else "")
        else:
            self._state.setText("○ 녹화 중지 상태")
            self._state.setStyleSheet(theme.text_qss("label", 600))
            self._note.setText("H.264(.mp4)로 저장 — 약 0.3MB/분")
        self._btn_full.setVisible(not recording)
        self._btn_cam.setVisible(not recording)
        self._btn_stop.setVisible(recording)
        self._note.setStyleSheet(theme.text_qss("label", 500))

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("text", 800))
        cta = (f"QPushButton {{ background-color: {theme.C('cta_bg')};"
               f" color: {theme.C('cta_text')}; border: 1px solid {theme.C('cta_border')};"
               f" border-radius: 8px; padding: 10px 16px; text-align: left; }}")
        self._btn_full.setStyleSheet(cta)
        self._btn_cam.setStyleSheet(cta)
        self._btn_stop.setStyleSheet(
            f"QPushButton {{ background-color: {theme.C('danger')};"
            f" color: #ffffff; border: none; border-radius: 8px; padding: 10px 16px; }}")
        self.set_state(getattr(self, "_recording", False))

    def relayout(self, parent_rect):
        place(self, parent_rect, width=0.30)
