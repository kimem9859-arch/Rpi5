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
            win._update_sub_view()                  # 조건 충족 → 자동 진행
        check(win.fsm.expected_step == before + 1 or win.fsm.state == State.IDLE,
              f"{btn} → 기대단계 {win.fsm.expected_step}")
    win.close()


def test_auto_advance_without_button():
    """🔴 대기가 차면 **버튼 없이** 다음 단계로 간다 (설계 §2.1)."""
    print("\n[3-c] 자동 진행")
    win = make_console()
    win._on_cta()                                   # 작업 시작
    before = win.fsm.expected_step
    key(win, "1")                                   # B1 물리 버튼
    check(win.fsm.expected_step == before,
          f"누른 직후엔 기대단계 {before} 유지 — 서브 작업 중")
    win._sub.tick(now=time.time() + 999)            # 대기 시간을 채운다
    win._update_sub_view()                          # 타이머가 부르는 것과 같다
    check(win._sub is None, "조건 충족 → 서브 작업이 스스로 끝난다")
    check(win.fsm.expected_step == before + 1,
          f"버튼 없이 다음 단계 → {win.fsm.expected_step}")
    check(win.btn_cta.isHidden(), "「다음 단계 진행」 버튼은 뜨지 않는다")
    win.close()


def test_tool_step_waits_until_grasped():
    """🔴 B2 는 시간만 차서는 넘어가지 않는다 — 쥘 때까지 대기 (설계 §2.4)."""
    print("\n[3-d] 공구 대기")
    win = make_console()
    win._on_cta()
    key(win, "1")
    win._sub.tick(now=time.time() + 999)
    win._update_sub_view()                          # B1 자동 통과

    key(win, "2")                                   # B2 — 공구 요구
    before = win.fsm.expected_step
    win._sub.tick(now=time.time() + 999)
    win._update_sub_view()
    check(win._sub is not None and win._sub.is_active,
          "시간이 차도 공구가 없으면 안 넘어간다")
    check(win.fsm.expected_step == before, f"기대단계 {before} 유지")

    win._sub.set_tool(win._sub.want_tool)           # 렌치를 쥔다
    win._update_sub_view()
    check(win.fsm.expected_step == before + 1, "쥐는 순간 자동 진행")
    win.close()


def test_tool_signal_drives_gate():
    """🔴 공구 판정(A-2)이 실제 GUI 를 통과해 게이트를 여는가.

    🔑 이것이 `@pyqtSlot(list, object)` 시그니처 불일치를 잡는 유일한 관문이다 —
       불일치는 connect 시점이 아니라 **emit 시점**에 TypeError 로 터지므로
       import 검사·기동 확인으로는 못 잡는다(실제로 GUI 가 즉사한 전례가 있다).

    설계 = ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §4
    """
    print("\n[3-b] 공구 판정 경로")
    win = make_console()
    win._on_cta()
    key(win, "1")                                    # B1 — 공구 없는 서브
    check(win._tool_state is None, "wait 서브에는 공구 판정이 붙지 않는다")
    win._sub.tick(now=time.time() + 999)
    win._update_sub_view()

    key(win, "2")                                    # B2 — wait_tool 서브
    check(win._sub is not None and win._sub.needs_tool, "B2 서브는 공구를 요구한다")
    check(win._tool_state is not None, "공구 판정 상태기계가 생긴다")
    want = win._sub.want_tool
    check(win._tool_state.want_tool == want, f"요구 공구 일치({want})")

    box_want = (want, 0.80, 100, 100, 200, 200)
    box_other = ("pliers" if want != "pliers" else "driver", 0.90, 300, 100, 400, 200)

    # ① 다른 공구를 쥐면 경고 — 🔑 emit 을 통과시켜 시그니처까지 검증한다
    win.camera_thread.tool_signal.emit([box_want, box_other], (350, 150))
    check(win._sub.wrong_tool == box_other[0],
          f"다른 공구를 쥐면 wrong_tool={box_other[0]}")

    # ② 정답으로 바꿔 쥐면 그 자리에서 통과 (2026-08-16 — 「넣음」 마디 폐기)
    win.camera_thread.tool_signal.emit([box_want, box_other], (150, 150))
    check(win._sub.wrong_tool is None, "정답으로 바꿔 쥐면 경고가 풀린다")
    check(win._tool_state.phase == "grasped", "쥠 확정")
    check(win._sub.tool_ok, "쥐는 즉시 tool_ok")

    # ③ 🔴 공구는 됐어도 시간이 안 찼으면 게이트는 닫혀 있다 (시간 AND 공구)
    check(not win._sub.can_advance, "🔴 공구만 됐다고 넘어가지 않는다")

    # ④ 손을 떼도 통과는 유지된다 — 안 그러면 자동 진행 조건을 못 채운다
    win.camera_thread.tool_signal.emit([], None)
    check(win._sub.tool_ok, "손을 떼도 유지")
    # 🔑 "게이트가 열린 채 유지"를 여기서 따로 확인하지 않는다 — 자동 진행 후에는
    #    win._sub 가 None 이 되어 관찰할 대상 자체가 사라진다(구 설계엔 「다음 단계
    #    진행」 버튼을 누르기 전까지 열린 게이트를 볼 창이 있었지만 지금은 없다).
    #    아래 ⑤에서 시간을 채우면 곧바로 자동 진행되는 것 자체가 그 증거다.

    # ⑤ 시간까지 차면 (시간 AND 공구) 조건이 다 채워져 **버튼 없이** 자동 진행하고,
    #    서브 작업이 끝나면 스캔이 꺼진다 (🔴 안 끄면 워커가 CPU 를 계속 먹는다)
    win._sub.tick(now=time.time() + 999)
    win._update_sub_view()
    check(win._sub is None, "시간까지 차면 자동 진행")
    check(win._tool_state is None, "판정 상태가 정리된다")
    check(win.camera_thread._tool_scan is False, "스캔이 꺼진다")
    win.close()


