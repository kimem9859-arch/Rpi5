"""판정 수정 ① 규칙별 미리보기 — 일회성 분석 (2026-09-25 · 세션 56d1f2c1)

🔴 측정 도구가 아니다. P1~P4 를 켜고 끄려고 판정 규칙을 흉내 낸 **재구현**이라
   재사용하지 않는다(측정도구 스킬 「재구현 금지」). 「현재(재구성)」 줄이 실제
   `fsm_sim.py` 출력과 같아야 흉내가 맞다는 뜻이다.
조건 = fsm_sim 시뮬레이션 정책 4종(BLOCK·WARNING 즉시 자동 해제 · 기대단계 사전 주입 ·
       IDLE 시 자동 다음 주기) · hoi.db 22세션(2026-07 모조 콘솔 VGA).
결론 = 설계서 docs/superpowers/specs/2026-09-25-런타임-문제수정-design.md D9.
실행: cd Rpi5/Demo && python3 ../조사/판정수정-20260925/preview_variants.py
"""
import sys, types, importlib.util
DEMO = "/home/pi/sop-project/Rpi5/Demo"
sys.path[:0] = [DEMO + "/test", DEMO]
import fsm as base
import fsm_sim, hoi_metrics
from fsm import SafetyFSM, State
from roi_zones import INSIDE as ZI
con = hoi_metrics.connect()

def make_cls(P1, P4, P2, P3):
    class V(SafetyFSM):
        def __init__(s, *a, **k):
            super().__init__(*a, **k); s._dwell_last = None; s._just_done = None
        def _reset_dwell(s):
            s._dwell_roi = s._dwell_start = None; s._dwell_last = None
        def _step_complete(s):
            if P2: s._just_done = s.correct_roi
            super()._step_complete()
        def update_vision(s, roi, now, level=ZI):
            observed = roi is not None
            if P4 and observed and s.gap_fill > 0 and s._last_seen is not None and now - s._last_seen > s.gap_fill:
                s._reset_dwell()
            if roi is not None:
                s._last_roi, s._last_level, s._last_seen = roi, level, now
            if roi is None:
                if s.gap_fill > 0 and s._last_roi is not None and s._last_seen is not None and now - s._last_seen <= s.gap_fill:
                    roi, level = s._last_roi, s._last_level
                else:
                    s._last_roi = s._last_level = s._last_seen = None
                    roi, level = None, None
            if P2 and s._just_done is not None and roi != s._just_done:
                s._just_done = None
            if s.state in (State.IDLE, State.WARNING, State.BLOCK): return
            if roi is None:
                if s.state == State.MONITOR: s._goto(State.PROCESS_RUN)
                s._reset_dwell(); return
            if s.state == State.PROCESS_RUN: s._goto(State.MONITOR)
            excl = [s.correct_roi] + ([s._just_done] if P2 else []) + ([s._emo] if P3 else [])
            if roi in excl:
                s._reset_dwell(); return
            if s._dwell_roi != roi:
                if observed or not P1:
                    s._dwell_roi = roi; s._dwell_start = s._dwell_last = now
                return
            if observed or not P1: s._dwell_last = now
            if s._dwell_last - s._dwell_start >= s.dwell_threshold and level == ZI:
                s._goto(State.WARNING); s._reset_dwell()
    return V

for name, flags in [("현재(재구성)", (0,0,0,0)), ("P4만", (0,1,0,0)), ("P1만", (1,0,0,0)),
                    ("P1+P4", (1,1,0,0)), ("P2+P3만", (0,0,1,1)), ("P2+P3+P4", (0,1,1,1)),
                    ("P1+P2+P3", (1,0,1,1)), ("P1~P4", (1,1,1,1))]:
    fsm_sim.SafetyFSM = make_cls(*flags)
    rows = fsm_sim.run_all(con)
    fa = sum(r['false_alarms'] for r in rows); mins = sum(r['duration_sec'] for r in rows)/60
    tb = sum(r['blocked'] for r in rows); tv = sum(r['violations'] for r in rows)
    print(f"{name:<10} 오경보 {fa:>4}건 ({fa/mins:5.2f}/분) · 사전 차단 {tb}/{tv}")
