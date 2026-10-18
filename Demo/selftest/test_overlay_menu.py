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


def test_menu_items_four_without_record_shutdown():
    """4.1 메뉴 — 항목 4개(점검 · 로그 · 설정 · 작업 초기화) · 녹화 · 시스템 종료 없음(사용자 10/13 · 설계 2026-10-13 §4.1)."""
    print("\n[1] MenuPanel 항목 · 신호")
    host = QWidget()
    m = MenuPanel(host)
    check(m.item_titles() == ["점검 (연결)", "로그", "설정", "작업 초기화"], f"{m.item_titles()}")
    check(not hasattr(m, "record_clicked") and not hasattr(m, "shutdown_clicked"), "녹화 · 종료 신호 없음")
    got = []
    for name in ("check_clicked", "log_clicked", "settings_clicked", "reset_clicked"):
        getattr(m, name).connect(lambda n=name: got.append(n))
    for b in m._items:
        b.click()
    check(got == ["check_clicked", "log_clicked", "settings_clicked", "reset_clicked"], f"{got}")


def test_menu_icons_are_line_art():
    """4.1 시안 대조(10/14) — 항목 아이콘 = 시안 선 그림(점검 · 로그 · 설정 · 초기화)."""
    print("\n[1-b] 메뉴 선 아이콘")
    host = QWidget(); m = MenuPanel(host); m.apply_theme()
    check(all(not it.icon.pixmap().isNull() and it.icon.text() == "" for it in m._items), "4개 모두 그림")
    check(m._items[0].desc.text() == "카메라 · 인터락 · AI 가속칩 상태", m._items[0].desc.text())


def test_menu_system_summary_and_place():
    """4.1 메뉴 — 아래 시스템 상태 4줄 · 자리 x 1201~1781 · y 100~1248(☰ 아래)."""
    print("\n[2] 시스템 상태 요약 · 자리")
    host = QWidget(); host.resize(1920, 1280); m = MenuPanel(host)
    m.set_system({"camera": True, "interlock": True, "gpio": False, "detector": True}, fps=23.7)
    check(m._sys["camera"][1].text() == "연결 · 23.7 fps", m._sys["camera"][1].text())
    check(m._sys["gpio"][1].text() == "끊김", m._sys["gpio"][1].text())
    m.set_system({"camera": True, "interlock": True, "gpio": True, "detector": True}, fps=23.7)
    check(m._sys["gpio"][1].text() == "B1 ~ B4 · EMO", f"시안 값 {m._sys['gpio'][1].text()}")
    check(m._sys["detector"][1].text() == "정상", m._sys["detector"][1].text())
    m.relayout(QRect(107, 0, 1707, 1280))
    check(m.geometry() == QRect(1201, 100, 580, 1148), f"{m.geometry()}")
    m.set_context("작업 진행 중 · 2단계 냉각")
    check(m._ctx.text() == "작업 진행 중 · 2단계 냉각", m._ctx.text())


def test_no_calibration_item():
    """캘리브레이션은 test/calib_capture.py 로만 한다(spec 2026-09-23 D2)."""
    print("\n[3-c] 캘리브레이션 항목 없음")
    import overlay_menu
    check(not hasattr(overlay_menu.MenuPanel, "calibrate_clicked"), "캘리브레이션 신호가 남아 있지 않다")


def test_no_cctv_item():
    """USB 웹캠 기능 제거(spec 2026-09-23 D5)."""
    print("\n[3-b] CCTV 항목 없음")
    import overlay_menu
    check(not any(hasattr(c, "cctv_clicked") for c in vars(overlay_menu).values()
                  if isinstance(c, type)), "CCTV 신호가 남아 있지 않다")
    host = QWidget()
    check(not any("CCTV" in t for t in MenuPanel(host).item_titles()),
          "메뉴에 「CCTV 전환」 글자가 없다")


