"""글라스 UI 흐름 검증 — 실제 SafetyConsole 을 만들어 시나리오를 끝까지 돌린다.

실행: python3 Demo/selftest/test_console_flow.py   (offscreen)

정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §5

왜 필요한가:
    "run_demo.sh 가 30초 생존"만으로는 **화면이 실제로 도는지 모른다.**
    여기서는 키보드 입력을 흉내내 작업 시작 → 서브 작업 → 다음 단계 진행 →
    순서 위반까지 실제로 밟는다.

⚠️ HW(ESP32·Arduino)가 없어도 전부 fallback 되므로 이 테스트는 HW 없이 돈다.
"""

import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SOP_USB_CAMERA"] = "0"          # 웹캠 점유 방지

import config
config.RECORDING_ENABLED = False            # 테스트가 녹화 파일을 남기지 않게

# ⚠️ 카메라 스레드 정리를 빠르게 — win.close() 가 CameraThread.stop() → wait() 로
#    스레드를 기다리는데, 죽은 IP 로 10초 타임아웃 + 3초 재연결 대기를 반복하면
#    테스트가 창을 닫을 때마다 십수 초씩 멈춘다.
#    127.0.0.1 은 리스너가 없어 **즉시 거절**되고, 대기도 0.1초로 줄인다.
#    🔴 config 를 먼저 고친 뒤에 safety_console 을 import 해야 한다
#       (camera_thread 가 import 시점에 from config import ... 로 값을 읽는다).
config.CAMERA_TCP_HOST = "127.0.0.1"
config.TCP_RECV_TIMEOUT_SEC = 0.3
config.TCP_RECONNECT_DELAY_SEC = 0.1

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

import theme
from fsm import State

_app = QApplication.instance() or QApplication([])
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def key(win, text):
    """키보드 입력 흉내."""
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, text)
    win.keyPressEvent(ev)


def make_console():
    from safety_console import SafetyConsole
    win = SafetyConsole()
    win.resize(1920, 1080)
    win._relayout()
    return win


def test_boot():
    """창이 만들어지고 오버레이가 다 붙는가."""
    print("\n[1] 기동")
    win = make_console()
    for name in ("status_panel", "gauge_panel", "glow", "alert",
                 "menu_panel", "notify_panel", "settings_panel",
                 "btn_menu", "btn_notify", "btn_cta", "camera_label"):
        check(hasattr(win, name), f"{name} 존재")
    check(win.fsm.state == State.IDLE, f"초기 상태 {win.fsm.state.value}")
    win.close()


def test_letterbox_geometry():
    """🔴 영상이 가운데 4:3, 좌우가 검정 레터박스인가 (design §1)."""
    print("\n[2] 레터박스")
    win = make_console()
    r = win.camera_label.geometry()
    check(abs(r.width() / r.height() - 4 / 3) < 0.02,
          f"영상 {r.width()}×{r.height()} — 비율 {r.width()/r.height():.3f} ≈ 4:3")
    side = (1920 - r.width()) // 2
    check(r.left() == side, f"좌우 여백 각 {side}px — 가운데 정렬")
    win.close()


def test_scenario_runs_to_end():
    """🔴 작업 시작 → 서브 작업 → 다음 단계 진행 을 4단계 끝까지."""
    print("\n[3] 시나리오 완주")
    win = make_console()
    win._on_cta()                                   # 작업 시작
    check(win.fsm.state != State.IDLE, f"작업 시작 후 {win.fsm.state.value}")

    for step, btn in enumerate(["B1", "B2", "B3", "B4"], start=1):
        before = win.fsm.expected_step
        key(win, str(step))                         # 물리 버튼 흉내
        if win._sub is not None and win._sub.is_active:
            # 🔑 서브 작업이 있으면 FSM 은 아직 안 올라가 있어야 한다
            check(win.fsm.expected_step == before,
                  f"{btn} 누름 → 서브 작업 중, 기대단계 {before} 유지")
            win._sub.tick(now=time.time() + 999)    # 시간 채움
            if win._sub.needs_tool:
                win._sub.set_tool(win._sub.want_tool)
            win._update_sub_view()
            check(win._sub.can_advance, f"{btn} 서브 작업 조건 충족")
            win._finish_sub()                       # 「다음 단계 진행」
        check(win.fsm.expected_step == before + 1 or win.fsm.state == State.IDLE,
              f"{btn} → 기대단계 {win.fsm.expected_step}")
    win.close()


