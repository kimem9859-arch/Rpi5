"""정지 장면 NPU·FPS 표 — `python3 npu_정지장면_계산.py` (2026-10-06 실콘솔 현장 작업 · 원자료 = npu_원자료/)."""
import csv, glob, re, statistics as st, os
T = L = os.path.join(os.path.dirname(os.path.abspath(__file__)), "npu_원자료")  # 측정 원자료(모니터·CPU·벤치 출력·perf/tool 로그 사본)
SLUG = {"A": "static-desk-cur", "B": "static-desk-e0b", "C": "static-desk-3npu", "D": "static-desk-3npu-1s"}
NAME = {"A": "현행(console_v2+손)", "B": "재학습 버튼(E0b)+손", "C": "재학습 버튼+손+공구(E0c) 매 프레임", "D": "재학습 버튼+손+공구 1초 간격"}
ansi = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
def perf(c, r):
    p = [x for x in glob.glob(f"{L}/*_esp32_{SLUG[c]}-r{r}_*_perf_log.csv")]
    v = [float(x["fps"]) for x in csv.DictReader(open(p[0])) if x.get("fps")]
    m = k = 0
    for x in v:
        k = k + 1 if x < 15 else 0; m = max(m, k)
    return st.mean(v), min(v), m, sum(x < 15 for x in v) / len(v) * 100
def mon(c, r):
    s = ansi.sub("", open(f"{T}/hmon_{c}-r{r}.txt", errors="ignore").read())
    dev = [float(x) for x in re.findall(r"^\S+:\S+\.\d\s+([\d.]+)\s+HAILO8", s, re.M)]
    mod = {}
    for n, u in re.findall(r"^(button|yolov8n|palm_detection_lite|hand_landmark_lite|tool)\s+([\d.]+)\s+[\d.]+\s+\d+", s, re.M):
        mod.setdefault(n, []).append(float(u))
    return (st.mean(dev) if dev else None), {k: st.mean(v) for k, v in mod.items()}
def cpu(c, r):
    rows = [l.split() for l in open(f"{T}/cpu_{c}-r{r}.txt") if l.strip()]
    cp = [float(x[0]) for x in rows]; tp = [float(re.findall(r"[\d.]+", x[1])[0]) for x in rows if len(x) > 1]
    return st.mean(cp[2:-2] or cp), max(tp) if tp else None
def ms(c, r):
    s = open(f"{T}/bench_{c}-r{r}.txt").read()
    h = re.findall(r"소요\s+평균 ([\d.]+)ms", s)
    return [float(x) for x in h]
print("| 조합 | 회차 | 평균 FPS | 최저 | 15미만 연속 최장 | 15미만 비율 | NPU 장치 % | 버튼 % | 손바닥 % | 공구 % | 파이 CPU % | 파이 최고 온도 | 손·공구 ms |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for c in "ABCD":
    for r in (1, 2, 3):
        try:
            a, mn, lg, pct = perf(c, r); d, md = mon(c, r); cu, tm = cpu(c, r); m = ms(c, r)
            f = lambda x: "—" if x is None else f"{x:.1f}"
            print(f"| {NAME[c]} | r{r} | {a:.1f} | {mn:.1f} | {lg} | {pct:.0f}% | {f(d)} | {f(md.get('button', md.get('yolov8n')))} | {f(md.get('palm_detection_lite'))} | {f(md.get('tool'))} | {cu:.0f} | {f(tm)} | {' · '.join(f'{x:.1f}' for x in m)} |")
        except Exception as e:
            print(f"| {NAME[c]} | r{r} | 오류 {e} |")
