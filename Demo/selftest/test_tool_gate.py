"""공구 워커 게이트(A-2) 검증 — 워커 없이 IPC 짝맞춤만 본다.

실행: python3 Demo/selftest/test_tool_gate.py

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §3·§4.6

⚠️ **실제 추론은 시험하지 않는다** — 그것은 tool_worker.py 단독 검증의 몫이고
   여기서 모델을 올리면 테스트가 수십 초로 늘어난다. resp.json 을 직접 써서
   워커를 흉내낸다.
"""

import json
import os
import shutil
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import numpy as np

from tool_gate import ToolGate

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


FRAME = np.zeros((48, 64, 3), dtype=np.uint8)


def _gate(tmp, python="/없는/경로/python"):
    """워커를 띄우지 않는 게이트 — python 경로가 없으므로 spawn 이 실패한다."""
    return ToolGate(shm_dir=tmp, python=python, model="없음.pt", conf=0.65)


def _write_resp(tmp, seq, dets):
    """워커 흉내 — resp.json 을 원자적으로 쓴다."""
    path = os.path.join(tmp, "resp.json")
    with open(path + ".tmp", "w") as f:
        json.dump({"seq": seq, "dets": dets}, f)
    os.replace(path + ".tmp", path)


def _mark_ready(tmp):
    """워커 흉내 — ready 를 만들어 available 이 True 가 되게 한다."""
    with open(os.path.join(tmp, "ready"), "w") as f:
        f.write("0")


# ------------------------------------------------------- ① 없어도 죽지 않는다
def test_워커없으면_조용히_비활성():
    """🔴 rfenv·모델이 없어도 GUI 가 죽으면 안 된다(손 검출과 같은 방침)."""
    print("[1] 워커가 못 뜨면 조용히 비활성")
    tmp = tempfile.mkdtemp()
    logs = []
    try:
        gate = ToolGate(shm_dir=tmp, python="/없는/경로/python",
                        model="없음.pt", conf=0.65, log=logs.append)
        gate.start()
        check(gate.available is False, "available=False")
        check(gate.poll() is None, "poll 이 예외 없이 None")
        gate.request(FRAME, (1, 2))
        check(gate.poll() is None, "request 도 예외 없이 넘어간다")
        check(any("공구" in m for m in logs),
              "🔴 로그에 남는다 — 조용하면 게이트가 안 열리는 원인을 못 찾는다")
        gate.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ready없으면_비활성():
    print("[2] ready 가 없으면 available=False")
    tmp = tempfile.mkdtemp()
    try:
        gate = _gate(tmp)
        gate._proc = object()          # spawn 이 된 것처럼 꾸민다
        check(gate.available is False, "ready 파일이 없으면 아직 비활성")
        _mark_ready(tmp)
        check(gate.available is True, "ready 가 생기면 활성")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------- ② 요청/응답 짝맞춤
def test_요청시점_손좌표와_짝지어_돌아온다():
    """🔴 §4.6 — 지금 손 위치와 1초 전 공구 박스를 섞으면 안 된다."""
    print("[3] 요청 시점의 손 좌표가 결과와 함께 돌아온다")
    tmp = tempfile.mkdtemp()
    try:
        gate = _gate(tmp)
        gate._proc = object()
        _mark_ready(tmp)

        gate.request(FRAME, (10, 20))                  # seq=1
        gate.request(FRAME, (99, 99))                  # seq=2

        # seq=1 응답이 먼저 올 수 있다(워커가 이미 처리 중이었던 경우).
        # 🔑 버리지 않는다 — 짝이 맞으면 유효한 결과다. 1Hz 에서 1초 지연은 감수한다.
        _write_resp(tmp, seq=1, dets=[["wrench", 0.8, 1, 2, 3, 4]])
        dets, tip = gate.poll()
        check(tip == (10, 20), "seq=1 응답에는 seq=1 의 손 좌표가 붙는다")
        check(dets[0][0] == "wrench", "그 seq 의 검출 결과가 붙는다")

        _write_resp(tmp, seq=2, dets=[])
        got = gate.poll()
        check(got is not None, "다음 seq 응답도 받는다")
        dets, tip = got
        check(tip == (99, 99), "seq=2 요청 당시의 손 좌표가 돌아온다")
        check(dets == [], "🔴 지금 손 위치와 옛 공구 박스를 섞지 않는다")

        # seq=2 를 소비한 뒤에는 더 오래된 응답이 다시 와도 무시한다.
        _write_resp(tmp, seq=1, dets=[["driver", 0.9, 0, 0, 1, 1]])
        check(gate.poll() is None, "이미 지나간 seq 는 되돌아오지 않는다")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_같은응답을_두번_주지않는다():
    print("[4] 같은 응답을 두 번 주지 않는다")
    tmp = tempfile.mkdtemp()
    try:
        gate = _gate(tmp)
        gate._proc = object()
        _mark_ready(tmp)
        gate.request(FRAME, (5, 5))
        _write_resp(tmp, seq=1, dets=[])
        check(gate.poll() is not None, "1회차 — 받는다")
        check(gate.poll() is None, "2회차 — 이미 소비했으므로 None")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_손이_안보인_요청도_그대로():
    """손이 안 보이는 프레임도 보낸다 — 판정은 tool_state 가 한다."""
    print("[5] fingertip=None 도 그대로 실려 돌아온다")
    tmp = tempfile.mkdtemp()
    try:
        gate = _gate(tmp)
        gate._proc = object()
        _mark_ready(tmp)
        gate.request(FRAME, None)
        _write_resp(tmp, seq=1, dets=[["wrench", 0.7, 0, 0, 9, 9]])
        dets, tip = gate.poll()
        check(tip is None, "None 이 그대로 돌아온다")
        check(dets[0][0] == "wrench", "검출은 정상")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_깨진응답을_견딘다():
    """resp.json 이 반쯤 쓰였거나 깨져도 예외로 올라오지 않는다."""
    print("[6] 깨진 resp.json 을 견딘다")
    tmp = tempfile.mkdtemp()
    try:
        gate = _gate(tmp)
        gate._proc = object()
        _mark_ready(tmp)
        gate.request(FRAME, (1, 1))
        with open(os.path.join(tmp, "resp.json"), "w") as f:
            f.write('{"seq": 1, "dets": [[')       # 깨진 JSON
        check(gate.poll() is None, "예외 없이 None")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_요청파일이_실제로_생긴다():
    print("[7] request 가 req_<seq>.jpg 를 남긴다")
    tmp = tempfile.mkdtemp()
    try:
        gate = _gate(tmp)
        gate._proc = object()
        _mark_ready(tmp)
        gate.request(FRAME, (1, 1))
        reqs = [f for f in os.listdir(tmp) if f.startswith("req_")]
        check(reqs == ["req_1.jpg"], f"req_1.jpg 가 생긴다 (실제: {reqs})")
        check(not any(f.endswith(".tmp") for f in os.listdir(tmp)),
              "tmp 파일이 남지 않는다(원자적 쓰기)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    t0 = time.time()
    test_워커없으면_조용히_비활성()
    test_ready없으면_비활성()
    test_요청시점_손좌표와_짝지어_돌아온다()
    test_같은응답을_두번_주지않는다()
    test_손이_안보인_요청도_그대로()
    test_깨진응답을_견딘다()
    test_요청파일이_실제로_생긴다()

    elapsed = time.time() - t0
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    if elapsed > 5.0:
        print(f"❌ 느림 {elapsed:.1f}s — 모델을 올리고 있는 것 아닌가")
        sys.exit(1)
    print(f"✅ 공구 게이트 검증 통과 ({elapsed:.3f}s)")
