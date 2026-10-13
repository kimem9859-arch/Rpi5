"""글라스 UI — 메뉴 · 알림 · 설정 패널.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §4.4·§4.7·§4.8

세 패널의 공통 성격:
    상시 노출이 아니라 **열었을 때만** 나온다. 그래서 배경을 진하게(`sheet`) 두어
    가독성을 우선한다 — 시야를 막는 시간이 짧기 때문이다.

로그와 알림은 역할이 다르다:
    로그(메뉴 안)는 **전부**를 시간순으로 담고, 알림은 **알려야 할 것만** 골라 띄운다.
    둘 다 유지한다.
"""

from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QRadioButton, QButtonGroup, QFrame, QSizePolicy,
)

import os

import config
import theme
from overlay import place, _glow, vpx, vplace, cut_corner_path, _qcolor


# 알림 종류 — design §4.8. (아이콘, 색 토큰)
# 🔴 컬러 이모지를 쓴다 — 종전 흑백 기호(✓ ▶ ⚠)는 본문 글자와 구별되지 않아
#    목록이 글자 덩어리로 읽혔다(2026-08-04 실기동 피드백).
NOTIFY_KINDS = {
    "check":  ("✅", "done"),     # 점검
    "work":   ("▶️", "info"),     # 이벤트 — 작업
    "warn":   ("⚠️", "warn"),     # 이벤트 — 경고
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

# 알림 행의 좌우 여백 — 아이콘이 행 가장자리에 붙지 않게(2026-08-04)
_NOTIFY_ROW_PAD = 12

# 메뉴 항목의 좌측 들여쓰기 — 🔴 제목·「＋」·종료가 **같은 값**을 써야 글자
#    시작점이 세로로 한 줄이 된다(2026-08-04. 종전 2px 라 왼쪽에 치우쳐 보였다).
_MENU_PAD_LEFT = 12


class _Sheet(QWidget):
    """열었을 때만 나오는 진한 패널.

    CUT > 0 이면 게임 메뉴 느낌의 각진 바탕(왼쪽 위 · 오른쪽 아래 모서리 자름 · 시연 UI 개선 설계 2026-10-13 §2.3)을
    직접 그린다 — 효과가 아니라 도형 한 번. 0 이면 종전처럼 QSS 바탕(결과창 · 녹화창).
    """

    closed = pyqtSignal()          # ✕ 를 누르면 나온다 (항목 패널만 ✕ 를 단다)
    CUT = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = None            # 각진 바탕 그림 — 크기 · 테마가 바뀔 때만 다시 만든다
        self.hide()

    def paintEvent(self, event):
        # 🔴 바탕은 그려 둔 그림(QPixmap)을 붙인다 — 매번 경로를 채우면 차단 맥박이 메뉴 아래를 다시 그릴 때마다
        #    함께 그려져 메뉴 열림 GUI CPU 가 25.7 → 29.1%(코어 1개)로 올랐다(10/14 시제품 측정).
        if self.CUT:
            if self._bg is None or self._bg.size() != self.size():
                self._bg = QPixmap(self.size())
                self._bg.fill(Qt.GlobalColor.transparent)
                p = QPainter(self._bg)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = cut_corner_path(QRect(0, 0, self.width() - 1, self.height() - 1), self.CUT)
                p.fillPath(path, _qcolor(theme.C("sheet_bg")))
                p.setPen(QPen(_qcolor(theme.C("sheet_border")), 1))
                p.drawPath(path)
                p.end()
            p = QPainter(self)
            p.drawPixmap(event.rect(), self._bg, event.rect())
            p.end()
        super().paintEvent(event)

    def _make_close_button(self):
        """우상단 ✕. 🔴 네 패널이 같은 모양·같은 자리여야 하므로 여기서만 만든다.

        메뉴·알림 **창 자체**에는 달지 않는다 — 자기 버튼(☰/🔔)이 보이므로
        재클릭으로 닫는다. ✕ 가 필요한 것은 자기 버튼이 없는 **항목 패널**이다.
        """
        # ⚠️ ✕ 글리프는 같은 pt 의 한글보다 훨씬 작게 그려진다 — body(12pt) 로는
        #    8px 남짓이라 누를 자리가 잘 안 보였다(2026-08-04 확인). banner(16pt)로.
        b = QPushButton("✕")
        b.setFont(config.font("banner", 700))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFlat(True)
        b.setFixedSize(32, 32)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # ESC·1~4 키가 창으로 가게
        b.setStyleSheet(
            f"QPushButton {{ color: {theme.C('text')}; background: transparent;"
            f" border: none; }}"
            f"QPushButton:hover {{ color: {theme.C('info')}; }}")
        b.clicked.connect(lambda: self.closed.emit())
        return b

    def apply_theme(self):
        # 🔴 시트는 **항상 배경을 그린다** — 읽고 눌러야 하므로 가독성이 우선이다.
        #    (맨 QWidget 은 이 속성 없이는 스타일시트 배경이 무시된다.)
        self._bg = None                  # 테마가 바뀌면 각진 바탕 그림을 다시 만든다
        if self.CUT:
            # 각진 바탕은 paintEvent 가 그린다 — QSS 바탕을 끄면 자식에 padding 이 번지던 함정도 없다
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
            self.setStyleSheet("")
            self.update()
        else:
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
        f" text-align: left; padding: 9px 2px 9px {_MENU_PAD_LEFT}px; }}"
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


class _MenuItem(QPushButton):
    """메뉴 한 줄 — 아이콘 타일 · 제목 · 설명 · ›(시안 96px · 설계 2026-10-13 §4.1).

    글은 자식 라벨이라 버튼 QSS 는 테두리 · 바탕만 맡는다. 🔴 이모지는 굵기 800 에서 안 그려진다(알림 함정) — 기호 글자를 쓴다.
    """

    def __init__(self, icon, title, desc, tone="text", parent=None):
        super().__init__(parent)
        self.tone = tone
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # ESC·1~4 키가 창으로 가게
        self.setFixedHeight(96)
        h = QHBoxLayout(self)
        h.setContentsMargins(22, 0, 22, 0)
        h.setSpacing(20)
        self.icon = QLabel(icon)
        self.icon.setFixedSize(56, 56)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setFont(config.font("item", 600))
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel(title)
        self.title.setFont(config.font("item", 800))
        self.desc = QLabel(desc)
        self.desc.setFont(config.font("item_sub", 500))
        col.addWidget(self.title)
        col.addWidget(self.desc)
        self.chev = QLabel("›")
        self.chev.setFont(config.font("item", 500))
        h.addWidget(self.icon)
        h.addLayout(col, 1)
        h.addWidget(self.chev)
        for w in (self.icon, self.title, self.desc, self.chev):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def apply_theme(self):
        accent = self.tone != "text"
        edge = theme.rgba(self.tone, 0.35) if accent else theme.C("sheet_border")
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {edge}; }}"
            f"QPushButton:hover, QPushButton:pressed {{ background: {theme.rgba('current', 0.14)};"
            f" border: 2px solid {theme.C('current')}; }}")
        self.icon.setStyleSheet(
            f"background: {theme.rgba(self.tone, 0.10) if accent else theme.C('panel_border')};"
            f" border: 1px solid {edge}; color: {theme.C(self.tone)};")
        self.title.setStyleSheet(theme.text_qss(self.tone + "_text" if self.tone == "warn" else self.tone, 800))
        self.desc.setStyleSheet(theme.text_qss("label", 500))
        self.chev.setStyleSheet(theme.text_qss("todo", 500))