def test_tool_hand_unseen_does_not_advance():
    """🔴 쥐기 전에는 무엇으로도 완료되지 않는다 — 부재를 증거로 쓰지 않는다(§4.4).

    🔑 구 3마디 설계의 오완료(통합문서 §10.44-(3))에 대한 **회귀 테스트**를
       GUI 배선까지 통과시켜 확인한다. 단위 검증은 test_tool_state.py.
    """
    print("\n[3-c] 쥐기 전에는 완료되지 않는다")
    win = make_console()
    win._on_cta()
    key(win, "1"); win._sub.tick(now=time.time() + 999); win._finish_sub()
    key(win, "2")
    win._sub.tick(now=time.time() + 999)                  # 시간은 이미 찼다

    for _ in range(10):
        win.camera_thread.tool_signal.emit([], None)      # 손·공구 함께 사라짐
    check(not win._sub.tool_ok, "고개를 돌려도 완료되지 않는다")

    for _ in range(10):
        win.camera_thread.tool_signal.emit([], (150, 150))   # 손만 보이고 공구 미검출
    check(not win._sub.tool_ok, "🔴 공구를 못 잡아도 완료되지 않는다(§10.44 회귀)")
    check(not win._sub.can_advance, "게이트도 닫힌 채")
    check(win._tool_state.phase == "search", "search 에 머문다")
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


def test_same_button_during_sub_is_ignored():
    """🔴 대기 중 **같은** 버튼 재입력은 무시된다 (§10.32-(6)③ 결함 회귀 방지).

    고치기 전에는 여기서 단계가 올라갔다 — 서브 대기 중에는 expected_step 이
    아직 안 올라가 correct_roi 가 여전히 그 버튼이라, FSM 이 "정답"으로 받아
    can_advance(시간 AND 공구) 검사를 통째로 건너뛰었다.
    """
    print("\n[4-1] 대기 중 같은 버튼 재입력")
    win = make_console()
    win._on_cta()
    key(win, "1")                                   # B1 → 서브 작업 시작
    check(win._sub is not None and win._sub.is_active, "B1 서브 작업 진행 중")
    before = win.fsm.expected_step

    key(win, "1")                                   # 🔴 같은 버튼 재입력
    check(win.fsm.expected_step == before,
          f"기대단계가 안 올라간다({before}) — can_advance 우회 차단")
    check(win._sub is not None and win._sub.is_active,
          "서브 작업이 계속 진행 중이다")
    check(win.fsm.state != State.BLOCK,
          f"위반 처리도 하지 않는다({win.fsm.state.value}) — 조급함이지 순서 위반이 아니다")
    win.close()


