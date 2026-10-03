"""학습 실행기 — 대기열의 실험을 차례로(입력 방식별 동시 개수까지 · 최대 3) 돌리고, 간격마다 진행·시간·자원을 보고 멈춤 조건을 지킨다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §7
실행(데스크톱): venv/bin/python runner.py --루트 ~/학습실험 [--간격 30]   — 걸기·재개가 setsid 로 띄운다(SSH·Claude 세션과 무관)
- 하나만 뜬다(실행기.lock). 대기열이 비거나 멈췄고 도는 학습이 없으면 끝난다.
- 폴더: 대기열/(이름 순서) → 도는중/ → 끝/ · runs/<id>/(train_one 이 쓴다) · 대기열멈춤(이유 한 줄) · 상태.json · 속도.json
- 이상 종료(진행없음 · 시간초과 · 오류 · 점수0 · 끊김)면 대기열멈춤을 쓰고 새 학습을 띄우지 않는다 — 도는 학습은 끝까지 둔다.
- 하나 더 띄우는 조건 = 동시 개수 한도 안 · 도는 학습이 모두 첫 에폭을 마침 · GPU·데스크톱 메모리 여유(속도표의 학습 하나 몫 + 여유).
표준 라이브러리만 쓴다.
"""
import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import stoprules  # noqa: E402

