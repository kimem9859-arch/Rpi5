"""로그 거르기 · 색 HTML(시연 UI 개선 설계 2026-10-13 §4.5).

실행: python3 Demo/selftest/test_log_view.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import log_view

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_kind():
    print("\n[분류]")
    check(log_view.kind("[10:00:00.000] [FSM] MONITOR → WARNING") == "alert", "경고 전이")
    check(log_view.kind("[10:00:00.000] [FSM] 🚫 BLOCK 해제 거부 — EMO 미복귀") == "alert", "차단")
    check(log_view.kind("[10:00:00.000] [버튼] B2 눌림") == "step", "버튼")
    check(log_view.kind("[10:00:00.000] [서브] N2 퍼지 일시정지 — 경고 중") == "alert", "경고가 들어간 서브는 경고 쪽")
    check(log_view.kind("[10:00:00.000] [FPS] 23.4 (애니메이션 on)") == "other", "그 밖")


def test_keep_and_html():
    print("\n[거르기 · HTML]")
    a = "[10:00:00.000] [FSM] MONITOR → WARNING"
    check(log_view.keep(a, "all") and log_view.keep(a, "alert") and not log_view.keep(a, "step"), "거르기")
    h = log_view.to_html("[10:00:00.000] [설정] <b>x</b> & y")
    check("&lt;b&gt;" in h and "&amp;" in h, "HTML 이스케이프")
    check(h.count("<span") == 2, "시각 · 본문 두 칸")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 로그 거르기 통과")
