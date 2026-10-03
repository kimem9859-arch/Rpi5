"""학습 실행기(학습/runner.py)를 가짜 학습으로 고정한다 — 정상 · 진행없음 · 시간초과 · 점수0 · 오류 · 동시 2개 · 짝 이상 종료 · 잠금 · 끊김 복구 · 데스크톱 메모리 여유.

실행: python3 Demo/selftest/test_train_runner.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §7
⚠️ GPU·Windows 가 필요 없다 — nvidia-smi(TRAIN_NVIDIA_SMI) · 데스크톱 메모리(TRAIN_WIN_PROBE)는 가짜. 약 30초.
"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER = os.path.join(_RPI5, "학습", "runner.py")

FAKE = r'''
import json, sys, time
from pathlib import Path
job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rd = Path(job["루트"]) / "runs" / job["id"]; rd.mkdir(parents=True, exist_ok=True)
(rd / "시작").write_text(str(time.time()))
def row(i):
    with open(rd / "results.csv", "a") as f:
        if i == 1: f.write("epoch,time,train/box_loss,metrics/mAP50(B),metrics/mAP50-95(B)\n")
        f.write(f"{i},{i * 0.1},1.0,0.5,0.3\n")
def summ(reason, bad):
    (rd / "요약.json").write_text(json.dumps({"id": job["id"], "group": job["group"], "입력": job["입력"], "바꾼것": "", "종료이유": reason, "이상": bad}, ensure_ascii=False))
m = job["가짜"]
if m == "normal":
    for i in range(1, 4): row(i); time.sleep(0.15)
    summ("최대에폭", False); sys.exit(0)
if m == "slow_ok":
    for i in range(1, 7): row(i); time.sleep(0.4)
    (rd / "끝").write_text(str(time.time())); summ("최대에폭", False); sys.exit(0)
if m == "hang":
    row(1); time.sleep(120)
if m == "slow":
    for i in range(1, 900): row(i); time.sleep(0.1)
if m == "zero":
    row(1); summ("점수0", True); sys.exit(3)
if m == "crash":
    row(1); sys.exit(1)
if m == "crash_late":
    row(1); time.sleep(0.8); sys.exit(1)
'''

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _setup(t):
    root = Path(t) / "루트"
    (root / "대기열").mkdir(parents=True)
    fake = Path(t) / "fake_train.py"
    fake.write_text(FAKE, encoding="utf-8")
    smi = Path(t) / "nvidia-smi"
    smi.write_text("#!/bin/sh\necho '5, 1000, 8000'\n")
    smi.chmod(0o755)
    for name, body in (("win_ok", "echo 30000"), ("win_low", "echo 8000"), ("win_fail", "exit 1")):
        w = Path(t) / name
        w.write_text(f"#!/bin/sh\n{body}\n")
        w.chmod(0o755)
    return root, fake, smi


def _job(root, fake, i, jid, mode, stall=0.5, limit=None):
    job = {"id": jid, "group": "button", "입력": "늘리기640", "바꾼것": "", "루트": str(root), "가짜": mode,
           "멈춤": {"진행없음_분": stall, "포화_에폭": 30, "포화_향상": 0.005, "점수0_에폭": 10, "점수0_mAP50": 0.05, "시간상한_배": 2},
           "시간상한_s": limit, "train_kwargs": {"epochs": 3}, "명령": [sys.executable, str(fake)]}
    (root / "대기열" / f"20261004-000000-{i:02d}_{jid}.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def _env(root, smi=None, win="win_ok"):
    env = dict(os.environ)
    if smi:
        env["TRAIN_NVIDIA_SMI"] = str(smi)
    env["TRAIN_WIN_PROBE"] = str(Path(root).parent / win)
    return env


def _run(root, smi=None, timeout=60, win="win_ok"):
    env = _env(root, smi, win)
    return subprocess.run([sys.executable, RUNNER, "--루트", str(root), "--간격", "0.2"],
                          capture_output=True, text=True, timeout=timeout, env=env)


def _summ(root, jid):
    return json.loads((root / "runs" / jid / "요약.json").read_text(encoding="utf-8"))


def _stop(root):
    p = root / "대기열멈춤"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_정상():
    print("[1] 정상 2개 — 차례로 끝 · 멈춤 없음 · 상태 끝")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-a", "normal")
        _job(root, fake, 1, "E0-button-b", "normal")
        r = _run(root)
        check(r.returncode == 0, f"실행기 종료 0 — {r.returncode} {r.stderr[-200:]}")
        check(len(list((root / "끝").glob("*.json"))) == 2 and not _stop(root), "끝 2 · 멈춤 없음")
        st = json.loads((root / "상태.json").read_text(encoding="utf-8"))
        check(st["끝"] and st["대기"] == [] and st["끝남"] == 2, "상태 = 끝 · 대기 0 · 끝남 2")


def test_진행없음():
    print("[2] 진행 없음 — 끄고 대기열 멈춤 · 뒤 실험은 안 뜬다")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-h", "hang", stall=0.02)
        _job(root, fake, 1, "E0-button-n", "normal")
        _run(root)
        s = _summ(root, "E0-button-h")
        check(s["종료이유"] == "진행없음" and s["이상"], f"요약 = 진행없음 · 이상 — {s}")
        check("진행없음: E0-button-h" in _stop(root), "대기열멈춤 = 진행없음")
        check(len(list((root / "대기열").glob("*E0-button-n.json"))) == 1 and not (root / "runs" / "E0-button-n").exists(), "뒤 실험은 대기열에 그대로")


def test_시간초과():
    print("[3] 시간 상한 — 진행 중이어도 끈다")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-s", "slow", limit=1.0)
        _run(root)
        check(_summ(root, "E0-button-s")["종료이유"] == "시간초과" and "시간초과" in _stop(root), "시간초과 · 멈춤")


def test_점수0과_오류():
    print("[4] 점수0(종료 코드 3) · 오류(종료 코드 1)")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-z", "zero")
        _run(root)
        check(_summ(root, "E0-button-z")["종료이유"] == "점수0" and "점수0: E0-button-z" in _stop(root), "점수0 — 학습이 쓴 요약 유지 · 멈춤")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-c", "crash")
        _run(root)
        s = _summ(root, "E0-button-c")
        check(s["종료이유"] == "오류(rc=1)" and s["이상"] and "오류(rc=1)" in _stop(root), f"오류 — 실행기가 요약을 쓴다 — {s}")


def test_동시_2개():
    print("[5] 동시 2개 — 속도표 동시 2 · 앞 학습 첫 에폭 뒤 둘째가 뜬다")
    with tempfile.TemporaryDirectory() as t:
        root, fake, smi = _setup(t)
        (root / "속도.json").write_text(json.dumps({"늘리기640": {"동시": 2, "gpu_mb": 100, "ram_mb": 100}}), encoding="utf-8")
        _job(root, fake, 0, "E0-button-p", "slow_ok")
        _job(root, fake, 1, "E0-button-q", "slow_ok")
        _run(root, smi)
        rd = root / "runs"
        s2, e1 = float((rd / "E0-button-q" / "시작").read_text()), float((rd / "E0-button-p" / "끝").read_text())
        check(s2 < e1, "둘째가 첫째 끝나기 전에 시작(겹침)")


def test_짝_이상_종료():
    print("[6] 동시 중 하나가 오류 — 짝은 끝까지 · 새 실험은 안 뜬다")
    with tempfile.TemporaryDirectory() as t:
        root, fake, smi = _setup(t)
        (root / "속도.json").write_text(json.dumps({"늘리기640": {"동시": 2, "gpu_mb": 100, "ram_mb": 100}}), encoding="utf-8")
        _job(root, fake, 0, "E0-button-p", "slow_ok")
        _job(root, fake, 1, "E0-button-x", "crash_late")
        _job(root, fake, 2, "E0-button-n", "normal")
        _run(root, smi)
        check(_summ(root, "E0-button-p")["종료이유"] == "최대에폭" and (root / "runs" / "E0-button-p" / "끝").exists(), "짝은 정상으로 끝까지")
        check("E0-button-x" in _stop(root) and not (root / "runs" / "E0-button-n").exists(), "멈춤 · 셋째는 안 뜸")


def test_속도표_없으면_1개():
    print("[7] 속도표가 없으면 동시 1개")
    with tempfile.TemporaryDirectory() as t:
        root, fake, smi = _setup(t)
        _job(root, fake, 0, "E0-button-p", "slow_ok")
        _job(root, fake, 1, "E0-button-q", "slow_ok")
        _run(root, smi)
        rd = root / "runs"
        check(float((rd / "E0-button-q" / "시작").read_text()) >= float((rd / "E0-button-p" / "끝").read_text()), "겹치지 않음")


def test_잠금():
    print("[8] 실행기가 이미 돌면 둘째는 바로 끝난다")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-a", "normal")
        lk = open(root / "실행기.lock", "w")
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        t0 = time.time()
        r = _run(root, timeout=20)
        check(r.returncode == 0 and "이미 돈다" in r.stdout and time.time() - t0 < 10, "「이미 돈다」 · 바로 끝")
        check(len(list((root / "대기열").glob("*.json"))) == 1, "대기열은 그대로")
        lk.close()


def test_끊김_복구():
    print("[9] 도는중에 남은 작업(실행기·WSL 이 죽었다) — 끊김 기록 · 멈춤")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        (root / "도는중").mkdir()
        job = {"id": "E0-button-o", "group": "button", "입력": "늘리기640", "바꾼것": "", "루트": str(root)}
        (root / "도는중" / "20261004-000000-00_E0-button-o.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        (root / "runs" / "E0-button-o").mkdir(parents=True)
        (root / "runs" / "E0-button-o" / "pid").write_text("999999")
        _run(root)
        check(_summ(root, "E0-button-o")["종료이유"] == "끊김" and "끊김: E0-button-o" in _stop(root), "끊김 · 멈춤")
        check(len(list((root / "끝").glob("*E0-button-o.json"))) == 1, "끝으로 옮김")


def _wait_status(root, win):
    """실행기를 띄워 2초 뒤 상태를 읽고 끈다 — 메모리가 모자라면 끝나지 않고 기다리기 때문."""
    pr = subprocess.Popen([sys.executable, RUNNER, "--루트", str(root), "--간격", "0.2"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_env(root, None, win))
    time.sleep(2.5)
    st = json.loads((root / "상태.json").read_text(encoding="utf-8"))
    pr.terminate()
    pr.wait(timeout=10)
    return st


def test_데스크톱_메모리_여유():
    print("[10] 데스크톱 사용 가능 메모리 − 학습 몫 < 8GB 면 띄우지 않고 기다린다(첫 학습도)")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        (root / "속도.json").write_text(json.dumps({"늘리기640": {"동시": 2, "gpu_mb": 100, "ram_mb": 100}}), encoding="utf-8")
        _job(root, fake, 0, "E0-button-a", "normal")
        st = _wait_status(root, "win_low")
        check(not (root / "runs" / "E0-button-a").exists(), "8000 − 100 < 8192 → 안 띄움")
        check("데스크톱 메모리" in (st.get("기다리는이유") or "") and st.get("데스크톱사용가능MB") == 8000, f"이유·값 표시 — {st.get('기다리는이유')} · {st.get('데스크톱사용가능MB')}")
        check(st["대기"] == ["E0-button-a"] and not st["끝"], "대기열 그대로 · 끝나지 않음")


def test_데스크톱_메모리_못_읽음():
    print("[11] 데스크톱 메모리를 못 읽으면 띄우지 않고 기다린다")
    with tempfile.TemporaryDirectory() as t:
        root, fake, _ = _setup(t)
        _job(root, fake, 0, "E0-button-a", "normal")
        st = _wait_status(root, "win_fail")
        check(not (root / "runs" / "E0-button-a").exists() and "못 읽" in (st.get("기다리는이유") or ""), f"안 띄움 · 이유 — {st.get('기다리는이유')}")


if __name__ == "__main__":
    test_정상()
    test_진행없음()
    test_시간초과()
    test_점수0과_오류()
    test_동시_2개()
    test_짝_이상_종료()
    test_속도표_없으면_1개()
    test_잠금()
    test_끊김_복구()
    test_데스크톱_메모리_여유()
    test_데스크톱_메모리_못_읽음()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 학습 실행기 검증 통과")
