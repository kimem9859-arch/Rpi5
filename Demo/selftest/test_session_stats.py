"""작업 결과 집계 검증.

실행: python3 Demo/selftest/test_session_stats.py

정본: 상위 docs/superpowers/specs/2026-08-19-자동진행-결과창-design.md §3

⚠️ 시간을 인자로 주입하므로 **10초를 실제로 기다리지 않는다.**
🔴 오탐지(false positive)는 집계하지 않는다 — 정답 라벨 없이는 셀 수 없다(§3.4).
"""

import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from session_stats import SessionStats

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_clean_run():
    """위반 없이 4단계를 마치면 ok=True 이고 순서·시간이 남는다."""
    print("\n[1] 완주")
    s = SessionStats()
    s.start("PECVD 정비(PM) 시퀀스", 4, now=100.0)
    for i, (btn, name) in enumerate([("B1", "클린·가스차단"), ("B2", "펌프/퍼지"),
                                     ("B3", "전극 냉각"), ("B4", "챔버 벤트")]):
        t = 100.0 + i * 12
        s.button_pressed(btn, btn, True, now=t)
        s.step_done(i + 1, btn, name, now=t + 10)
    out = s.finish(now=150.0)
    check(out["ok"] is True, "위반 없음 → ok=True")
    check([x["button"] for x in out["steps"]] == ["B1", "B2", "B3", "B4"],
          f"누른 순서 {[x['button'] for x in out['steps']]}")
    check(abs(out["total_sec"] - 50.0) < 1e-6, f"총 시간 {out['total_sec']}s")
    check(abs(out["steps"][0]["sec"] - 10.0) < 1e-6,
          f"1단계 소요 {out['steps'][0]['sec']}s")


def test_violation_and_interlock():
    """순서 위반과 인터락이 시각과 함께 남는다."""
    print("\n[2] 위반·인터락")
    s = SessionStats()
    s.start("t", 4, now=0.0)
    s.violation("B2", "B4", "block", now=5.0)
    s.interlock(True, now=5.0)
    s.interlock(False, now=9.0)
    out = s.finish(now=10.0)
    check(out["ok"] is False, "위반이 있으면 ok=False")
    check(len(out["violations"]) == 1, "위반 1건")
    v = out["violations"][0]
    check(v["expected"] == "B2" and v["actual"] == "B4" and v["level"] == "block",
          f"기대 {v['expected']} → 실제 {v['actual']} ({v['level']})")
    check(len(out["interlocks"]) == 1 and out["interlocks"][0]["released_at"] == 9.0,
          "인터락 1건 · 해제 시각 기록")


def test_tool_subtask():
    """공구를 쥐기까지 걸린 시간과 오답 공구가 남는다."""
    print("\n[3] 공구")
    s = SessionStats()
    s.start("t", 4, now=0.0)
    s.sub_started("B2", {"type": "wait_tool", "sec": 10, "tool": "wrench"}, now=0.0)
    s.tool_grasped("driver", False, now=3.0)      # 다른 공구를 집었다
    s.tool_grasped("wrench", True, now=7.5)       # 요구 공구를 쥐었다
    s.sub_done("B2", now=7.5)
    out = s.finish(now=10.0)
    t = out["tools"][0]
    check(t["want"] == "wrench", f"요구 공구 {t['want']}")
    check(abs(t["grasp_sec"] - 7.5) < 1e-6, f"쥐기까지 {t['grasp_sec']}s")
    check(t["wrong"] == ["driver"], f"오답 공구 {t['wrong']}")


def test_detection_counts():
    """검출은 **프레임 수와 신뢰도 합**으로만 남는다 — 비율을 만들지 않는다."""
    print("\n[4] 검출")
    s = SessionStats()
    s.start("t", 4, now=0.0)
    s.frame([("B1", 0.90), ("손", 0.80)])
    s.frame([("B1", 0.80)])
    s.frame([])
    out = s.finish(now=1.0)
    check(out["frames"] == 3, f"전체 프레임 {out['frames']}")
    check(out["detections"]["B1"]["frames"] == 2, "B1 검출 2프레임")
    check(abs(out["detections"]["B1"]["score_sum"] - 1.70) < 1e-6, "신뢰도 합 1.70")
    check(out["detections"]["손"]["frames"] == 1, "손 검출 1프레임")
    check("rate" not in out["detections"]["B1"],
          "🔴 비율(rate)을 만들지 않는다 — 손 없는 프레임이 분모에 섞인다")


def test_no_false_positive_field():
    """🔴 오탐지 항목이 존재하지 않는다 (설계 §3.4)."""
    print("\n[5] 오탐지 없음")
    s = SessionStats()
    s.start("t", 4, now=0.0)
    out = s.finish(now=1.0)
    for bad in ("false_positive", "fp", "오탐", "misdetect"):
        check(bad not in out, f"'{bad}' 항목 없음")


if __name__ == "__main__":
    t0 = time.time()
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    elapsed = time.time() - t0
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    if elapsed > 1.0:
        print(f"❌ 느림 {elapsed:.1f}s — 실시간을 기다리고 있다(시간 주입이 안 됨)")
        sys.exit(1)
    print(f"✅ 결과 집계 검증 통과 ({elapsed:.3f}s)")
