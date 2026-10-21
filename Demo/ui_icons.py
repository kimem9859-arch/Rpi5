"""시안 선 아이콘 — Claude Design 시안(2026-10-13 시연 UI 개선)의 SVG 경로를 그대로 옮겼다.

🔑 색 · 크기별로 한 번만 그려 두고(QPixmap 캐시) 붙인다 — 정지 그림이라 장면마다 다시 그리지 않는다.
   🔴 이모지를 쓰지 않는다 — 굵은 글꼴에서 안 그려지던 함정(2026-08-04)과 테마 색을 못 따르는 문제.
사용: `ui_icons.pixmap("bell", theme.C("current"), 24)`
"""
from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

# 이름 → (viewBox, 경로 d, 선 굵기, 채움 여부)
_ICONS = {
    "check":     ("0 0 16 16", "M3 8.5l3 3 7-7", 2.4, False),
    "check_big": ("0 0 24 24", "M5 12.5l4.5 4.5L19 7", 2.6, False),
    "alert":     ("0 0 24 24", "M12 7v6M12 16.5v.5", 2.8, False),
    "alert_sm":  ("0 0 16 16", "M8 3.5v5.5M8 12v.5", 2.4, False),
    "minus":     ("0 0 24 24", "M6.5 12h11", 3.0, False),
    "x":         ("0 0 24 24", "M6 6l12 12M18 6L6 18", 2.8, False),
    "x_sm":      ("0 0 16 16", "M4.5 4.5l7 7M11.5 4.5l-7 7", 2.4, False),
    "lock":      ("0 0 16 18", "M4 8V5.5a4 4 0 0 1 8 0V8M2.5 8h11v8.5h-11z", 2.0, False),
    "play":      ("0 0 24 24", "M8 5l11 7-11 7z", 2.6, False),
    "play_fill": ("0 0 24 24", "M7 4l13 8-13 8z", 0.0, True),
    "info":      ("0 0 24 24", "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-5M12 8h.01", 2.0, False),
    "wrench":    ("0 0 24 24", "M14.5 3.5a5 5 0 0 0-6 6.2L3.6 14.6a1.9 1.9 0 0 0 2.7 2.7l4.9-4.9a5 5 0 0 0 6.2-6"
                               "l-2.6 2.6-2.5-.6-.6-2.5z", 1.8, False),
    "menu":      ("0 0 28 22", "M2 3h24M2 11h24M2 19h24", 3.0, False),
    "bell":      ("0 0 22 24", "M11 2a6 6 0 0 0-6 6v5l-2 4h16l-2-4V8a6 6 0 0 0-6-6zM8 20a3 3 0 0 0 6 0", 2.0, False),
    "camera":    ("0 0 24 24", "M3 8h3l2-3h8l2 3h3v11H3zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", 2.0, False),
    "plug":      ("0 0 24 24", "M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5", 2.0, False),
    "button":    ("0 0 24 24", "M5 12a7 7 0 1 0 14 0 7 7 0 1 0-14 0M9.5 12a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0",
                  2.0, False),
    "pulse":     ("0 0 24 24", "M3 12h4l3-8 4 16 3-8h4", 2.0, False),
    "list":      ("0 0 24 24", "M9 6h12M9 12h12M9 18h12M4 6h.01M4 12h.01M4 18h.01", 2.2, False),
    "sliders":   ("0 0 24 24", "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6", 2.2, False),
    "reset":     ("0 0 24 24", "M2 4v6h6M4.3 15a8.5 8.5 0 1 0 1.9-8.8L2 10", 2.2, False),
    "power":     ("0 0 24 24", "M12 3v8M6.3 6.4a8 8 0 1 0 11.4 0", 2.2, False),   # 프로그램 종료(2026-10-21 — 시안에 없어 같은 선 굵기로)
    "cube":      ("0 0 24 24", "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5", 2.0, False),
    "hand":      ("0 0 24 24", "M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10.5V4a1.5 1.5 0 0 1 3 0v6.5M14 10.5V5.5a1.5 1.5 0 0 1 3 0"
                               "V14a6 6 0 0 1-6 6h-.5A6.5 6.5 0 0 1 5 15l-1.6-3a1.5 1.5 0 0 1 2.6-1.5L8 13", 2.0, False),
    "grid":      ("0 0 24 24", "M4 7h16M4 12h16M4 17h16M8 4v16M16 4v16", 2.0, False),
}
NAMES = tuple(_ICONS)
_cache = {}


def paint_pixmap(w, h, draw):
    """투명 바탕 그림 — draw(QPainter) 로 그린다.

    🔴 QPixmap 을 만들어 fill(투명)하면 환경에 따라 투명 채널 없이 **검게** 됐다(10/14 캡처 — 단계 카드의 검은 네모).
       투명 채널이 보장되는 QImage(ARGB32 premultiplied)에 그린 뒤 바꾼다. 투명 그림은 모두 여기서 만든다.
    """
    img = QImage(int(w), int(h), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    return QPixmap.fromImage(img)


def pixmap(name, color, size):
    """이름 · 색('#rrggbb') · 한 변 px → QPixmap(투명 바탕). 같은 인자는 캐시에서."""
    key = (name, color, int(size))
    pm = _cache.get(key)
    if pm is not None:
        return pm
    vb, d, sw, fill = _ICONS[name]
    paint = (f'fill="{color}"' if fill else
             f'fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><path d="{d}" {paint}/></svg>'
    r = QSvgRenderer(QByteArray(svg.encode()))
    vw, vh = (float(v) for v in vb.split()[2:])
    s = size / max(vw, vh)                      # 가로세로 비율 유지 · 가운데
    w, h = vw * s, vh * s
    pm = paint_pixmap(size, size, lambda p: r.render(p, QRectF((size - w) / 2, (size - h) / 2, w, h)))
    _cache[key] = pm
    return pm
