"""카메라 쪽 측정 기록(측정 도구 정합 §4.3 저장 형식) — 프레임 · 박스 · 장소 지표 · 끄면 아무것도 안 함.

실행: python3 Demo/selftest/test_measure_camera.py
"""
import csv
import os
import sys
import tempfile
import types

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np


class _FakeDetector:
    backend_name = "시험용"
    NAMES = {0: "B1", 1: "B2", 2: "B3", 3: "B4", 4: "EMO"}

    def __init__(self):
        self.dets = [(0, 0.9, 10, 10, 30, 30)]

    def class_name(self, i):
        return self.NAMES[i]

    def detect(self, frame):
        return list(self.dets)

    def close(self):
        pass


_fake = types.ModuleType("detector")
_fake.create_detector = lambda: _FakeDetector()
sys.modules["detector"] = _fake

import config
config.HAND_ENABLED = False
config.TOOL_ENABLED = False

from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

import camera_thread as ct
import measure_log as ML

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def rows(d, name):
    with open(os.path.join(d, f"{name}.csv"), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_frames_and_boxes():
    print("\n[카메라 기록] 프레임 한 줄 · 박스(원시·트랙) · 단계별 ms")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["frames", "boxes", "env", "events"])
    th = ct.CameraThread()
    th.set_measure(lg)
    for i in range(2):                                   # 트랙 확정(CONFIRM_HITS=2)까지
        th._measure_begin(t_recv=100.0 + i, decode_ms=1.5, recv_seq=3 + 2 * i)
        th._process_frame(np.zeros((48, 64, 3), np.uint8), 100.0 + i)
        th._measure_end()
    lg.close()
    fr = rows(d, "frames")
    check(len(fr) == 2 and fr[0]["frame"] == "1" and fr[1]["frame"] == "2", f"프레임 번호 {[r['frame'] for r in fr]}")
    check(fr[0]["t_recv_ms"] == "100000.0" and fr[0]["decode_ms"] == "1.5", f"받은 시각·디코드 {fr[0]}")
    check([r["recv_seq"] for r in fr] == ["3", "5"], f"받은 프레임 누적 수 {[r['recv_seq'] for r in fr]}")
    for k in ("orient_ms", "detect_ms", "track_ms", "zone_ms"):
        check(fr[0][k] != "" and float(fr[0][k]) >= 0, f"{k} = {fr[0][k]!r}")
    check(fr[0]["tip_x"] == "" and fr[0]["roi"] == "", "손 없음 → 손끝·구역 빈칸")
    bx = rows(d, "boxes")
    raw = [b for b in bx if b["kind"] == "raw"]
    trk = [b for b in bx if b["kind"] == "track"]
    check(len(raw) == 2 and raw[0]["cls_name"] == "B1" and raw[0]["score"] == "0.9", f"원시 {raw}")
    check(len(trk) == 2 and trk[1]["confirmed"] == "1", f"트랙 확정 표시 {trk}")


def test_env_every_30_frames():
    print("\n[카메라 기록] 장소 환경 지표 = 30프레임마다")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["frames", "boxes", "env", "events"])
    th = ct.CameraThread()
    th.set_measure(lg)
    img = np.full((48, 64, 3), 128, np.uint8)
    for i in range(31):
        th._measure_begin(t_recv=float(i), decode_ms=0.0)
        th._process_frame(img.copy(), float(i))
        th._measure_end()
    lg.close()
    env = rows(d, "env")
    check([r["frame"] for r in env] == ["1", "31"], f"지표 프레임 {[r['frame'] for r in env]}")
    check(abs(float(env[0]["brightness"]) - 128) < 1, f"밝기 {env[0]['brightness']}")


def test_error_frame_leaves_no_row():
    print("\n[카메라 기록] 처리 오류 프레임은 줄을 남기지 않는다 · 번호는 계속 는다")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["frames", "boxes", "env", "events"])
    th = ct.CameraThread()
    th.set_measure(lg)
    th._measure_begin(t_recv=1.0, decode_ms=0.0)          # 이 프레임은 _process_frame 에서 예외 → _measure_end 없음
    th._measure_begin(t_recv=2.0, decode_ms=0.0)
    th._process_frame(np.zeros((48, 64, 3), np.uint8), 2.0)
    th._measure_end()
    lg.close()
    fr = rows(d, "frames")
    check([r["frame"] for r in fr] == ["2"], f"남은 줄 {[r['frame'] for r in fr]}")


def test_size_event():
    print("\n[카메라 기록] 프레임 크기가 정해질 때 사건 하나")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["frames", "boxes", "env", "events"])
    th = ct.CameraThread()
    th.set_measure(lg)
    th._ensure_calibration(1024, 768)
    th._ensure_calibration(1024, 768)                     # 같은 크기 = 사건 없음
    lg.close()
    with open(os.path.join(d, "events.csv"), encoding="utf-8", newline="") as f:
        ev = [r for r in csv.DictReader(f) if r["kind"] == "camera"]
    check(len(ev) == 1 and '"size"' in ev[0]["data"] and "1024" in ev[0]["data"], f"{ev}")


def test_recv_counts_drained_frames():
    print("\n[카메라 기록] 받은 수 = 한 번에 비워 버린 프레임도 센다(측정 27)")
    import socket
    import struct
    th = ct.CameraThread()
    a, b = socket.socketpair()
    for p in (b"x1", b"x22", b"x333"):                    # 밀려 쌓인 세 장
        b.sendall(struct.pack("<I", len(p)) + p)
    data, n = th._recv_latest_frame(a)
    check(data == b"x333" and n == 3, f"가장 최근 한 장 · 받은 수 3 → {data!r} · {n}")
    b.sendall(struct.pack("<I", 2) + b"y1")
    b.close()                                             # 한 장 뒤 끊김
    th._conn_gen = 1
    th._recv_worker(a, 1)
    a.close()
    check(th._recv_seq == 1 and th._recv_error, f"끊기기 전에 받은 것도 센다 → {th._recv_seq}")


def test_off_writes_nothing():
    print("\n[카메라 기록] 끄면(NullLog) 아무것도 안 쓴다 · 시험 안 깨짐")
    th = ct.CameraThread()
    th._measure_begin(t_recv=1.0, decode_ms=0.0)
    th._process_frame(np.zeros((48, 64, 3), np.uint8), 1.0)
    th._measure_end()
    check(not th._measure.enabled, "기본은 NullLog")


if __name__ == "__main__":
    test_frames_and_boxes()
    test_env_every_30_frames()
    test_error_frame_leaves_no_row()
    test_size_event()
    test_recv_counts_drained_frames()
    test_off_writes_nothing()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 카메라 측정 기록 검증 통과")
