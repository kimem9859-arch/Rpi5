"""첫 속도 측정 — 입력 방식 하나로 학습을 1·2·3개 동시에 짧게 돌려 에폭당 시간과 GPU·데스크톱 메모리 최고치를 재고,
동시 개수를 정해 속도.json 에 쓴다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §7 · §9
실행(데스크톱): venv/bin/python speedprobe.py --루트 ~/학습실험 <작업틀.json> [--최대 3]   — 학습.py 속도재기가 띄운다
- 실행기와 같은 잠금(실행기.lock)을 잡는다 — 실험과 섞여 돌지 않게.
- n 개로 올리는 조건 = n 개 모두 정상으로 끝나고 · GPU 최고치가 전체 − 1GB 안 · 처리량(n ÷ 에폭당 시간)이 n−1 개보다 10% 이상.
- 에폭당 시간은 첫 에폭(준비·캐시)을 뺀다. 학습 하나 몫(gpu_mb · ram_mb) = 1개 실행의 최고치 − 시작 전.
"""
import argparse
import fcntl
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner     # noqa: E402
import stoprules  # noqa: E402

GAIN = 1.1


def s_per_epoch(rows):
    t = [r["time"] for r in rows if "time" in r]
    if len(t) >= 3:
        return (t[-1] - t[0]) / (len(t) - 1)
    return t[-1] / len(t) if t else None


def choose_concurrency(meas, gpu_total_mb):
    best = 1
    for n in (2, 3):
        m, p = meas.get(n), meas.get(n - 1)
        if not m or not p or not m["ok"] or not p["ok"]:
            break
        if m["gpu_peak_mb"] > gpu_total_mb - runner.GPU_MARGIN_MB:
            break
        if n / m["s_per_epoch"] < GAIN * (n - 1) / p["s_per_epoch"]:
            break
        best = n
    return best


def measure(root, tmpl, n, py):
    jobs = []
    for k in range(n):
        j = {**tmpl, "id": f"SPEED-{tmpl['입력']}-{n}-{k}"}
        rd = root / "runs" / j["id"]
        if rd.exists():
            shutil.rmtree(rd)
        rd.mkdir(parents=True)
        p = rd / "작업틀.json"
        runner.write_json(p, j)
        jobs.append((j, p, rd))
    g0, ram0 = runner.query_gpu(), runner.mem_available_mb()
    procs = []
    for j, p, rd in jobs:
        with open(rd / "학습.log", "ab") as log:
            procs.append(subprocess.Popen([py, str(HERE / "train_one.py"), str(p)], stdout=log,
                                          stderr=subprocess.STDOUT, start_new_session=True))
    gpu_peak, ram_min, t_end = (g0[1] if g0 else 0), ram0, time.time() + 3600
    while any(pr.poll() is None for pr in procs) and time.time() < t_end:
        g = runner.query_gpu()
        if g:
            gpu_peak = max(gpu_peak, g[1])
        ram_min = min(ram_min, runner.mem_available_mb())
        time.sleep(2)
    for pr in procs:
        if pr.poll() is None:
            os.killpg(pr.pid, signal.SIGKILL)
            pr.wait()
    ok, spe = all(pr.returncode == 0 for pr in procs), []
    for j, p, rd in jobs:
        csv = rd / "results.csv"
        rows = stoprules.csv_rows(csv.read_text(encoding="utf-8")) if csv.exists() else []
        v = s_per_epoch(rows)
        ok = ok and v is not None and len(rows) >= 3
        if v:
            spe.append(v)
    return {"ok": ok, "s_per_epoch": statistics.mean(spe) if spe else None, "gpu_base_mb": g0[1] if g0 else None,
            "gpu_total_mb": g0[2] if g0 else None, "gpu_peak_mb": gpu_peak, "ram_used_mb": ram0 - ram_min,
            "rc": [pr.returncode for pr in procs]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--루트", dest="root", default="~/학습실험")
    ap.add_argument("--최대", dest="max_n", type=int, default=3)
    ap.add_argument("tmpl")
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser()
    lock = open(root / "실행기.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("🔴 실행기가 돈다 — 실험이 없을 때 잰다")
        return 1
    tmpl = json.loads((root / a.tmpl).read_text(encoding="utf-8"))
    mode, meas = tmpl["입력"], {}
    for n in range(1, a.max_n + 1):
        meas[n] = measure(root, tmpl, n, sys.executable)
        print(n, meas[n], flush=True)
        if not meas[n]["ok"]:
            break
    if not meas[1]["ok"]:
        print("🔴 학습 1개도 정상으로 끝나지 않았다 — runs/SPEED-*/학습.log 확인")
        return 1
    total = meas[1]["gpu_total_mb"] or 0
    sp_path = root / "속도.json"
    sp = json.loads(sp_path.read_text(encoding="utf-8")) if sp_path.exists() else {}
    sp[mode] = {"동시": choose_concurrency(meas, total),
                "gpu_mb": meas[1]["gpu_peak_mb"] - (meas[1]["gpu_base_mb"] or 0), "ram_mb": meas[1]["ram_used_mb"],
                "s_per_epoch": {str(n): m["s_per_epoch"] for n, m in meas.items() if m["ok"]},
                "측정": runner.now_iso(), "기록": {str(n): m for n, m in meas.items()}}
    runner.write_json(sp_path, sp)
    print("속도.json", json.dumps(sp[mode], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
