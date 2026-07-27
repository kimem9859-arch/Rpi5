"""FSM 오프라인 시뮬레이터 — hoi.db 를 실제 SafetyFSM 에 먹여 재생한다.

왜 필요한가 (2026-07-27):
    ① **E2E 오경보를 한 번도 잰 적이 없다.** 팜 오검출이 flag→구역→체류 0.3초를
       지나 실제 경고가 되는 비율이 미지수인 채로 임계를 정해 왔다.
    ② 파라미터를 바꿔 볼 때마다 재촬영하거나 40분짜리 팜 추론을 다시 돌렸다.
       팜 추론 결과는 이미 palm_cache 에 있고 raw 가 정본이라 안 바뀐다 — DB 를
       읽어 재생하면 수 초다.

🔴 **재구현하지 않는다.** 이 파일은 실제 `SafetyFSM` 을 import 해서 프레임을 먹이는
   얇은 껍데기다. 체류·갭메우기·발화 규칙을 여기 다시 쓰면 정본이 둘이 되고 측정이
   런타임을 대표하지 못한다 — 도구가 config 를 안 따라 네 번 물렸던 전례(§10.23).

실제 운용과 다른 점 4가지 (설계 §4.3 — 인용 시 반드시 병기):
    1. BLOCK 진입 즉시 자동 해제. 촬영 당시 GUI 를 안 돌려 해제 조작 기록이 없다.
       해제하지 않으면 첫 위반 이후 모든 눌림이 평가에서 빠진다.
    2. WARNING 도 즉시 자동 해제. 같은 이유.
    3. 기대단계를 매 눌림 직전 `expected_button` 으로 설정. 상태를 눌림으로 굴리면
       한 번 어긋날 때 이후가 전부 오염된다.
    4. 공정 완료(`IDLE`)에 도달하면 `load_recipe()` 를 다시 불러 다음 주기를 시작한다
       (2026-07-27 추가 — Critical 버그 수정). `mixed` 세션(예: `far-high-r3`)은 정상
       주기(B1→B2→B3→B4)를 여러 번 돈 뒤 위반 주기로 넘어가는 촬영인데, 마지막 단계
       (B4) 정답 눌림이 `_step_complete()` 에서 `State.IDLE` 로 떨어뜨리고
       `update_vision()` 은 `IDLE` 에서 즉시 return 한다 — 다음 주기를 시작해 주지
       않으면 **이후 모든 비전 입력이 영구히 무시돼 위반 눌림에 경고가 0건이 된다.**
       `expect_b1` 세션(정답 눌림이 없는 순수 위반 촬영)은 애초에 IDLE 에 도달하지
       않아 이 버그가 드러나지 않았다 — 관문(§2)이 그 세션들만 써서 통과해 온 이유.

사용:
    python3 test/fsm_sim.py --gate          # 🔴 검증 관문 (아래 §2 새 정의)
    python3 test/fsm_sim.py                 # 현행 설정으로 전 세션
    python3 test/fsm_sim.py --dwell 0.5

🔴 관문 재정의 (2026-07-27, §10.23 폐기): 종전 관문은 §10.23 의 0.3초 57%·0.5초 14%를
   재현하는 것이었으나, 그 수치를 만든 `dwell_probe`가 config 를 안 따라 네 번 물렸고
   그 수정이 §10.23 **이후**에 이뤄져 재구성 불가능하다. 실제로 고친 시뮬레이터로 재면
   0.3초는 59%로 근접하나 0.5초는 35%(기대 14%)로 크게 벌어지고, 그 59%를 뜯어보면
   직전 5프레임 내 발화가 22건 중 6건뿐 — 일치가 우연일 수 있다.
   새 관문 = **오늘 두 독립 경로로 잰 값끼리의 대조**(설계 §3):
     A. 능력 상한 — dwell_probe(raw 재추론) vs hoi_metrics DB 경로(캐시). 이미 측정
        완료(30/37 vs 31/37, 참고 출력만 — PASS/FAIL 을 가르지 않는다).
     B. 런타임 거울 — dwell_probe 사전 감지율(선행시간>0) vs fsm_sim 거울(눌림 시점
        관측, 선행시간 0 도 포함). 두 정의의 차이는 "눌림 프레임에서 처음 관측된"
        위반 눌림 수와 정확히 같아야 한다: 거울 − 사전감지율 == 선행시간0 건수.
        **이 항등식이 성립하는지가 관문(PASS/FAIL)이다.**
"""

