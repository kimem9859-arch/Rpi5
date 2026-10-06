"""장소2 손·공구 장면 NPU·FPS 표 — `python3 npu_장소2_계산.py` (2026-10-06 실콘솔 Task 2-2 · 원자료 = npu_원자료_장소2/).
계산 방식은 npu_정지장면_계산.py 와 같다(perf_log fps · hailortcli monitor · psutil CPU · vcgencmd 온도 · tool_log ≥0.65)."""
import csv, glob, re, statistics as st, os
from collections import Counter
L = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npu_원자료_장소2")
RUNS = ["D-S2-r1", "D-S2-r2", "B-S2-r1", "C-S2-r1", "D-S6-r1", "D-S7-r1", "D-S7-r2"]
NAME = {"B": "재학습 버튼+손", "C": "+공구 매 프레임", "D": "+공구 1초 간격"}
SCENE = {"S2": "손 좌우", "S6": "B1→B4 누르기", "S7": "공구 들기"}
ansi = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
def perf(t):
    p = glob.glob(f"{L}/*_place2-{t.lower()}_*_perf_log.csv")[0]
    v = [float(x["fps"]) for x in csv.DictReader(open(p)) if x.get("fps")]
    m = k = 0
    for x in v:
        k = k + 1 if x < 15 else 0; m = max(m, k)
    return st.mean(v), min(v), m, sum(x < 15 for x in v) / len(v) * 100
def mon(t):
    s = ansi.sub("", open(f"{L}/hmon_{t}.txt", errors="ignore").read())
    dev = [float(x) for x in re.findall(r"^\S+:\S+\.\d\s+([\d.]+)\s+HAILO8", s, re.M)]
    mod = {}
    for n, u in re.findall(r"^(button|palm_detection_lite|hand_landmark_lite|tool)\s+([\d.]+)\s+[\d.]+\s+\d+", s, re.M):
        mod.setdefault(n, []).append(float(u))
    return (st.mean(dev) if dev else None), {k: st.mean(v) for k, v in mod.items()}
def cpu(t):
    rows = [l.split() for l in open(f"{L}/cpu_{t}.txt") if l.strip()]
    cp = [float(x[0]) for x in rows]; tp = [float(re.findall(r"[\d.]+", x[1])[0]) for x in rows if len(x) > 1]
    return st.mean(cp[2:-2] or cp), max(tp) if tp else None
def tool(t):
    p = glob.glob(f"{L}/*_place2-{t.lower()}_*_tool_log.csv")
    if not p: return None
    rows = list(csv.DictReader(open(p[0])))
    det = [r for r in rows if r["cls_name"] and float(r["score"] or 0) >= 0.65]
    return len({r["frame"] for r in rows}), len({r["frame"] for r in det}), dict(Counter(r["cls_name"] for r in det))
f = lambda x, d=0: "—" if x is None else f"{x:.{d}f}"
print("| 조합 | 장면 | 회차 | 평균 FPS | 최저 | 15미만 연속 최장 | 15미만 비율 | NPU 장치 % | 버튼 % | 손바닥 % | 손가락 % | 공구 % | 파이 CPU % | 최고 온도 | 공구 실행 · ≥0.65 프레임 · 종류 |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for t in RUNS + ["D-video-r1", "D-video-r2"]:
    c, s, r = t.split("-")
    a, lo, m, pct = perf(t)
    if t.startswith("D-video"):
        tl = tool(t) or ("—", "—", "—")
        print(f"| D {NAME['D']} | 눈 확인 영상(판정 안 씀) | {r} | {a:.1f} | {lo:.1f} | {m} | {pct:.0f}% | — | — | — | — | — | — | — | {tl[0]} · {tl[1]} · {tl[2]} |")
        continue
    dv, md = mon(t); cu, tp = cpu(t); tl = tool(t)
    print(f"| {c} {NAME[c]} | {s} {SCENE[s]} | {r} | {a:.1f} | {lo:.1f} | {m} | {pct:.0f}% | {f(dv)} | {f(md.get('button'))} | {f(md.get('palm_detection_lite'))} | {f(md.get('hand_landmark_lite'))} | {f(md.get('tool'))} | {cu:.0f} | {f(tp,1)} | {'—' if tl is None else f'{tl[0]} · {tl[1]} · {tl[2]}'} |")
