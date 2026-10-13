"""시안 선 아이콘(SVG) 그리기 — 시연 UI 개선 시안 대조(10/14).

실행: python3 Demo/selftest/test_ui_icons.py   (offscreen)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
import ui_icons

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_every_icon_draws():
    print("\n[아이콘] 모두 그려진다")
    for name in ui_icons.NAMES:
        pm = ui_icons.pixmap(name, "#ff0000", 28)
        img = pm.toImage()
        hit = any(img.pixelColor(x, y).alpha() > 0 for x in range(28) for y in range(28))
        check(pm.width() == 28 and hit, f"{name}")


def test_cache_and_color():
    print("\n[아이콘] 같은 것은 한 번만 만든다 · 색")
    a = ui_icons.pixmap("bell", "#ffd75c", 24)
    b = ui_icons.pixmap("bell", "#ffd75c", 24)
    check(a.cacheKey() == b.cacheKey(), "캐시")
    img = ui_icons.pixmap("check", "#00ff00", 32).toImage()
    px = [img.pixelColor(x, y) for x in range(32) for y in range(32) if img.pixelColor(x, y).alpha() > 200]
    check(px and all(c.green() > 200 and c.red() < 60 for c in px), "선 색 = 준 색")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 아이콘 통과")
