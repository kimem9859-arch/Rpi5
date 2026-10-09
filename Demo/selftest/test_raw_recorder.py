"""1인칭 원본 녹화기(raw_recorder) — 가짜 ffmpeg 로 「처리한 프레임을 번호와 함께 빠짐없이」를 고정한다.

실행: python3 Demo/selftest/test_raw_recorder.py
설계 = 상위 docs/superpowers/specs/2026-10-09-측정녹화-보관판-design.md R1
"""
import csv
import os
import sys
import tempfile
import threading
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import numpy as np

import raw_recorder as RR

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _Pipe:
    def __init__(self, gate=None):
        self.data, self.closed, self.gate = bytearray(), False, gate

    def write(self, b):
        if self.gate is not None:
            self.gate.wait(5)
        self.data += b
        return len(b)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _Proc:
    def __init__(self, dead=False, gate=None):
        self.stdin, self.dead, self.args, self.signals = _Pipe(gate), dead, None, []

    def poll(self):
        return 1 if self.dead else (0 if self.stdin.closed else None)

    def wait(self, timeout=None):
        return 0

    def send_signal(self, s):
        self.signals.append(s)


def _spawner(proc):
    def spawn(args):
        proc.args = args
        return proc
    return spawn


W, H = 4, 2
IMG = np.zeros((H, W, 3), np.uint8)


def _rows(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_frames_in_order():
    print("\n[녹화기] 넣은 프레임이 번호 그대로 영상·대응표에")
    d = tempfile.mkdtemp()
    proc = _Proc()
    r = RR.RawRecorder(os.path.join(d, "a.mp4"), os.path.join(d, "a.csv"), spawn=_spawner(proc))
    check(r.start((W, H)) == [], "시작 문제 없음")
    for k in range(3):
        r.submit(IMG + k, 100 + k, 5000.0 + k)
    out = r.stop()
    rows = _rows(os.path.join(d, "a.csv"))
    check(out["written"] == 3 and out["dropped"] == 0, f"쓴 3 · 버림 0 · {out}")
    check([(x["video_frame"], x["frame"], x["dropped"]) for x in rows] == [("0", "100", "0"), ("1", "101", "0"), ("2", "102", "0")],
          f"대응표 {[(x['video_frame'], x['frame'], x['dropped']) for x in rows]}")
    check(len(proc.stdin.data) == 3 * W * H * 3 and proc.stdin.closed, f"파이프 바이트 {len(proc.stdin.data)} · 닫힘")
    check("rawvideo" in proc.args and f"{W}x{H}" in proc.args and "libx264" in proc.args, "rawvideo → x264(시연영상 촬영과 같은 설정)")


def test_overflow_keeps_numbers():
    print("\n[녹화기] 넘치면 버리되 버린 번호를 대응표에 남긴다(카메라 스레드는 기다리지 않는다)")
    d = tempfile.mkdtemp()
    gate = threading.Event()
    proc = _Proc(gate=gate)
    r = RR.RawRecorder(os.path.join(d, "b.mp4"), os.path.join(d, "b.csv"), queue_max=1, spawn=_spawner(proc))
    r.start((W, H))
    t0 = time.monotonic()
    for k in range(5):
        r.submit(IMG, k, float(k))
    check(time.monotonic() - t0 < 0.5, "넣기는 막히지 않는다")
    gate.set()
    out = r.stop()
    rows = _rows(os.path.join(d, "b.csv"))
    check(out["written"] + out["dropped"] == 5 and out["dropped"] >= 1, f"쓴+버림 = 5 · {out}")
    check([x["frame"] for x in rows] == ["0", "1", "2", "3", "4"], f"번호 순서 그대로 {[x['frame'] for x in rows]}")
    check(all((x["video_frame"] == "") == (x["dropped"] == "1") for x in rows), "버린 줄은 영상 순번이 비어 있다")
    vf = [int(x["video_frame"]) for x in rows if x["video_frame"]]
    check(vf == list(range(len(vf))), f"영상 순번은 빈틈 없이 0부터 {vf}")


def test_ffmpeg_dies_or_missing():
    print("\n[녹화기] ffmpeg 가 바로 죽거나 없으면 시작이 문제를 돌려준다 — 조용히 실패하지 않는다")
    d = tempfile.mkdtemp()
    r = RR.RawRecorder(os.path.join(d, "c.mp4"), os.path.join(d, "c.csv"), spawn=_spawner(_Proc(dead=True)))
    probs = r.start((W, H))
    check(probs and not r.active, f"죽음 → 문제 {probs}")
    r.submit(IMG, 1, 1.0)                       # 무시돼야 한다
    check(r.stop()["written"] == 0, "넣어도 쓰지 않는다")

    def missing(args):
        raise FileNotFoundError("ffmpeg")
    r2 = RR.RawRecorder(os.path.join(d, "e.mp4"), os.path.join(d, "e.csv"), spawn=missing)
    probs = r2.start((W, H))
    check(probs and not r2.active, f"없음 → 문제 {probs}")


def test_stop_without_frames():
    print("\n[녹화기] 프레임이 하나도 안 와도(카메라 끊김) 정지가 막히지 않는다")
    d = tempfile.mkdtemp()
    proc = _Proc()
    r = RR.RawRecorder(os.path.join(d, "f.mp4"), os.path.join(d, "f.csv"), spawn=_spawner(proc))
    r.start((W, H))
    t0 = time.monotonic()
    out = r.stop()
    check(out["written"] == 0 and time.monotonic() - t0 < 3 and proc.stdin.closed, f"바로 끝 {out}")
    check(_rows(os.path.join(d, "f.csv")) == [], "대응표 = 머리줄만")


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 1인칭 원본 녹화기 검증 통과")