def test_notify_kinds():
    """알림 종류 4가지가 정의돼 있는가 (design §4.8)."""
    print("\n[4] 알림 종류")
    check(set(NOTIFY_KINDS) == {"check", "work", "warn", "danger"},
          f"종류 {sorted(NOTIFY_KINDS)}")
    tokens = {v[1] for v in NOTIFY_KINDS.values()}
    check(tokens <= set(theme.THEMES["dark"]), f"색 토큰이 테마에 존재: {sorted(tokens)}")


def test_notify_newest_at_top():
    """4.3 알림 — 최신이 맨 위(설계 2026-10-13 §4.3 · 종전 메신저 방식 맨 아래)."""
    print("\n[5] 알림 순서")
    host = QWidget()
    n = NotifyPanel(host)
    for i in range(5):
        n.push("work", f"항목 {i}")
    check(n.count == 5, f"{n.count}건 적재")
    check(n._list.itemAt(0).widget() is n._rows[-1], "마지막에 넣은 것이 맨 위")
    check(n.first_title() == "항목 4", n.first_title())


def test_notify_matches_comp():
    """4.3 시안 대조(10/14) — ALERTS · 「최근 N건 · 새 알림 M건」 · 닫기 · 각진 아이콘 칸 · 왼쪽 위 (139, 448) · 폭 640."""
    print("\n[5-c] 알림 시안")
    host = QWidget(); host.resize(1920, 1280); n = NotifyPanel(host)
    got = []; n.closed.connect(lambda: got.append(1))
    n.push("work", "작업 시작", "PECVD 정비 · 4단계"); n.push("danger", "버튼 입력 차단됨", "B3")
    n.apply_theme(); n.relayout(QRect(107, 0, 1707, 1280))
    check(n._sub.text() == "최근 2건 · 새 알림 2건", n._sub.text())
    check((n.x(), n.y(), n.width()) == (139, 448, 640), f"{n.geometry()}")
    btns = [b for b in n.findChildren(QPushButton) if b.text() == "✕"]
    check(len(btns) == 1, "닫기 있음")
    if btns:
        btns[0].click(); check(got == [1], "닫기 → closed")
    n.mark_all_read(); check(n._sub.text() == "최근 2건 · 새 알림 0건", n._sub.text())


def test_notify_new_and_height():
    """Review Focus 5 — NEW 표시가 붙고 다 읽으면 지워진다 · 100건이 넘어도 🔔(y 1204) 위에서 끝나고 화면 위로 넘치지 않는다."""
    print("\n[5-b] NEW · 높이")
    host = QWidget(); host.resize(1920, 1280); n = NotifyPanel(host)
    vr = QRect(107, 0, 1707, 1280)
    n.push("warn", "순서가 다릅니다"); n.push("work", "작업 초기화")
    n.relayout(vr)
    short = n.height()
    check(n.new_count == 2, f"NEW {n.new_count}")
    n.mark_all_read(); check(n.new_count == 0, "다 읽음")
    for i in range(120):
        n.push("work", f"알림 {i}")
    n.relayout(vr)
    check(n.geometry().bottom() <= 1204 - 12, f"🔔 위에서 끝남 {n.geometry()}")
    check(n.geometry().top() >= 100, f"위로 넘치지 않음 {n.geometry()}")
    check(short < n.height(), f"내용에 맞는 높이 {short} < {n.height()}")


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
    """4.2 테마 = 나눠 고르는 버튼 · 같은 것을 다시 눌러도 신호 한 번."""
    print("\n[10] 테마 전환")
    host = QWidget()
    s = SettingsPanel(host)
    got = []
    s.theme_changed.connect(got.append)
    s._theme_buttons["light"].click()
    check(got == ["light"], f"신호 {got}")
    s._theme_buttons["light"].click()
    check(got == ["light"], "같은 것을 다시 눌러도 한 번")


