"""UI 테마 토큰 — 다크(기본) / 화이트 2벌.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §3
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
        "panel_bg":      "rgba(0, 0, 0, 0.60)",      # 🔴 순검정. rgb(18,20,22)보다 같은 알파에서 더 진하다
        "panel_border":  "rgba(255, 255, 255, 0.22)",
        "sheet_bg":      "rgba(0, 0, 0, 0.90)",      # 메뉴·알림·설정 — 읽고 눌러야 하므로 진하게
        "sheet_border":  "rgba(255, 255, 255, 0.26)",
        # 글자
        "text":          "#e6e8ea",
        "label":         "#c3c9cf",                  # 부가 라벨
        "todo":          "#c3c9cf",                  # 🔴 종전 #6d7378 은 밝은 배경에서 사실상 안 보였다
        "done":          "#7dffa8",
        "current":       "#ffd75c",
        "warn":          "#ff8f2e",
        "danger":        "#ff5252",
        "info":          "#5aa8ff",
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
    },

    # =========================================================================
    # 화이트 — design §3.2
    # =========================================================================
    "light": {
        "panel_bg":      "rgba(255, 255, 255, 0.30)",   # 채도 상향 + 흰 후광 3겹으로 30%까지 낮췄다
        "panel_border":  "rgba(0, 0, 0, 0.26)",
        "sheet_bg":      "rgba(255, 255, 255, 0.92)",
        "sheet_border":  "rgba(0, 0, 0, 0.30)",
        "text":          "#0b0f12",
        "label":         "#39424a",
        "todo":          "#49525a",
        "done":          "#009a42",                     # 채도 상향 (#0a7a3d → #009a42)
        "current":       "#cc6f00",                     # 채도 상향 (#8a5200 → #cc6f00)
        "warn":          "#b34700",                     # 🔴 다크(#ff8f2e)보다 어둡게 — 밝은 판 위 대비
        "danger":        "#a80000",                     # 🔴 다크(#ff5252)보다 어둡게
        "info":          "#0b5cad",
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
    },
}

# 경고·차단 시 다른 오버레이를 낮추는 값 (design §3.1 「흐림 처리」)
DIM_OPACITY = 0.40

# 🔴 상시 오버레이(공정 단계·게이지)의 판 배경을 그릴지.
#    False 면 글자만 영상 위에 뜬다 — 사용자 의견: "배경 없는 쪽이 AR 글라스답다".
#    ⚠️ 아직 **결정 전**이다. 밝은/어두운 실기동 영상에서 확인한 뒤 기본값을 정한다.
#       (지금은 배경이 없는 상태가 QWidget 의 WA_StyledBackground 누락 때문이었다 —
#        의도한 것이 아니었으므로 껐다 켤 수 있게만 만들어 둔다.)
PANEL_BACKGROUND = False

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


def panel_qss(kind="panel", radius=8, padding="12px 14px"):
    """오버레이 패널의 스타일시트 문자열.

    kind: "panel" = 상시 오버레이(반투명) / "sheet" = 메뉴·알림·설정(진하게)
    """
    bg = C("panel_bg") if kind == "panel" else C("sheet_bg")
    border = C("panel_border") if kind == "panel" else C("sheet_border")
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
            f"border-radius: 4px;")
