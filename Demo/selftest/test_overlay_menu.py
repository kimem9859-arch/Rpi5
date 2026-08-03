"""메뉴·알림·설정 패널 스모크 테스트.

실행: python3 Demo/selftest/test_overlay_menu.py   (offscreen)

정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §4.4·§4.7·§4.8
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

import theme
from overlay_menu import MenuPanel, NotifyPanel, SettingsPanel, NOTIFY_KINDS

_app = QApplication.instance() or QApplication([])
_fails = []
SCREEN = QRect(0, 0, 1920, 1080)


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_menu_signals():
    """메뉴 항목 5개가 각각 신호를 낸다."""
    print("\n[1] MenuPanel 신호")
    host = QWidget()
    m = MenuPanel(host)
    got = []
    for name in ("log_clicked", "calibrate_clicked", "cctv_clicked",
                 "settings_clicked", "shutdown_clicked"):
        getattr(m, name).connect(lambda n=name: got.append(n))
    m._items[0].click(); m._items[1].click(); m._items[2].click(); m._items[3].click()
    m._shutdown.click()
    check(len(got) == 5, f"5개 신호 발생: {got}")


def test_menu_shutdown_separated():
    """🔴 시스템 종료는 목록 맨 아래에 분리돼 있는가."""
    print("\n[2] 종료 분리")
    host = QWidget()
    m = MenuPanel(host)
    lay = m.layout()
    last_idx = lay.count() - 1
    check(lay.itemAt(last_idx).widget() is m._shutdown, "종료가 레이아웃 맨 끝")
    check("종료" in m._shutdown.text(), f"라벨: {m._shutdown.text()}")


def test_menu_has_free_slots():
    """추후 항목 자리 3칸이 있는가 (design §4.7)."""
    print("\n[3] 추후 항목 자리")
    host = QWidget()
    m = MenuPanel(host)
    check(len(m._free) == 3, f"빈 자리 {len(m._free)}칸")


def test_notify_kinds():
    """알림 종류 4가지가 정의돼 있는가 (design §4.8)."""
    print("\n[4] 알림 종류")
    check(set(NOTIFY_KINDS) == {"check", "work", "warn", "danger"},
          f"종류 {sorted(NOTIFY_KINDS)}")
    tokens = {v[1] for v in NOTIFY_KINDS.values()}
    check(tokens <= set(theme.THEMES["dark"]), f"색 토큰이 테마에 존재: {sorted(tokens)}")


def test_notify_newest_at_bottom():
    """🔴 메신저 방식 — 최신이 맨 아래로 쌓인다."""
    print("\n[5] 알림 순서")
    host = QWidget()
    n = NotifyPanel(host)
    for i in range(5):
        n.push("work", f"항목 {i}")
    check(n.count == 5, f"{n.count}건 적재")
    lay = n._list
    last_widget = lay.itemAt(lay.count() - 1).widget()
    check(last_widget is n._rows[-1], "마지막에 넣은 것이 레이아웃 맨 아래")


def test_notify_all_kinds():
    """4종 전부 예외 없이 들어가는가."""
    print("\n[6] 알림 4종")
    host = QWidget()
    n = NotifyPanel(host)
    ok = True
    for kind in NOTIFY_KINDS:
        try:
            n.push(kind, f"{kind} 제목", "부가 설명")
        except Exception as e:
            ok = False
            print(f"     {kind} → {type(e).__name__}: {e}")
    check(ok and n.count == 4, "점검·작업·경고·위험 4종 예외 없음")


def test_notify_not_persisted():
    """🔴 파일로 남기지 않는다 — 종료 시 초기화(메모리 전용)."""
    print("\n[7] 파일 저장 없음")
    import inspect
    import overlay_menu
    src = inspect.getsource(overlay_menu.NotifyPanel)
    check("open(" not in src and "write(" not in src,
          "NotifyPanel 안에 파일 쓰기 코드가 없다")


def test_settings_tools_from_recipe():
    """설정의 라디오는 레시피가 준 목록으로 만들어진다 — 코드에 박지 않는다."""
    print("\n[8] 설정 공구 목록")
    host = QWidget()
    s = SettingsPanel(host)
    s.set_tools(["spanner", "driver", "wrench"], "driver",
                {"spanner": "스패너", "driver": "드라이버", "wrench": "렌치"})
    check(len(s._tool_buttons) == 3, f"라디오 {len(s._tool_buttons)}개")
    check(s._tool_buttons["driver"].isChecked(), "기본값 driver 선택됨")
    check(s._tool_buttons["spanner"].text() == "스패너", "한글 표시명 적용")

    got = []
    s.tool_changed.connect(got.append)
    s._tool_buttons["wrench"].setChecked(True)
    check(got == ["wrench"], f"변경 신호 {got}")


def test_settings_tool_locked_while_running():
    """🔴 작업 중에는 공구를 못 바꾼다."""
    print("\n[9] 작업 중 잠금")
    host = QWidget()
    s = SettingsPanel(host)
    s.set_tools(["spanner", "driver"], "spanner")
    s.set_tool_editable(False)
    check(all(not b.isEnabled() for b in s._tool_buttons.values()), "라디오 비활성")
    check("작업 중" in s._tool_note.text(), f"안내: {s._tool_note.text()}")
    s.set_tool_editable(True)
    check(all(b.isEnabled() for b in s._tool_buttons.values()), "IDLE 이면 활성")
    check(s._tool_note.text() == "", "안내 사라짐")


def test_settings_theme_switch():
    """테마 라디오가 신호를 낸다."""
    print("\n[10] 테마 전환")
    host = QWidget()
    s = SettingsPanel(host)
    got = []
    s.theme_changed.connect(got.append)
    for b in s._theme_group.buttons():
        if "화이트" in b.text():
            b.setChecked(True)
    check(got == ["light"], f"신호 {got}")


def test_all_relayout_inside_screen():
    """세 패널 모두 화면 안에 배치되는가."""
    print("\n[11] 배치 경계")
    host = QWidget()
    host.setGeometry(SCREEN)
    panels = [("MenuPanel", MenuPanel(host)),
              ("NotifyPanel", NotifyPanel(host)),
              ("SettingsPanel", SettingsPanel(host))]
    for name, p in panels:
        p.relayout(SCREEN)
        r = p.geometry()
        inside = (r.left() >= 0 and r.top() >= 0
                  and r.right() <= SCREEN.width() and r.bottom() <= SCREEN.height())
        check(inside, f"{name} {r.left()},{r.top()} {r.width()}×{r.height()}")


def test_both_themes():
    """두 테마에서 apply_theme 이 예외 없이 도는가."""
    print("\n[12] 테마 적용")
    host = QWidget()
    m, n, s = MenuPanel(host), NotifyPanel(host), SettingsPanel(host)
    s.set_tools(["spanner"], "spanner")
    n.push("warn", "테스트")
    ok = True
    for t in ("dark", "light"):
        theme.set_theme(t)
        for p in (m, n, s):
            try:
                p.apply_theme()
            except Exception as e:
                ok = False
                print(f"     {t}/{type(p).__name__} → {type(e).__name__}: {e}")
    theme.set_theme("dark")
    check(ok, "다크·화이트 × 3패널 예외 없음")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 메뉴·알림·설정 스모크 통과")