def test_wrong_button_during_sub_is_violation():
    """🔴 대기 중 다른 버튼 = 순서 위반 (design §5의 핵심 명제)."""
    print("\n[4] 대기 중 오조작")
    win = make_console()
    win._on_cta()
    key(win, "1")                                   # B1 → 서브 작업 시작
    check(win._sub is not None and win._sub.is_active, "B1 서브 작업 진행 중")
    before = win.fsm.expected_step

    key(win, "3")                                   # 대기 중에 B3 누름
    check(win.fsm.expected_step == before,
          f"기대단계가 안 올라간다({before}) — FSM 이 오답으로 본다")
    win.close()


def test_theme_switch():
    """설정에서 테마를 바꾸면 오버레이에 반영되는가."""
    print("\n[5] 테마 전환")
    win = make_console()
    win._on_theme_changed("light")
    check(theme.current() == "light", "화이트로 전환")
    # ⚠️ 패널 배경은 theme.PANEL_BACKGROUND 로 껐다 켠다(기본 False — AR 글라스 느낌).
    #    배경을 켰을 때만 테마 색이 스타일시트에 나타난다.
    win._on_panel_bg_changed(True)
    ss = win.status_panel.styleSheet()
    check("255, 255, 255" in ss or "255,255,255" in ss, f"배경 켜면 흰 계열: {ss[:40]}")
    win._on_panel_bg_changed(False)
    check("transparent" in win.status_panel.styleSheet(), "배경 끄면 투명")
    win._on_theme_changed("dark")
    check(theme.current() == "dark", "다크 복귀")
    win.close()


def test_panels_toggle():
    """메뉴·알림·설정이 열리고 닫히는가. 서로 배타적인가.

    ⚠️ 창을 show() 하지 않으면 자식 위젯의 isVisible() 은 **항상 False** 다(Qt 규칙).
       그래서 isHidden() 으로 본다.
    """
    print("\n[6] 패널 토글")
    win = make_console()
    win._toggle_menu(True)
    check(not win.menu_panel.isHidden(), "메뉴 열림")
    win._toggle_notify(True)
    check(not win.notify_panel.isHidden() and win.menu_panel.isHidden(),
          "알림을 열면 메뉴가 닫힌다")
    win._open_settings()
    check(not win.settings_panel.isHidden(), "설정 열림")
    check(win.notify_panel.isHidden(), "설정을 열면 알림이 닫힌다")
    win.close()


def test_cta_hidden_while_sheet_open():
    """🔴 시트가 열려 있는 동안 CTA 를 감춘다 — 시트 배경이 10% 투과라 비친다.

    ⚠️ 마지막 케이스가 핵심이다: **시트를 열어 둔 사이에 게이지가 다 차도**
       닫으면 「다음 단계 진행」이 나와야 한다. 열기 직전 상태를 기억하는
       방식으로 만들면 여기서 버튼이 영영 안 나온다.
    """
    print("\n[10] 시트 열림 중 CTA")
    win = make_console()
    check(not win.btn_cta.isHidden(), "IDLE — 「작업 시작」 보임")

    win._open_settings()
    check(win.btn_cta.isHidden(), "설정을 열면 CTA 가 감춰진다")
    win._toggle_settings(False)
    check(not win.btn_cta.isHidden(), "닫으면 다시 「작업 시작」")

    win._on_cta()                                   # 작업 시작 → 눌림 대기
    check(win.btn_cta.isHidden(), "버튼 눌림 대기 중엔 CTA 없음")
    win._toggle_menu(True)
    win._toggle_menu(False)
    check(win.btn_cta.isHidden(), "메뉴를 여닫아도 되살아나지 않는다")

    key(win, "1")                                   # B1 → 서브 작업
    win._toggle_settings(True)                      # 시트를 열어 둔 채
    if win._sub is not None and win._sub.is_active:
        win._sub.tick(now=time.time() + 999)        # 게이지가 다 참
        if win._sub.needs_tool:
            win._sub.set_tool(win._sub.want_tool)
        win._update_sub_view()
        check(win.btn_cta.isHidden(), "시트가 열려 있는 동안엔 여전히 감춤")
        win._toggle_settings(False)
        check(not win.btn_cta.isHidden(),
              "🔴 닫으면 「다음 단계 진행」이 나온다 — 기억 방식이면 여기서 실패")
    win.close()


