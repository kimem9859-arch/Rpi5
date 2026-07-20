"""test/logs의 벤치마크 CSV 전량을 SQLite(bench.db) 하나로 적재한다.

왜 필요한가:
    세션 메타데이터(카메라·조명조건)가 파일명과 통합문서 §10.13에 흩어져 있어
    세션 간 비교(v1↔v2, 저조도↔기준선)마다 일회성 스크립트를 새로 짜야 했다.
    DB로 모으면 같은 질문이 SQL 한 줄이 되고, 다가올 test 세션 채점도 같은 틀로 쌓인다.

사용:
    python3 test/db_import.py            # Demo/ 에서 실행 → test/bench.db 재구축
    sqlite3 test/bench.db "SELECT s.condition, d.cls_name, COUNT(*), AVG(d.score)
                           FROM rawdet d JOIN sessions s ON d.session_id=s.id
                           GROUP BY 1,2"

원칙:
    - 매 실행 = 전량 재구축(drop & rebuild). 원본 CSV가 정본이고 10만 행 규모라 수 초.
    - DB엔 원천 데이터·조건 분류만 담는다. 요약 수치(검출률 등)는 질의로 계산 —
      측정 수치의 정본은 통합문서 §10 (복제 금지).
    - confusion 로그는 테이블을 만들지 않는다 — 21세션 전부 0행. 트랙 클래스 "전환"만
      기록하는 설계라 처음부터 오분류된 경우를 못 잡는 계측 사각지대(§10.8).
"""

import argparse
import csv
import glob
import json
import os
import re
import sqlite3
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(_TEST_DIR, "logs")
REPLAY_DIR = os.path.join(LOGS_DIR, "replay")
RAW_DIR = os.path.join(_TEST_DIR, "raw")
DEFAULT_DB = os.path.join(_TEST_DIR, "bench.db")

# {YYYYMMDD}_{HHMMSS}_{source}[_{condition}][_{model}]_{kind}_log.csv
#   condition/model 접미사는 2026-07-20 도입(bench_detector.py --condition). 그 이전 세션은
#   접미사가 없으므로 둘 다 optional — 기존 21개 세션의 파싱을 그대로 유지한다.
#   condition은 [a-z0-9-], model은 '_v<숫자>'를 포함해 서로 모호하지 않다.
#   ⚠️ 이 규약은 bench_detector.py의 _tag 생성과 공유한다 — 한쪽만 바꾸면 여기서 조용히 스킵된다.
_LOG_RE = re.compile(
    r"^(\d{8})_(\d{6})_(esp32|usb)"
    r"(?:_([a-z0-9-]+))?"
    r"(?:_([a-z0-9]+_v\d+|best))?"
    r"_(rawdet|detection|perf|stability|confusion)_log\.csv$")

# 바탕화면 '실테스트 점검' 바로가기가 쓰는 조건 슬러그. 카메라·모델이 살아있는지만 보는
# 30프레임 세션이라 측정값이 아니다 — 적재에서 제외해 조건 비교를 오염시키지 않는다.
_SMOKETEST_COND = "smoketest"

# 세션 → 촬영 조건 분류 (근거 = 통합문서 §10.13/§10.17; 수치는 담지 않는다)
_CONDITIONS = {
    "20260713_174153": ("baseline", "§10.13"),   # 각도±30°·거리 변화 (비교 기준선)
    "20260713_175129": ("specular", "§10.13"),   # 정반사(라이트)
    "20260713_175658": ("distance", "§10.13"),   # 원거리 + 배경 다양
    "20260713_180016": ("lowlight", "§10.13"),   # 저조도
    "20260713_173728": ("holdout",  "§10.17"),   # 누출-프리(학습 미사용)
}

