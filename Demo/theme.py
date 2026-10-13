"""UI 테마 토큰 — 다크(기본) / 화이트 2벌.

정본: 상위 `docs/superpowers/specs/2026-10-13-시연UI-개선-design.md` §2.2 (앞 정본 2026-08-03 글라스 §3 을 갱신)
      **값을 여기서 임의로 바꾸지 말 것.** 바꿔야 하면 그 문서를 먼저 고친다.

왜 모듈로 뺐나:
    색이 safety_console.py 의 setStyleSheet 문자열 9곳에 흩어져 있어
    **테마 전환이 구조적으로 불가능**했다. 폰트를 config 로 모은 것과 같은 정리다.

설계 원칙 (design §3):
    "불투명도를 올리지 않고 **글자 쪽으로** 대비를 얻는다."
    - 다크: 밝은 글자 + 어두운 후광 3겹
    - 화이트: 어두운 글자 + **밝은 후광 3겹** (대칭)

🔴 화이트는 다크의 단순 반전이 아니다:
    경고·위험색을 그대로 뒤집으면 밝은 판 위 밝은 주황·빨강이라 **대비가 사라진다.**
    안전 표시라 화이트 쪽을 **더 어둡게** 따로 잡았다. selftest/test_theme.py 가 이를 강제한다.
"""

DEFAULT_THEME = "dark"

THEMES = {
    # =========================================================================
    # 다크 (기본) — design §3.1
    # =========================================================================
    "dark": {
        # 판
        "panel_bg":       "rgba(12, 14, 16, 0.68)",     # 🔴 55% 는 밝은 창가에서 작은 글씨 대비 3.0 → 68% 로 4.8 이상(설계 2026-10-13 §2.2)
        "panel_bg_alert": "rgba(12, 14, 16, 0.82)",     # 경고 · 차단 때 — 뒤가 어두워지는 화면
        "panel_border":   "rgba(255, 255, 255, 0.16)",
        "sheet_bg":       "rgba(10, 12, 14, 0.94)",     # 메뉴·알림·설정 — 읽고 눌러야 하므로 진하게
        "sheet_border":   "rgba(255, 255, 255, 0.14)",
        # 글자
        "text":          "#e6e8ea",
        "label":         "#c3c9cf",                  # 부가 라벨
        "todo":          "#d5dade",                  # 🔴 종전 #6d7378 은 밝은 배경에서 사실상 안 보였다
        "done":          "#7dffa8",
        "current":       "#ffd75c",
        "warn":          "#ff9d45",
        "danger":        "#ff6b6b",
        "info":          "#9ccaff",
        # 글씨용 — 다크는 채움색과 같다(화이트는 채움색이 글씨로는 대비가 모자라 따로)
        "current_text":  "#ffd75c",
        "done_text":     "#7dffa8",
        "warn_text":     "#ff9d45",
        # 글자 그림자 3겹 — 배경 밝기와 무관하게 글자를 분리
        "text_shadow":   "0 1px 2px #000, 0 0 5px rgba(0,0,0,.95), 0 0 12px rgba(0,0,0,.8)",
        # 게이지
        "gauge_track":   "rgba(0, 0, 0, 0.65)",      # 🔴 흰색 반투명은 밝은 배경에서 채움과 구분이 안 됐다
        "gauge_edge":    "rgba(255, 255, 255, 0.22)",
        "gauge_from":    "#e8a000",
        "gauge_to":      "#ffd75c",
        # 버튼
        "cta_bg":        "rgba(56, 150, 255, 0.92)",
        "cta_border":    "rgba(160, 210, 255, 0.80)",
        "cta_text":      "#ffffff",
        # 상태 영상 처리
        "video_dim":     "0.60",                     # 메뉴·설정이 열렸을 때 영상 밝기 배수
        # 공구 문구 판 — 🔴 다크·화이트 **공통**이다. 대비 상대가 테마가 아니라
        #    **영상**이고, 영상에는 테마가 없다(설계 §6.3).
        "tool_plate":      "rgba(0, 0, 0, 0.50)",
        "tool_plate_text": "#ffffff",
    },

    # =========================================================================
    # 화이트 — design §3.2
    # =========================================================================
    "light": {
        "panel_bg":       "rgba(242, 239, 232, 0.68)",  # 아이보리 — 흰색은 너무 밝았다(사용자 10/13) · 다크와 같은 진하기
        "panel_bg_alert": "rgba(242, 239, 232, 0.82)",
        "panel_border":   "rgba(0, 0, 0, 0.26)",
        "sheet_bg":       "rgba(242, 239, 232, 0.95)",
        "sheet_border":  "rgba(0, 0, 0, 0.30)",
        "text":          "#0b0f12",
        "label":         "#39424a",
        "todo":          "#49525a",
        "done":          "#009a42",                     # 채도 상향 (#0a7a3d → #009a42)
        "current":       "#cc6f00",                     # 채도 상향 (#8a5200 → #cc6f00)
        "warn":          "#b34700",                     # 🔴 다크(#ff8f2e)보다 어둡게 — 밝은 판 위 대비
        "danger":        "#a80000",                     # 🔴 다크(#ff5252)보다 어둡게
        "info":          "#084a8c",
        "current_text":  "#8f4a00",                     # 채움 #cc6f00 은 글씨로는 대비가 모자란다
        "done_text":     "#00702f",
        "warn_text":     "#9a3c00",
        # 🔴 밝은 후광 3겹 — 다크의 검은 후광을 그대로 뒤집은 것.
        #    검정에 가까운 본문은 채도를 올릴 수 없어(검정은 채도가 없다) 후광이 유일한 해법이다.
        "text_shadow":   "0 1px 2px #fff, 0 0 5px rgba(255,255,255,.98), 0 0 12px rgba(255,255,255,.9)",
        "gauge_track":   "rgba(255, 255, 255, 0.80)",
        "gauge_edge":    "rgba(0, 0, 0, 0.30)",
        "gauge_from":    "#cc6f00",
        "gauge_to":      "#ffb300",
        "cta_bg":        "rgba(11, 92, 173, 0.92)",
        "cta_border":    "rgba(0, 40, 90, 0.55)",
        "cta_text":      "#ffffff",
        "video_dim":     "0.72",
        # 공구 문구 판 — 🔴 다크·화이트 **공통**이다. 대비 상대가 테마가 아니라
        #    **영상**이고, 영상에는 테마가 없다(설계 §6.3).
        "tool_plate":      "rgba(0, 0, 0, 0.50)",
        "tool_plate_text": "#ffffff",
    },
}