def test_settings_switches():
    """4.2 화면 표시 켬/끔 4개(설계 2026-10-13 §4.2) — 점수는 상자가 켜졌을 때만 · 「감지·차단은 그대로」."""
    print("\n[10-b] 켬/끔 스위치")
    host = QWidget(); s = SettingsPanel(host)
    got = []
    for sig in ("panel_bg_changed", "boxes_changed", "scores_changed", "hand_changed"):
        getattr(s, sig).connect(lambda v, n=sig: got.append((n, v)))
    check(s.switch("bg").isChecked() and s.switch("boxes").isChecked() and s.switch("hand").isChecked(),
          "배경 · 상자 · 손 기본 켬")
    check(s.switch("scores").isChecked() is False, "점수 기본 끔")
    s.switch("scores").click()
    check(("scores_changed", True) in got and s.switch("scores").text() == "켬", "점수 켬 신호 · 글 「켬」")
    s.switch("boxes").click()
    check(("boxes_changed", False) in got and not s.switch("scores").isEnabled(), "상자 끄면 점수 스위치 잠김")
    s.switch("hand").click()
    check(("hand_changed", False) in got, "손 끔 신호")
    check("감지 · 차단은 그대로" in s._box_note.text(), s._box_note.text())


def test_settings_guide_switch():
    """시연 안내 스위치(상위 specs/2026-10-18-시연안내모드-design.md §6.1) — 기본 끔 · 켜면 신호 한 번."""
    print("\n[10-c] 시연 안내 스위치")
    host = QWidget(); s = SettingsPanel(host)
    got = []
    s.guide_changed.connect(lambda v: got.append(v))
    check(s.switch("guide").isChecked() is False, "「시연 안내」 기본 끔(켤 때마다 끔으로 시작)")
    check("시연 안내" in [n.text() for n in s._switch_names], "이름 「시연 안내」")
    s.switch("guide").click()
    check(got == [True] and s.switch("guide").text() == "켬", f"켜면 guide_changed(True) 한 번 · 글 「켬」({got})")
    s.switch("guide").click()
    check(got == [True, False], f"끄면 guide_changed(False)({got})")
    s.resize(856, 1100)
    s.show()
    QApplication.processEvents()
    y_guide = s.switch("guide").mapTo(s, s.switch("guide").rect().topLeft()).y()
    y_note = s._box_note.mapTo(s, s._box_note.rect().topLeft()).y()
    y_hand = s.switch("hand").mapTo(s, s.switch("hand").rect().topLeft()).y()
    check(y_hand < y_note < y_guide, f"「화면 표시만 끕니다」 문장 아래에 있다(사용자 — 그 문장이 이 스위치에 걸려 읽히지 않게 · 손 {y_hand} · 문장 {y_note} · 안내 {y_guide})")
    s.hide()


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
    """🔴 메뉴·알림 **창 자체**에는 ✕ 를 두지 않는다 — 같은 버튼(☰/🔔)으로 닫는다.

    🔴 2026-08-04 정정 — 설정은 이 목록에서 빠졌다. 메뉴에서 연 **항목 패널**
       (점검·녹화·설정·로그)은 자기 버튼이 따로 없어 ✕ 가 필요하다
       (test_item_sheets_have_close_button 참조).
    """
    print("\n[13] ✕ 버튼 없음 (메뉴·알림 창)")
    host = QWidget()
    for name, p in (("MenuPanel", MenuPanel(host)),):     # 시안(10/14) — 알림 창에는 닫기가 있다
        texts = [b.text() for b in p.findChildren(QPushButton)]
        check("✕" not in texts, f"{name} 에 ✕ 없음 (버튼: {texts or '없음'})")


def test_panels_do_not_cover_their_buttons():
    """🔴 패널이 자기 버튼을 덮지 않는가 (2026-08-04 피드백) — ☰(y 32~84) 아래에서 메뉴가 시작한다(y 100)."""
    print("\n[14] 버튼 가림 방지")
    host = QWidget(); host.resize(1920, 1280); m = MenuPanel(host)
    m.relayout(QRect(107, 0, 1707, 1280))
    check(m.y() > 32 + 52, f"메뉴 위 {m.y()} > ☰ 아래 84")
    from overlay_menu import _NOTIFY_POS
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


