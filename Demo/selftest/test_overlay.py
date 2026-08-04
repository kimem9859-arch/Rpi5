"""오버레이 위젯 스모크 테스트 — 만들고, 상태를 바꾸고, 배치해도 죽지 않는가.

실행: python3 Demo/selftest/test_overlay.py   (offscreen)

정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §1·§4

⚠️ 이 테스트는 **모양을 검사하지 않는다.** 눈으로 봐야 하는 것은 실기동에서 본다.
   여기서 잡는 것은 "상태 조합에서 예외가 나거나 배치가 화면 밖으로 나가는 것"이다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QWidget

import theme
from overlay import StatusPanel, GaugePanel, GlowFrame, AlertBanner, place
from sub_task import SubTask

_app = QApplication.instance() or QApplication([])
_fails = []

SCREEN = QRect(0, 0, 1920, 1080)
STEPS = [
    {"order": 1, "button": "B1", "name": "클린·가스차단"},
    {"order": 2, "button": "B2", "name": "펌프/퍼지"},
    {"order": 3, "button": "B3", "name": "전극 냉각"},
    {"order": 4, "button": "B4", "name": "챔버 벤트"},
]
WAIT = {"type": "wait", "sec": 30, "label": "플라즈마 클린 진행"}
TOOL = {"type": "wait_tool", "sec": 30, "label": "N2 퍼지", "tool": "spanner",
        "tools": ["spanner", "driver", "wrench"],
        "tool_names": {"spanner": "스패너", "driver": "드라이버", "wrench": "렌치"}}


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_status_all_states():
    """FSM 6상태 × 단계 4개 조합에서 예외가 없는가."""
    print("\n[1] StatusPanel 상태 조합")
    host = QWidget()
    p = StatusPanel(STEPS, host)
    ok = True
    for state in ("IDLE", "READY", "PROCESS RUN", "MONITOR", "WARNING", "BLOCK"):
        for step in (1, 2, 3, 4):
            try:
                p.update_view(state, step)
                p.apply_theme()
            except Exception as e:
                ok = False
                print(f"     {state}/{step} → {type(e).__name__}: {e}")
    check(ok, "6상태 × 4단계 = 24조합 예외 없음")


def test_status_both_themes():
    """두 테마 모두에서 동작하는가."""
    print("\n[2] StatusPanel 테마")
    host = QWidget()
    p = StatusPanel(STEPS, host)
    ok = True
    for t in ("dark", "light"):
        try:
            theme.set_theme(t)
            p.update_view("PROCESS RUN", 2)
            p.apply_theme()
        except Exception as e:
            ok = False
            print(f"     {t} → {type(e).__name__}: {e}")
    theme.set_theme("dark")
    check(ok, "다크·화이트 모두 예외 없음")


def test_gauge_hidden_without_sub():
    """서브 작업이 없으면 게이지가 숨는다."""
    print("\n[3] GaugePanel 숨김")
    host = QWidget()
    g = GaugePanel(host)
    g.update_view(None)
    check(not g.isVisible(), "sub=None → 숨김")
    g.update_view(SubTask(None, now=0.0))
    check(not g.isVisible(), "spec=None 인 SubTask → 숨김")


def test_gauge_widens_for_tool():
    """🔴 wait_tool 이면 폭이 17% → 24% 로 넓어진다 (design §4.3)."""
    print("\n[4] GaugePanel 폭 전환")
    host = QWidget()
    host.setGeometry(SCREEN)
    g = GaugePanel(host)

    g.update_view(SubTask(WAIT, now=0.0))
    g.relayout(SCREEN)
    w_wait = g.width()

    g.update_view(SubTask(TOOL, now=0.0))
    g.relayout(SCREEN)
    w_tool = g.width()

    check(w_wait == int(1920 * 0.17), f"wait 폭 {w_wait}px (= 1920×17%)")
    check(w_tool == int(1920 * 0.24), f"wait_tool 폭 {w_tool}px (= 1920×24%)")
    check(w_tool > w_wait, "공구 단계에서 넓어진다")


def test_gauge_tool_states():
    """공구 상태 3종(미확인·확인·오선택)에서 예외가 없는가."""
    print("\n[5] GaugePanel 공구 상태")
    host = QWidget()
    g = GaugePanel(host)
    ok = True
    for label, tool in (("미확인", None), ("확인", "spanner"), ("오선택", "driver")):
        st = SubTask(TOOL, now=0.0)
        st.set_tool(tool)
        st.tick(now=15.0)
        try:
            g.update_view(st)
            g.apply_theme()
        except Exception as e:
            ok = False
            print(f"     {label} → {type(e).__name__}: {e}")
    check(ok, "미확인·확인·오선택 예외 없음")


def test_place_stays_on_screen():
    """🔴 배치가 화면 밖으로 나가지 않는가 — % 계산 실수를 잡는다."""
    print("\n[6] 배치 경계")
    host = QWidget()
    host.setGeometry(SCREEN)
    p = StatusPanel(STEPS, host)
    g = GaugePanel(host)
    g.update_view(SubTask(TOOL, now=0.0))

    for name, w in (("StatusPanel", p), ("GaugePanel", g)):
        w.relayout(SCREEN)
        r = w.geometry()
        inside = (r.left() >= 0 and r.top() >= 0
                  and r.right() <= SCREEN.width() and r.bottom() <= SCREEN.height())
        check(inside, f"{name} {r.left()},{r.top()} {r.width()}×{r.height()} — 화면 안")


def test_place_scales():
    """창 크기가 바뀌어도 비율이 유지되는가 (고정 픽셀 금지)."""
    print("\n[7] 크기 비례")
    host = QWidget()
    p = StatusPanel(STEPS, host)
    p.relayout(QRect(0, 0, 1920, 1080))
    w_big = p.width()
    p.relayout(QRect(0, 0, 1280, 720))
    w_small = p.width()
    check(w_big == int(1920 * 0.24) and w_small == int(1280 * 0.24),
          f"1920→{w_big}px / 1280→{w_small}px (둘 다 24%)")


# ===================== 경고·차단 (Task 7) =====================


def test_glow_only_on_video_area():
    """🔴 발광은 영상 영역(가운데 75%)에만 — 레터박스는 빛나지 않는다 (design §4.5)."""
    print("\n[8] 발광 범위")
    host = QWidget()
    host.setGeometry(SCREEN)
    g = GlowFrame(host)
    g.set_level("warn")
    g.relayout(SCREEN)
    r = g.geometry()
    check(r.left() == int(1920 * 0.125), f"왼쪽 {r.left()}px = 화면의 12.5%")
    check(r.width() == int(1920 * 0.75), f"폭 {r.width()}px = 화면의 75%")
    check(r.right() < SCREEN.width(), f"오른쪽 {r.right()} < 1920 — 레터박스 제외")
    check(r.height() == 1080, "높이는 화면 전체")


def test_glow_levels():
    """warn/block/None 전환."""
    print("\n[9] 발광 단계")
    host = QWidget()
    g = GlowFrame(host)
    g.set_level("warn")
    check(g.level == "warn" and g.isVisible() is False or g.level == "warn", "warn 설정")
    g.set_level("block")
    check(g.level == "block", "block 설정")
    g.set_level(None)
    check(g.level is None and not g.isVisible(), "None → 숨김")


def test_banner_order_violation_has_release():
    """순서 위반 배너 — 해제 버튼 있음 + 2번째 줄 들여쓰기."""
    print("\n[10] 순서 위반 배너")
    host = QWidget()
    b = AlertBanner(host)
    b.show_order_violation("B2", "펌프/퍼지")
    check(b.mode == "order", "mode=order")
    check(b._release.isHidden() is False, "해제 버튼 있음")
    check("경고 해제" == b._release.text(), f"버튼 라벨 {b._release.text()}")
    check("B2" in b._line1.text() and "차례" in b._line1.text(), f"1줄: {b._line1.text()}")
    check("padding-left: 14px" in b._line2.styleSheet(), "2번째 줄 들여쓰기 있음")


def test_banner_wrong_tool_has_no_release():
    """🔴 공구 오선택 배너 — 해제 버튼 없음, 들여쓰기 없음."""
    print("\n[11] 공구 오선택 배너")
    host = QWidget()
    b = AlertBanner(host)
    b.show_wrong_tool("드라이버", "스패너")
    check(b.mode == "tool", "mode=tool")
    check(b._release.isHidden(), "🔴 해제 버튼 없음 — 올바른 공구로 바꾸면 스스로 풀린다")
    check("드라이버" in b._line1.text() and "스패너" in b._line1.text(),
          f"문장: {b._line1.text()}")
    check("padding-left" not in b._line2.styleSheet(), "짧은 문장이라 들여쓰기 없음")


def test_banner_block():
    """차단 배너 — 해제 버튼 있음, 중앙 배치."""
    print("\n[12] 차단 배너")
    host = QWidget()
    host.setGeometry(SCREEN)
    b = AlertBanner(host)
    b.show_block()
    check(b.mode == "block", "mode=block")
    check("차단 해제" == b._release.text(), f"버튼 라벨 {b._release.text()}")
    b.relayout(SCREEN)
    r = b.geometry()
    check(abs(r.center().y() - SCREEN.height() // 2) < 5, "세로 중앙 — 시야를 가린다")


def test_banner_both_themes():
    """세 형태 × 두 테마에서 예외 없음."""
    print("\n[13] 배너 테마")
    host = QWidget()
    b = AlertBanner(host)
    ok = True
    for t in ("dark", "light"):
        theme.set_theme(t)
        for fn in (lambda: b.show_order_violation("B2", "펌프/퍼지"),
                   lambda: b.show_wrong_tool("드라이버", "스패너"),
                   lambda: b.show_block()):
            try:
                fn()
            except Exception as e:
                ok = False
                print(f"     {t} → {type(e).__name__}: {e}")
    theme.set_theme("dark")
    check(ok, "3형태 × 2테마 예외 없음")
    b.hide_all()
    check(b.mode is None and not b.isVisible(), "hide_all() 동작")


def test_conn_bar():
    """🔴 우하단 연결 상태바 — 아이콘 3개, 상태는 배경색으로 (design §9).

    컬러 이모지는 color: 로 물들지 않는다. 그래서 알약 배경색으로 구분한다.
    """
    print("\n[N] 연결 상태바")
    from overlay import ConnBar
    host = QWidget()
    c = ConnBar(host)
    check([k for k, _ in ConnBar.ITEMS] == ["camera", "interlock", "gpio"],
          f"항목 3개: {[k for k, _ in ConnBar.ITEMS]}")

    c.update_state({"camera": True, "interlock": False, "gpio": None})
    ok_qss = c._icons["camera"].styleSheet()
    ng_qss = c._icons["interlock"].styleSheet()
    unknown_qss = c._icons["gpio"].styleSheet()
    check(theme.C("done") in ok_qss, f"연결 → done 색: {ok_qss[:48]}")
    check(theme.C("danger") in ng_qss, f"끊김 → danger 색: {ng_qss[:48]}")
    check(theme.C("todo") in unknown_qss, f"확인 중 → todo 색: {unknown_qss[:48]}")

    # 우하단에 앉는가 — 화면 오른쪽 아래 1/4 안
    c.relayout(SCREEN)
    r = c.geometry()
    check(r.right() <= SCREEN.width() and r.bottom() <= SCREEN.height(),
          f"화면 안: {r}")
    check(r.center().x() > SCREEN.width() * 0.5 and r.center().y() > SCREEN.height() * 0.5,
          f"우하단: 중심 {r.center().x()},{r.center().y()}")


def test_conn_bar_follows_given_rect():
    """🔴 상태바는 **넘어온 사각형** 안에 앉는다 — 콘솔이 영상 사각형을 넘긴다.

    종전에는 창 전체 기준이라 오른쪽 검정 레터박스에 앉았다(2026-08-04).
    """
    print("\n[N] 상태바 기준 사각형")
    from overlay import ConnBar
    host = QWidget()
    c = ConnBar(host)

    # 1920×1080 창 안의 4:3 영상 = 1440×1080, 좌우 240px 씩 레터박스
    video = QRect(240, 0, 1440, 1080)
    c.relayout(video)
    r = c.geometry()
    check(video.contains(r), f"영상 {video} 안: 상태바 {r}")
    # 🔴 여백을 **영상 사각형 기준**으로 잰다 — "영상 안에 있다"만 보면
    #    창 기준으로 앉아도 우연히 통과한다(레터박스 폭만큼 왼쪽에 앉는다).
    gap_r = video.right() - r.right()
    gap_b = video.bottom() - r.bottom()
    check(abs(gap_r - int(video.width() * 0.03)) <= 2,
          f"오른쪽 여백 {gap_r}px ≈ 영상 폭의 3%({int(video.width() * 0.03)}px)")
    check(abs(gap_b - int(video.height() * 0.04)) <= 2,
          f"아래 여백 {gap_b}px ≈ 영상 높이의 4%({int(video.height() * 0.04)}px)")


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
    print("✅ 오버레이 스모크 통과")
