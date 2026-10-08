"""사전 감지율 판정 규칙 — **단일 출처**.

왜 별도 모듈인가 (2026-07-27):
    같은 지표가 세 군데에서 **서로 다르게** 계산되고 있었다 — `dwell_probe` 는 눌림
    직전 프레임 하나로 판정하고, `hoi_import` docstring 의 SQL 예시는 직전 15프레임
    창을 쓰고, 세션마다 즉석 질의를 또 썼다. 두 정의의 격차가 세션마다 벌어져
    §10 의 수치들이 서로 비교되지 않았다(격차 크기는 설계 §3.2 참조).

    🔴 **판정 규칙을 바꿀 때는 여기만 고친다.** `roi_zones.py` 와 같은 원칙이다.

2층 구조:
    · 순수 층 (`capability_*` · `analyze_presses` · `segments`) — 구역 시계열과 눌림 목록만
      받는다. **소스를 모른다.** 측정 도구 정합 1단계-나(세기)가 시연 기록(`frames.csv` ·
      `fsm.csv` · `events.csv`)으로 부른다 · 옛 도구는 실시간 추론 시계열·palm_frames 로 불렀다.
      `analyze_presses` · `segments` 는 2026-10-09 `dwell_probe` 에서 글자 그대로 옮겼다
      (설계 상위 `docs/superpowers/specs/2026-10-09-세기도구정리-design.md` §4).
    · DB 어댑터 (`connect` · `load_*`) — 옛 hoi.db 전용(옛 데이터 · 조사 스크립트 · 백업 도구
      `백업/세기-20261009/`). 새 측정에는 쓰지 않는다.

정의 (설계 = ../docs/superpowers/specs/2026-07-27-창판정-design.md §3):
    사전 감지율 = (감지 성공한 눌림 수) ÷ (전체 눌림 수). **단위는 눌림 1건**이며
    프레임이 아니다. 프레임 단위 손 검출률을 성능 지표로 쓰지 말 것(§10.25).

    "능력 상한" = 창 안에 그 버튼 구역인 프레임이 **하나라도** 있으면 성공.
    "런타임 거울" = FSM 을 재생해 판정한다 → `fsm_sim.py` 담당.

창 길이 5 의 근거 = §10.29⑥ 의 계단 위치. 9 로 넓히면 감지가 거의 안 늘면서 타 버튼
혼입만 크게 는다 — 교환비 비교는 설계 §3.2 참조.
"""

import os
import sqlite3

WINDOW_N = 5          # 눌림 직전 몇 프레임까지 되돌아보는가 (총 N+1 프레임)
PALM_THRESH = 0.5     # 팜 임계 고정 — 변수를 섞지 않는다 (§10.27·§10.28)
CLIFF_Y_VGA = 337     # 절벽 경계(VGA 480×640 회전 후 좌표). 이보다 아래 버튼은 창으로 못 고친다 (§10.27)
CLIFF_Y = CLIFF_Y_VGA # hoi.db 의 y 값은 hoi_import 가 VGA 기준으로 환산해 담는다(sessions.px_scale) — 그대로 비교한다

_DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hoi.db")


# ────────────────────────────────────────────────────────── 순수 층 (소스 무관)
def capability_hit(series, press_frame, button, n=WINDOW_N):
    """창 안에 `button` 구역인 프레임이 하나라도 있으면 True.

    series = {프레임번호: 구역라벨 or None}
    창 = [press_frame - n, press_frame] (총 n+1 프레임)
    """
    for fr in range(press_frame - n, press_frame + 1):
        if series.get(fr) == button:
            return True
    return False


def capability_rate(series, presses, n=WINDOW_N):
    """→ (성공 눌림 수, 전체 눌림 수). presses = [{'frame':.., 'button':..}, ...]"""
    hits = sum(1 for p in presses
               if capability_hit(series, p["frame"], p["button"], n))
    return hits, len(presses)


def analyze_presses(presses, series, frames, times, dwell, raw_series=None):
    """눌림 하나하나에 대해 '비전이 언제 그 버튼을 봤는가'를 대조한다.

    선행시간 = t_눌림 − t_도착. t_도착은 **눌림 직전의 연속 ROI 구간이 시작된 시각**이다.
    이 값이 양수여야 "누르기 직전에 사전 감지"라는 프로젝트 명제가 성립한다.

    `win` = 창 기반 능력 상한(§3, `hoi_metrics`). 선행시간과 **다른 것을 잰다** —
    선행시간은 연속 구간을 요구하고, 창은 창 안에 한 번이라도 보이면 성공이다.
    두 값의 격차 = 판정 로직이 버리는 양.

    `raw_series` = 갭메우기 **이전** 시계열. 능력 상한은 런타임 동작(갭메우기)에
    영향받지 않는 고정 지표라 이쪽으로 잰다(설계 §3.1) — 선행시간·ROI 일치율은
    그대로 `series`(런타임과 동일하게 갭메우기가 적용된 것)를 쓴다. 없으면 `series`를 쓴다.
    """
    cap_by_frame = {fr: (raw_series or series)[i] for i, fr in enumerate(frames)}
    rows = []
    for t_press, btn, fr in presses:
        win = capability_hit(cap_by_frame, fr, btn)
        # 눌림 시각 이하인 마지막 프레임 인덱스
        idx = max((i for i, t in enumerate(times) if t <= t_press), default=None)
        if idx is None:
            rows.append((btn, fr, None, None, "프레임 없음", win))
            continue
        seen = series[idx]
        if seen != btn:
            rows.append((btn, fr, None, seen, "ROI 불일치" if seen else "미검출", win))
            continue
        # 같은 ROI가 연속으로 유지된 구간의 시작까지 거슬러 올라간다
        j = idx
        while j > 0 and series[j - 1] == btn:
            j -= 1
        rows.append((btn, fr, t_press - times[j], seen, "OK", win))
    return rows


def segments(series, frames, times):
    """연속 동일 ROI 구간 → [(roi, 시작프레임, 끝프레임, 지속초)]."""
    segs = []
    i = 0
    n = len(series)
    while i < n:
        if series[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and series[j + 1] == series[i]:
            j += 1
        segs.append((series[i], frames[i], frames[j], times[j] - times[i]))
        i = j + 1
    return segs


# ─────────────────────────────────────────────────────────────── DB 어댑터 층
def connect(db_path=None):
    con = sqlite3.connect(db_path or _DEFAULT_DB)
    con.row_factory = sqlite3.Row
    return con


def session_ids(con):
    return [r[0] for r in con.execute("SELECT id FROM sessions ORDER BY id")]


def load_series(con, session_id, thresh=PALM_THRESH):
    """palm_frames → {프레임: 구역라벨 or None}."""
    return {r["frame"]: r["zone_label"] for r in con.execute(
        "SELECT frame, zone_label FROM palm_frames "
        "WHERE session_id=? AND palm_thresh=? ORDER BY frame",
        (session_id, thresh))}


def load_presses(con, session_id):
    """presses → [{'frame','button','ts','button_y','is_violation','expected_button'}]."""
    return [dict(r) for r in con.execute(
        "SELECT frame, button, ts, button_y, is_violation, expected_button "
        "FROM presses WHERE session_id=? ORDER BY frame", (session_id,))]