def test_check_rows_state_and_place():
    """4.4 점검 — 줄마다 「정상/끊김」 · 재연결 · 가운데 폭 760(설계 2026-10-13 §4.4)."""
    print("\n[16-b] 점검 줄 상태 · 자리")
    from overlay_menu import CheckPanel
    from precheck import CheckResult
    host = QWidget(); host.resize(1920, 1280); c = CheckPanel(host)
    c.update_results([CheckResult("camera", "안경 카메라", False, "응답 없음", retryable=True),
                      CheckResult("interlock", "인터락 연결", True, "RUN")])
    check(c.row_state("camera") == "끊김" and c.row_state("interlock") == "정상", "상태 글")
    got = []; c.retry_requested.connect(got.append)
    c._retry_buttons["camera"].click(); check(got == ["camera"], f"{got}")
    c.layout().activate(); c.relayout(QRect(107, 0, 1707, 1280))
    check(c.width() == 856 and abs(c.geometry().center().x() - 960) <= 1, f"{c.geometry()}")     # 시안 856


def test_confirm_panel_default_cancel():
    """4.6 확인 상자 — 기본 = 취소 · 「초기화」 = accepted · 「취소」 = closed."""
    print("\n[4.6] 확인 상자")
    from overlay_menu import ConfirmPanel
    host = QWidget(); c = ConfirmPanel("작업을 초기화할까요?", "본문", "초기화", "취소", host)
    acc, clo = [], []
    c.accepted.connect(lambda: acc.append(1)); c.closed.connect(lambda: clo.append(1))
    check(c.cancel_button.isDefault() and not c.ok_button.isDefault(), "기본 = 취소")
    c.cancel_button.click(); check(clo == [1] and acc == [], "취소 = closed")
    c.ok_button.click(); check(acc == [1], "초기화 = accepted")