NVIDIA_SMI = os.environ.get("TRAIN_NVIDIA_SMI", "/usr/lib/wsl/lib/nvidia-smi")
GPU_MARGIN_MB = 1024
RAM_MARGIN_MB = 2048
EXIT_ABNORMAL = 3


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def query_gpu():
    """→ (사용률 %, 사용 MB, 전체 MB) · 못 읽으면 None."""
    try:
        r = subprocess.run([NVIDIA_SMI, "--query-gpu=utilization.gpu,memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20)
        u, used, total = (int(float(x)) for x in r.stdout.strip().splitlines()[0].split(","))
        return u, used, total
    except Exception:
        return None


def mem_available_mb():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 0


def write_json(p, d):
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def concurrency(mode, speed):
    return max(1, min(3, int(speed.get(mode, {}).get("동시", 1))))


def can_start(mode, running, speed, gpu, ram_free_mb):
    """running = [(입력 방식, 끝난 에폭 수)] → (띄워도 되나, 기다리는 이유)."""
    limit = min(concurrency(m, speed) for m in [m for m, _ in running] + [mode])
    if len(running) >= limit:
        return False, f"동시 {limit}개 한도"
    if not running:
        return True, ""
    if any(ep < 1 for _, ep in running):
        return False, "앞 학습이 첫 에폭 전(메모리가 아직 오르는 중)"
    need = speed.get(mode, {})
    if gpu is None or "gpu_mb" not in need or "ram_mb" not in need:
        return False, "GPU·메모리 측정값 없음"
    free = gpu[2] - gpu[1]
    if free < need["gpu_mb"] + GPU_MARGIN_MB:
        return False, f"GPU 메모리 여유 {free}MB"
    if ram_free_mb < need["ram_mb"] + RAM_MARGIN_MB:
        return False, f"데스크톱 메모리 여유 {ram_free_mb}MB"
    return True, ""


class Run:
    def __init__(self, path, job, proc, now):
        self.path, self.job, self.proc = path, job, proc
        self.started = self.last_progress = now
        self.epochs = 0
        self.last = {}


def run_dir(root, job):
    return Path(root) / "runs" / job["id"]


def set_stop(root, reason):
    p = Path(root) / "대기열멈춤"
    if not p.exists():
        p.write_text(f"{now_iso()} {reason}\n", encoding="utf-8")


def start(root, path, py, now):
    job = json.loads(path.read_text(encoding="utf-8"))
    rd = run_dir(root, job)
    rd.mkdir(parents=True, exist_ok=True)
    dst = Path(root) / "도는중" / path.name
    os.replace(path, dst)
    cmd = job.get("명령") or [py, str(Path(job["코드"]).expanduser() / "train_one.py")]   # 「명령」 = 시험용 가짜 학습
    with open(rd / "학습.log", "ab") as log:
        proc = subprocess.Popen([*cmd, str(dst)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (rd / "pid").write_text(str(proc.pid))
    return Run(dst, job, proc, now)


def kill(run):
    try:
        os.killpg(run.proc.pid, signal.SIGTERM)
        run.proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(run.proc.pid, signal.SIGKILL)
        run.proc.wait(timeout=30)
    except ProcessLookupError:
        pass


def finish(root, run, now, reason=None, rc=None):
    """학습이 끝났거나(rc) 실행기가 껐다(reason). 이상이면 대기열을 멈춘다. 학습이 요약을 못 썼으면 실행기가 쓴다."""
    rd = run_dir(root, run.job)
    sp = rd / "요약.json"
    if reason is None and rc not in (0, None):
        reason = "점수0" if rc == EXIT_ABNORMAL else f"오류(rc={rc})"
    if reason is not None:
        summ = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        if rc != EXIT_ABNORMAL or not summ:
            summ.update({"id": run.job["id"], "group": run.job["group"], "입력": run.job["입력"],
                         "바꾼것": run.job.get("바꾼것", ""), "종료이유": reason, "이상": True,
                         "에폭": run.epochs, "분": round((now - run.started) / 60, 1)})
            write_json(sp, summ)
        set_stop(root, f"{reason}: {run.job['id']}")
    os.replace(run.path, Path(root) / "끝" / run.path.name)


def recover_orphans(root):
    """도는중/ 에 남은 작업 = 실행기가 학습 도중 죽었다(데스크톱·WSL 꺼짐 등) → 남은 학습을 끄고 「끊김」 · 대기열 멈춤."""
    for p in sorted((Path(root) / "도는중").glob("*.json")):
        job = json.loads(p.read_text(encoding="utf-8"))
        rd = run_dir(root, job)
        rd.mkdir(parents=True, exist_ok=True)
        try:
            os.killpg(int((rd / "pid").read_text()), signal.SIGTERM)
        except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
            pass
        sp = rd / "요약.json"
        summ = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        summ.update({"id": job["id"], "group": job["group"], "입력": job["입력"], "바꾼것": job.get("바꾼것", ""),
                     "종료이유": "끊김", "이상": True})
        write_json(sp, summ)
        set_stop(root, f"끊김: {job['id']} — 학습 도중 실행기가 멈췄다(데스크톱·WSL 꺼짐?) · 이어서/건너뛰기를 정한다")
        os.replace(p, Path(root) / "끝" / p.name)


def tick(root, runs, speed, gpu, ram_free, py, now):
    """한 번 둘러보기 — 끝난 것 정리 · 진행없음/시간초과 끄기 · 하나 띄우기. 반환 = 기다리는 이유(없으면 None)."""
    for r in list(runs):
        csv = run_dir(root, r.job) / "results.csv"
        if csv.exists():
            rows = stoprules.csv_rows(csv.read_text(encoding="utf-8", errors="replace"))
            if len(rows) > r.epochs:
                r.epochs, r.last_progress, r.last = len(rows), now, rows[-1]
        rc, st = r.proc.poll(), r.job["멈춤"]
        if rc is not None:
            finish(root, r, now, rc=rc)
        elif stoprules.stalled(r.last_progress, now, st["진행없음_분"]):
            kill(r)
            finish(root, r, now, reason="진행없음")
        elif stoprules.over_time(r.started, now, r.job.get("시간상한_s")):
            kill(r)
            finish(root, r, now, reason="시간초과")
        else:
            continue
        runs.remove(r)
    if (Path(root) / "대기열멈춤").exists():
        return "대기열 멈춤"
    queue = sorted((Path(root) / "대기열").glob("*.json"))
    if not queue:
        return None
    mode = json.loads(queue[0].read_text(encoding="utf-8"))["입력"]
    ok, why = can_start(mode, [(r.job["입력"], r.epochs) for r in runs], speed, gpu, ram_free)
    if ok:
        runs.append(start(root, queue[0], py, now))
        return None
    return why


def status(root, runs, gpu, why, now, done=False):
    root = Path(root)
    items = []
    for r in runs:
        mx = (r.job.get("train_kwargs") or {}).get("epochs")
        el = now - r.started
        left = el / r.epochs * (mx - r.epochs) if r.epochs and mx else None
        items.append({"id": r.job["id"], "입력": r.job["입력"], "pid": r.proc.pid, "에폭": r.epochs, "최대": mx,
                      "경과분": round(el / 60, 1), "남은분어림": round(left / 60, 1) if left is not None else None,
                      "최근": {k: r.last.get(k) for k in ("train/box_loss", "train/cls_loss", "metrics/mAP50(B)", stoprules.FIT)}})
    stop = root / "대기열멈춤"
    write_json(root / "상태.json", {
        "시각": now_iso(), "실행기pid": os.getpid(), "도는중": items,
        "대기": [p.name.split("_", 1)[1][:-5] for p in sorted((root / "대기열").glob("*.json"))],
        "기다리는이유": why, "멈춤": stop.read_text(encoding="utf-8").strip() if stop.exists() else None,
        "gpu": None if gpu is None else {"사용률": gpu[0], "used_mb": gpu[1], "total_mb": gpu[2]},
        "끝남": len(list((root / "끝").glob("*.json"))), "끝": done})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--루트", dest="root", default="~/학습실험")
    ap.add_argument("--간격", dest="interval", type=float, default=30.0)
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser()
    for d in ("대기열", "도는중", "끝", "runs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    lock = open(root / "실행기.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("실행기가 이미 돈다 — 그대로 둔다")
        return 0
    recover_orphans(root)
    runs, py = [], sys.executable
    while True:
        now = time.time()
        sp = root / "속도.json"
        speed = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        gpu = query_gpu()
        why = tick(root, runs, speed, gpu, mem_available_mb(), py, now)
        idle = not runs and ((root / "대기열멈춤").exists() or not any((root / "대기열").glob("*.json")))
        status(root, runs, gpu, why, now, done=idle)
        if idle:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