class MenuPanel(_Sheet):
    """오른쪽 세로 메뉴 — 게임 메뉴 느낌(설계 2026-10-13 §4.1).

    🔴 「녹화」 · 「시스템 종료」 항목은 뺐다(사용자 10/13) — 녹화 코드 · RecordPanel · 종료 확인은 남는다(측정 · 촬영 런처가 쓴다).
    아래 시스템 상태 요약은 상태 막대와 같은 출처(콘솔 `_update_conn_bar`)가 열린 동안만 채운다.
    """

    CUT = 28
    log_clicked = pyqtSignal()
    check_clicked = pyqtSignal()      # 점검(연결) — 수동 재연결·재확인
    settings_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()      # 작업 초기화 — 「작업 시작」 직전으로 되돌린다
    closed = pyqtSignal()
    SYS = (("camera", "안경 카메라"), ("interlock", "인터락"),
           ("gpio", "버튼 입력 (GPIO)"), ("detector", "AI 가속칩"))

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 34, 30, 28)
        lay.setSpacing(10)
        self._tag = QLabel("MENU")
        self._tag.setFont(config.font("item_sub", 700))
        self._title = QLabel("메뉴")
        self._title.setFont(config.font("sheet_title", 800))
        self._ctx = QLabel("")
        self._ctx.setFont(config.font("item_sub", 500))
        for w in (self._tag, self._title, self._ctx):
            lay.addWidget(w)
        self._lines = [self._hline()]
        lay.addWidget(self._lines[0])

        self._items = []
        for icon, title, desc, tone, sig in (
                ("◉", "점검 (연결)", "카메라 · 인터락 · 버튼 입력 상태", "text", self.check_clicked),
                ("☰", "로그", "시스템이 남긴 최근 기록", "text", self.log_clicked),
                ("⚙", "설정", "공구 · 테마 · 화면 표시", "text", self.settings_clicked),
                ("↺", "작업 초기화", "「작업 시작」 전으로 되돌립니다", "warn", self.reset_clicked)):
            b = _MenuItem(icon, title, desc, tone)
            b.clicked.connect(sig.emit)
            lay.addWidget(b)
            self._items.append(b)
        lay.addStretch()

        box = QWidget()
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box.setObjectName("sysBox")
        self._sys_box = box
        bl = QVBoxLayout(box)
        bl.setContentsMargins(22, 20, 22, 20)
        bl.setSpacing(12)
        self._sys_cap = QLabel("SYSTEM · 시스템 상태")
        self._sys_cap.setFont(config.font("item_sub", 700))
        bl.addWidget(self._sys_cap)
        self._sys = {}
        for key, name in self.SYS:
            row = QHBoxLayout()
            row.setSpacing(12)
            dot = QLabel("")
            dot.setFixedSize(12, 12)
            n = QLabel(name)
            n.setFont(config.font("sub", 600))
            v = QLabel("확인 중")
            v.setFont(config.font("sub", 500))
            row.addWidget(dot)
            row.addWidget(n, 1)
            row.addWidget(v)
            bl.addLayout(row)
            self._sys[key] = (dot, v, n, None)
        lay.addWidget(box)
        self._hint = QLabel("오른쪽 위 ✕ 를 누르면 닫힙니다")
        self._hint.setFont(config.font("item_sub", 500))
        lay.addWidget(self._hint)
        self.set_system({})

    @staticmethod
    def _hline():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

    def item_titles(self):
        return [b.title.text() for b in self._items]

    def set_context(self, text):
        """제목 아래 지금 상태 한 줄(「작업 진행 중 · 2단계 냉각」)."""
        self._ctx.setText(text)

    def set_system(self, states, fps=None):
        """states = {"camera"|"interlock"|"gpio"|"detector": True|False|None} — 점검(1차)과 같은 출처."""
        for key, _ in self.SYS:
            dot, v, n, _old = self._sys[key]
            ok = (states or {}).get(key)
            if ok is None:
                text = "확인 중"
            elif not ok:
                text = "끊김"
            elif key == "camera" and fps is not None:
                text = f"연결 · {fps:.1f} fps"
            elif key == "detector":
                text = "정상"
            else:
                text = "연결"
            v.setText(text)
            self._sys[key] = (dot, v, n, ok)
            tok = "done" if ok else "danger" if ok is False else "todo"
            dot.setStyleSheet(f"border-radius: 6px; border: none; background: {theme.C(tok)};")

    def apply_theme(self):
        super().apply_theme()
        self._tag.setStyleSheet(theme.text_qss("current_text", 700) + "letter-spacing: 6px;")
        self._title.setStyleSheet(theme.text_qss("text", 800))
        for w in (self._ctx, self._hint):
            w.setStyleSheet(theme.text_qss("label", 500))
        for b in self._items:
            b.apply_theme()
        self._sys_box.setStyleSheet(f"QWidget#sysBox {{ background: {theme.rgba('text', 0.04)};"
                                    f" border: 1px solid {theme.C('sheet_border')}; }}")
        self._sys_cap.setStyleSheet(theme.text_qss("label", 700) + "letter-spacing: 4px;")
        for key, (dot, v, n, ok) in self._sys.items():
            n.setStyleSheet(theme.text_qss("text", 600))
            v.setStyleSheet(theme.text_qss("label", 500))
            tok = "done" if ok else "danger" if ok is False else "todo"
            dot.setStyleSheet(f"border-radius: 6px; border: none; background: {theme.C(tok)};")
        for line in self._lines:
            line.setStyleSheet(f"background-color: {theme.C('sheet_border')}; border: none;")

    def relayout(self, vr):
        """☰ 아래 · 오른쪽 끝을 ☰ 와 맞춘다(x 1094~1674 · y 100~1248 · 영상 기준)."""
        vplace(self, vr, 1094, 100, 580, 1148)


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
        self._painted = []                # (라벨, 색 토큰, 굵기, 덧붙인 QSS) — 테마 전환 때 다시 칠한다(U14)

    def push(self, kind, title, sub=""):
        """알림 하나 추가. 최신이 맨 아래로 간다."""
        mark, token = NOTIFY_KINDS.get(kind, NOTIFY_KINDS["work"])
        row = QWidget()
        rl = QHBoxLayout(row)
        # 아이콘이 행 왼쪽 가장자리에 붙어 치우쳐 보였다 — 좌우 여백을 준다
        # (2026-08-04). 값은 공정 단계 행과 같은 계열로 맞춘다.
        rl.setContentsMargins(_NOTIFY_ROW_PAD, 0, _NOTIFY_ROW_PAD, 0)
        rl.setSpacing(8)

        icon = QLabel(mark)
        # ⚠️ weight 800 으로 두면 **이모지가 아예 안 그려진다** — Pretendard 에는
        #    이모지 글리프가 없어 폴백해야 하는데, ExtraBold 에서는 폴백이 깨진다
        #    (2026-08-04 확인. 메뉴 항목의 🔧📜🎯 는 600 이라 멀쩡했다).
        icon.setFont(config.font("body", 600))
        # 🔴 padding: 0 을 반드시 명시한다 — 시트의 padding(10px 12px)이 자식에
        #    상속되는데, 아이콘은 폭이 26px 로 고정이라 좌우 24px 에 눌려
        #    **글리프가 아예 안 그려졌다**(2026-08-04 확인).
        self._paint(icon, token, 600, "padding: 0;")
        icon.setFixedWidth(26)          # 이모지는 종전 기호보다 넓다(20 → 26)

        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        t = QLabel(title)
        t.setFont(config.font("body", 600))
        self._paint(t, "text", 600)
        t.setWordWrap(True)

        # 🔴 아이콘과 제목을 **같은 줄**에 넣는다 — 레이아웃이 세로 중앙을 맞춰 준다.
        #    높이를 계산해 맞추려 했더니(setFixedHeight + sizeHint) 창 크기에 따라
        #    제목 라벨이 늘어나 글자가 그 중앙으로 내려가면서 어긋났다
        #    (1280 에선 맞고 1920 에선 10px 어긋남, 2026-08-04). 구조로 푼다.
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(icon)
        head.addWidget(t, 1)

        col = QVBoxLayout()
        col.setSpacing(1)
        col.addLayout(head)
        if sub:
            s = QLabel(sub)
            s.setFont(config.font("small"))
            self._paint(s, "label", 500)
            s.setWordWrap(True)
            # 설명은 아이콘 폭만큼 들여쓴다 — 제목 글자와 왼쪽을 맞춘다.
            s.setContentsMargins(26 + 8, 0, 0, 0)   # 아이콘 폭 + 간격
            col.addWidget(s)

        rl.addLayout(col, 1)
        self._list.addWidget(row)         # addStretch 뒤에 넣어 아래로 쌓인다
        self._rows.append(row)
        self._scroll_to_latest()

    def _paint(self, lbl, token, weight, extra=""):
        """글자색을 칠하고 기억한다 — 테마가 바뀌면 apply_theme 이 다시 칠한다(리뷰 U14 ②)."""
        lbl.setStyleSheet(theme.text_qss(token, weight) + extra)
        self._painted.append((lbl, token, weight, extra))

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
        # 🔴 이미 쌓인 알림도 새 색으로 — 다크 글자(#e6e8ea)가 화이트 시트 위에 남아 거의 안
        #    보였다(리뷰 U14 ②).
        for lbl, token, weight, extra in self._painted:
            lbl.setStyleSheet(theme.text_qss(token, weight) + extra)

    def relayout(self, parent_rect):
        p = _NOTIFY_POS
        h = 1.0 - p["top"] - p["bottom"]
        place(self, parent_rect, left=p["left"], top=p["top"],
              width=p["width"], height=h)


