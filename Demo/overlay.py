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
    """부모 사각형 안에 비율로 배치한다. 픽셀 계산을 한 곳에 모은다.

    🔴 parent_rect 의 **좌상단 오프셋을 존중한다** — 창 전체가 아니라 영상 사각형
       처럼 화면 일부를 넘겨받는 경우가 있다(연결 상태바, 2026-08-04).
       종전에는 폭·높이만 쓰고 left/top 을 버려서, 영상 사각형을 넘겨도 창 기준으로
       앉았다(상태바가 오른쪽 검정 레터박스에 놓였다).
    ⚠️ 다른 오버레이는 영향받지 않는다 — `_relayout` 이 넘기는 `_root.rect()` 는
       좌상단이 (0, 0) 이라 오프셋이 0 이다.
    """
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
    widget.setGeometry(QRect(parent_rect.left() + x, parent_rect.top() + y, w, h))


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
        # 🔴 스타일시트를 **이 위젯에만** 걸기 위한 이름 — 아래 apply_theme 참조.
        self.setObjectName("glassPanel")

    def apply_theme(self):
        """🔴 맨 QWidget 은 WA_StyledBackground 없이는 스타일시트 배경을 **안 그린다**.

        2026-08-04 에 픽셀로 확인: 속성이 꺼져 있으면 배경이 통째로 무시된다
        (빨강 바탕 위에서 RGB(255,0,0) 그대로 → 판이 안 보임).
        theme.PANEL_BACKGROUND 로 켜고 끈다 — 배경 없는 쪽이 AR 글라스답다는 의견이
        있어 **실기동 영상에서 확인한 뒤** 기본값을 정한다.
        """
        on = getattr(theme, "PANEL_BACKGROUND", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, on)
        # 🔴 selector(`#glassPanel`)를 붙여 **이 위젯에만** 건다 — selector 가 없으면
        #    Qt 가 자식 위젯에도 규칙을 물려줘, 배경을 켤 때 panel_qss 의
        #    padding(12px 14px)이 **행 라벨마다** 붙는다. 그래서 배경을 켜면
        #    공정 단계 행 높이가 20 → 44px 로 뛰고 글자가 밀렸다(2026-08-04).
        body = (theme.panel_qss(self.KIND) if on
                else "background: transparent; border: none;")
        self.setStyleSheet(f"QWidget#glassPanel {{ {body} }}")
        for lbl in self.findChildren(QLabel):
            _glow(lbl)


