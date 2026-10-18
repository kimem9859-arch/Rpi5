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
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainter, QPen, QPixmap, QPolygonF, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QRadioButton, QButtonGroup, QFrame, QSizePolicy,
)

import os

import config
import theme
from overlay import place, _glow, vpx, vplace, cut_corner_path, _qcolor


# 알림 종류 — design §4.8. (아이콘, 색 토큰)
# 종전 흑백 기호(✓ ▶ ⚠)는 본문 글자와 구별되지 않아 목록이 글자 덩어리로 읽혔다(2026-08-04) → 색 원 안에 넣는다.
NOTIFY_KINDS = {
    "check":  ("check_big", "done"),   # 점검
    "work":   ("play", "done"),        # 이벤트 — 작업(시안 = 초록)
    "warn":   ("alert", "warn"),       # 이벤트 — 경고
    "danger": ("x", "danger"),         # 이벤트 — 위험
}
# 시안(10/14 대조) — 각진 48 칸 · 2px 색 테두리 · 시안 선 아이콘(ui_icons 이름)
# 🔴 시연 UI 개선(10/13) — 컬러 이모지 대신 **종류 색 원 + 기호**. 색이 테마를 따르고, 이모지가 굵은 글꼴에서
#    안 그려지던 함정(2026-08-04)이 없다.

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
                import ui_icons
                path = cut_corner_path(QRect(0, 0, self.width() - 1, self.height() - 1), self.CUT)

                def draw(p):
                    p.fillPath(path, _qcolor(theme.C("sheet_bg")))
                    p.setPen(QPen(_qcolor(theme.C("sheet_border")), 1))
                    p.drawPath(path)
                self._bg = ui_icons.paint_pixmap(self.width(), self.height(), draw)
            p = QPainter(self)
            p.drawPixmap(event.rect(), self._bg, event.rect())
            p.end()
        super().paintEvent(event)

    def _make_close_button(self):
        """우상단 닫기 — 시안 56×52 각진 칸 · ✕ 선 아이콘. 🔴 항목 패널이 같은 모양 · 같은 자리여야 하므로 여기서만 만든다.

        메뉴·알림 **창 자체**에는 달지 않는다 — 자기 버튼(☰/🔔)이 보이므로 재클릭으로 닫는다.
        """
        b = _CloseButton()
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


