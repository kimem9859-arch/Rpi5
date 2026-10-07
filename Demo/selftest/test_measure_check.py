"""관문 검사(측정 도구 정합 §4.3 검증 관문 1단계 ①②③) — 손으로 만든 작은 기록으로.

실행: python3 Demo/selftest/test_measure_check.py
"""
import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import measure_check as MC

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


EV = [(1000.0, "press", {"button": "B1"}), (1001.0, "state", {"old": "READY", "new": "PROCESS_RUN"}),
      (2000.0, "press", {"button": "B3"}), (2001.0, "state", {"old": "PROCESS_RUN", "new": "BLOCK"}),
      (3000.0, "press", {"button": "B2"})]
LOG = ["[12:00:01.000] [버튼] B1 눌림", "[12:00:01.001] [FSM] READY → PROCESS RUN",
       "[12:00:01.002] [FSM] 단계 진행 → 2단계: 덮개 열기 (B2)",          # 상태 전이가 아닌 [FSM] 줄 — 걸리면 안 된다
       "[12:00:02.000] [버튼] B3 눌림", "[12:00:02.001] [FSM] PROCESS RUN → BLOCK",
       "[12:00:02.002] [FSM] 🚫 BLOCK 해제 거부 — EMO 미복귀(눌림/단선)",   # 〃
       "[12:00:03.000] [버튼] B2 눌림 — 차단 중이라 무시"]


def test_events_match():
    print("\n[관문②] 사건 ↔ 시연 로그 일치(공백 든 상태 이름 · 전이 아닌 [FSM] 줄 · 차단 중 무시 누름)")
    check(MC.check_events_vs_log(EV, LOG) == [], f"{MC.check_events_vs_log(EV, LOG)}")


def test_events_mismatch():
    print("\n[관문②] 누름 하나가 빠지면 잡는다 · 전이 순서가 바뀌면 잡는다")
    bad = MC.check_events_vs_log(EV[:2] + EV[3:], LOG)
    check(bad and "누름" in bad[0], f"{bad}")
    swapped = [EV[0], EV[3], EV[2], EV[1], EV[4]]
    bad = MC.check_events_vs_log(swapped, LOG)
    check(bad and "상태 전이" in bad[0], f"{bad}")


def test_voice_match():
    print("\n[관문③] 음성 사건 ↔ 데몬 로그 — 받음(alert)이 아니라 재생 마침(alert_played)을 센다")
    vev = [(0.5, "alert", {"key": "alert_warn_B2"}),                      # 뒤 알림이 거둬 재생 안 된 알림
           (1.0, "alert", {"key": "alert_emo"}), (1.5, "alert_played", {"key": "alert_emo", "ok": True}),
           (2.0, "alert_clear", {})]
    dlog = ["[12:00:01.000] 🔔 알림 → alert_emo · 재생됨", "[12:00:02.000] 알림 상황이 풀렸다 — 재생 멈춤을 보냈다"]
    check(MC.check_voice_vs_log(vev, dlog) == [], f"{MC.check_voice_vs_log(vev, dlog)}")
    check(MC.check_voice_vs_log(vev[:2] + vev[3:], dlog) != [], "재생 마침이 빠지면 잡는다")


def test_fps_gate():
    print("\n[관문①] FPS 중앙값 하락률")
    on = ["[12:00:10.000] [FPS] 13.6 (애니메이션 on)", "[12:00:20.000] [FPS] 13.8 (애니메이션 on)"]
    off = ["[12:00:10.000] [FPS] 14.0 (애니메이션 on)", "[12:00:20.000] [FPS] 14.0 (애니메이션 on)"]
    check(MC.fps_median(on) == 13.7 and MC.fps_median(off) == 14.0, f"{MC.fps_median(on)} {MC.fps_median(off)}")
    check(MC.fps_drop_pct(MC.fps_median(on), MC.fps_median(off)) < 3.0, "하락 3% 이내")


if __name__ == "__main__":
    test_events_match()
    test_events_mismatch()
    test_voice_match()
    test_fps_gate()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 관문 검사 도구 검증 통과")
