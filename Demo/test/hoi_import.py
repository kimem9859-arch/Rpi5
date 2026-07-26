"""HOI 분석 데이터를 SQLite(hoi.db) 하나로 적재한다 — "눌림 1회 = 1행".

왜 필요한가 (2026-07-26):
    §10.24~§10.29 여섯 절의 수치가 전부 세션 임시 폴더의 CSV 26개에서 나왔다. 세션이
    끝나면 사라지고 문서에는 결론만 남는다. 게다가 "49조합 y 곡선"·"365건 속도 곡선"을
    매번 CSV 13~18개를 파이썬으로 이어붙여 만들었다 — SQL 한 줄이면 될 일이다.

    ⚠️ `bench.db`(버튼 검출)와 **별도 파일**이다. 분석 단위가 다르고(프레임 vs 눌림
    이벤트), `db_import.py` 의 INSERT 가 컬럼 수에 고정돼 있어 손대면 그쪽 재구축이
    깨진다(§10.21). **서로를 참조하지 않는다** — 필요한 것은 CSV 에서 직접 읽는다.

사용:
    python3 test/hoi_probe_batch.py --thresh 0.5      # 1단계: 팜 추론 캐시 (1~2시간)
    python3 test/hoi_probe_batch.py --thresh 0.2
    python3 test/hoi_import.py                        # 2단계: DB 재구축 (수 초)

원칙 (`bench.db` 와 동일):
    - 매 실행 = 전량 재구축(drop & rebuild). 원본 CSV·캐시가 정본이다.
    - **원천만 담고 요약은 질의로.** 사전 감지율·선행시간 같은 지표를 테이블에 넣지
      않는다 — 판정 생산(링 폭·체류 임계)이 바뀌면 stale 이 된다.
    - 측정 수치의 정본은 통합문서 §10 (복제 금지).

예시 질의 — 오늘 파이썬으로 재조립하던 것들:

    -- ① §10.27 버튼 y 구간별 팜 검출률 (절벽 y≈337 확인)
    SELECT CAST(p.button_y/40 AS INT)*40 AS y_bin, COUNT(*) AS n,
           ROUND(AVG(f.n_palm>0)*100,1) AS palm_pct
    FROM presses p JOIN palm_frames f
      ON f.session_id=p.session_id AND f.frame BETWEEN p.frame-5 AND p.frame+5
    WHERE f.palm_thresh=0.5 GROUP BY 1 ORDER BY 1;

    -- ② §10.29⑥ 눌림 간격(프레임)별 사전 감지율 — 절벽 눌림 제외
    --    "사전 감지" = 눌림 직전 15프레임 안에 손끝이 그 버튼 구역에 있었나
    SELECT CASE WHEN p.gap_frames<5 THEN '0~5' WHEN p.gap_frames<8 THEN '5~8'
                WHEN p.gap_frames<10 THEN '8~10' ELSE '10+' END AS gap_bin,
           COUNT(*) AS n,
           ROUND(AVG(EXISTS(SELECT 1 FROM palm_frames f
                            WHERE f.session_id=p.session_id AND f.palm_thresh=0.5
                              AND f.frame BETWEEN p.frame-15 AND p.frame
                              AND f.zone_label=p.button))*100,1) AS detect_pct
    FROM presses p
    WHERE p.gap_frames IS NOT NULL AND p.button_y < 337
    GROUP BY 1;

    -- ③ §10.28 팜 임계 대조 (같은 눌림을 0.5/0.2로)
    SELECT s.condition, p.button, ROUND(p.button_y) AS y, f.palm_thresh,
           ROUND(AVG(f.n_palm>0)*100,1) AS palm_pct
    FROM presses p JOIN palm_frames f
      ON f.session_id=p.session_id AND f.frame BETWEEN p.frame-5 AND p.frame+5
    JOIN sessions s ON s.id=p.session_id
    WHERE s.condition='far-low' GROUP BY 1,2,3,4 ORDER BY 3,4;

    -- ④ 세션 요약 (자세·근접도·구도)
    SELECT condition, posture, ROUND(fps,1) AS fps, ROUND(emo_width) AS emo_w,
           ROUND(top_y) AS top_y, ROUND(bottom_y) AS bottom_y
    FROM sessions ORDER BY id;

설계: docs/superpowers/specs/2026-07-26-HOI-DB-design.md
"""

import argparse
import csv
import glob
import os
import re
import sqlite3
import statistics as st
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(_TEST_DIR, "logs")
RAW_DIR = os.path.join(_TEST_DIR, "raw")
CACHE_DIR = os.path.join(_TEST_DIR, "palm_cache")
DEFAULT_DB = os.path.join(_TEST_DIR, "hoi.db")

