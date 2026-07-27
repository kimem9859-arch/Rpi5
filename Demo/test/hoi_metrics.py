"""사전 감지율 판정 규칙 — **단일 출처**.

왜 별도 모듈인가 (2026-07-27):
    같은 지표가 세 군데에서 **서로 다르게** 계산되고 있었다 — `dwell_probe` 는 눌림
    직전 프레임 하나로 판정하고, `hoi_import` docstring 의 SQL 예시는 직전 15프레임
    창을 쓰고, 세션마다 즉석 질의를 또 썼다. 두 정의의 격차가 세션마다 벌어져
    §10 의 수치들이 서로 비교되지 않았다(격차 크기는 설계 §3.2 참조).

    🔴 **판정 규칙을 바꿀 때는 여기만 고친다.** `roi_zones.py` 와 같은 원칙이다.

2층 구조:
    · 순수 층 (`capability_*`) — {프레임: 구역라벨} 과 눌림 목록만 받는다. **소스를 모른다.**
      `dwell_probe` 는 실시간 추론 시계열로, DB 어댑터는 palm_frames 로 호출한다.
    · DB 어댑터 (`load_*`) — hoi.db 에서 그 딕셔너리를 만든다.

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
CLIFF_Y = 337         # 절벽 경계. 이보다 아래 버튼은 창으로 못 고친다 (§10.27)

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