# 공정 단계 행의 안쪽 여백 — 🔴 **배경 유무와 무관하게 늘 같아야 한다.**
#    종전에는 panel_qss 의 padding 이 자식에 상속돼 배경을 켤 때만 붙었고,
#    상속을 막자 이번엔 늘 없어졌다. 사용자가 원한 것은 **넉넉한 쪽**이라
#    여기서 명시적으로 준다(2026-08-04).
_ROW_PAD_V, _ROW_PAD_H = 12, 14
_ROW_BAR = 3                                    # 현재 단계의 왼쪽 막대 두께


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

        # 상태·캡션도 행과 **같은 좌우 여백**을 준다 — 글자 시작점이 세로로
        # 한 줄이 되게. 상하 여백은 주지 않는다(행만큼 벌어지면 머리가 커진다).
        side = f"padding-left: {_ROW_PAD_H}px; padding-right: {_ROW_PAD_H}px;"
        self._state.setText(f"● {state_value}")
        self._state.setStyleSheet(theme.text_qss(
            "warn" if state_value == "WARNING" else
            "danger" if state_value == "BLOCK" else "done", 800) + side)
        self._caption.setStyleSheet(theme.text_qss("label", 600) + side)

        for i, (s, row) in enumerate(zip(self._steps, self._rows)):
            order = i + 1
            text = f"{s['button']} {s.get('name', '')}"
            pad = f"padding: {_ROW_PAD_V}px {_ROW_PAD_H}px;"
            # 현재 단계는 왼쪽 막대가 붙으므로 그만큼 덜 띄워 **글자 시작점을 맞춘다**
            pad_cur = (f"padding: {_ROW_PAD_V}px {_ROW_PAD_H}px"
                       f" {_ROW_PAD_V}px {_ROW_PAD_H - _ROW_BAR}px;")
            if not started:
                row.setText(f"○ {text}")
                row.setStyleSheet(theme.text_qss("todo", 600) + pad)
            elif order < expected_step:
                row.setText(f"✓ {text}")
                row.setStyleSheet(theme.text_qss("done", 600) + pad)
            elif order == expected_step:
                row.setText(f"{mark} {text}")
                row.setStyleSheet(theme.text_qss(cur_token, 800)
                                  + f"border-left: {_ROW_BAR}px solid {theme.C(cur_token)};"
                                  + pad_cur)
            else:
                row.setText(f"○ {text}")
                row.setStyleSheet(theme.text_qss("todo", 600) + pad)

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
            # 윗줄 = 무엇이 필요한가 / 아랫줄 = 지금 어디까지 왔나.
            # 🔑 완료 기준은 「손으로 쥠」이다(2026-08-16, 통합문서 §10.44-(8)).
            #    grasped ⟺ tool_ok 라 phase 를 따로 받지 않아도 구분된다.
            self._tool_box.show()
            self._tool_text.setText(f"{sub.want_tool_name}가 필요합니다")
            self._tool_text.setStyleSheet(theme.text_qss("text", 800))
            if sub.tool_ok:
                state, token = f"✓ {sub.want_tool_name}를 쥐었습니다", "done"
            elif sub.wrong_tool:
                state, token = "⚠ 다른 공구를 쥐고 있습니다", "warn"
            else:
                state, token = "○ 손에 쥐면 확인됩니다", "todo"
            self._tool_state.setText(state)
            self._tool_state.setStyleSheet(theme.text_qss(token, 600))
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
                    f"쥔 것: {wrong_name} — {want_name}로 바꿔 주세요",
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


class ConnBar(_Panel):
    """우하단 연결 상태 — 📷 카메라 · 🔌 인터락 · 🔘 GPIO (design §9).

    🔴 상태는 **아이콘 뒤 알약 배경색**으로 나타낸다. 컬러 이모지는 스타일시트의
       color: 로 물들지 않아 글자색으로는 상태를 구분할 수 없다.
    🔴 상태 판단은 여기서 하지 않는다 — 콘솔이 점검 기능과 **같은 출처**로 계산해
       update_state() 로 넣어 준다. 두 곳이 따로 판단하면 표시바와 점검 화면이
       서로 다른 말을 하게 된다.
    """

    ITEMS = (("camera", "📷"), ("interlock", "🔌"), ("gpio", "🔘"))

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._icons = {}
        self._states = {}
        for key, glyph in self.ITEMS:
            lbl = QLabel(glyph)
            lbl.setFont(config.font("body", 600))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(34, 28)
            lay.addWidget(lbl)
            self._icons[key] = lbl
            self._states[key] = None
        self.update_state({})

    def update_state(self, states):
        """states = {"camera": True|False|None, ...}. None = 확인 중."""
        self._states.update(states or {})
        for key, _ in self.ITEMS:
            v = self._states.get(key)
            token = "done" if v is True else ("danger" if v is False else "todo")
            # 🔴 padding: 0 을 명시한다 — 패널의 padding 이 자식에 상속되면 크기가
            #    고정된 아이콘은 눌려 글리프가 사라진다(2026-08-04 알림에서 겪음).
            self._icons[key].setStyleSheet(
                f"background-color: {theme.C(token)}; border-radius: 6px;"
                f" border: none; padding: 0;")

    def apply_theme(self):
        super().apply_theme()
        self.update_state({})            # 테마가 바뀌면 색을 다시 칠한다

    def relayout(self, parent_rect):
        place(self, parent_rect, right=0.03, bottom=0.04)