BOX_WINDOW = 15          # 눌림 ±N프레임의 버튼 박스만 담는다(전량은 bench.db 소관)

# palm_cache 파일명: <세션>_t{임계}_ring{링}.csv  ← hoi_probe_batch.cache_path 와 공유하는 규약
_CACHE_RE = re.compile(r"^(.+)_t([\d.]+)_ring(\d+)\.csv$")

SCHEMA = """
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,   -- raw 폴더명 = 로그 파일명 접두사
    date         TEXT, time TEXT,
    condition    TEXT,               -- 'far-high' | 'upright-violation' | 'ypos1-high-diag' ...
    posture      TEXT,               -- 'flat' | 'upright' (파일명에 없어 수동 매핑)
    model        TEXT,
    frames       INTEGER, duration_sec REAL, fps REAL,
    emo_width    REAL,               -- 근접도 대리지표 (§10.28)
    top_y        REAL, bottom_y REAL -- 윗줄(B2·B3)/아랫줄(B1·B4) median y (§10.26)
);
CREATE TABLE button_boxes (          -- 눌림 ±15프레임 구간만
    session_id TEXT REFERENCES sessions(id),
    frame INTEGER, cls_name TEXT,
    x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER
);
CREATE TABLE presses (               -- 눌림 1회 = 1행
    session_id  TEXT REFERENCES sessions(id),
    frame INTEGER, button TEXT,
    ts          REAL,                -- 세션 시작 기준 초
    gap_frames  INTEGER,             -- 직전 눌림과의 간격 (첫 눌림 NULL) — §10.29⑥의 축
    gap_sec     REAL,
    button_y    REAL,                -- 그 버튼의 세션 median y — §10.26 절벽 판정의 축
    is_violation INTEGER             -- 오답인가 (규칙 미정 세션은 NULL)
);
CREATE TABLE palm_frames (           -- 팜 임계·링을 행 안에 (같은 프레임이 임계별로 여러 행)
    session_id  TEXT REFERENCES sessions(id),
    frame INTEGER,
    palm_thresh REAL, ring_px INTEGER,
    n_palm INTEGER, flag REAL,
    tip_x REAL, tip_y REAL,
    palm_cx REAL, palm_cy REAL, palm_size REAL,
    zone_label TEXT, zone_level INTEGER   -- roi_zones.zone_at_point() 결과
);
CREATE INDEX idx_presses ON presses(session_id, button);
CREATE INDEX idx_palm ON palm_frames(session_id, palm_thresh, frame);
CREATE INDEX idx_boxes ON button_boxes(session_id, frame);
"""

# ── 수동 매핑 2개 ────────────────────────────────────────────────────────────
# 파일명·manifest 에 없는 축이라 여기 둔다. `db_import.py` 의 `_CONDITIONS` 와 같은 방식.
# 🔴 세션이 늘면 갱신할 것 — 표에 없으면 NULL 이 되고, 아래 main() 이 그 목록을 보고한다.

# 콘솔 자세. §10.26 에서 처음 변수로 잡혔는데 촬영 시엔 기록되지 않았다.
_POSTURE = {
    "20260722": "flat",       # 7/22 전 세션 = 누운 콘솔
    "20260724": "upright",    # 7/24 전 세션 = 세운 콘솔
}

# 위반 판정 규칙. 🔴 recipe.json 을 돌려 자동 판정하지 않는다 — 촬영 의도가 세션마다 달라
# 코드가 추측하면 틀린다(§10.23·§10.26 촬영 설계).
#   'expect_b1' = 기대단계 B1 고정 → B1 이 아니면 위반
#   'normal'    = 정상 순서 반복   → 전부 정답
#   'mixed'     = 정답 구간 뒤에 위반 구간 → B1 이 마지막으로 눌린 뒤부터 위반
_VIOLATION_RULE = {
    "violation-press": "expect_b1",
    "violation-press-slow": "expect_b1",
    "upright-violation": "expect_b1",
    "press-sim": "normal",
    "press-sim-holdout": "normal",
    "press-sim-slow": "normal",
    "press-sim-slow-holdout": "normal",
    "falsealarm-clean": "normal",
    "upright-normal": "normal",
    "upright-falsealarm": "normal",
    "upright-holdout": "normal",
    # ypos·far 는 정답 주기 뒤에 위반 주기를 붙여 찍었다(§10.27·§10.28 설계)
    "ypos1-high-diag": "mixed", "ypos2-high-front": "mixed", "ypos3-mid-front": "mixed",
    "ypos4-low-diag": "mixed", "ypos5-low-front": "mixed",
    "far-high": "mixed", "far-low": "mixed",
    "far-high-r1": "mixed", "far-high-r2": "mixed", "far-high-r3": "mixed",
}


