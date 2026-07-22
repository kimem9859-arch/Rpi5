"""ESP32 카메라 실측 속도 점검 — 촬영을 시작해도 되는 상태인가.

왜 있나:
    `run_bench_test.sh` 는 원래 `ping` 만 봤다. ping 은 **"닿는가"만** 알려주고
    **"빠른가"는 모른다.** 2026-07-20 클린룸 촬영에서 카메라가 라우팅을 경유해 붙은 상태로
    ping 을 통과했고, 런처는 "✅ ESP32 응답 정상"을 띄웠으며, 그대로 **0.9fps**(정상 12.5fps)로
    한 세션을 통째로 찍어 버렸다. 클린룸은 다시 들어가기 어려운 곳이라 그 손실이 크다.
    → **프레임을 실제로 받아 속도를 재고** 나서 촬영을 허락한다.

수신 로직은 `bench_detector` 것을 그대로 쓴다 — 촬영 본체와 같은 경로로 재야 의미가 있다.

실행:
    python3 test/cam_probe.py                    # 기본: 10프레임, 하한 8fps
    python3 test/cam_probe.py --min-fps 10

종료코드 (런처가 읽는다):
    0 = 정상 (>= min_fps)            → 촬영 진행
    2 = 느림 (min_fps 의 절반 이상)  → 계속할지 사람이 판단
    1 = 불가 (그 미만·연결/디코드 실패) → 촬영 중단
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # bench_detector
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # config

import config
from bench_detector import _connect_tcp, _recv_latest_frame

EXIT_OK, EXIT_FAIL, EXIT_SLOW = 0, 1, 2


def probe(host, frames, min_fps):
    sock = _connect_tcp(host)
    if sock is None:
        print(f"❌ {host}:{config.CAMERA_TCP_PORT} 에 붙지 못했습니다.")
        return EXIT_FAIL

    try:
        # 첫 프레임은 버린다 — 연결 직후 지연이 섞여 속도를 왜곡한다.
        if _recv_latest_frame(sock) is None:
            print("❌ 첫 프레임을 받지 못했습니다 (스트림이 오지 않음).")
            return EXIT_FAIL

        last = None
        t0 = time.perf_counter()
        for i in range(frames):
            data = _recv_latest_frame(sock)
            if data is None:
                print(f"❌ 프레임 수신이 {i}장에서 끊겼습니다.")
                return EXIT_FAIL
            last = data
        elapsed = time.perf_counter() - t0
    finally:
        try:
            sock.close()
        except OSError:
            pass

    img = cv2.imdecode(np.frombuffer(last, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("❌ JPEG 디코드 실패 — 스트림이 깨졌습니다.")
        return EXIT_FAIL

    fps = frames / elapsed if elapsed > 0 else 0.0
    h, w = img.shape[:2]
    print(f"📷 실측 {fps:.1f}fps  ({frames}장 / {elapsed:.1f}초)  해상도 {w}×{h}")

    if fps >= min_fps:
        print(f"✅ 정상 — 촬영을 시작해도 됩니다 (하한 {min_fps:.0f}fps)")
        return EXIT_OK
    if fps >= min_fps / 2:
        print(f"⚠️ 느립니다 (하한 {min_fps:.0f}fps). 파이와 ESP32가 같은 공유기에")
        print("   직접 붙어 있는지 확인하세요 — 라우팅을 경유하면 이렇게 떨어집니다.")
        return EXIT_SLOW
    print(f"❌ 너무 느립니다 (하한 {min_fps:.0f}fps). 이대로 찍으면 세션을 버리게 됩니다.")
    print("   ESP32 재부팅 / 바탕화면 'ESP32 IP 갱신' / WiFi 확인 후 다시 시도하세요.")
    return EXIT_FAIL


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ESP32 카메라 실측 속도 점검")
    p.add_argument("--host", default=None, help=f"ESP32 IP (기본 {config.CAMERA_TCP_HOST})")
    p.add_argument("--frames", type=int, default=10, help="측정에 쓸 프레임 수 (기본 10)")
    p.add_argument("--min-fps", type=float, default=8.0,
                   help="정상 판정 하한 (기본 8.0 — 정상 실측 12.5fps, 사고 사례 0.9fps 사이)")
    a = p.parse_args()
    sys.exit(probe(a.host or config.CAMERA_TCP_HOST, a.frames, a.min_fps))