class StartButton(QPushButton):
    """「작업 시작」 — 게임 메뉴 각진 버튼(시안 A · 사용자 10/14).

    노란 ▶ 타일 · 「START」 · 큰 「작업 시작」 · 부제(공정 · 단계 수 · 1단계 · 콘솔이 레시피에서 넣는다) · ›.
    🔑 전부 paintEvent 가 한 번에 그린다 — 대기 중에만 보이고 마우스를 올리거나 누를 때만 다시 그린다.
    `text()` 는 버튼 글(「▶  작업 시작」)을 그대로 쓴다 — ▶ 는 타일이 그리므로 글에서 뺀다.
    """

    W, H = 640, 148           # 시안 px
    CUT = 24
    TILE = 96

    def __init__(self, parent=None):
        super().__init__("▶  작업 시작", parent)
        self._sub = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)    # ESC·1~4 키가 창으로 가게
        self._f_tag = config.font("item_sub", 700)
        self._f_tag.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6)
        self._f_title = config.font("start_title", 800)
        self._f_sub = config.font("sub", 500)

    def set_subtitle(self, text):
        self._sub = text or ""
        self.update()

    def subtitle(self):
        return self._sub

    def apply_theme(self):
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        down = self.isDown() or self.underMouse()
        path = cut_corner_path(QRect(1, 1, self.width() - 2, self.height() - 2), self.CUT)
        p.fillPath(path, _qcolor(theme.C("sheet_bg")))
        p.setPen(QPen(QColor(theme.C("current")), 3 if down else 2))
        p.drawPath(path)
        pad = 30
        t = self.TILE
        top = (self.height() - t) // 2
        p.fillRect(QRect(pad, top, t, t), QColor(theme.C("current")))
        cx, cy, r = pad + t / 2 + 3, self.height() / 2, t * 0.22
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#111111"))
        p.drawPolygon(QPolygonF([QPointF(cx - r * 0.8, cy - r), QPointF(cx - r * 0.8, cy + r),
                                 QPointF(cx + r, cy)]))
        x = pad + t + 26
        p.setFont(self._f_tag)
        p.setPen(QColor(theme.C("current_text")))
        p.drawText(x, top + 16, "START")
        p.setFont(self._f_title)
        p.setPen(QColor(theme.C("text")))
        title = self.text().replace("▶", "").strip()
        p.drawText(x, top + 16 + p.fontMetrics().ascent() + 2, title)
        p.setFont(self._f_sub)
        p.setPen(QColor(theme.C("label")))
        p.drawText(x, top + t - 4, self._sub)
        p.setFont(self._f_title)
        p.setPen(QColor(theme.C("current_text")))
        p.drawText(self.width() - pad - p.fontMetrics().horizontalAdvance("›"), top + t - 4, "›")
        p.end()

    def relayout(self, vr):
        """영상 가운데."""
        w, h = vpx(vr, self.W), vpx(vr, self.H)
        self.setGeometry(QRect(vr.left() + (vr.width() - w) // 2, vr.top() + (vr.height() - h) // 2, w, h))


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
        self.icon_name = icon            # ui_icons 이름(시안 선 그림)
        self.icon = QLabel("")
        self.icon.setFixedSize(56, 56)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        import ui_icons
        self.icon.setStyleSheet(
            f"background: {theme.rgba(self.tone, 0.10) if accent else theme.rgba('text', 0.07)};"
            f" border: 1px solid {theme.rgba(self.tone, 0.45) if accent else theme.rgba('text', 0.18)};")
        self.icon.setPixmap(ui_icons.pixmap(self.icon_name, theme.C(self.tone), 28))
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
                ("pulse", "점검 (연결)", "카메라 · 인터락 · AI 가속칩 상태", "text", self.check_clicked),
                ("list", "로그", "시스템이 남긴 최근 기록", "text", self.log_clicked),
                ("sliders", "설정", "공구 · 테마 · 화면 표시", "text", self.settings_clicked),
                ("reset", "작업 초기화", "「작업 시작」 전으로 되돌립니다", "warn", self.reset_clicked)):
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
            elif key == "gpio":
                text = "B1 ~ B4 · EMO"           # 시안 — 버튼 입력이 읽는 것
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


_ICON_D = 48          # 알림 아이콘 칸(시안 48 · 각진 8)
_notify_icon_cache = {}


def _notify_icon(kind):
    """알림 줄 아이콘 — 각진 칸 · 2px 색 테두리 · 선 아이콘(시안)."""
    import ui_icons
    name, token = NOTIFY_KINDS.get(kind, NOTIFY_KINDS["work"])
    c = theme.C(token)
    key = (kind, c)
    pm = _notify_icon_cache.get(key)
    if pm is None:
        def draw(p):
            p.setPen(QPen(QColor(c), 2))
            p.drawPath(cut_corner_path(QRect(1, 1, _ICON_D - 2, _ICON_D - 2), 8))
            p.drawPixmap((_ICON_D - 22) // 2, (_ICON_D - 22) // 2, ui_icons.pixmap(name, c, 22))
        pm = ui_icons.paint_pixmap(_ICON_D, _ICON_D, draw)
        _notify_icon_cache[key] = pm
    return pm


class NotifyPanel(_Sheet):
    """알림 — 시안(Claude Design 2026-10-13 · 4.3) 그대로.

    머리 ALERTS · 「알림」 40 · 「최근 N건 · 새 알림 M건」 · 닫기 / 줄 = 각진 판 · 아이콘 칸 48 · 제목(종류 색) + NEW · 설명 · 시각
    / 아래 안내. 왼쪽 위 (139, 448) · 폭 640 · 많으면 위로 자라고 그 안에서 스크롤 · 🔔 를 덮지 않는다.
    🔴 프로그램을 종료하면 초기화 — 메모리에만 둔다(파일 저장 없음).
    `_rows` 는 **넣은 순서**(오래된 것 먼저) — 화면 순서만 거꾸로다.
    """

    CUT = 28
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 24)
        lay.setSpacing(12)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        self._tag = QLabel("ALERTS")
        self._tag.setFont(config.font("item_sub", 700))
        self._title = QLabel("알림")
        f = config.font("sheet_title", 800)
        f.setPointSize(30)                              # 40px
        self._title.setFont(f)
        self._sub = QLabel("")
        self._sub.setFont(config.font("sub", 500))
        for w in (self._tag, self._title, self._sub):
            col.addWidget(w)
        head.addLayout(col)
        head.addStretch()
        head.addWidget(self._make_close_button(), 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self._head_line = QFrame()
        self._head_line.setFrameShape(QFrame.Shape.HLine)
        self._head_line.setFixedHeight(1)
        lay.addSpacing(6)
        lay.addWidget(self._head_line)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                                   " QScrollArea > QWidget > QWidget { background: transparent; }")
        self._body = QWidget()
        self._list = QVBoxLayout(self._body)
        self._list.setContentsMargins(0, 0, 4, 0)
        self._list.setSpacing(12)
        self._list.addStretch()          # 맨 끝 여백 → 항목이 위부터 쌓인다
        self._scroll.setWidget(self._body)
        lay.addWidget(self._scroll)
        self._foot = QLabel("최신 알림이 위에 · 🔔을 다시 누르면 닫힙니다")
        ff = config.font("item_sub", 500)
        ff.setPointSize(12)                              # 16px
        self._foot.setFont(ff)
        lay.addWidget(self._foot)

        self._rows = []
        self._new_tags = []
        self._painted = []                # (라벨, 색 토큰, 굵기, 덧붙인 QSS) — 테마 전환 때 다시 칠한다(U14)
        self._icons = []                  # (아이콘 라벨, 종류)
        self._update_new_label()

    def push(self, kind, title, sub=""):
        """알림 하나 추가 — 최신이 맨 위 · NEW 표시."""
        from datetime import datetime
        _name, token = NOTIFY_KINDS.get(kind, NOTIFY_KINDS["work"])
        row = _CutRow()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(16, 14, 16, 14)
        rl.setSpacing(16)

        icon = QLabel("")
        icon.setFixedSize(_ICON_D, _ICON_D)
        icon.setPixmap(_notify_icon(kind))
        self._icons.append((icon, kind))

        t = QLabel(title)
        ft = config.font("sub", 800)
        ft.setPointSize(16)                              # 22px
        t.setFont(ft)
        self._paint(t, {"done": "done_text", "warn": "warn_text"}.get(token, token), 800)
        new = QLabel("NEW")
        fn = config.font("item_sub", 800)
        fn.setPointSize(10)                              # 13px
        fn.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        new.setFont(fn)
        self._paint(new, "current", 800, "")
        new.setStyleSheet(f"background: {theme.C('current')}; color: #111111; border: none; padding: 2px 8px;")
        self._new_tags.append(new)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        head.addWidget(t)
        head.addWidget(new)
        head.addStretch()
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addLayout(head)
        if sub:
            sl = QLabel(sub)
            fs = config.font("sub", 500)
            fs.setPointSize(13)                          # 17px
            sl.setFont(fs)
            self._paint(sl, "label", 500)
            sl.setWordWrap(True)
            col.addWidget(sl)
        tm = QLabel(datetime.now().strftime("%H:%M:%S"))
        fm = config.font("item_sub", 600)
        fm.setPointSize(12)                              # 16px
        tm.setFont(fm)
        self._paint(tm, "todo", 600)

        rl.addWidget(icon)
        rl.addLayout(col, 1)
        rl.addWidget(tm)
        self._list.insertWidget(0, row)  # 최신이 맨 위
        self._rows.append(row)
        self._update_new_label()
        self._scroll_to_latest()

    def _paint(self, lbl, token, weight, extra=""):
        """글자색을 칠하고 기억한다 — 테마가 바뀌면 apply_theme 이 다시 칠한다(리뷰 U14 ②)."""
        lbl.setStyleSheet(theme.text_qss(token, weight) + extra)
        self._painted.append((lbl, token, weight, extra))

    def mark_all_read(self):
        """패널을 닫을 때 — NEW 표시를 지운다."""
        for tag in self._new_tags:
            tag.hide()
        self._new_tags = []
        self._update_new_label()

    @property
    def new_count(self):
        return len(self._new_tags)

    def first_title(self):
        """화면 맨 위(최신) 알림의 제목(시험용)."""
        if not self._rows:
            return ""
        return self._rows[-1].findChildren(QLabel)[1].text()

    def _update_new_label(self):
        self._sub.setText(f"최근 {len(self._rows)}건 · 새 알림 {len(self._new_tags)}건")

    def _scroll_to_latest(self):
        self._scroll.verticalScrollBar().setValue(0)

    def showEvent(self, event):
        super().showEvent(event)
        self._scroll_to_latest()          # 열면 최신(맨 위)이 보이는 위치에서 시작

    def hideEvent(self, event):
        """🔴 어떤 경로로 닫혀도(🔔 · ✕ · 다른 창 열기 · ESC) NEW 를 지운다(최종 검토 M-3)."""
        super().hideEvent(event)
        if hasattr(self, "_new_tags"):   # _Sheet.__init__ 의 hide() 는 목록을 만들기 전이다
            self.mark_all_read()

    @property
    def count(self):
        return len(self._rows)

    def apply_theme(self):
        super().apply_theme()
        self._tag.setStyleSheet(theme.text_qss("current_text", 700) + "letter-spacing: 6px;")
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._sub.setStyleSheet(theme.text_qss("label", 500))
        self._foot.setStyleSheet(theme.text_qss("todo", 500))
        self._head_line.setStyleSheet(f"background-color: {theme.C('sheet_border')}; border: none;")
        # 🔴 이미 쌓인 알림도 새 색으로(리뷰 U14 ②)
        for lbl, token, weight, extra in self._painted:
            if lbl.text() == "NEW":
                lbl.setStyleSheet(f"background: {theme.C('current')}; color: #111111; border: none; padding: 2px 8px;")
            else:
                lbl.setStyleSheet(theme.text_qss(token, weight) + extra)
        for icon, kind in self._icons:
            icon.setPixmap(_notify_icon(kind))

    def relayout(self, vr):
        """왼쪽 위 (영상 32, 448) · 폭 640(시안) — 길면 위로 자라되 y 100 아래 · 🔔(y 1204) 위 12px 에서 끝."""
        w = vpx(vr, 640)
        bottom = vr.top() + vpx(vr, 1204 - 12)
        top_min = vr.top() + vpx(vr, 100)
        self.setFixedWidth(w)
        m = self.layout().contentsMargins()
        self._body.setFixedWidth(max(1, w - m.left() - m.right() - 4))
        self._body.layout().activate()
        self.layout().activate()
        chrome = self.layout().sizeHint().height() - self._scroll.sizeHint().height()
        need = chrome + self._body.sizeHint().height() + 4
        h = max(vpx(vr, 240), min(need, bottom - top_min))
        top = max(top_min, min(vr.top() + vpx(vr, 448), bottom - h))
        self.setGeometry(QRect(vr.left() + vpx(vr, 32), top, w, h))


class _CloseButton(QPushButton):
    """닫기 — 각진 56×52 · 바탕 7% · 테두리 20% · ✕ 선 아이콘(시안). 글은 「✕」(시험 · 접근성)."""

    def __init__(self, parent=None):
        super().__init__("✕", parent)
        self.setFixedSize(56, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # ESC·1~4 키가 창으로 가게

    def paintEvent(self, _event):
        import ui_icons
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = cut_corner_path(QRect(0, 0, self.width() - 1, self.height() - 1), 10)
        p.fillPath(path, _qcolor(theme.rgba("text", 0.12 if self.underMouse() else 0.07)))
        p.setPen(QPen(_qcolor(theme.rgba("text", 0.2)), 1))
        p.drawPath(path)
        p.drawPixmap((self.width() - 22) // 2, (self.height() - 22) // 2, ui_icons.pixmap("x", theme.C("text"), 22))
        p.end()


class _CutButton(QPushButton):
    """나눠 고르는 칸 — 각진 칸 · 고르면 노란 채움 · 검은 굵은 글(시안 설정 · 로그 거르기)."""

    def __init__(self, text, height=64, pt=16, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(height)
        f = config.font("sub", 700)
        f.setPointSize(pt)
        self.setFont(f)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = cut_corner_path(QRect(1, 1, self.width() - 2, self.height() - 2), 10)
        on = self.isChecked()
        if on:
            p.fillPath(path, _qcolor(theme.C("current")))
            p.setPen(QPen(_qcolor(theme.C("current")), 2))
        else:
            p.fillPath(path, _qcolor(theme.rgba("text", 0.06)))
            p.setPen(QPen(_qcolor(theme.rgba("text", 0.18)), 1))
        p.drawPath(path)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.ExtraBold if on else QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#111111") if on else _qcolor(theme.C("todo" if not self.isEnabled() else "text")))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


def _seg_button(text, height=64, pt=16):
    """나눠 고르는 버튼 한 칸(설정 공구 · 테마 · 로그 거르기) — 눌린 채로 남는다."""
    return _CutButton(text, height, pt)


def _seg_qss():
    """칸은 직접 그린다(_CutButton) — 스타일시트는 비운다(호출부 호환)."""
    return ""


class _Toggle(QPushButton):
    """켬/끔 스위치 — 각진 112×46 · 켬 = 노란 바탕 · 「켬」 · 오른쪽 검은 손잡이 / 끔 = 12% 바탕 · 왼쪽 회색 손잡이 · 「끔」(시안)."""

    def __init__(self, on, parent=None):
        super().__init__("켬" if on else "끔", parent)
        self.setCheckable(True)
        self.setChecked(bool(on))
        self.setFixedSize(112, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        f = config.font("sub", 800)
        f.setPointSize(13)                              # 17px
        self.setFont(f)
        self.toggled.connect(lambda v: self.setText("켬" if v else "끔"))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        on = self.isChecked()
        p.fillPath(cut_corner_path(QRect(0, 0, self.width() - 1, self.height() - 1), 8),
                   _qcolor(theme.C("current") if on else theme.rgba("text", 0.12)))
        k = 34
        kx = self.width() - 6 - k if on else 6
        knob = cut_corner_path(QRect(kx, (self.height() - k) // 2, k, k), 6)
        p.fillPath(knob, QColor("#111111") if on else _qcolor(theme.C("label")))
        p.setFont(self.font())
        p.setPen(QColor("#111111") if on else _qcolor(theme.C("label")))
        tr = QRect(6, 0, kx - 6, self.height()) if on else QRect(kx + k, 0, self.width() - kx - k - 6, self.height())
        p.drawText(tr, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class _CutRow(QWidget):
    """설정 「화면 표시」 한 줄 판 — 각진 12 · 바탕 4% · 테두리 10%(시안)."""

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = cut_corner_path(QRect(0, 0, self.width() - 1, self.height() - 1), 12)
        p.fillPath(path, _qcolor(theme.rgba("text", 0.04)))
        p.setPen(QPen(_qcolor(theme.rgba("text", 0.1)), 1))
        p.drawPath(path)
        p.end()


def _section(tag, title):
    """「TOOL  2단계 지정 공구」 같은 절 머리 — 노란 영문 표지 14 + 제목 22(시안)."""
    row = QHBoxLayout()
    row.setSpacing(14)
    t = QLabel(tag)
    f = config.font("item_sub", 700)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
    f.setPointSize(11)
    t.setFont(f)
    h = QLabel(title)
    f2 = config.font("sub", 800)
    f2.setPointSize(16)
    h.setFont(f2)
    row.addWidget(t)
    row.addWidget(h)
    row.addStretch()
    return row, t, h


class SettingsPanel(_Sheet):
    """설정 — 시안(Claude Design 2026-10-13 · 4.2) 그대로.

    머리 SETTINGS · 「설정」 40 · 「바꾸면 바로 적용됩니다」 · 닫기 / 절(TOOL · THEME · DISPLAY) / 고르는 칸 64 /
    화면 표시 줄 = 이름 23 + 설명 16 + 켬·끔 스위치. 폭 856 · 위 96.
    🔴 바꾼 값은 저장하지 않는다 — 이 세션에만. 레시피가 정답 순서의 단일 출처라 UI 가 파일을 고치면 정본이 흐려진다.
    """

    CUT = 28
    tool_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    panel_bg_changed = pyqtSignal(bool)
    boxes_changed = pyqtSignal(bool)
    scores_changed = pyqtSignal(bool)
    hand_changed = pyqtSignal(bool)
    guide_changed = pyqtSignal(bool)     # 시연 안내(상위 specs/2026-10-18-시연안내모드-design.md §6.1) — 기본 끔 · 저장 안 함
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool_buttons = {}
        self._tags, self._heads = [], []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(14)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        self._tag = QLabel("SETTINGS")
        self._tag.setFont(config.font("item_sub", 700))
        self._title = QLabel("설정")
        f = config.font("sheet_title", 800)
        f.setPointSize(30)                              # 40px
        self._title.setFont(f)
        self._sub = QLabel("바꾸면 바로 적용됩니다")
        self._sub.setFont(config.font("sub", 500))
        for w in (self._tag, self._title, self._sub):
            col.addWidget(w)
        head.addLayout(col)
        head.addStretch()
        head.addWidget(self._make_close_button(), 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self._head_line = QFrame()
        self._head_line.setFrameShape(QFrame.Shape.HLine)
        self._head_line.setFixedHeight(1)
        lay.addSpacing(4)
        lay.addWidget(self._head_line)

        row, t, self._tool_caption = _section("TOOL", "지정 공구")   # 단계 번호는 set_tools 가 레시피에서 붙인다(G6)
        self._tags.append(t); self._heads.append(self._tool_caption)
        lay.addLayout(row)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_box = QHBoxLayout()
        self._tool_box.setSpacing(10)
        lay.addLayout(self._tool_box)
        self._tool_note = QLabel("")
        self._tool_note.setFont(config.font("item_sub"))
        self._tool_note.setWordWrap(True)
        lay.addWidget(self._tool_note)
        self._tool_note.hide()

        row, t, self._theme_caption = _section("THEME", "화면 테마")
        self._tags.append(t); self._heads.append(self._theme_caption)
        lay.addLayout(row)
        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_buttons = {}
        trow = QHBoxLayout()
        trow.setSpacing(10)
        for key, text in (("dark", "다크 (기본)"), ("light", "화이트")):
            b = _seg_button(text)
            b.setChecked(key == theme.current())
            b.toggled.connect(lambda on, k=key: on and self.theme_changed.emit(k))
            self._theme_group.addButton(b)
            self._theme_buttons[key] = b
            trow.addWidget(b, 1)
        lay.addLayout(trow)

        row, t, self._show_caption = _section("DISPLAY", "화면 표시")
        self._tags.append(t); self._heads.append(self._show_caption)
        lay.addLayout(row)
        self._switches, self._switch_desc, self._switch_names = {}, {}, []
        fd = config.font("item_sub", 500)
        fd.setPointSize(12)                             # 16px

        def add_switch(name, label, desc, on, sig):
            """「화면 표시」 줄 하나(시안 모양) — 이름 23 + 설명 16 + 켬·끔 스위치."""
            box = _CutRow()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(18, 14, 18, 14)
            bl.setSpacing(20)
            tc = QVBoxLayout()
            tc.setSpacing(4)
            n = QLabel(label)
            fn = config.font("item", 700)
            fn.setPointSize(17)                         # 23px
            n.setFont(fn)
            d = QLabel(desc)
            d.setFont(fd)
            tc.addWidget(n)
            tc.addWidget(d)
            sw = _Toggle(on)
            sw.toggled.connect(lambda v, sg=sig: sg.emit(bool(v)))
            bl.addLayout(tc, 1)
            bl.addWidget(sw)
            lay.addWidget(box)
            self._switches[name] = sw
            self._switch_desc[name] = d
            self._switch_names.append(n)

        for args in (("bg", "공정 단계 패널 배경", "글자 뒤에 반투명 카드를 깝니다",
                      getattr(theme, "PANEL_BACKGROUND", True), self.panel_bg_changed),
                     ("boxes", "객체 인식 상자", "버튼 · 공구에 모서리 상자와 이름표",
                      config.SHOW_DETECT_BOXES, self.boxes_changed),
                     ("scores", "인식 점수 숫자", "이름표 옆에 신뢰도(예: 0.96) · 인식 상자가 켜졌을 때만",
                      config.SHOW_DETECT_SCORES, self.scores_changed),
                     ("hand", "손 인식 오버레이", "손끝 점과 손가락 선", config.HAND_DRAW, self.hand_changed)):
            add_switch(*args)
        self._switches["boxes"].toggled.connect(self._switches["scores"].setEnabled)
        self._switches["scores"].setEnabled(self._switches["boxes"].isChecked())

        # 🔴 이 문장을 빼면 "상자를 끄면 감시도 꺼지나?"를 반드시 묻게 된다(설계 §4.2).
        note = QHBoxLayout()
        note.setSpacing(10)
        self._note_icon = QLabel("")
        self._note_icon.setFixedSize(20, 20)
        self._box_note = QLabel("화면 표시만 끕니다 — 순서 위반 감지 · 차단은 그대로 작동합니다")
        self._box_note.setFont(fd)
        self._box_note.setWordWrap(True)
        note.addWidget(self._note_icon)
        note.addWidget(self._box_note, 1)
        lay.addLayout(note)
        # 🔑 시연 안내는 위 안내 문장 아래 — 「화면 표시만 끕니다」가 이 스위치에도 걸려 읽히지 않게(사용자 2026-10-18)
        add_switch("guide", "시연 안내", "참여자용 — 작업 시작부터 안경으로 단계별 안내", False, self.guide_changed)

    def switch(self, name):
        """켬/끔 스위치 — "bg" | "boxes" | "scores" | "hand" | "guide"(시연 안내)."""
        return self._switches[name]

    def set_tools(self, tools, current_tool, tool_names=None, step_order=None):
        """레시피가 준 선택지로 칸을 만든다 — 목록을 코드에 박지 않는다(G6 · 제목에 단계 번호)."""
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

    def set_tool_editable(self, editable):
        """🔴 작업 중에는 공구를 바꿀 수 없다 — 진행 중에 바뀌면 판정이 흔들린다."""
        for b in self._tool_buttons.values():
            b.setEnabled(editable)
        self._tool_note.setText("" if editable else "ⓘ 작업 중에는 변경할 수 없습니다")
        self._tool_note.setStyleSheet(theme.text_qss("warn_text", 600))
        # 🔴 빈 문자열이어도 라벨은 높이를 차지한다(실측 37px) — 숨기면 공간까지 사라진다(2026-08-04).
        self._tool_note.setVisible(not editable)

    def apply_theme(self):
        import ui_icons
        super().apply_theme()
        self._tag.setStyleSheet(theme.text_qss("current_text", 700) + "letter-spacing: 6px;")
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._sub.setStyleSheet(theme.text_qss("label", 500))
        self._head_line.setStyleSheet(f"background-color: {theme.C('sheet_border')}; border: none;")
        for t in self._tags:
            t.setStyleSheet(theme.text_qss("current_text", 700))
        for h in self._heads:
            h.setStyleSheet(theme.text_qss("text", 800))
        for n in self._switch_names:
            n.setStyleSheet(theme.text_qss("text", 700))
        for d in self._switch_desc.values():
            d.setStyleSheet(theme.text_qss("label", 500))
        self._box_note.setStyleSheet(theme.text_qss("label", 500))
        self._note_icon.setPixmap(ui_icons.pixmap("info", theme.C("label"), 20))
        for b in list(self._tool_buttons.values()) + list(self._theme_buttons.values()) + list(self._switches.values()):
            b.update()

    def relayout(self, vr):
        """폭 856 · 위 96 · 가로 가운데(시안)."""
        w = vpx(vr, 856)
        self.setFixedWidth(w)
        h = self.sizeHint().height()
        self.setGeometry(QRect(vr.left() + (vr.width() - w) // 2, vr.top() + vpx(vr, 96), w, h))


_CHECK_ICON = {"camera": "camera", "stream": "camera", "interlock": "plug", "interlock_ack": "plug",
               "gpio": "grid", "detector": "cube", "buttons": "cube", "hand": "hand", "hand_infer": "hand"}


class _ActionButton(QPushButton):
    """각진 실행 버튼 — 「재연결」(회색) · 「다시 점검」(노랑) · 「취소/초기화」(시안). 직접 그린다."""

    def __init__(self, text, kind="plain", height=48, pt=13, cut=8, parent=None):
        super().__init__(text, parent)
        self.kind, self.cut = kind, cut
        self.setMinimumHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        f = config.font("sub", 800 if kind != "plain" else 700)
        f.setPointSize(pt)
        self.setFont(f)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = cut_corner_path(QRect(1, 1, self.width() - 2, self.height() - 2), self.cut)
        if self.kind == "primary":                       # 노란 채움 · 검은 글
            p.fillPath(path, _qcolor(theme.C("current")))
            fg = QColor("#111111")
        elif self.kind == "danger_outline":               # 주황 테두리 · 주황 글(초기화)
            p.setPen(QPen(_qcolor(theme.C("warn")), 2))
            p.drawPath(path)
            fg = _qcolor(theme.C("warn_text"))
        else:                                             # 회색(재연결)
            p.fillPath(path, _qcolor(theme.rgba("text", 0.07)))
            p.setPen(QPen(_qcolor(theme.rgba("text", 0.22)), 1))
            p.drawPath(path)
            fg = _qcolor(theme.C("text"))
        if self.isDown():
            p.fillPath(path, QColor(0, 0, 0, 40))
        p.setPen(fg)
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class CheckPanel(_Sheet):
    """점검(연결) — 시안(Claude Design 2026-10-13 · 4.4) 그대로.

    머리 SYSTEM CHECK · 「점검 (연결)」 40 · 「N개 중 M개 정상 · 시각 확인」 · 닫기 /
    줄 = 각진 판 · 선 아이콘 칸 52 · 이름 23 · 설명 17 · 「● 정상/끊김」 · (끊김 + 재연결 가능) 「재연결」 / 노란 「다시 점검」 72.
    🔴 재연결 5회 실패 후 **다시 붙일 수 있는 유일한 수단**이다.
    """

    CUT = 28
    retry_requested = pyqtSignal(str)     # 항목 key
    recheck_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = {}
        self._retry_buttons = {}
        self._states = {}
        self._row_icons = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(12)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        self._tag = QLabel("SYSTEM CHECK")
        self._tag.setFont(config.font("item_sub", 700))
        self._title = QLabel("점검 (연결)")
        f = config.font("sheet_title", 800)
        f.setPointSize(30)                              # 40px
        self._title.setFont(f)
        self._sub = QLabel("")
        self._sub.setFont(config.font("sub", 500))
        for w in (self._tag, self._title, self._sub):
            col.addWidget(w)
        head.addLayout(col)
        head.addStretch()
        head.addWidget(self._make_close_button(), 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self._head_line = QFrame()
        self._head_line.setFrameShape(QFrame.Shape.HLine)
        self._head_line.setFixedHeight(1)
        lay.addSpacing(6)
        lay.addWidget(self._head_line)

        self._body = QVBoxLayout()
        self._body.setSpacing(12)
        lay.addLayout(self._body)

        lay.addSpacing(8)
        self._recheck = _ActionButton("다시 점검", "primary", height=72, pt=20, cut=14)   # 26px
        self._recheck.clicked.connect(lambda: self.recheck_requested.emit())
        lay.addWidget(self._recheck)

    def update_results(self, results):
        """CheckResult 목록을 그린다. 끊긴 · 재연결 가능한 항목엔 버튼을 붙인다."""
        import ui_icons
        from datetime import datetime
        for w in list(self._rows.values()):
            w.setParent(None)
        self._rows.clear()
        self._retry_buttons.clear()
        self._states.clear()
        self._row_icons.clear()

        for r in results:
            row = _CutRow()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(18, 14, 18, 14)
            rl.setSpacing(18)

            icon = QLabel("")
            icon.setFixedSize(52, 52)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet(f"background: {theme.rgba('text', 0.07)}; border: 1px solid {theme.rgba('text', 0.18)};")
            icon.setPixmap(ui_icons.pixmap(_CHECK_ICON.get(r.key, "grid"), theme.C("text"), 26))

            col = QVBoxLayout()
            col.setSpacing(3)
            name = QLabel(r.name)
            fn = config.font("item", 800)
            fn.setPointSize(17)                         # 23px
            name.setFont(fn)
            name.setStyleSheet(theme.text_qss("text", 800))
            detail = QLabel(r.detail)
            fd = config.font("sub", 500)
            fd.setPointSize(13)                         # 17px
            detail.setFont(fd)
            detail.setStyleSheet(theme.text_qss("label", 500))
            col.addWidget(name)
            col.addWidget(detail)

            tok = "done" if r.ok else "danger"
            dot = QLabel("")
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"border-radius: 6px; border: none; background: {theme.C(tok)};")
            state = QLabel("정상" if r.ok else "끊김")
            fs = config.font("sub", 800)
            fs.setPointSize(14)                         # 18px
            state.setFont(fs)
            state.setStyleSheet(theme.text_qss("done_text" if r.ok else "danger", 800))

            rl.addWidget(icon)
            rl.addLayout(col, 1)
            rl.addWidget(dot)
            rl.addWidget(state)
            if r.retryable and not r.ok:
                btn = _ActionButton("재연결", "plain", height=48, pt=14)
                btn.setMinimumWidth(110)
                btn.clicked.connect(lambda _=False, k=r.key: self.retry_requested.emit(k))
                rl.addWidget(btn)
                self._retry_buttons[r.key] = btn

            self._body.addWidget(row)
            self._rows[r.key] = row
            self._states[r.key] = state.text()
            self._row_icons[r.key] = icon
        ok_n = sum(1 for r in results if r.ok)
        self._sub.setText(f"{len(results)}개 중 {ok_n}개 정상 · {datetime.now().strftime('%H:%M:%S')} 확인")

    def row_state(self, key):
        """그 줄의 「정상」/「끊김」(시험용)."""
        return self._states.get(key)

    def apply_theme(self):
        super().apply_theme()
        self._tag.setStyleSheet(theme.text_qss("current_text", 700) + "letter-spacing: 6px;")
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._sub.setStyleSheet(theme.text_qss("label", 500))
        self._head_line.setStyleSheet(f"background-color: {theme.C('sheet_border')}; border: none;")
        self._recheck.update()

    def relayout(self, vr):
        """폭 856 · 위 150 · 가로 가운데(시안)."""
        w = vpx(vr, 856)
        self.setFixedWidth(w)
        h = self.sizeHint().height()
        self.setGeometry(QRect(vr.left() + (vr.width() - w) // 2, vr.top() + vpx(vr, 150), w, h))


class ConfirmPanel(_Sheet):
    """앱 안 확인 상자(설계 2026-10-13 §4.6) — 운영체제 창(QMessageBox) 대신.

    🔴 기본 = 취소(오동작 방지 · 종전 확인창과 같다). ESC 는 콘솔이 시트로 닫는다(= 취소).
    """

    CUT = 28
    accepted = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, title, body, ok_text, cancel_text, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 36, 40, 32)
        lay.setSpacing(16)
        self._title = QLabel(title)
        self._title.setFont(config.font("sheet_title", 800))
        self._title.setWordWrap(True)
        self._body = QLabel(body)
        self._body.setFont(config.font("sub", 500))
        self._body.setWordWrap(True)
        lay.addWidget(self._title)
        lay.addWidget(self._body)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.cancel_button = QPushButton(cancel_text)
        self.ok_button = QPushButton(ok_text)
        for b in (self.cancel_button, self.ok_button):
            b.setFont(config.font("item", 800))
            b.setMinimumHeight(72)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # ESC 가 창으로 가게
            row.addWidget(b, 1)
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.closed.emit)
        self.ok_button.clicked.connect(self.accepted.emit)
        lay.addLayout(row)

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._body.setStyleSheet(theme.text_qss("label", 500))
        self.cancel_button.setStyleSheet(
            f"QPushButton {{ background: {theme.C('current')}; color: #111111; border: none; }}")
        self.ok_button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.C('warn_text')};"
            f" border: 2px solid {theme.C('warn')}; }}")

    def relayout(self, vr):
        """영상 가운데 · 폭 760(시안)."""
        w = vpx(vr, 760)
        self.setFixedWidth(w)
        h = self.sizeHint().height()
        self.setGeometry(QRect(vr.left() + (vr.width() - w) // 2, vr.top() + (vr.height() - h) // 2, w, h))


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
