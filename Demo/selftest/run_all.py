"""자가 테스트 일괄 러너 — selftest/test_*.py 를 하나씩 따로 실행해 통과·실패·건너뜀을 판정한다.

실행: python3 Demo/selftest/run_all.py        (어디서 불러도 Demo/ 안에서 돌린다)
출력: 파일마다 한 줄 + 마지막 줄 `SELFTEST N pass / N fail / N skip (T s)`
종료 코드: 실패가 하나라도 있으면 1 · 없으면 0(건너뜀은 실패가 아니다)

판정 규칙의 근거 = 상위 docs/claude-code-작업로그.md 2026-09-22 블록(일괄 실행 실측):
  🔴 pytest 로 모으지 않는다 — 이 폴더의 시험은 실패를 예외로 터뜨리지 않고 **세기만** 해서
     pytest 가 실패를 「passed」로 보고한 적이 있다. 파일을 프로세스로 하나씩 돌려 결과를 읽는다.
  🔴 종료 코드와 마지막 줄을 **둘 다** 본다 — 「✅ 통과」를 찍고 종료 중에 크래시(139)한 시험이 있었다.
  🔴 건너뜀은 **전용 파이썬이 없을 때만**이다 — 모듈을 못 찾는 오류를 건너뜀으로 치면
     우리 코드의 이름이 바뀌어 나는 진짜 오류까지 숨는다.
"""
import glob
import os
import re
import subprocess
import sys
import time

_SELFTEST_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_DIR = os.path.dirname(_SELFTEST_DIR)
TIMEOUT_SEC = 180          # 가장 긴 test_console_flow 가 약 17초(2026-09-26 실측)
# 전용 파이썬이 필요한 시험 — 없으면 건너뛴다(run_voice.sh 와 같은 환경)
INTERPRETERS = {"test_voice_tts.py": os.path.expanduser("~/env/tts/.venv/bin/python")}

_PASS_LINE = (re.compile(r"^✅.*통과"), re.compile(r"^ALL OK$"))
_COUNT_LINE = re.compile(r"^(\d+)/(\d+) passed$")


def judge(returncode, stdout, timed_out=False):
    """(상태, 사유) — 상태는 'pass' 또는 'fail'. 통과 = 종료 코드 0 그리고 마지막 줄이 통과 형식."""
    if timed_out:
        return "fail", "시간 초과"
    if returncode != 0:
        return "fail", f"종료 코드 {returncode}"
    lines = [l.strip() for l in stdout.splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    m = _COUNT_LINE.match(last)
    if m:
        return ("pass", "") if m.group(1) == m.group(2) else ("fail", f"일부 실패 — {last}")
    if any(p.match(last) for p in _PASS_LINE):
        return "pass", ""
    return "fail", "통과 줄 없음" + (f" — 마지막 줄 {last!r}" if last else " — 출력 없음")


def _details(stdout, stderr, limit=8):
    """실패를 설명할 줄 — ❌ 줄이 있으면 그것, 없으면 출력 끝부분(예외 추적 등)."""
    marked = [l.rstrip() for l in stdout.splitlines() if "❌" in l]
    if marked:
        return marked[:limit]
    tail = [l.rstrip() for l in (stdout + "\n" + stderr).splitlines() if l.strip()]
    return tail[-limit:]


def run_one(path, python, cwd, timeout):
    name = os.path.splitext(os.path.basename(path))[0]
    if not os.path.exists(python):
        return {"name": name, "status": "skip", "reason": f"전용 파이썬 없음 — {python}",
                "secs": None, "details": []}
    # 화면 없이 그린다(사용자 환경의 QT 설정을 따라 창이 뜨지 않게) · 크래시해도 앞 출력이 남게 즉시 쓴다
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUNBUFFERED="1")
    t0 = time.monotonic()
    try:
        p = subprocess.run([python, path], cwd=cwd, env=env, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        rc, out, err, timed_out = p.returncode, p.stdout, p.stderr, False
    except subprocess.TimeoutExpired as e:
        rc, timed_out = None, True
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
    secs = time.monotonic() - t0
    status, reason = judge(rc, out, timed_out)
    if timed_out:
        reason = f"시간 초과 {timeout}s"
    return {"name": name, "status": status, "reason": reason, "secs": secs,
            "details": _details(out, err) if status == "fail" else []}


def run_suite(test_dir, cwd=DEMO_DIR, timeout=TIMEOUT_SEC, interpreters=None, out=print):
    """test_dir 의 test_*.py 를 이름 순으로 **하나씩** 돌린다(Hailo 장치가 하나라 동시에 돌리지 않는다).

    돌려주는 값 = (개수 {pass·fail·skip}, 파일별 결과, 종료 코드)
    """
    interpreters = INTERPRETERS if interpreters is None else interpreters
    counts = {"pass": 0, "fail": 0, "skip": 0}
    results = []
    t0 = time.monotonic()
    for path in sorted(glob.glob(os.path.join(test_dir, "test_*.py"))):
        python = interpreters.get(os.path.basename(path), sys.executable)
        r = run_one(path, python, cwd, timeout)
        results.append(r)
        counts[r["status"]] += 1
        mark = {"pass": "✅", "fail": "❌", "skip": "⏭"}[r["status"]]
        secs = f"{r['secs']:5.1f}s" if r["secs"] is not None else "    —"
        out(f"{mark} {r['name']:<24} {secs}" + (f"  — {r['reason']}" if r["reason"] else ""))
        for line in r["details"]:
            out(f"      {line}")
    code = 1 if counts["fail"] else 0
    out(f"SELFTEST {counts['pass']} pass / {counts['fail']} fail / {counts['skip']} skip "
        f"({time.monotonic() - t0:.1f}s)")
    return counts, results, code


def main():
    _, _, code = run_suite(_SELFTEST_DIR, out=lambda s: print(s, flush=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
