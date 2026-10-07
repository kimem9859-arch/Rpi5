"""측정 기록 관문 검사 — 기록이 실제 시연 로그와 맞는가(측정 도구 정합 §4.3 검증 관문 1단계 ①②③).

실행: python3 test/measure_check.py <세션폴더> --log <시연 로그> [--voice-log <데몬 로그>] [--off-log <기록 끔 회차 시연 로그>]
① 기록 켬/끔 FPS 중앙값 하락 ≤ 3% ② events ↔ 시연 로그(누름 수 · 상태 전이 순서) ③ voice_events ↔ 데몬 로그(알림 재생 · 풀림 수)
🔴 판정 규칙은 계획서(2026-10-07-측정도구-정합-1단계-가-적기 Task 8)에 고정 — 결과를 보고 바꾸지 않는다.
"""
import argparse
import csv
import json
import os
import re
import statistics as st
import sys

_PRESS = re.compile(r"\] \[버튼\] (B\d|EMO) 눌림")
# 상태 전이 줄 = 「[FSM] OLD → NEW」 로 **줄이 끝나는** 것만(safety_console._on_fsm_state · State.value 는
# 대문자와 공백뿐 — 「PROCESS RUN」). 「단계 진행 → …」·「🚫 BLOCK 해제 거부 …」 같은 다른 [FSM] 줄은 안 걸린다.
_STATE = re.compile(r"\] \[FSM\] ([A-Z][A-Z ]*) → ([A-Z][A-Z ]*)$")
_FPS = re.compile(r"\] \[FPS\] ([\d.]+)")


def _norm(s):
    return s.strip().replace(" ", "_")


def load_events(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [(float(r["t_ms"]), r["kind"], json.loads(r["data"] or "{}")) for r in csv.DictReader(f)]


def check_events_vs_log(events, log_lines):
    bad = []
    n_ev = sum(1 for _t, k, _d in events if k == "press")
    n_log = sum(1 for l in log_lines if _PRESS.search(l))
    if n_ev != n_log:
        bad.append(f"누름 수 다름 — 기록 {n_ev} · 로그 {n_log}")
    ev_st = [(d.get("old"), d.get("new")) for _t, k, d in events if k == "state"]
    lg_st = [(_norm(m.group(1)), _norm(m.group(2))) for l in log_lines for m in [_STATE.search(l.rstrip())] if m]
    if ev_st != lg_st:
        bad.append(f"상태 전이 다름 — 기록 {len(ev_st)}개 · 로그 {len(lg_st)}개 · 처음 다른 곳 "
                   f"{next((i for i, (a, b) in enumerate(zip(ev_st, lg_st)) if a != b), min(len(ev_st), len(lg_st)))}")
    return bad


def check_voice_vs_log(voice_events, daemon_lines):
    bad = []
    for kind, needle in (("alert_played", "🔔 알림 →"), ("alert_clear", "알림 상황이 풀렸다")):
        a = sum(1 for _t, k, _d in voice_events if k == kind)
        b = sum(1 for l in daemon_lines if needle in l)
        if a != b:
            bad.append(f"{kind} 수 다름 — 기록 {a} · 로그 {b}")
    return bad


def fps_median(log_lines):
    v = [float(m.group(1)) for l in log_lines for m in [_FPS.search(l)] if m]
    return round(st.median(v), 2) if v else None


def fps_drop_pct(on, off):
    return (off - on) / off * 100 if on is not None and off else None


def _lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--log", required=True)
    ap.add_argument("--voice-log")
    ap.add_argument("--off-log")
    a = ap.parse_args()
    fails = 0
    log = _lines(a.log)
    bad = check_events_vs_log(load_events(os.path.join(a.session, "events.csv")), log)
    print("관문② 사건 ↔ 시연 로그:", "✅" if not bad else "❌ " + " · ".join(bad))
    fails += bool(bad)
    if a.voice_log:
        bad = check_voice_vs_log(load_events(os.path.join(a.session, "voice_events.csv")), _lines(a.voice_log))
        print("관문③ 음성 사건 ↔ 데몬 로그:", "✅" if not bad else "❌ " + " · ".join(bad))
        fails += bool(bad)
    if a.off_log:
        on, off = fps_median(log), fps_median(_lines(a.off_log))
        drop = fps_drop_pct(on, off)
        ok = drop is not None and drop <= 3.0
        print(f"관문① FPS 중앙값 켬 {on} · 끔 {off} · 하락 {drop if drop is None else round(drop, 2)}% →", "✅" if ok else "❌")
        fails += not ok
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
