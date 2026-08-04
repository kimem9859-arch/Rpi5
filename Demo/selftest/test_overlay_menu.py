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
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton

import theme
from overlay_menu import MenuPanel, NotifyPanel, SettingsPanel, NOTIFY_KINDS, NotifyButton

_app = QApplication.instance() or QApplication([])
_fails = []
SCREEN = QRect(0, 0, 1920, 1080)


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_menu_signals():
    """메뉴 항목 6개 + 종료가 각각 신호를 낸다.

    구성(2026-08-04): 점검(연결) · 녹화 · 로그 · 캘리브레이션 · CCTV · 설정 + 종료
    """
    print("\n[1] MenuPanel 신호")
    host = QWidget()
    m = MenuPanel(host)
    got = []
    for name in ("check_clicked", "record_clicked", "log_clicked",
                 "calibrate_clicked", "cctv_clicked", "settings_clicked",
                 "shutdown_clicked"):
        getattr(m, name).connect(lambda n=name: got.append(n))
    for b in m._items:
        b.click()
    m._shutdown.click()
    check(len(got) == 7, f"7개 신호 발생: {got}")
    check("check_clicked" in got and "record_clicked" in got,
          "점검(연결)·녹화 항목이 신설됨")


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
    """추후 항목 자리가 남아 있는가 (design §4.7).

    항목이 4개 → 6개로 늘어 여유 자리는 3칸 → 1칸으로 줄였다.
    """
    print("\n[3] 추후 항목 자리")
    host = QWidget()
    m = MenuPanel(host)
    check(len(m._free) >= 1, f"빈 자리 {len(m._free)}칸")
    check(len(m._items) == 6, f"메뉴 항목 {len(m._items)}개")


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


def test_panels_no_close_button():
    """🔴 ✕ 버튼을 두지 않는다 — 같은 버튼(☰/🔔)을 다시 눌러 닫는다."""
    print("\n[13] ✕ 버튼 없음")
    host = QWidget()
    for name, p in (("MenuPanel", MenuPanel(host)), ("NotifyPanel", NotifyPanel(host)),
                    ("SettingsPanel", SettingsPanel(host))):
        texts = [b.text() for b in p.findChildren(QPushButton)]
        check("✕" not in texts, f"{name} 에 ✕ 없음 (버튼: {texts or '없음'})")


def test_panels_do_not_cover_their_buttons():
    """🔴 패널이 자기 버튼을 덮지 않는가 (2026-08-04 피드백).

    메뉴 버튼은 top 5%, 알림 버튼은 bottom 5% 에 있다.
    """
    print("\n[14] 버튼 가림 방지")
    from overlay_menu import _MENU_POS, _NOTIFY_POS
    check(_MENU_POS["top"] > 0.05, f"메뉴 패널 top {_MENU_POS['top']:.2f} > 버튼 0.05")
    check(_NOTIFY_POS["bottom"] > 0.05, f"알림 패널 bottom {_NOTIFY_POS['bottom']:.2f} > 버튼 0.05")


def test_notify_badge():
    """알림 배지 — 0이면 숨기고, 숫자는 버튼 글자에 넣지 않는다."""
    print("\n[15] 알림 배지")
    from overlay_menu import NotifyButton
    host = QWidget(); host.resize(800, 600)
    b = NotifyButton(host); b.setGeometry(0, 0, 60, 50)
    b.set_count(0)
    check(b._badge.isHidden(), "0 → 배지 숨김")
    b.set_count(3)
    check(not b._badge.isHidden() and b._badge.text() == "3", f"3 → 배지 '{b._badge.text()}'")
    check(b.text() == "🔔", f"버튼 글자는 아이콘만: '{b.text()}'")
    b.set_count(150)
    check(b._badge.text() == "99+", f"큰 수는 99+ : '{b._badge.text()}'")
    g = b._badge.geometry()
    # 🔴 2026-08-04 정정 — 종전에는 "꼭짓점에 걸침"(g.y() < 0)을 요구했으나,
    #    걸치면 Qt 가 부모 경계에서 잘라내 배지가 반쪽만 보였다. **안쪽 우상단**으로
    #    바꿨다(설계 §3). 잘림 검사는 test_badge_inside_button 이 맡는다.
    check(g.top() >= 0 and g.right() <= b.width() and g.right() > b.width() * 0.5,
          f"버튼 안 우상단 {g.x()},{g.y()} (버튼 폭 {b.width()})")


