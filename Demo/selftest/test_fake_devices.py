"""가짜 장치 — 카메라(형식 · 속도 · 램프 흉내) · 인터락(ACK) · 카메라 주소 덮기(학교 방문 준비 설계 §7.1).

실행: python3 Demo/selftest/test_fake_devices.py
"""
import os
import socket
import struct
import subprocess
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import cv2
import numpy as np

import fake_camera as FC
import fake_interlock as FI

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _jpeg(v, w=160, h=120):
    return cv2.imencode(".jpg", np.full((h, w, 3), v, np.uint8))[1].tobytes()


def _read_one(s):
    n = struct.unpack("<I", _exact(s, 4))[0]
    return _exact(s, n)


def _exact(s, n):
    b = b""
    while len(b) < n:
        part = s.recv(n - len(b))
        if not part:
            raise ConnectionError("끊김")
        b += part
    return b


def test_camera_format_and_rate():
    print("\n[가짜 카메라] 안경과 같은 형식(4바이트 길이 + JPEG) · 정한 속도로 되풀이")
    frames = [_jpeg(10), _jpeg(200)]
    cam = FC.FakeCamera(frames, port=0, fps=40).start()
    try:
        s = socket.create_connection(("127.0.0.1", cam.port), timeout=3)
        got = [_read_one(s) for _ in range(3)]
        check(got == [frames[0], frames[1], frames[0]], "보낸 바이트 = 원본 그대로 · 차례대로 되풀이")
        t0, n0 = time.monotonic(), cam.sent
        time.sleep(1.0)
        rate = (cam.sent - n0) / (time.monotonic() - t0)
        check(30 <= rate <= 45, f"속도 약 40장/초 → {rate:.1f}")
        s.close()
    finally:
        cam.stop()


def test_camera_lamp_mimic():
    print("\n[가짜 카메라] 램프 흉내 — 정한 지연 뒤부터 램프 자리가 밝다")
    cam = FC.FakeCamera([_jpeg(60, 320, 240)], port=0, fps=40, mimic=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", cam.port), timeout=3)
        x1, y1, x2, y2 = FC.LAMP_BOX

        def lamp_level():
            img = cv2.imdecode(np.frombuffer(_read_one(s), np.uint8), cv2.IMREAD_GRAYSCALE)
            return float(img[y1:y2, x1:x2].mean())

        check(lamp_level() < 40, "켜기 전 = 어둡다")
        cam.lamp(True, 0.2)
        t0 = time.monotonic()
        while lamp_level() < 200:
            if time.monotonic() - t0 > 2:
                break
        dt = time.monotonic() - t0
        check(0.15 <= dt <= 0.5, f"켜진 장이 지연 0.2초 뒤에 온다 → {dt:.2f}초")
        s.close()
    finally:
        cam.stop()


def test_interlock_ack():
    print("\n[가짜 인터락] 명령 한 줄 → ACK · 받은 명령 기록 · 콜백")
    import serial
    seen = []
    fi = FI.FakeInterlock(on_cmd=lambda cmd, t: seen.append(cmd)).start()
    try:
        ser = serial.Serial(fi.port, 115200, timeout=1)
        ser.write(b"WARN\n")
        ack = ser.readline()
        check(ack == b"ACK\n", f"ACK 응답 → {ack!r}")
        check([c for _, c in fi.cmds] == ["WARN"] and seen == ["WARN"], f"기록 {fi.cmds} · 콜백 {seen}")
        ser.close()
    finally:
        fi.stop()


def test_camera_host_override():
    print("\n[주소 덮기] SOP_CAMERA_HOST 가 있으면 시연 · 음성비서 둘 다 그 주소로(.camera_ip 는 그대로)")
    env = dict(os.environ, SOP_CAMERA_HOST="127.0.0.1")
    r = subprocess.run([sys.executable, "-c", "import config; print(config.CAMERA_TCP_HOST)"], cwd=_DEMO_DIR,
                       env=env, capture_output=True, text=True)
    check(r.stdout.strip() == "127.0.0.1", f"시연 = {r.stdout.strip()!r}")
    r = subprocess.run([sys.executable, "-c", "import voice_assistant as V; print(V.esp_ip())"], cwd=_DEMO_DIR,
                       env=env, capture_output=True, text=True)
    check(r.stdout.strip().splitlines()[-1:] == ["127.0.0.1"], f"음성비서 = {r.stdout.strip()[-40:]!r}")
    env.pop("SOP_CAMERA_HOST")
    r = subprocess.run([sys.executable, "-c", "import config; print(config.CAMERA_TCP_HOST)"], cwd=_DEMO_DIR,
                       env=env, capture_output=True, text=True)
    check(r.stdout.strip() != "127.0.0.1", f"없으면 종전(.camera_ip) = {r.stdout.strip()!r}")


def test_unorient_mp4():
    print("\n[가짜 카메라] 녹화 영상(화면 방향)을 안경 원본 방향으로 되돌려 보낸다 — 시연이 다시 돌리면 원래 장")
    import tempfile
    import frame_orient
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v.mp4")
    h, w = 160, 120                                       # 화면 방향 = 세로
    img = np.zeros((h, w, 3), np.uint8)
    img[:40, :, 2] = 255                                  # 위쪽 빨강
    img[:, :30, 1] = 255                                  # 왼쪽 초록
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for _ in range(3):
        vw.write(img)
    vw.release()
    frames = FC.load_frames(path, unorient_video=True)
    raw = cv2.imdecode(np.frombuffer(frames[0], np.uint8), cv2.IMREAD_COLOR)
    check(raw.shape[:2] == (w, h), f"원본 방향 = 가로 {raw.shape[:2]}")
    back = frame_orient.flip(raw)
    back = frame_orient.rotate(back)
    diff = float(np.abs(back.astype(int) - img.astype(int)).mean())
    check(back.shape == img.shape and diff < 12, f"반전 → 회전하면 원래 장(평균 차이 {diff:.1f})")


if __name__ == "__main__":
    test_camera_format_and_rate()
    test_camera_lamp_mimic()
    test_interlock_ack()
    test_camera_host_override()
    test_unorient_mp4()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 가짜 장치 검증 통과")
