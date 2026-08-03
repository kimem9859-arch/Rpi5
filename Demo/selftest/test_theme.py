"""테마 토큰 2벌(다크·화이트) 검증.

실행: python3 Demo/selftest/test_theme.py

정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §3

왜 필요한가:
    화이트 테마는 다크의 단순 반전이 **아니다.** 색을 그대로 뒤집으면
    밝은 판 위의 밝은 주황·빨강은 대비가 사라져 **경고가 눈에 안 들어온다.**
    안전 표시라 여기가 가장 중요하므로, 그 제약을 테스트로 못 박는다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import theme

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _luma(hex_color):
    """상대 밝기(0~255). #rrggbb 만 받는다."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_same_token_set():
    """두 테마가 같은 토큰 집합을 갖는가 — 키가 빠지면 그 테마에서 KeyError 로 죽는다."""
    print("\n[1] 토큰 집합 일치")
    dk = set(theme.THEMES["dark"])
    lt = set(theme.THEMES["light"])
    check(dk == lt,
          f"다크 {len(dk)}개 / 화이트 {len(lt)}개, 차이 {sorted(dk ^ lt) or '없음'}")


def test_warning_darker_in_light():
    """🔴 핵심 — 화이트의 경고·위험색이 다크보다 어두운가."""
    print("\n[2] 경고·위험색 (화이트가 더 어두워야 함)")
    for token in ("warn", "danger"):
        d = theme.THEMES["dark"][token]
        l = theme.THEMES["light"][token]
        check(_luma(l) < _luma(d),
              f"{token}: 다크 {d}(밝기 {_luma(d):.0f}) > 화이트 {l}(밝기 {_luma(l):.0f})")


def test_text_contrast_direction():
    """본문 글자는 다크에서 밝고 화이트에서 어두워야 한다."""
    print("\n[3] 본문 글자 방향")
    d = theme.THEMES["dark"]["text"]
    l = theme.THEMES["light"]["text"]
    check(_luma(d) > 128, f"다크 본문 {d} 밝기 {_luma(d):.0f} > 128")
    check(_luma(l) < 128, f"화이트 본문 {l} 밝기 {_luma(l):.0f} < 128")


def test_switch_and_query():
    """set_theme / current / C 가 동작하는가."""
    print("\n[4] 전환")
    theme.set_theme("dark")
    check(theme.current() == "dark", "current() == 'dark'")
    dark_text = theme.C("text")
    theme.set_theme("light")
    check(theme.current() == "light", "current() == 'light'")
    check(theme.C("text") != dark_text, "전환 후 C('text') 가 바뀐다")
    theme.set_theme("dark")  # 기본값 복귀


def test_default_is_dark():
    """기본값은 다크다."""
    print("\n[5] 기본값")
    check(theme.DEFAULT_THEME == "dark", f"DEFAULT_THEME = {theme.DEFAULT_THEME}")


def test_unknown_theme_rejected():
    """없는 테마 이름은 거부한다 — 조용히 무시하면 화면이 왜 안 바뀌는지 모른다."""
    print("\n[6] 잘못된 이름 거부")
    try:
        theme.set_theme("solarized")
        check(False, "set_theme('solarized') 가 예외를 내지 않았다")
    except ValueError:
        check(True, "set_theme('solarized') → ValueError")
    finally:
        theme.set_theme("dark")


def test_panel_qss():
    """패널 스타일 문자열이 현재 테마를 반영하는가."""
    print("\n[7] panel_qss")
    theme.set_theme("dark")
    dq = theme.panel_qss("panel")
    theme.set_theme("light")
    lq = theme.panel_qss("panel")
    check("rgba(" in dq and "rgba(" in lq, "rgba() 배경 포함")
    check(dq != lq, "테마마다 다른 문자열")
    theme.set_theme("dark")


if __name__ == "__main__":
    test_same_token_set()
    test_warning_darker_in_light()
    test_text_contrast_direction()
    test_switch_and_query()
    test_default_is_dark()
    test_unknown_theme_rejected()
    test_panel_qss()

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 테마 검증 통과")