def test_check_panel():
    """점검 패널 — 결과를 그리고 실패 항목에 재연결 버튼을 붙인다."""
    print("\n[16] 점검 패널")
    from overlay_menu import CheckPanel
    import precheck
    host = QWidget()
    p = CheckPanel(host)
    results = [precheck.CheckResult("camera", "카메라 연결", False, "연결 실패", retryable=True),
               precheck.CheckResult("hand", "손 검출 모델", True, "사용 가능")]
    p.update_results(results)
    check(len(p._rows) == 2, f"{len(p._rows)}행 표시")
    got = []
    p.retry_requested.connect(got.append)
    btns = [b for b in p._rows["camera"].findChildren(QPushButton)]
    check(len(btns) == 1, "실패+재시도가능 항목에 버튼 있음")
    btns[0].click()
    check(got == ["camera"], f"재연결 신호 {got}")
    check(not p._rows["hand"].findChildren(QPushButton), "통과 항목엔 버튼 없음")


def test_record_panel():
    """녹화 패널 — 모드 2종, 중지 버튼 전환."""
    print("\n[17] 녹화 패널")
    from overlay_menu import RecordPanel
    host = QWidget()
    p = RecordPanel(host)
    got = []
    p.start_requested.connect(got.append)
    p._btn_full.click(); p._btn_cam.click()
    check(got == ["full", "camera"], f"모드 신호 {got}")

    p.set_state(True, "/tmp/a.mp4", 12)
    check(p._btn_stop.isVisible() or not p._btn_stop.isHidden(), "녹화 중 → 중지 버튼")
    check(p._btn_full.isHidden(), "녹화 중 → 시작 버튼 숨김")
    p.set_state(False)
    check(p._btn_stop.isHidden(), "중지 → 시작 버튼 복귀")


def test_badge_inside_button():
    """🔴 배지가 버튼 안에 들어 있는가 — 밖으로 나가면 Qt 가 잘라낸다.

    실측(2026-08-04): 버튼 (179,640,58,44) 안의 배지가 (45,-6,19,18) 이라
    위 6px·오른쪽 6px 이 잘려 보였다.
    """
    print("\n[16] 알림 배지 잘림")
    host = QWidget()
    b = NotifyButton(host)
    b.setGeometry(0, 0, 58, 44)
    for n in (1, 9, 12, 150):
        b.set_count(n)
        r = b._badge.geometry()
        inside = (r.left() >= 0 and r.top() >= 0
                  and r.right() <= b.width() and r.bottom() <= b.height())
        check(inside, f"{n}건 → 배지 {r.x()},{r.y()} {r.width()}×{r.height()} "
                      f"⊂ 버튼 {b.width()}×{b.height()}")
    b.set_count(0)
    check(b._badge.isHidden(), "0건이면 배지 숨김")


def test_menu_width_widened():
    """메뉴 폭 1.5배 — 항목 글자가 오른쪽 경계에 닿아 답답했다(2026-08-04).

    🔴 글자 크기는 유지한다. 멀리서 보는 화면이라 줄이면 가독성을 잃는다(사용자 결정).
    """
    print("\n[17] 메뉴 폭")
    from overlay_menu import _MENU_POS
    check(abs(_MENU_POS["width"] - 0.195) < 1e-6,
          f"폭 비율 {_MENU_POS['width']} (종전 0.13 의 1.5배)")

    host = QWidget()
    m = MenuPanel(host)
    m.relayout(SCREEN)
    check(m.width() == int(SCREEN.width() * 0.195),
          f"1920 기준 폭 {m.width()}px")
    # 가장 긴 항목이 폭 안에 들어가는가 (좌우 여백 24px 감안)
    longest = max(m._items, key=lambda b: b.fontMetrics().horizontalAdvance(b.text()))
    need = longest.fontMetrics().horizontalAdvance(longest.text())
    check(need + 24 <= m.width(),
          f"가장 긴 항목 '{longest.text()}' {need}px + 여백 ≤ {m.width()}px")


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
