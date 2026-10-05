"""데스크톱 메모리 감시 — WSL 이 스왑으로 넘어가기 전에 HEF 변환을 멈춘다.

계기: 2026-10-05 01:04 U1 변환(수준 1 편향 보정 · 임시 파일 6.5GB)에서 WSL 이 멈춰 데스크톱을 재부팅했다.
      ⚠️ 그 멈춤의 원인은 뒤에 Windows C: 가득 참으로 규명됐다(메모리가 아님 · WSL 디스크를 D: 로 옮겨 해결 · 통합문서 §14.2).
      이 감시는 그 뒤에도 스왑 넘침을 막는 장치로 남는다.
사용자 「WSL 메모리 스왑 오버되지 않게 메모리 감시 붙여주고」.
- 멈춤 조건 = 사용 가능 메모리 < --최소가용(MB) 또는 스왑 사용 > --최대스왑(MB).
- 멈출 대상 = 변환 프로세스만(우리 hef_convert.py · Model Zoo hailomz compile · ultralytics ul.py) — 감시 자신 · 학습 · 띄우는 셸 · 파일을 여는 명령은 아니다.
  🔴 이름으로 찾아 끄는 pkill -f 는 쓰지 않는다(제 셸을 죽인 함정) — /proc 의 명령줄을 정해진 꼴로만 맞춘다.
- 멈추면 SIGTERM → 10초 뒤 남았으면 SIGKILL · 이유와 대상을 로그에 남긴다. 학습은 실행기가 띄우기 전에 메모리를 따로 본다.
실행(데스크톱 · 시스템 python3): cd ~/학습실험 && ( setsid nohup python3 memguard.py >> memguard.log 2>&1 < /dev/null & )
"""
import argparse
import hashlib
import os
import re
import signal
import sys
import time
from pathlib import Path

TARGET_RES = (
    re.compile(r"^\S*python\S* \S*/hef_convert\.py (onnx|hef) "),
    re.compile(r"^\S*python\S* \S*/hailomz compile "),
    re.compile(r"^\S*python\S* (\S*/)?ul\.py$"),
)


def parse(text):
    kb = {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+) kB", text, re.M)}
    return {"avail_mb": kb["MemAvailable"] // 1024, "swap_used_mb": (kb["SwapTotal"] - kb["SwapFree"]) // 1024}


def reason(m, min_avail_mb, max_swap_mb):
    if m["avail_mb"] < min_avail_mb:
        return f"사용 가능 {m['avail_mb']}MB < {min_avail_mb}MB"
    if m["swap_used_mb"] > max_swap_mb:
        return f"스왑 사용 {m['swap_used_mb']}MB > {max_swap_mb}MB"
    return None


def is_target(cmdline):
    return any(r.search(cmdline) for r in TARGET_RES)


def targets():
    me, out = os.getpid(), []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if is_target(cmd):
            out.append((int(p.name), cmd))
    return out


def cmdline_of(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return None


def kill_if_same(pid, cmd):
    """SIGKILL 직전 명령줄을 다시 대조한다 — 그사이 끝났거나 PID 가 다른 프로세스로 바뀌었으면 건드리지 않는다(1-2 최종 리뷰 m3)."""
    if cmdline_of(pid) != cmd:
        return False
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except OSError:
        return False


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop(procs):
    for pid, _ in procs:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(10)
    for pid, cmd in procs:
        if _alive(pid):
            kill_if_same(pid, cmd)


def main(argv=None):
    ap = argparse.ArgumentParser(description="데스크톱 메모리 감시 — 스왑 전에 변환을 멈춘다")
    ap.add_argument("--최소가용", type=int, default=1500)
    ap.add_argument("--최대스왑", type=int, default=256)
    ap.add_argument("--간격", type=float, default=5)
    a = ap.parse_args(argv)
    say = lambda s: print(time.strftime("%Y-%m-%d %H:%M:%S"), s, flush=True)
    me = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]   # 손으로 복사해 띄우므로 어느 판인지 남긴다
    say(f"시작 pid {os.getpid()} · 파일 {me} · 사용 가능 < {a.최소가용}MB 또는 스왑 > {a.최대스왑}MB 이면 변환을 멈춘다")
    last = 0.0
    while True:
        m = parse(Path("/proc/meminfo").read_text())
        why = reason(m, a.최소가용, a.최대스왑)
        procs = targets() if why else []
        if why and procs:
            say(f"🔴 멈춤 — {why} · 대상 " + " ; ".join(f"{pid} {cmd[:120]}" for pid, cmd in procs))
            stop(procs)
            say("멈춤 끝")
        elif time.time() - last > 300:
            say(f"살아 있음 · 사용 가능 {m['avail_mb']}MB · 스왑 {m['swap_used_mb']}MB · 변환 {len(targets())}개")
            last = time.time()
        time.sleep(a.간격)


if __name__ == "__main__":
    sys.exit(main())