def test_emo_during_sub_still_works():
    """🔴 서브 대기 중에도 EMO 는 통과해야 한다.

    재입력 필터가 EMO 를 삼키면 비상정지가 죽는다. `_sub_button` 에는 레시피
    단계 버튼만 들어가므로 구조적으로 안전하지만, 그 전제를 여기서 못박는다.
    """
    print("\n[4-2] 대기 중 EMO")
    win = make_console()
    win._on_cta()
    key(win, "1")                                   # B1 → 서브 작업 시작
    check(win._sub is not None and win._sub.is_active, "B1 서브 작업 진행 중")

    key(win, "E")                                   # 비상정지
    check(win.fsm.state == State.BLOCK,
          f"EMO 가 서브 대기를 뚫고 BLOCK 을 만든다({win.fsm.state.value})")
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

    ⚠️ 마지막 두 케이스가 핵심이다.
       ① **시트를 열어 둔 사이에 서브 작업이 스스로 끝나도**(2026-08-19
          자동 진행) 상태가 여전히 IDLE 이 아니면 CTA 는 나오면 안 된다.
       ② **열기 직전의 CTA 값을 기억했다가 그대로 복원하면 안 된다.**
          IDLE(CTA 보임)에서 시트를 연 뒤, 시트가 열린 채로 작업을 시작해
          상태를 IDLE 밖으로 보내면 — 재계산 구현은 닫을 때 CTA 가
          **숨어 있어야** 하고, 열기 직전 값을 기억해 복원하는 구현은
          **보이게 되어** 여기서 갈린다. 🔑 ①만으로는 판별력이 없다 —
          열기 직전에도 이미 hidden(서브 작업 중)이라 기억값과 재계산값이
          우연히 같아진다. 상태가 IDLE→비IDLE 로 **바뀌는** ②라야
          "기억 vs 재계산"이 실제로 갈린다.
    """
    print("\n[10] 시트 열림 중 CTA")
    win = make_console()
    check(not win.btn_cta.isHidden(), "IDLE — 「작업 시작」 보임")

    win._open_settings()
    check(win.btn_cta.isHidden(), "설정을 열면 CTA 가 감춰진다")
    win._toggle_settings(False)
    check(not win.btn_cta.isHidden(), "닫으면 다시 「작업 시작」")

    win._on_cta()                                   # 작업 시작 → IDLE 아님
    check(win.btn_cta.isHidden(), "작업 시작 후엔 CTA 없음")
    win._toggle_menu(True)
    win._toggle_menu(False)
    check(win.btn_cta.isHidden(), "메뉴를 여닫아도 되살아나지 않는다")

    key(win, "1")                                   # B1 → 서브 작업
    win._toggle_settings(True)                      # 시트를 열어 둔 채
    if win._sub is not None and win._sub.is_active:
        win._sub.tick(now=time.time() + 999)        # 시간이 다 참
        if win._sub.needs_tool:
            win._sub.set_tool(win._sub.want_tool)
        win._update_sub_view()                      # 시트가 열려 있어도 스스로 진행한다
        check(win._sub is None, "시트가 열려 있어도 자동 진행은 막히지 않는다")
        check(win.btn_cta.isHidden(), "시트가 열려 있는 동안엔 여전히 감춤")
        win._toggle_settings(False)
        check(win.btn_cta.isHidden(),
              "🔴 닫아도 CTA 는 안 나온다 — IDLE 이 아니다(자동 진행)")
    win.close()

    # ② 판별 케이스 — 열기 직전엔 IDLE(CTA 보임)이었는데, 시트가 열린 채로
    # 상태가 IDLE 을 벗어난다. 기억 방식이면 열기 직전 값(보임)을 그대로
    # 복원해 여기서 실패하고, 재계산 방식이면 닫아도 숨은 채 유지된다.
    win2 = make_console()
    check(not win2.btn_cta.isHidden(), "새 창 — IDLE, CTA 보임")
    win2._open_settings()
    check(win2.btn_cta.isHidden(), "시트를 열면 감춰진다(이 시점 상태는 아직 IDLE)")
    win2._on_start_process()                        # 시트가 열린 채로 상태만 바꾼다 — CTA 는 안 건드린다
    check(win2.fsm.state != State.IDLE, "상태가 IDLE 을 벗어났다")
    win2._toggle_settings(False)
    check(win2.btn_cta.isHidden(),
          "🔴 닫아도 CTA 안 나옴 — 기억 방식이면 열기 직전 값(보임)을 복원해 여기서 실패")
    win2.close()


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

    # 🔴 설정 패널도 같다 — 「작업 중에는 변경할 수 없습니다」 문구가 생기면
    #    필요 높이가 커진다. 다시 재지 않으면 공구 라디오가 눌려 겹친다.
    win._close_sheets()
    win._on_cta()                           # 작업 중 → 문구가 붙는다
    win._open_settings()
    h, want = win.settings_panel.height(), win.settings_panel.sizeHint().height()
    check(h >= want, f"설정 패널(작업 중) 높이 {h} ≥ 내용이 요구하는 {want}")
    win.close()


def test_cctv_switch_needs_confirm():
    """🔴 CCTV 전환은 확인을 받고 나서 바뀐다 (2026-08-04).

    실수로 카메라가 바뀌면 감지가 끊긴다. 종료 확인창과 같은 방어다.
    ⚠️ 모달을 실제로 띄우면 테스트가 응답을 기다리며 멎는다 — 확인 함수를
       가짜로 바꿔 「응답을 받은 뒤」만 검사한다.
    """
    print("\n[13] CCTV 전환 확인")
    win = make_console()
    before = win._active_camera

    win._confirm_camera_switch = lambda target: False      # 「아니요」
    win._toggle_camera_source()
    check(win._active_camera == before, f"거절하면 그대로: {win._active_camera}")

    asked = []
    win._confirm_camera_switch = lambda target: asked.append(target) or True   # 「예」
    win._toggle_camera_source()
    check(asked and asked[0] != before, f"전환할 카메라를 묻는다: {asked}")
    check(win._active_camera != before, f"승낙하면 바뀐다: {win._active_camera}")
    win.close()


def test_reset_returns_to_prestart():
    """🔴 작업 초기화 — 진행 중이던 작업을 「작업 시작」 직전으로 되돌린다."""
    print("\n[작업 초기화]")
    win = make_console()
    win._on_cta()                                   # 작업 시작
    key(win, "1")                                   # B1 눌림 → 서브 작업 시작
    check(win.fsm.state != State.IDLE, "초기화 전에는 작업 중")

    win._reset_work()                               # 확인창을 건너뛴 실제 되돌리기
    check(win.fsm.state == State.IDLE, f"IDLE 복귀 (실제 {win.fsm.state.value})")
    check(win.fsm.expected_step == 1, f"1단계로 (실제 {win.fsm.expected_step})")
    check(win._sub is None, "서브 작업이 지워졌다")
    check(win._sub_button is None, "서브 작업 버튼 기억도 지워졌다")
    check(not win._sub_timer.isActive(), "서브 타이머가 멈췄다")
    check(win.alert.mode is None, "경고·차단 배너가 사라졌다")
    check(win.gauge_panel.isHidden(), "게이지가 숨겨졌다")
    check(win.btn_cta.text().endswith("작업 시작"), f"CTA 문구 {win.btn_cta.text()!r}")
    check(not win.btn_cta.isHidden(), "「작업 시작」 버튼이 다시 보인다")
    win.close()


def test_reset_after_block_clears_alert():
    """차단 상태에서 초기화 — 배너·발광까지 정리된다."""
    print("\n[차단 중 초기화]")
    win = make_console()
    win._on_cta()
    key(win, "2")                                   # 오답 버튼 → 즉시 BLOCK
    check(win.fsm.state == State.BLOCK, f"차단 상태 (실제 {win.fsm.state.value})")

    win._reset_work()
    check(win.fsm.state == State.IDLE, "IDLE 복귀")
    check(win.alert.mode is None, "차단 배너가 사라졌다")
    check(win.glow.level is None, f"발광이 꺼졌다 (실제 {win.glow.level})")
    win.close()


def test_reset_when_idle_is_safe():
    """이미 「작업 시작」 전이면 눌러도 아무 문제가 없다."""
    print("\n[IDLE 에서 초기화]")
    win = make_console()
    win._reset_work()
    check(win.fsm.state == State.IDLE, "IDLE 유지")
    check(not win.btn_cta.isHidden(), "「작업 시작」 버튼 유지")
    win.close()


def test_detect_box_toggle():
    """🔴 설정에서 탐지 박스를 끄면 두 카메라 스레드에 모두 전달되는가.

    🔑 표시만 끄는 것이다 — 끈 상태에서도 순서 위반 판정은 그대로 돈다(설계 §4.2).
    """
    print("\n[N] 탐지 박스 토글")
    win = make_console()
    check(win.camera_thread.draw_boxes() is True, "기본은 켜짐")

    win.settings_panel._box_buttons[False].setChecked(True)
    check(win.camera_thread.draw_boxes() is False, "끄면 ESP32 스레드에 전달")
    check(win.usb_camera_thread.draw_boxes() is False, "끄면 USB 스레드에도 전달")

    # 끈 상태에서도 판정은 살아 있다
    win._on_cta()
    before = win.fsm.expected_step
    key(win, "1")
    check(win._sub is not None and win._sub.is_active,
          "박스를 꺼도 서브 작업이 시작된다 — 판정은 표시와 무관하다")
    check(win.fsm.expected_step == before, "기대단계 유지")

    win.settings_panel._box_buttons[True].setChecked(True)
    check(win.camera_thread.draw_boxes() is True, "다시 켜진다")
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
