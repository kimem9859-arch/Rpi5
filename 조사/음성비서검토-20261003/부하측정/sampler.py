# 일회용 — 1초마다 코어별 CPU · 역할별 프로세스 CPU · 메모리 · 온도 기록 → CSV + 요약
import json, psutil, subprocess, sys, time
tag, dur, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
ROLES = [("tool_probe", "sop_tool_probe"), ("tool_gui", "tool_worker.py"), ("voice", "voice_assistant.py"), ("fake_glass", "fake_glass.py"),
         ("tts_loop", "tts_loop.py"), ("tool_feed", "tool_feed.py"), ("mock_cam", "mock_cam.py"),
         ("ffmpeg", "ffmpeg"), ("demo", "launch_demo.py")]
def role(p):
    try: cl = " ".join(p.cmdline())
    except Exception: return None
    for r, k in ROLES:
        if k in cl: return r
    return None
def temp():
    try: return float(subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True).stdout.split("=")[1].split("'")[0])
    except Exception: return None
procs = {}
psutil.cpu_percent(percpu=True)
for p in psutil.process_iter(): 
    try: p.cpu_percent()
    except Exception: pass
rows = []; end = time.monotonic() + dur
while time.monotonic() < end:
    time.sleep(1.0)
    cores = psutil.cpu_percent(percpu=True); per = {}
    for p in psutil.process_iter():
        r = role(p)
        if r is None: continue
        try: c = p.cpu_percent()
        except Exception: continue
        per[r] = per.get(r, 0) + c
    m = psutil.virtual_memory()
    rows.append({"t": time.time(), "cores": cores, "total": sum(cores), "max_core": max(cores), "roles": per,
                 "mem_used_gb": (m.total - m.available) / 2**30, "temp": temp()})
thr = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True).stdout.strip()
json.dump({"tag": tag, "rows": rows, "throttled": thr}, open(out, "w"), ensure_ascii=False)
def avg(k): return sum(r[k] for r in rows) / len(rows)
def p95(v): v = sorted(v); return v[int(len(v) * 0.95) - 1]
roles = sorted({k for r in rows for k in r["roles"]})
print(f"== {tag} · {len(rows)}초 · CPU 합계 평균 {avg('total'):.0f}% / 400% · 가장 바쁜 코어 평균 {avg('max_core'):.0f}% (p95 {p95([r['max_core'] for r in rows]):.0f}%) · "
      f"메모리 {avg('mem_used_gb'):.2f}GB · 온도 최고 {max(r['temp'] or 0 for r in rows):.1f}℃ · {thr}")
for k in roles:
    v = [r["roles"].get(k, 0) for r in rows]
    print(f"   {k:12s} 평균 {sum(v)/len(v):6.1f}%  최대 {max(v):6.1f}%  (코어 1개 = 100%)")
