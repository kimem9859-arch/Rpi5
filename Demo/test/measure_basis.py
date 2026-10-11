#!/usr/bin/env python3
"""근거 분석 도구 — 근거 측정 세션에서 장면마다 손 움직임 값을 내고, 표본이 모자란 장면의 판을 알려 준다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §5.3 · 판정 틀 = 상위 2026-10-12-처리흐름-판정기준 D5 · D9
실행: python3 Demo/test/measure_basis.py <세션 폴더>   → 표 · basis.json · 종료 코드 1 = 다시 할 판 있음
값(장면마다 · 들어감 = 손끝 구역이 빈칸 · 다른 구역에서 버튼으로 바뀐 장):
  다가옴 = 들어가기 직전 0.3초 장들의 손끝 속도 중앙값(화면 기준 화소/초)
  안 속도 = 같은 구역에 머무는 동안 손끝 속도 중앙값 · 머묾 = 마지막 안 장 − 들어간 장(초)
  감속 비 = 안 속도 ÷ 다가옴 · 보임 = 들어간 시각 ±0.5초 장 가운데 손끝이 있는 비율
  속도 = 앞 손끝(최대 3장 앞 · 0.25초 안)과의 거리 ÷ 시간 — 10/11 분석(~/lab/판정처리분석-20261011/judge/feat.py tip_feats)과 같은 정의
장면 = 그 판 대본 「안내」 칸 맨 앞 낱말(G1~G7) · 쓸 만한 들어감 = 보임 ≥ 0.7 · 장면마다 5개 미만이면 「다시 할 판」.
🔴 값은 판정 기준을 정할 근거다 — 여기서 기준을 정하지 않는다(판정 기준 계획에서).
"""
import csv
import json
import math
import os
import statistics
import sys

TEST = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(TEST)
sys.path.insert(0, DEMO)