def test_start_button_look_and_place():
    """작업 시작 버튼 시안 A(사용자 10/14) — 각진 판 · 노란 ▶ 타일 · START · 부제 · 영상 가운데 폭 640."""
    print("\n[작업 시작] 시안 A")
    from overlay_menu import StartButton
    host = QWidget(); host.resize(1920, 1280); b = StartButton(host)
    b.set_subtitle("PECVD 정비 · 4단계 · 1단계 공정 정지부터")
    b.apply_theme(); b.relayout(QRect(107, 0, 1707, 1280))
    check(b.width() == 640 and abs(b.geometry().center().x() - 960) <= 1
          and abs(b.geometry().center().y() - 640) <= 1, f"가운데 폭 640 {b.geometry()}")
    check(b.text().endswith("작업 시작"), b.text())
    check(b.subtitle() == "PECVD 정비 · 4단계 · 1단계 공정 정지부터", b.subtitle())
    host.show(); _app.processEvents()
    img = b.grab().toImage()
    c = img.pixelColor(30 + 20, b.height() // 2)             # ▶ 타일 안(왼쪽 여백 30 뒤)
    check(c.red() > 200 and c.green() > 180 and c.blue() < 140, f"노란 타일 {c.name()}")
    corner = img.pixelColor(2, 2)
    check(corner.alpha() < 50, f"왼쪽 위 모서리는 잘림(투명) {corner.alpha()}")


def test_check_matches_comp():
    """4.4 시안 대조(10/14) — SYSTEM CHECK · 「N개 중 M개 정상 · 시각 확인」 · 선 아이콘 칸 · 노란 「다시 점검」 · (532, 150) 폭 856."""
    print("\n[16-c] 점검 시안")
    from overlay_menu import CheckPanel
    from precheck import CheckResult
    host = QWidget(); host.resize(1920, 1280); c = CheckPanel(host)
    c.update_results([CheckResult("camera", "카메라 연결", False, "응답 없음", retryable=True),
                      CheckResult("detector", "버튼 인식 모델", True, "적재"),
                      CheckResult("gpio", "GPIO 입력", True, "B1 ~ B4 · EMO")])
    c.apply_theme(); c.layout().activate(); c.relayout(QRect(107, 0, 1707, 1280))
    check((c.x(), c.y(), c.width()) == (532, 150, 856), f"{c.geometry()}")
    check(c._sub.text().startswith("3개 중 2개 정상 · ") and c._sub.text().endswith(" 확인"), c._sub.text())
    check(all(not ic.pixmap().isNull() for ic in c._row_icons.values()), "선 아이콘 칸")
    host.show(); _app.processEvents()
    px = c._recheck.grab().toImage().pixelColor(30, c._recheck.height() // 2)
    check(px.red() > 200 and px.green() > 180 and px.blue() < 140, f"다시 점검 = 노랑 {px.name()}")


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


def test_menu_titles_fit():
    """메뉴 항목 제목이 폭 안에 들어간다(글자 크기는 유지 — 멀리서 보는 화면 · 사용자 결정)."""
    print("\n[17] 메뉴 항목 글자 폭")
    host = QWidget(); host.resize(1920, 1280); m = MenuPanel(host)
    m.relayout(QRect(107, 0, 1707, 1280)); m.layout().activate()
    for it in m._items:
        need = it.title.fontMetrics().horizontalAdvance(it.title.text())
        check(need <= it.title.width() or it.title.width() == 0, f"{it.title.text()} {need}px ≤ {it.title.width()}px")


def test_settings_note_hidden_when_empty():
    """🔴 문구가 없으면 라벨을 숨긴다 — 빈칸이 공구와 테마 사이를 벌렸다.

    실측(2026-08-04): 빈 문구 라벨이 37px 를 차지했다.
    """
    print("\n[18] 설정 빈칸")
    host = QWidget()
    s = SettingsPanel(host)
    s.set_tools(["spanner", "driver"], "spanner")

    s.set_tool_editable(True)                  # IDLE — 문구 없음
    check(s._tool_note.isHidden(), "변경 가능하면 문구 라벨이 숨겨진다")

    s.set_tool_editable(False)                 # 작업 중 — 문구 있음
    check(not s._tool_note.isHidden(), "작업 중이면 문구가 보인다")
    check("변경할 수 없습니다" in s._tool_note.text(), f"문구: {s._tool_note.text()}")


def test_item_sheets_have_close_button():
    """🔴 메뉴에서 연 항목 패널은 ✕ 로 닫는다 (2026-08-04).

    종전에는 ☰ 를 다시 눌러야 닫혔다. 메뉴·알림 창 **자체**는 자기 버튼이
    보이므로 재클릭으로 닫는 방식을 그대로 둔다 — ✕ 는 항목 패널에만 단다.
    """
    print("\n[19] 항목 패널 ✕")
    from overlay_menu import CheckPanel, RecordPanel
    host = QWidget()
    for cls in (CheckPanel, RecordPanel, SettingsPanel):
        pnl = cls(host)
        btns = [b for b in pnl.findChildren(QPushButton) if b.text() == "✕"]
        check(len(btns) == 1, f"{cls.__name__} 에 ✕ 1개")
        if btns:
            got = []
            pnl.closed.connect(lambda: got.append(1))
            btns[0].click()
            check(got == [1], f"{cls.__name__} ✕ → closed 신호")


def test_notify_icons_are_marks():
    """4.3 알림 아이콘 = 종류별 색 원 + 기호(설계 2026-10-13 §4.3) — 🔴 이모지는 굵은 글꼴에서 안 그려지던 함정이 있었다."""
    print("\n[20] 알림 아이콘")
    want = {"check": "check_big", "work": "play", "warn": "alert", "danger": "x"}   # 시안 선 아이콘 이름
    check(set(NOTIFY_KINDS) == set(want), f"종류 4가지 유지: {sorted(NOTIFY_KINDS)}")
    for k, icon in want.items():
        check(NOTIFY_KINDS[k][0] == icon, f"{k} → {NOTIFY_KINDS[k][0]}")
    host = QWidget()
    pnl = NotifyPanel(host)
    pnl.push("danger", "전기 입력 차단됨", "1단계 B1")
    check(pnl.count == 1, "알림 1건 추가")


def test_notify_icon_aligned_with_title():
    """아이콘 칸(48)은 **제목+설명 두 줄 전체**의 세로 가운데 — 시안(10/14 대조 · align-items: center).

    종전(2026-08-04)은 작은 아이콘을 제목 줄에 맞췄다 — 시안의 큰 각진 칸은 줄 전체에 맞춘다.
    """
    print("\n[21] 알림 아이콘 정렬")
    from PyQt6.QtWidgets import QLabel
    host = QWidget()
    host.setGeometry(SCREEN)
    pnl = NotifyPanel(host)
    pnl.relayout(SCREEN)
    pnl.push("warn", "순서가 다릅니다", "부가 설명 한 줄")
    pnl.show()
    # ⚠️ 스크롤 안쪽까지 레이아웃을 확정시켜야 좌표가 나온다 — 패널만 activate 하면
    #    행 위젯의 geometry 가 계산 전 값으로 남는다(2026-08-04).
    pnl.layout().activate()
    pnl._body.layout().activate()
    _app.processEvents()

    row = pnl._rows[-1]
    row.layout().activate()
    _app.processEvents()
    lbls = row.findChildren(QLabel)
    icon, title, sub = lbls[0], lbls[1], [l for l in lbls if l.text() == "부가 설명 한 줄"][0]
    ic = icon.geometry().center().y()
    tc = (title.mapTo(row, title.rect().topLeft()).y() + sub.mapTo(row, sub.rect().bottomLeft()).y()) / 2
    check(abs(ic - tc) <= 4, f"아이콘 중심 {ic} ≈ 두 줄 중심 {tc:.0f} (차이 {abs(ic - tc):.0f}px)")
    pnl.hide()


def test_record_buttons_side_by_side():
    """🔴 시작 버튼 2개는 가로로 나란히 (2026-08-04).

    세로로 쌓여 있어 패널이 가로로 지나치게 길었다.
    """
    print("\n[22] 녹화 버튼 가로 배치")
    from overlay_menu import RecordPanel
    host = QWidget()
    host.setGeometry(SCREEN)
    p = RecordPanel(host)
    p.relayout(SCREEN)
    p.show()
    p.layout().activate()
    _app.processEvents()

    a, b = p._btn_full.geometry(), p._btn_cam.geometry()
    check(abs(a.center().y() - b.center().y()) <= 2,
          f"두 버튼이 같은 줄: y={a.center().y()} / {b.center().y()}")
    check(a.right() <= b.left(), f"가로로 나란히: {a.right()} ≤ {b.left()}")
    p.hide()


def test_record_folder_row():
    """저장 경로를 보여 주고, 누르면 폴더 열기 신호가 나온다."""
    print("\n[23] 녹화 저장 폴더")
    from overlay_menu import RecordPanel
    host = QWidget()
    p = RecordPanel(host)
    p.set_save_dir("/home/pi/sop-project/Rpi5/Demo/recordings")
    check("recordings" in p._folder.text(), f"경로 표시: {p._folder.text()}")

    got = []
    p.open_folder_requested.connect(lambda: got.append(1))
    p._folder.click()
    check(got == [1], f"누르면 신호: {got}")


def test_settings_matches_comp():
    """4.2 시안 대조(10/14) — 폭 856 · 위 96 · 「다크 (기본) / 화이트」 · 줄마다 설명 · 노란 스위치 · 고른 칸 노란 채움."""
    print("\n[24-b] 설정 시안")
    from PyQt6.QtCore import QRect as _R
    host = QWidget(); host.resize(1920, 1280); s = SettingsPanel(host)
    s.set_tools(["driver", "wrench"], "wrench", {"driver": "드라이버", "wrench": "렌치"}, step_order=2)
    s.apply_theme(); s.layout().activate(); s.relayout(_R(107, 0, 1707, 1280))
    check(s.width() == 856 and s.y() == 96 and abs(s.geometry().center().x() - 960) <= 1, f"{s.geometry()}")
    check(s._theme_buttons["dark"].text() == "다크 (기본)" and s._theme_buttons["light"].text() == "화이트", "테마 이름")
    check(s._switch_desc["scores"].text().startswith("이름표 옆에 신뢰도"), s._switch_desc["scores"].text())
    host.show(); _app.processEvents()
    on = s.switch("bg").grab().toImage(); off = s.switch("scores").grab().toImage()
    c_on, c_off = on.pixelColor(12, on.height() // 2), off.pixelColor(off.width() - 12, off.height() // 2)
    check(c_on.red() > 200 and c_on.green() > 180 and c_on.blue() < 140, f"켬 = 노랑 {c_on.name()}")
    check(not (c_off.red() > 200 and c_off.blue() < 140), f"끔 ≠ 노랑 {c_off.name()}")
    sel = s._tool_buttons["wrench"].grab().toImage().pixelColor(20, 32)
    check(sel.red() > 200 and sel.blue() < 140, f"고른 공구 = 노란 채움 {sel.name()}")
    check(s._sub.text() == "바꾸면 바로 적용됩니다", s._sub.text())


def test_settings_buttons_uniform():
    """🔴 나눠 고르는 버튼(공구 · 테마)의 글자 크기 · 스타일이 하나로(종전 라디오 통일 2026-08-04 규칙을 이어감)."""
    print("\n[24] 설정 버튼 통일")
    host = QWidget()
    s = SettingsPanel(host)
    s.set_tools(["spanner", "driver"], "spanner")
    s.apply_theme()
    btns = list(s._tool_buttons.values()) + list(s._theme_buttons.values())
    check(len({b.font().pointSize() for b in btns}) == 1, "글자 크기 하나로")
    check(len({b.styleSheet() for b in btns}) == 1, "스타일 하나로")
    check(all(b.isCheckable() for b in btns), "고르면 눌린 채로 남는다")


def test_settings_tool_caption_from_step():
    """G6 — 지정 공구 제목이 레시피의 공구 단계 번호를 따른다."""
    print("\n[G6] 지정 공구 제목")
    p = SettingsPanel()
    p.set_tools(["a", "b"], "a", None, step_order=2)
    check(p._tool_caption.text() == "2단계 지정 공구", f"'{p._tool_caption.text()}'")

def test_u14_notify_rows_follow_theme():
    """U14 ② — 이미 쌓인 알림도 테마를 바꾸면 새 색으로(다크 글자가 흰 바탕에 묻히던 것)."""
    print("\n[U14] 쌓인 알림 테마")
    from PyQt6.QtWidgets import QLabel
    theme.set_theme("dark")
    try:
        host = QWidget()
        n = NotifyPanel(host)
        n.push("work", "옛 알림", "부가 설명")
        theme.set_theme("light")
        n.apply_theme()
        title = [lb for lb in n._rows[-1].findChildren(QLabel) if lb.text() == "옛 알림"][0]   # _rows = 넣은 순서
        check(theme.C("done_text") in title.styleSheet(), "제목 글자가 화이트 테마 색(작업 = 초록 · 시안)")
    finally:
        theme.set_theme("dark")


def test_u14_record_panel_keeps_file_on_theme():
    """U14 ⑤ — 녹화 중 테마를 바꿔도 파일 이름·경과가 지워지지 않는다."""
    print("\n[U14] 녹화 패널 테마")
    from overlay_menu import RecordPanel
    try:
        host = QWidget()
        p = RecordPanel(host)
        p.set_state(True, "/tmp/시연_01.mp4", 12)
        theme.set_theme("light")
        p.apply_theme()
        check(p._note.text() == "시연_01.mp4", f"파일 이름 줄 = {p._note.text()!r}")
        check("12초" in p._state.text(), f"경과 = {p._state.text()!r}")
    finally:
        theme.set_theme("dark")

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