def _parse_ts(s):
    """'15:49:48.316' → 초(float). 자정 넘김은 이 용도에선 무시한다.

    `dwell_probe._parse_ts` 와 같은 규약 — 두 도구의 초 단위가 어긋나면 대조가 깨진다.
    """
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _session_ids():
    """대상 = raw 폴더 + GPIO 눌림 로그를 모두 가진 세션 (HOI 분석 대상의 정의)."""
    out = []
    for name in sorted(os.listdir(RAW_DIR)):
        if not os.path.isdir(os.path.join(RAW_DIR, name)):
            continue
        if os.path.exists(os.path.join(LOGS_DIR, f"{name}_gpio_log.csv")):
            out.append(name)
    return out


def _parse_session_id(sid):
    """'20260724_193521_esp32_far-high_console_v2' → (date, time, condition, model)."""
    parts = sid.split("_")
    date_s, time_s = parts[0], parts[1]
    rest = parts[3:]                                   # parts[2] = source (esp32/usb)
    model = None
    if len(rest) >= 2 and re.match(r"^v\d+$", rest[-1]):
        model = "_".join(rest[-2:])                    # 'console_v2'
        rest = rest[:-2]
    condition = "_".join(rest) if rest else None
    return date_s, time_s, condition, model


def _violation_flags(presses, rule):
    """[(frame, button)] → [is_violation | None]. 규칙별 판정."""
    if rule == "normal":
        return [0] * len(presses)
    if rule == "expect_b1":
        return [0 if b == "B1" else 1 for _, b in presses]
    if rule == "mixed":
        # 정답 주기(B1B2B3B4) 를 몇 번 돌린 뒤 위반 주기(B2B3B4) 로 넘어간 촬영이다.
        # ⚠️ 경계는 "마지막 B1" 이 아니라 **그 B1 이 속한 주기의 끝(다음 B4)** 이다 —
        #    마지막 B1 로 자르면 그 주기의 B2·B3·B4 가 위반으로 잘못 셈된다(실측 확인:
        #    far-high 가 6 대신 9 로 나왔다).
        last_b1 = max((i for i, (_, b) in enumerate(presses) if b == "B1"), default=-1)
        cut = last_b1
        if last_b1 >= 0:
            for i in range(last_b1 + 1, len(presses)):
                if presses[i][1] == "B4":
                    cut = i
                    break
            else:
                cut = len(presses) - 1          # 주기가 안 끝났으면 전부 정답
        return [0 if i <= cut else (0 if b == "B1" else 1)
                for i, (_, b) in enumerate(presses)]
    return [None] * len(presses)