SPEED_BACK_MS = 250.0    # 앞 손끝을 찾는 한도(10/11 정의)
SPEED_BACK_N = 3
APPROACH_MS = 300.0
SEEN_MS = 500.0
USABLE_SEEN = 0.7
MIN_USABLE = 5
DATA_CSV = {"frames.csv", "boxes.csv", "env.csv", "events.csv", "fsm.csv", "guide.csv", "voice_events.csv"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def speeds(frames):
    """장마다 손끝 속도(화소/초) — 손끝이 없거나 앞 손끝이 없으면 None."""
    out = []
    for i, f in enumerate(frames):
        v = None
        if f["tip"] is not None:
            for k in range(i - 1, max(-1, i - 1 - SPEED_BACK_N), -1):
                g = frames[k]
                if g["tip"] is not None and f["t"] - g["t"] <= SPEED_BACK_MS:
                    dt = (f["t"] - g["t"]) / 1000
                    v = math.hypot(f["tip"][0] - g["tip"][0], f["tip"][1] - g["tip"][1]) / dt
                    break
        out.append(v)
    return out


def _med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def entries(frames):
    sp = speeds(frames)
    out = []
    for i, f in enumerate(frames):
        if not f["roi"] or (i > 0 and frames[i - 1]["roi"] == f["roi"]):
            continue
        j = i
        while j + 1 < len(frames) and frames[j + 1]["roi"] == f["roi"]:
            j += 1
        before = [sp[k] for k in range(i) if f["t"] - frames[k]["t"] <= APPROACH_MS]
        inside = sp[i:j + 1]
        win = [g for g in frames if abs(g["t"] - f["t"]) <= SEEN_MS]
        a, b = _med(before), _med(inside)
        out.append({"roi": f["roi"], "i": i, "t": f["t"], "approach": a, "inside": b,
                    "dwell": (frames[j]["t"] - f["t"]) / 1000,
                    "decel": (b / a) if (a and b is not None) else None,
                    "seen": sum(1 for g in win if g["tip"] is not None) / len(win) if win else 0.0})
    return out


def _frames(d):
    out = []
    with open(os.path.join(d, "frames.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            t = _f(r.get("t_recv_ms"))
            if t is None:
                continue
            x, y = _f(r.get("tip_x")), _f(r.get("tip_y"))
            out.append({"t": t, "tip": (x, y) if x is not None and y is not None else None, "roi": r.get("roi") or ""})
    return out


def _events(d):
    out = []
    with open(os.path.join(d, "events.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                data = json.loads(r.get("data") or "{}")
            except ValueError:
                data = {}
            out.append((float(r["t_ms"]), r["kind"], data))
    return out


def script_path(d):
    """세션의 대본 — session.json 「입력.대본」(세기와 같은 출처) · 없으면 데이터 · 녹화 CSV 를 뺀 첫 CSV."""
    try:
        with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
            name = (json.load(f).get("입력") or {}).get("대본") or ""
        if name and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    except (OSError, ValueError):
        pass
    for n in sorted(os.listdir(d)):
        if n.endswith(".csv") and n not in DATA_CSV and not n.startswith("녹화_"):   # 🔑 1인칭 녹화 프레임 CSV 는 대본이 아니다
            return os.path.join(d, n)
    return None


def _script(d):
    import measure_script as MS
    import recipe
    rcp = recipe.load_recipe()
    p = script_path(d)
    if p is None:
        raise SystemExit(f"세션 폴더에 대본이 없다: {d}")
    emo = rcp.get("emo_button") or "EMO"
    return MS.load_script(p, [s["button"] for s in rcp["steps"]], emo), emo


def summarize(d):
    import measure_script as MS
    rows, emo = _script(d)
    scene = {}
    for r in rows:
        w = (r.get("안내") or "").split()
        if w:
            scene.setdefault(int(r["판"]), w[0])
    ev = _events(d)
    import measure_report as MR
    marks = MR.load_marks(os.path.join(d, "guide.csv"))   # 🔑 진행 도우미 N 표시 — 빼지 않으면 뒤 판의 장면이 한 칸씩 밀린다(리뷰 Important 1)
    res = MS.match(ev, rows, marks, emo=emo, auto=MS.has_tokens(rows), final=True)
    frames = _frames(d)
    per = {}
    for run in res["runs"]:
        if run["status"] in ("ng", "extra"):
            continue                                   # NG · 대본 밖 판은 근거에서 뺀다(세기와 같게)
        sc = scene.get(run["script"]) if run["script"] is not None else None
        if sc is None:
            continue
        t1 = run["t1"] if run["t1"] is not None else float("inf")
        ent = entries([f for f in frames if run["t0"] <= f["t"] <= t1])
        p = per.setdefault(sc, {"runs": 0, "scripts": [], "entries": [], "warn": 0})
        p["runs"] += 1
        p["warn"] += run.get("warn", 0)               # 경고(WARNING) 수 — G3 머무름 · G7 대기 중 손이 실제로 있었나
        p["scripts"].append(run["script"])
        p["entries"] += ent
    out = {"장면": {}, "redo": {}}
    for sc, p in sorted(per.items()):
        good = [e for e in p["entries"] if e["seen"] >= USABLE_SEEN]
        out["장면"][sc] = {"runs": p["runs"], "entries": len(p["entries"]), "usable": len(good), "warn": p["warn"],
                         "approach_med": _med([e["approach"] for e in good]),
                         "inside_med": _med([e["inside"] for e in good]),
                         "dwell_med": _med([e["dwell"] for e in good]),
                         "decel_med": _med([e["decel"] for e in good]),
                         "seen_med": _med([e["seen"] for e in p["entries"]])}
        if len(good) < MIN_USABLE:
            out["redo"][sc] = sorted(set(p["scripts"]))
    missing = sorted(set(scene.values()) - set(per))
    for sc in missing:
        out["redo"][sc] = sorted(k for k, v in scene.items() if v == sc)
    return out


def _fmt(v, n=0):
    return "—" if v is None else f"{v:.{n}f}"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    d = argv[0]
    s = summarize(d)
    print("| 장면 | 판 | 들어감(쓸 만함) | 경고 | 다가옴 px/s | 안 속도 px/s | 머묾 초 | 감속 비 | 보임 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for sc, v in s["장면"].items():
        print(f"| {sc} | {v['runs']} | {v['entries']}({v['usable']}) | {v['warn']} | {_fmt(v['approach_med'])} | {_fmt(v['inside_med'])} "
              f"| {_fmt(v['dwell_med'], 2)} | {_fmt(v['decel_med'], 2)} | {_fmt(v['seen_med'], 2)} |")
    if s["redo"]:
        print("⚠️ 다시 할 판(쓸 만한 들어감 < %d): " % MIN_USABLE
              + " · ".join(f"{sc} → 판 {'·'.join(map(str, ps))}" for sc, ps in s["redo"].items())
              + "  — 실행기 「몇 판부터」로 그 판부터(필요한 판까지 하고 ESC)")
    else:
        print("✅ 장면마다 표본 충분")
    with open(os.path.join(d, "basis.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    return 1 if s["redo"] else 0


if __name__ == "__main__":
    sys.exit(main())
