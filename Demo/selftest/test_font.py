"""UI 폰트 중앙화 검증 — config.font() 가 Pretendard 를 실제로 적용하는가.

실행: python3 Demo/selftest/test_font.py

왜 필요한가:
    2026-08-03 이전 코드는 QFont("Consolas") 를 7곳에서 썼는데 이 파이에 Consolas 가
    없어 Qt 가 조용히 WenQuanYi Zen Hei Mono(중국어 폰트)로 대체하고 있었다.
    **아무도 의도한 적 없는 글꼴로 3개월을 보냈다.** 요청과 실제가 어긋나도
    아무 신호가 없는 것이 문제였으므로, 여기서 그것을 잡는다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontInfo, QFontMetrics

import config

_app = QApplication.instance() or QApplication([])

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_family_is_pretendard():
    """요청한 폰트가 실제로 적용되는가 — 폴백이면 실패."""
    print("\n[1] 폰트 계열")
    for role in config.UI_FONT_SIZES:
        f = config.font(role)
        fam = QFontInfo(f).family()
        check(fam.startswith(config.UI_FONT_FAMILY),
              f"{role:8s} → {fam} (요청 {config.UI_FONT_FAMILY})")


def test_weights_resolve():
    """굵기 4단계가 요청대로 잡히는가."""
    print("\n[2] 굵기")
    for w in (400, 600, 700, 800):
        f = config.font("body", weight=w)
        info = QFontInfo(f)
        check(info.family().startswith(config.UI_FONT_FAMILY) and info.weight() == w,
              f"weight {w} → {info.family()} / 실제 {info.weight()}")


def test_tabular_numbers():
    """숫자 폭이 균일한가 — 게이지 '18/30s → 19/30s' 흔들림 방지."""
    print("\n[3] 고정폭 숫자(tnum)")
    m = QFontMetrics(config.font("body"))
    widths = [m.horizontalAdvance(str(d)) for d in range(10)]
    check(len(set(widths)) == 1, f"0~9 폭 {widths}")
    check(m.horizontalAdvance("18/30s") == m.horizontalAdvance("19/30s"),
          "'18/30s' 와 '19/30s' 폭 동일")


def test_korean_glyphs():
    """한글이 실제로 그려지는가 — 폭이 0이면 글리프가 없는 것."""
    print("\n[4] 한글 글리프")
    m = QFontMetrics(config.font("body"))
    for s in ("B1 클린·가스차단", "순서가 다릅니다", "스패너를 가져오세요"):
        check(m.horizontalAdvance(s) > 0, f"'{s}' 폭 {m.horizontalAdvance(s)}px")


def test_actual_family_reporter():
    """실제 적용 폰트를 문자열로 돌려주는 헬퍼 — 기동 로그에 쓴다."""
    print("\n[5] 적용 폰트 보고")
    s = config.font_report()
    check(isinstance(s, str) and config.UI_FONT_FAMILY in s, f"font_report() = {s}")


if __name__ == "__main__":
    test_family_is_pretendard()
    test_weights_resolve()
    test_tabular_numbers()
    test_korean_glyphs()
    test_actual_family_reporter()

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 폰트 검증 통과")