def test_esc_closes_panels_first():
    """🔴 ESC 는 열린 패널부터 닫는다 — 한 번에 창을 닫지 않는다."""
    print("\n[7] ESC 탈출구")
    win = make_console()
    win._toggle_menu(True)
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    win.keyPressEvent(ev)
    check(win.menu_panel.isHidden(), "1번째 ESC — 메뉴만 닫힘")
    win.close()


def test_settings_tool_lock():
    """🔴 작업 중에는 공구를 못 바꾼다."""
    print("\n[8] 공구 잠금")
    win = make_console()
    win._open_settings()
    editable_idle = all(b.isEnabled() for b in win.settings_panel._tool_buttons.values()) \
        if win.settings_panel._tool_buttons else True
    check(editable_idle, "IDLE 이면 변경 가능")

    win._toggle_settings(False)
    win._on_cta()                                   # 작업 시작 → IDLE 아님
    win._open_settings()
    if win.settings_panel._tool_buttons:
        locked = all(not b.isEnabled() for b in win.settings_panel._tool_buttons.values())
        check(locked, "작업 중이면 잠김")
    else:
        check(True, "(공구 선택지 미설정 — 잠금 검사 생략)")
    win.close()


def test_notify_grows():
    """알림이 쌓이고 뱃지 숫자가 오르는가."""
    print("\n[9] 알림")
    win = make_console()
    n0 = win.notify_panel.count
    win._on_cta()                                   # 작업 시작 → 알림 1건
    check(win.notify_panel.count > n0, f"{n0} → {win.notify_panel.count}건")
    # 🔴 배지는 버튼 글자가 아니라 별도 위젯이다(폰 앱 방식, 2026-08-04).
    check(win.btn_notify.text() == "🔔", f"버튼 글자는 아이콘만: '{win.btn_notify.text()}'")
    check(win.btn_notify._badge.text() == str(win._unread),
          f"배지 숫자 '{win.btn_notify._badge.text()}' = 안 읽은 {win._unread}건")

    win._toggle_notify(True)          # 열면 읽음 처리
    check(win._unread == 0 and win.btn_notify._badge.isHidden(),
          "알림을 열면 배지가 사라진다")
    win.close()


def test_sheet_sized_on_first_open():
    """🔴 처음 여는 패널도 내용에 맞는 크기여야 한다 (2026-08-04).

    패널은 내용이 비었을 때 배치된 뒤 내용이 채워져도 다시 배치되지 않아,
    첫 열기에서 높이가 89px(정상 496px)로 납작하게 눌려 글자가 겹쳤다.
    """
    print("\n[12] 첫 열기 크기")
    win = make_console()
    win._open_check()                       # 한 번도 연 적 없는 상태에서 연다
    h, want = win.check_panel.height(), win.check_panel.sizeHint().height()
    check(h >= want, f"점검 패널 높이 {h} ≥ 내용이 요구하는 {want}")

    win._close_sheets()
    win._open_record()
    h, want = win.record_panel.height(), win.record_panel.sizeHint().height()
    check(h >= want, f"녹화 패널 높이 {h} ≥ 내용이 요구하는 {want}")
    win.close()


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 글라스 UI 흐름 통과")