def _import_session(con, sid):
    """세션 1개의 sessions·presses·button_boxes 적재. → (눌림 수, 규칙명 or None)."""
    date_s, time_s, condition, model = _parse_session_id(sid)
    posture = _POSTURE.get(date_s)
    rule = _VIOLATION_RULE.get(condition)

    # ── perf: 프레임 → 초, 세션 길이·fps
    perf = _rows(os.path.join(LOGS_DIR, f"{sid}_perf_log.csv"))
    times = {int(r["frame"]): _parse_ts(r["timestamp"]) for r in perf}
    t0 = min(times.values()) if times else 0.0
    frames = len(perf)
    duration = (max(times.values()) - t0) if times else None
    fps = (frames / duration) if duration else None

    # ── rawdet: 버튼 박스 + 구도 지표(EMO 폭·윗줄/아랫줄 y)
    boxes_by_frame = {}
    ys, emo_w = {}, []
    rd_path = os.path.join(LOGS_DIR, f"{sid}_rawdet_log.csv")
    if os.path.exists(rd_path):
        for r in _rows(rd_path):
            fr, cls = int(r["frame"]), r["cls_name"]
            x1, y1, x2, y2 = int(r["x1"]), int(r["y1"]), int(r["x2"]), int(r["y2"])
            boxes_by_frame.setdefault(fr, []).append((cls, x1, y1, x2, y2))
            ys.setdefault(cls, []).append((y1 + y2) / 2)
            if cls == "EMO":
                emo_w.append(x2 - x1)

    def med(*classes):
        vals = [v for c in classes for v in ys.get(c, [])]
        return st.median(vals) if vals else None

    con.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, f"{date_s[:4]}-{date_s[4:6]}-{date_s[6:]}", time_s, condition, posture,
         model, frames, duration, fps,
         st.median(emo_w) if emo_w else None, med("B2", "B3"), med("B1", "B4")))

    # ── gpio: 눌림 (정답 라벨)
    presses = [(int(r["frame"]), r["button"])
               for r in _rows(os.path.join(LOGS_DIR, f"{sid}_gpio_log.csv"))]
    presses.sort()
    flags = _violation_flags(presses, rule)

    rows, want_frames = [], set()
    for i, (frame, button) in enumerate(presses):
        prev = presses[i - 1][0] if i else None
        gap_f = (frame - prev) if prev is not None else None
        gap_s = None
        if prev is not None and frame in times and prev in times:
            gap_s = times[frame] - times[prev]
        by = med(button)
        rows.append((sid, frame, button,
                     (times[frame] - t0) if frame in times else None,
                     gap_f, gap_s, by, flags[i]))
        want_frames.update(range(frame - BOX_WINDOW, frame + BOX_WINDOW + 1))
    con.executemany("INSERT INTO presses VALUES (?,?,?,?,?,?,?,?)", rows)

    # ── button_boxes: 눌림 근처만
    box_rows = [(sid, fr, *b) for fr in sorted(want_frames & boxes_by_frame.keys())
                for b in boxes_by_frame[fr]]
    con.executemany("INSERT INTO button_boxes VALUES (?,?,?,?,?,?,?)", box_rows)

    return len(rows), rule, posture


def _import_palm_cache(con, known_sessions):
    """palm_cache/*.csv → palm_frames. → (행 수, 조합 수, 캐시 없는 세션 목록)."""
    total, combos = 0, 0
    covered = set()
    for path in sorted(glob.glob(os.path.join(CACHE_DIR, "*.csv"))):
        m = _CACHE_RE.match(os.path.basename(path))
        if not m:
            continue
        sid, thresh, ring = m.group(1), float(m.group(2)), int(m.group(3))
        if sid not in known_sessions:            # 삭제된 세션의 캐시가 남아 있을 수 있다
            continue
        rows = []
        for r in _rows(path):
            def num(k, cast=float):
                v = r.get(k)
                return cast(v) if v not in (None, "") else None
            rows.append((sid, int(r["frame"]), thresh, ring,
                         num("n_palm", int), num("flag"),
                         num("tip_x"), num("tip_y"),
                         num("palm_cx"), num("palm_cy"), num("palm_size"),
                         r.get("zone_label") or None, num("zone_level", int)))
        con.executemany(
            "INSERT INTO palm_frames VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        total += len(rows)
        combos += 1
        covered.add(sid)
    return total, combos, sorted(known_sessions - covered)


def main():
    ap = argparse.ArgumentParser(description="HOI 분석 CSV → SQLite (전량 재구축)")
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()

    if os.path.exists(args.db):
        os.remove(args.db)                       # 전량 재구축 — 원본이 정본이다
    con = sqlite3.connect(args.db)
    con.executescript(SCHEMA)

    sessions = _session_ids()
    if not sessions:
        print("❌ 대상 세션이 없습니다 (raw + gpio 로그 둘 다 필요)")
        return 2

    n_press = 0
    no_rule, no_posture = [], []
    for sid in sessions:
        cnt, rule, posture = _import_session(con, sid)
        n_press += cnt
        if rule is None:
            no_rule.append(sid)
        if posture is None:
            no_posture.append(sid)

    palm_rows, combos, no_cache = _import_palm_cache(con, set(sessions))
    con.commit()

    print(f"✅ {args.db}")
    print(f"   세션 {len(sessions)} · 눌림 {n_press} · 팜 프레임 {palm_rows} ({combos} 조합)")
    if no_cache:
        print(f"\n⚠️ 팜 캐시 없는 세션 {len(no_cache)}개 — hoi_probe_batch.py 를 돌리세요:")
        for s in no_cache:
            print(f"     {s}")
    if no_rule:
        print(f"\n⚠️ 위반 판정 규칙 미등록 {len(no_rule)}개 (is_violation=NULL) "
              f"— _VIOLATION_RULE 에 추가하세요:")
        for s in no_rule:
            print(f"     {s}")
    if no_posture:
        print(f"\n⚠️ 자세 미등록 {len(no_posture)}개 (posture=NULL) — _POSTURE 에 추가하세요:")
        for s in no_posture:
            print(f"     {s}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