_SCHEMA = """
CREATE TABLE sessions (
    id            TEXT PRIMARY KEY,   -- 'YYYYMMDD_HHMMSS_source[_condition][_model]' = raw 폴더명
    date          TEXT,               -- '2026-07-13'
    time          TEXT,               -- '174153'
    source        TEXT,               -- 'esp32' | 'usb'
    condition     TEXT,               -- baseline/specular/distance/lowlight/holdout/bench-camera
    condition_ref TEXT,               -- 근거 문서 포인터 (§10.x) 또는 '파일명'
    model         TEXT,               -- 'console_v2' 등. 파일명 접미사에서 (구 세션은 NULL)
    -- 이하 manifest.json에서 승격 (raw 프레임 보존 세션만, 나머지 NULL)
    hef_path      TEXT,
    conf_high     REAL,
    conf_low      REAL,
    lock_exposure INTEGER,
    exposure      INTEGER,
    note          TEXT
);
CREATE TABLE rawdet (                 -- 트래킹 이전 raw 검출 전량 (>= conf_low)
    session_id TEXT REFERENCES sessions(id),
    frame INTEGER, ts TEXT, cls_name TEXT, score REAL,
    x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER
);
CREATE TABLE detections (             -- confirm된 트랙 검출 (>= conf_high)
    session_id TEXT REFERENCES sessions(id),
    frame INTEGER, ts TEXT, cls_name TEXT, score REAL,
    x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER
);
CREATE TABLE perf (
    session_id TEXT REFERENCES sessions(id),
    frame INTEGER, ts TEXT, fps REAL, inference_ms REAL, detection_count INTEGER
);
CREATE TABLE stability (
    session_id TEXT REFERENCES sessions(id),
    track_id INTEGER, cls_name TEXT,
    start_frame INTEGER, end_frame INTEGER, duration_frames INTEGER, miss_count INTEGER
);
CREATE TABLE replay_runs (            -- replay_raw.py 실행 1회 = 1행
    id INTEGER PRIMARY KEY,
    run_ts     TEXT,                  -- 'YYYYMMDD_HHMMSS'
    session_id TEXT REFERENCES sessions(id),
    hef        TEXT,                  -- console_v1.hef / console_v2.hef ...
    conf_high  REAL,
    conf_low   REAL,
    degrade    TEXT                   -- 열화 조건 라벨 ('원본' 등)
);
CREATE TABLE replay_dets (            -- replay 프레임별 raw 검출
    run_id INTEGER REFERENCES replay_runs(id),
    frame INTEGER, cls_name TEXT, score REAL,
    x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER
);
CREATE INDEX idx_rawdet ON rawdet(session_id, cls_name);
CREATE INDEX idx_detections ON detections(session_id, cls_name);
CREATE INDEX idx_perf ON perf(session_id);
CREATE INDEX idx_replay_dets ON replay_dets(run_id, cls_name);
"""


def _read_rows(path, skip_comment=False):
    with open(path, newline="") as f:
        first = f.readline()
        if skip_comment and first.startswith("#"):
            first = f.readline()               # 헤더로 진행
        reader = csv.reader(f)
        return list(reader)


def _condition_for(date_s, time_s, cond_tag=None):
    # 파일명이 조건을 직접 들고 있으면 그것이 우선 — 하드코딩 매핑은 그 이전 세션용 폴백이다.
    if cond_tag:
        return (cond_tag, "파일명")
    key = f"{date_s}_{time_s}"
    if key in _CONDITIONS:
        return _CONDITIONS[key]
    if date_s == "20260710":                   # 카메라 비교·요인분리 벤치(§10.8~10.11)
        return ("bench-camera", "§10.8~10.11")
    return (None, None)