import argparse
import fnmatch
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, _TEST_DIR)

import config
import hoi_metrics
from fsm import SafetyFSM, State
from roi_zones import INSIDE, RING

CLIFF_Y = hoi_metrics.CLIFF_Y


def _expected_step_for(button):
    """'B2' → 2. 레시피가 B1..B4 순서라는 전제(recipe.json·§6.1)."""
    return int(button[1:])


def simulate(con, session_id, dwell=None, gap_fill=None, thresh=hoi_metrics.PALM_THRESH,
             exclude_cliff=False, **fsm_kwargs):
    """세션 1개를 재생한다. → 지표 dict.

    반환 키:
      mirror_hits/mirror_total  런타임 거울 사전 감지율 (눌림 시점 FSM 이 그 ROI 관측 중)
      blocked/violations        위반 사전 차단율 (위반 눌림 **전에** WARNING 이 떴나)
      false_alarms              정상 눌림만 있는 구간에서 발생한 WARNING 수
      duration_sec              세션 길이 (오경보를 분당으로 환산할 때 쓴다)
    """
    series = hoi_metrics.load_series(con, session_id, thresh)
    levels = {r["frame"]: r["zone_level"] for r in con.execute(
        "SELECT frame, zone_level FROM palm_frames "
        "WHERE session_id=? AND palm_thresh=? ORDER BY frame", (session_id, thresh))}
    times = {r["frame"]: r["ts"] for r in con.execute(
        "SELECT frame, ts FROM palm_frames "
        "WHERE session_id=? AND palm_thresh=? ORDER BY frame", (session_id, thresh))}
    presses = hoi_metrics.load_presses(con, session_id)
    if exclude_cliff:
        presses = [p for p in presses
                   if p["button_y"] is not None and p["button_y"] < CLIFF_Y]
    if not series:
        return None

    warnings = []                      # WARNING 진입 시각
    fsm = SafetyFSM(
        dwell_threshold=dwell if dwell is not None else config.FSM_DWELL_THRESHOLD_SEC,
        gap_fill=gap_fill if gap_fill is not None else config.FSM_GAP_FILL_SEC,
        on_state_change=lambda o, n: warnings.append(n),
        **fsm_kwargs)
    fsm.load_recipe()

    press_at = {p["frame"]: p for p in presses}
    mirror_hits = 0
    blocked = violations = 0
    n_warn = 0
    nxt = 0                            # 다음에 올 눌림의 인덱스
    if presses and presses[0]["expected_button"]:
        fsm.expected_step = _expected_step_for(presses[0]["expected_button"])

    for fr in sorted(series):
        ts = times.get(fr)
        if ts is None:
            continue                   # 시각이 없으면 체류를 못 잰다 — 건너뛴다

        p = press_at.get(fr)

        before = len(warnings)
        fsm.update_vision(series[fr], ts, levels.get(fr) or INSIDE)
        fired = [s for s in warnings[before:] if s == State.WARNING]
        n_warn += len(fired)

        if p is not None:
            # 런타임 거울 — 이 시점에 FSM 이 그 버튼 ROI 를 관측 중이었나
            if fsm.last_roi == p["button"]:
                mirror_hits += 1
            if p["is_violation"] == 1:
                violations += 1
                # 사전 차단 = 이 눌림 **전에** WARNING 이 떠 있었나.
                # 🔴 해제(정책 1·2)를 이 판정보다 **먼저** 하면 안 된다 — 앞선
                #    프레임에서 올라온 WARNING 이 지워져 "그 프레임에서 새로 발화한
                #    것"만 세게 된다(2026-07-27 실측으로 확인된 버그).
                if fsm.state == State.WARNING or fired:
                    blocked += 1
            if fsm.state in (State.WARNING, State.BLOCK):
                fsm.release_warning(); fsm.release_block()   # 정책 1·2
            fsm.press_button(p["button"], ts)
            if fsm.state in (State.WARNING, State.BLOCK):
                fsm.release_warning(); fsm.release_block()
            if fsm.state == State.IDLE:
                fsm.load_recipe()      # 정책 4 — 공정 완료 후 다음 주기 시작
            # 다음 눌림의 기대단계를 **미리** 넣는다 (정책 3).
            # 체류 타이머는 눌림 **이전** 접근 프레임에서 쌓이므로, 눌림 시점에
            # 넣으면 그 접근 구간이 낡은 기대단계로 판정된다.
            nxt += 1
            if nxt < len(presses) and presses[nxt]["expected_button"]:
                fsm.expected_step = _expected_step_for(presses[nxt]["expected_button"])

    ts_all = [t for t in times.values() if t is not None]
    return {
        "session": session_id,
        "mirror_hits": mirror_hits, "mirror_total": len(presses),
        "blocked": blocked, "violations": violations,
        "false_alarms": n_warn - blocked,
        "duration_sec": (max(ts_all) - min(ts_all)) if ts_all else 0.0,
    }