# 경고·차단 시 다른 오버레이를 낮추는 값 (design §3.1 「흐림 처리」)
DIM_OPACITY = 0.40

# 상시 오버레이(단계 카드 · 대기 시간)의 판 배경을 그릴지 — 기본 켬(시연 UI 개선 · 사용자 10/13 「반투명 카드」).
#    False 면 글자만 영상 위에 뜬다(종전 기본 · 설정 화면에서 끌 수 있다).
PANEL_BACKGROUND = True

# 경고·차단 때 영상 가장자리 테두리 — 기본 켬(시연 UI 개선 설계 2026-10-13 §3.3).
#    종전 「쓰지 않는다」(2026-09-25)는 번짐 · 75% 상수 자리 때문이었다 → 번짐 없는 선명한 선 · 실제 영상 사각형에.
GLOW_BORDER = True

_current = DEFAULT_THEME


def set_theme(name):
    """테마 전환. 없는 이름은 ValueError — 조용히 무시하면 왜 안 바뀌는지 모른다."""
    global _current
    if name not in THEMES:
        raise ValueError(f"알 수 없는 테마: {name!r} (가능: {', '.join(THEMES)})")
    _current = name


def current():
    return _current


def C(token):
    """현재 테마의 색·값. 없는 토큰은 KeyError로 즉시 드러낸다."""
    return THEMES[_current][token]


def rgba(token, alpha):
    """#rrggbb 토큰 → rgba() 문자열(알파만 바꿀 때 · 불빛 60% 등)."""
    h = C(token).lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def panel_qss(kind="panel", radius=8, padding="12px 14px"):
    """오버레이 패널의 스타일시트 문자열.

    kind: "panel" = 상시 오버레이(반투명) / "alert" = 경고·차단 상자(더 진하게) / "sheet" = 메뉴·알림·설정(진하게)
    """
    bg = {"panel": C("panel_bg"), "alert": C("panel_bg_alert")}.get(kind, C("sheet_bg"))
    border = C("sheet_border") if kind == "sheet" else C("panel_border")
    return (f"background-color: {bg};"
            f"border: 1px solid {border};"
            f"border-radius: {radius}px;"
            f"padding: {padding};"
            f"color: {C('text')};")


def text_qss(token="text", weight=600):
    """글자 색·굵기 스타일시트. 그림자는 Qt 스타일시트가 지원하지 않아
    QGraphicsDropShadowEffect 로 따로 건다(overlay.py)."""
    return f"color: {C(token)}; font-weight: {weight}; border: none; background: transparent;"


def gauge_qss():
    """게이지 트랙 스타일시트."""
    return (f"background-color: {C('gauge_track')};"
            f"border: 1px solid {C('gauge_edge')};"
            f"border-radius: 6px;")