def _import_logs(con):
    files = sorted(glob.glob(os.path.join(LOGS_DIR, "*_log.csv")))
    counts = {"rawdet": 0, "detection": 0, "perf": 0, "stability": 0}
    skipped = []
    for path in files:
        m = _LOG_RE.match(os.path.basename(path))
        if not m:
            skipped.append(os.path.basename(path))
            continue
        date_s, time_s, source, cond_tag, model, kind = m.groups()
        if cond_tag == _SMOKETEST_COND:        # 장비 점검용 — 측정 데이터가 아니라 DB에 넣지 않는다
            continue
        # 세션 id = 로그 파일명 접두사 = raw 폴더명. 이 등식이 깨지면 manifest 조인이 끊긴다.
        sid = "_".join(x for x in (date_s, time_s, source, cond_tag, model) if x)
        cond, ref = _condition_for(date_s, time_s, cond_tag)
        con.execute(
            "INSERT OR IGNORE INTO sessions"
            " (id, date, time, source, condition, condition_ref, model)"
            " VALUES (?,?,?,?,?,?,?)",
            (sid, f"{date_s[:4]}-{date_s[4:6]}-{date_s[6:]}", time_s, source, cond, ref, model))
        if kind == "confusion":                # 전 세션 0행 — 테이블 없음 (모듈 주석 참조)
            continue
        rows = _read_rows(path)
        if kind == "rawdet":
            # 컬럼: frame,timestamp,source,cls_name,score,x1,y1,x2,y2 — source는 세션으로 정규화
            con.executemany(
                "INSERT INTO rawdet VALUES (?,?,?,?,?,?,?,?,?)",
                [(sid, r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows])
        elif kind == "detection":
            con.executemany(
                "INSERT INTO detections VALUES (?,?,?,?,?,?,?,?,?)",
                [(sid, *r) for r in rows])
        elif kind == "perf":
            con.executemany(
                "INSERT INTO perf VALUES (?,?,?,?,?,?)",
                [(sid, *r) for r in rows])
        elif kind == "stability":
            con.executemany(
                "INSERT INTO stability VALUES (?,?,?,?,?,?,?)",
                [(sid, *r) for r in rows])
        counts[kind] += len(rows)
    return counts, skipped


def _import_manifests(con):
    n = 0
    for mpath in sorted(glob.glob(os.path.join(RAW_DIR, "*", "manifest.json"))):
        sid = os.path.basename(os.path.dirname(mpath))     # raw 폴더명 = 세션 id
        with open(mpath) as f:
            man = json.load(f)
        cur = con.execute(
            "UPDATE sessions SET hef_path=?, conf_high=?, conf_low=?,"
            " lock_exposure=?, exposure=?, note=? WHERE id=?",
            (man.get("hef_path"), man.get("yolo_conf_high"), man.get("yolo_conf_low"),
             int(bool(man.get("lock_exposure"))), man.get("exposure"),
             man.get("note"), sid))
        n += cur.rowcount
    return n


def _import_replays(con):
    runs = dets = 0
    for path in sorted(glob.glob(os.path.join(REPLAY_DIR, "*.csv"))):
        with open(path, newline="") as f:
            first = f.readline()
        if not first.startswith("# meta:"):
            print(f"  ⚠️ meta 줄 없음 — 건너뜀: {os.path.basename(path)}")
            continue
        meta = json.loads(first[len("# meta:"):])
        cur = con.execute(
            "INSERT INTO replay_runs (run_ts, session_id, hef, conf_high, conf_low, degrade)"
            " VALUES (?,?,?,?,?,?)",
            (meta.get("run_ts"), meta.get("session"), meta.get("hef"),
             meta.get("conf_high"), meta.get("conf_low"), meta.get("degrade")))
        run_id = cur.lastrowid
        rows = _read_rows(path, skip_comment=True)
        con.executemany(
            "INSERT INTO replay_dets VALUES (?,?,?,?,?,?,?,?)",
            [(run_id, *r) for r in rows])
        runs += 1
        dets += len(rows)
    return runs, dets


def main():
    ap = argparse.ArgumentParser(description="벤치마크 CSV → SQLite 적재 (전량 재구축)")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"DB 파일 경로 (기본 {DEFAULT_DB})")
    args = ap.parse_args()

    if not os.path.isdir(LOGS_DIR):
        print(f"logs 디렉토리 없음: {LOGS_DIR}")
        sys.exit(1)

    if os.path.exists(args.db):
        os.remove(args.db)
    con = sqlite3.connect(args.db)
    con.executescript(_SCHEMA)

    counts, skipped = _import_logs(con)
    manifests = _import_manifests(con)
    runs, rdets = _import_replays(con)
    con.commit()

    n_sessions = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print(f"[bench.db] {args.db}")
    print(f"  sessions   : {n_sessions} (manifest 반영 {manifests})")
    for k in ("rawdet", "detection", "perf", "stability"):
        print(f"  {k:<11}: {counts[k]:,}행")
    print(f"  replay     : {runs}회 실행 / {rdets:,}검출")
    if skipped:
        print(f"  ⚠️ 패턴 불일치로 건너뜀: {skipped}")
    con.close()


if __name__ == "__main__":
    main()