def _pct(a, b):
    return f"{a/b*100:5.1f}%" if b else "    -"


def run_all(con, pattern=None, **kw):
    rows = []
    for sid in hoi_metrics.session_ids(con):
        if pattern and not fnmatch.fnmatch(sid, f"*{pattern}*"):
            continue
        r = simulate(con, sid, **kw)
        if r:
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser(description="FSM 오프라인 시뮬레이터")
    ap.add_argument("--dwell", type=float, default=None,
                    help=f"체류 임계(초). 기본 = config({config.FSM_DWELL_THRESHOLD_SEC})")
    ap.add_argument("--gap-fill", type=float, default=None,
                    help=f"갭메우기(초). 기본 = config({config.FSM_GAP_FILL_SEC})")
    ap.add_argument("--sessions", default=None, help="세션명 부분일치 필터")
    ap.add_argument("--exclude-cliff", action="store_true",
                    help=f"버튼 y >= {CLIFF_Y} 인 눌림 제외")
    ap.add_argument("--gate", action="store_true",
                    help="🔴 검증 관문 — 거울−사전감지율==선행시간0건수 항등식 확인")
    args = ap.parse_args()

    con = hoi_metrics.connect()
    if args.gate:
        return gate(con)

    rows = run_all(con, args.sessions, dwell=args.dwell, gap_fill=args.gap_fill,
                   exclude_cliff=args.exclude_cliff)
    print(f"{'세션':<44}{'거울':>7}{'차단':>7}{'위반':>5}{'오경보/분':>10}")
    tb = tv = th = tm = 0
    for r in rows:
        fa = r["false_alarms"] / (r["duration_sec"] / 60) if r["duration_sec"] else 0
        print(f"{r['session'][:44]:<44}"
              f"{_pct(r['mirror_hits'], r['mirror_total']):>7}"
              f"{_pct(r['blocked'], r['violations']):>7}"
              f"{r['violations']:>5}{fa:>10.2f}")
        tb += r["blocked"]; tv += r["violations"]
        th += r["mirror_hits"]; tm += r["mirror_total"]
    print(f"\n통합  거울 {_pct(th, tm)} ({th}/{tm})  ·  차단 {_pct(tb, tv)} ({tb}/{tv})")


# A·B 두 대조의 기준값 — dwell_probe(raw 이미지 재추론)로 2026-07-27 측정.
# 대상 = `violation-press`·`violation-press-slow` 두 세션, 위반 눌림 37건(전량 위반).
# 재실행 비용(세션당 수 분·Hailo 장치 점유)이 커 여기서는 상수로 둔다 — 재측정하려면
# `python3 test/dwell_probe.py test/raw/<세션> --gpio-log ...` (실행 금지, 브리프 참조).
_DWELL_PROBE_CAP_HITS   = 30   # 능력 상한(창 안에 한 번이라도 관측)
_DWELL_PROBE_CAP_TOTAL  = 37
_DWELL_PROBE_LEAD_HITS  = 26   # 사전 감지율(선행시간 > 0, 눌림 이전부터 연속 관측)
_DWELL_PROBE_LEAD_TOTAL = 37

_VIOLATION_PATTERN = "violation-press"   # `violation-press`·`violation-press-slow` 둘 다 (부분일치)