def _seg_button(text):
    """나눠 고르는 버튼 한 칸(설정 공구 · 테마 · 로그 거르기) — 눌린 채로 남는다."""
    b = QPushButton(text)
    b.setCheckable(True)
    b.setFont(config.font("sub", 700))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setMinimumHeight(52)
    return b


def _seg_qss():
    return (f"QPushButton {{ background: transparent; color: {theme.C('text')};"
            f" border: 1px solid {theme.C('sheet_border')}; padding: 10px 18px; }}"
            f"QPushButton:checked {{ background: {theme.rgba('current', 0.16)}; color: {theme.C('current_text')};"
            f" border: 2px solid {theme.C('current')}; }}"
            f"QPushButton:disabled {{ color: {theme.C('todo')}; }}")


def _switch_qss():
    return (f"QPushButton {{ background: {theme.C('panel_border')}; color: {theme.C('label')};"
            f" border: 1px solid {theme.C('sheet_border')}; border-radius: 20px; padding: 6px 18px; }}"
            f"QPushButton:checked {{ background: {theme.C('done')}; color: #111111; border: none; }}"
            f"QPushButton:disabled {{ background: transparent; color: {theme.C('todo')}; }}")


class SettingsPanel(_Sheet):
    """가운데 설정 — 게임 메뉴 느낌(설계 2026-10-13 §4.2).

    지정 공구 · 테마 = 나눠 고르는 버튼 / 화면 표시 = 켬·끔 스위치 4개(단계 패널 배경 · 객체 인식 상자 ·
    인식 점수 숫자(상자가 켜졌을 때만) · 손 인식 오버레이).
    🔴 바꾼 값은 저장하지 않는다 — 이 세션에만. 레시피가 정답 순서의 단일 출처라 UI 가 파일을 고치면 정본이 흐려진다.
    """

    CUT = 28
    tool_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    panel_bg_changed = pyqtSignal(bool)
    boxes_changed = pyqtSignal(bool)
    scores_changed = pyqtSignal(bool)
    hand_changed = pyqtSignal(bool)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool_buttons = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(10)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        self._tag = QLabel("SETTINGS")
        self._tag.setFont(config.font("item_sub", 700))
        self._title = QLabel("설정")
        self._title.setFont(config.font("sheet_title", 800))
        col.addWidget(self._tag)
        col.addWidget(self._title)
        head.addLayout(col)
        head.addStretch()
        head.addWidget(self._make_close_button())
        lay.addLayout(head)

        self._tool_caption = QLabel("지정 공구")      # 단계 번호는 set_tools 가 레시피에서 붙인다(G6)
        self._tool_caption.setFont(config.font("sub", 700))
        lay.addWidget(self._tool_caption)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_box = QHBoxLayout()
        self._tool_box.setSpacing(0)
        lay.addLayout(self._tool_box)
        self._tool_note = QLabel("")
        self._tool_note.setFont(config.font("item_sub"))
        self._tool_note.setWordWrap(True)
        lay.addWidget(self._tool_note)
        self._tool_note.hide()

        self._theme_caption = QLabel("화면 테마")
        self._theme_caption.setFont(config.font("sub", 700))
        lay.addWidget(self._theme_caption)
        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_buttons = {}
        row = QHBoxLayout()
        row.setSpacing(0)
        for key, text in (("dark", "어두운"), ("light", "밝은")):
            b = _seg_button(text)
            b.setChecked(key == theme.current())
            b.toggled.connect(lambda on, k=key: on and self.theme_changed.emit(k))
            self._theme_group.addButton(b)
            self._theme_buttons[key] = b
            row.addWidget(b, 1)
        lay.addLayout(row)

        self._show_caption = QLabel("화면 표시")
        self._show_caption.setFont(config.font("sub", 700))
        lay.addWidget(self._show_caption)
        self._switches = {}
        self._switch_names = []
        for name, label, on, sig in (
                ("bg", "단계 패널 배경", getattr(theme, "PANEL_BACKGROUND", True), self.panel_bg_changed),
                ("boxes", "객체 인식 상자", config.SHOW_DETECT_BOXES, self.boxes_changed),
                ("scores", "인식 점수 숫자", config.SHOW_DETECT_SCORES, self.scores_changed),
                ("hand", "손 인식 오버레이", config.HAND_DRAW, self.hand_changed)):
            line = QHBoxLayout()
            n = QLabel(label)
            n.setFont(config.font("sub", 600))
            sw = QPushButton("켬" if on else "끔")
            sw.setCheckable(True)
            sw.setChecked(bool(on))
            sw.setFont(config.font("sub", 700))
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            sw.setMinimumWidth(96)
            sw.toggled.connect(lambda v, b=sw, sg=sig: (b.setText("켬" if v else "끔"), sg.emit(bool(v))))
            line.addWidget(n, 1)
            line.addWidget(sw)
            lay.addLayout(line)
            self._switches[name] = sw
            self._switch_names.append(n)
        self._switches["boxes"].toggled.connect(self._switches["scores"].setEnabled)
        self._switches["scores"].setEnabled(self._switches["boxes"].isChecked())

        # 🔴 이 문장을 빼면 "상자를 끄면 감시도 꺼지나?"를 반드시 묻게 된다(설계 §4.2).
        self._box_note = QLabel("ⓘ 화면 표시만 끕니다 — 감지·차단은 그대로")
        self._box_note.setFont(config.font("item_sub"))
        self._box_note.setWordWrap(True)
        lay.addWidget(self._box_note)
        lay.addStretch()

    def switch(self, name):
        """켬/끔 스위치 — "bg" | "boxes" | "scores" | "hand"."""
        return self._switches[name]

    def set_tools(self, tools, current_tool, tool_names=None, step_order=None):
        """레시피가 준 선택지로 버튼을 만든다 — 목록을 코드에 박지 않는다.

        step_order = 공구를 쓰는 단계 번호 — 제목에 쓴다(G6).
        """
        names = tool_names or {}
        self._tool_caption.setText(f"{step_order}단계 지정 공구" if step_order else "지정 공구")
        for b in list(self._tool_buttons.values()):
            self._tool_group.removeButton(b)
            b.setParent(None)
        self._tool_buttons.clear()
        for key in tools:
            b = _seg_button(names.get(key, key))
            b.setChecked(key == current_tool)
            b.toggled.connect(lambda on, k=key: on and self.tool_changed.emit(k))
            self._tool_group.addButton(b)
            self._tool_box.addWidget(b, 1)
            self._tool_buttons[key] = b
        self.apply_theme()

    def set_tool_editable(self, editable):
        """🔴 작업 중에는 공구를 바꿀 수 없다 — 진행 중에 바뀌면 판정이 흔들린다."""
        for b in self._tool_buttons.values():
            b.setEnabled(editable)
        self._tool_note.setText("" if editable else "ⓘ 작업 중에는 변경할 수 없습니다")
        self._tool_note.setStyleSheet(theme.text_qss("warn_text", 600))
        # 🔴 빈 문자열이어도 라벨은 높이를 차지한다(실측 37px) — 숨기면 공간까지 사라진다(2026-08-04).
        self._tool_note.setVisible(not editable)

    def apply_theme(self):
        super().apply_theme()
        self._tag.setStyleSheet(theme.text_qss("current_text", 700) + "letter-spacing: 6px;")
        self._title.setStyleSheet(theme.text_qss("text", 800))
        for cap in (self._tool_caption, self._theme_caption, self._show_caption):
            cap.setStyleSheet(theme.text_qss("label", 700))
        for n in self._switch_names:
            n.setStyleSheet(theme.text_qss("text", 600))
        self._box_note.setStyleSheet(theme.text_qss("label", 600))
        seg = _seg_qss()
        for b in list(self._tool_buttons.values()) + list(self._theme_buttons.values()):
            b.setStyleSheet(seg)
        sw = _switch_qss()
        for b in self._switches.values():
            b.setStyleSheet(sw)

    def relayout(self, vr):
        """영상 가운데 · 폭 760(시안)."""
        w = vpx(vr, 760)
        self.setFixedWidth(w)
        h = self.sizeHint().height()
        self.setGeometry(QRect(vr.left() + (vr.width() - w) // 2, vr.top() + (vr.height() - h) // 2, w, h))


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

        head = QHBoxLayout()
        self._title = QLabel("🔧  점검 (연결)")
        self._title.setFont(config.font("title", 800))
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(self._make_close_button())
        lay.addLayout(head)

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
            # 🔴 남는 공간을 **이름 칸과 오른쪽 여백이 3:1 로 나눠 갖는다** —
            #    이름 칸에 전부 주면(addLayout(col, 1)) 버튼이 패널 오른쪽 끝까지
            #    밀려 항목 이름과 화면 폭만큼 벌어진다(2026-08-04).
            #    ⚠️ stretch 를 이름과 버튼 **사이**에 두면 오히려 더 밀려난다.
            rl.addLayout(col, 3)

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
            rl.addStretch(1)          # 버튼 **뒤**의 여백 — 버튼을 안쪽으로 당긴다

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
    open_folder_requested = pyqtSignal()      # 저장 폴더를 열어 달라

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        self._title = QLabel("⏺  녹화")
        self._title.setFont(config.font("title", 800))
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(self._make_close_button())
        lay.addLayout(head)

        self._state = QLabel("")
        self._state.setFont(config.font("body", 600))
        self._state.setWordWrap(True)
        lay.addWidget(self._state)

        # 🔴 시작 버튼 2개는 **가로로** 나란히 — 세로로 쌓으니 패널이 가로로
        #    지나치게 길었다(2026-08-04). 글자도 짧게 줄인다.
        self._btn_full = QPushButton("전체 화면")
        self._btn_cam = QPushButton("카메라 영역")
        # 1인칭 원본(오버레이 없음) + 프레임 대응표 — 측정 중이면 세션 폴더(측정 녹화 설계 R2)
        self._btn_raw = QPushButton("1인칭 원본")
        self._btn_stop = QPushButton("녹화 중지")
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for b, mode in ((self._btn_full, "full"), (self._btn_cam, "camera"), (self._btn_raw, "raw")):
            b.setFont(config.font("body", 700))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: self.start_requested.emit(m))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)
        self._btn_stop.setFont(config.font("body", 700))
        self._btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_stop.clicked.connect(lambda: self.stop_requested.emit())
        lay.addWidget(self._btn_stop)

        self._note = QLabel("")
        self._note.setFont(config.font("small"))
        self._note.setWordWrap(True)
        lay.addWidget(self._note)

        # 저장 폴더 — 누르면 파일관리자로 연다(design §7)
        self._save_dir = ""
        self._folder = QPushButton("")
        self._folder.setFont(config.font("small", 600))
        self._folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self._folder.setFlat(True)
        self._folder.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._folder.clicked.connect(lambda: self.open_folder_requested.emit())
        lay.addWidget(self._folder)

        lay.addStretch()

        self.set_state(False, "", 0)

    def set_save_dir(self, path):
        """화면에 보일 저장 경로. 🔴 경로를 코드에 박지 않는다 — config 가 정본이다."""
        self._save_dir = path
        self._folder.setText(f"📁  {path}")

    def set_state(self, recording, path="", elapsed=0):
        self._recording = recording
        self._rec_path, self._rec_elapsed = path, elapsed   # 테마 전환 때 그대로 다시 그린다(U14 ⑤)
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
        self._btn_raw.setVisible(not recording)
        self._btn_stop.setVisible(recording)
        self._note.setStyleSheet(theme.text_qss("label", 500))

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._folder.setStyleSheet(
            f"QPushButton {{ color: {theme.C('label')}; background: transparent;"
            f" border: none; text-align: left; padding: 4px 2px; }}"
            f"QPushButton:hover {{ color: {theme.C('info')}; }}")
        cta = (f"QPushButton {{ background-color: {theme.C('cta_bg')};"
               f" color: {theme.C('cta_text')}; border: 1px solid {theme.C('cta_border')};"
               f" border-radius: 8px; padding: 10px 16px; text-align: left; }}")
        self._btn_full.setStyleSheet(cta)
        self._btn_cam.setStyleSheet(cta)
        self._btn_raw.setStyleSheet(cta)
        self._btn_stop.setStyleSheet(
            f"QPushButton {{ background-color: {theme.C('danger')};"
            f" color: #ffffff; border: none; border-radius: 8px; padding: 10px 16px; }}")
        # 🔴 경로·경과도 넘긴다 — 빠뜨리면 녹화 중 테마를 바꿀 때 파일 이름 줄이 지워지고 경과가
        #    0초로 돌아갔다(리뷰 U14 ⑤).
        self.set_state(getattr(self, "_recording", False),
                       getattr(self, "_rec_path", ""), getattr(self, "_rec_elapsed", 0))

    def relayout(self, parent_rect):
        place(self, parent_rect, width=0.30)