def _lead0_count(con, session_id, gap_fill):
    """선행시간 0 인 위반 눌림 수 — DB 에서 계산 (dwell_probe 재실행 없이).

    갭메우기를 적용한 시계열에서 `series[눌림프레임]==버튼` 이고
    `series[눌림프레임-1]!=버튼` 인 위반 눌림을 센다 — "이 프레임에서 처음 관측됐다"는
    뜻이라 dwell_probe 의 "선행시간>0(눌림 **이전**부터 이어진 연속 구간)" 과 정확히
    반대 조건이다. `dwell_probe.fill_gaps` 를 그대로 쓴다(판정 규칙 복제 금지).
    """
    import dwell_probe   # cv2 의존이라 --gate 경로에서만 지연 import

    rows = con.execute(
        "SELECT frame, ts, zone_label FROM palm_frames "
        "WHERE session_id=? AND palm_thresh=? ORDER BY frame",
        (session_id, hoi_metrics.PALM_THRESH)).fetchall()
    frames = [r["frame"] for r in rows]
    filled, _ = dwell_probe.fill_gaps(
        [r["zone_label"] for r in rows], [r["ts"] for r in rows], gap_fill)
    by_frame = dict(zip(frames, filled))

    count = 0
    for p in hoi_metrics.load_presses(con, session_id):
        if p["is_violation"] != 1:
            continue
        fr = p["frame"]
        if by_frame.get(fr) == p["button"] and by_frame.get(fr - 1) != p["button"]:
            count += 1
    return count


def gate(con):
    """🔴 검증 관문 — 통과 못 하면 어떤 수치도 쓰지 않는다 (설계 §4.5).

    §10.23 재현은 폐기(모듈 docstring 참조). 새 정의 = 오늘 두 독립 경로의 대조:
      A. 능력 상한  — dwell_probe(raw) vs hoi_metrics DB(캐시). 참고 출력만.
      B. 런타임 거울 — 거울(fsm_sim) − 사전감지율(dwell_probe) == 선행시간0 건수(DB).
         **B 의 항등식만 PASS/FAIL 을 가른다.**
    """
    print("🔴 검증 관문 — 오늘 두 독립 경로 대조 (§10.23 재현 폐기, 2026-07-27)\n")

    # --- A. 능력 상한 (참고, 미판정) ---
    cap_hits = cap_total = 0
    for sid in hoi_metrics.session_ids(con):
        if not fnmatch.fnmatch(sid, f"*{_VIOLATION_PATTERN}*"):
            continue
        series = hoi_metrics.load_series(con, sid)
        presses = [p for p in hoi_metrics.load_presses(con, sid) if p["is_violation"] == 1]
        h, t = hoi_metrics.capability_rate(series, presses)
        cap_hits += h; cap_total += t
    print(f"  A. 능력 상한   dwell_probe {_DWELL_PROBE_CAP_HITS}/{_DWELL_PROBE_CAP_TOTAL}"
          f"  vs  DB {cap_hits}/{cap_total}  (참고 — PASS/FAIL 미판정)")

    # --- B. 런타임 거울 vs 사전감지율 (항등식으로 판정) ---
    print()
    ok = True
    for dwell in (0.3, 0.5):
        mirror_hits = mirror_total = lead0 = 0
        for sid in hoi_metrics.session_ids(con):
            if not fnmatch.fnmatch(sid, f"*{_VIOLATION_PATTERN}*"):
                continue
            r = simulate(con, sid, dwell=dwell)
            if r:
                mirror_hits += r["mirror_hits"]; mirror_total += r["mirror_total"]
            lead0 += _lead0_count(con, sid, gap_fill=config.FSM_GAP_FILL_SEC)

        lhs = mirror_hits - _DWELL_PROBE_LEAD_HITS   # 거울 − 사전감지율
        hit = (lhs == lead0)
        ok &= hit
        print(f"  B. 체류 {dwell}초  거울 {mirror_hits}/{mirror_total}  "
              f"− 사전감지율 {_DWELL_PROBE_LEAD_HITS}/{_DWELL_PROBE_LEAD_TOTAL}  "
              f"= {lhs}   선행시간0 건수(DB) = {lead0}   {'PASS' if hit else 'FAIL'}")

    print(f"\n{'✅ 통과 — 기준선 산출로 진행' if ok else '❌ 실패 — 원인을 찾기 전까지 진행 금지'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
