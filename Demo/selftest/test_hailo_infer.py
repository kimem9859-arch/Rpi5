"""처리 2단계 2a — Hailo InferModel 추론기 · NMS 풀기 · 추론 중 GIL 해제(학교 방문 준비 설계 §3.2).

실행: python3 Demo/selftest/test_hailo_infer.py — Hailo 장치가 없거나 다른 프로세스가 쓰면 장치 시험은 건너뛴다.
"""
import os
import sys
import threading
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import numpy as np

import config
import hailo_infer as HI

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_parse_nms():
    print("\n[NMS 풀기] 클래스마다 「개수 + 상자 × 개수」(빈틈없이) → 클래스마다 (k, 5)")
    a = [0.1, 0.2, 0.3, 0.4, 0.9]
    b = [0.5, 0.5, 0.6, 0.6, 0.8]
    c = [0.2, 0.2, 0.4, 0.4, 0.7]
    flat = np.zeros(3 * (1 + 100 * 5), np.float32)
    flat[:1 + 10 + 1 + 1 + 5] = [2] + a + b + [0] + [1] + c
    out = HI.parse_nms_by_class(flat, 3)
    check([x.shape for x in out] == [(2, 5), (0, 5), (1, 5)], f"모양 {[x.shape for x in out]}")
    check(np.allclose(out[0][1], b) and np.allclose(out[2][0], c), "값 그대로")


def _device_ok():
    try:
        import hailo_device
        hailo_device.get_vdevice()
        return True
    except Exception as e:                      # noqa: BLE001
        print(f"  ⏭ Hailo 장치 없음 · 사용 중 — 장치 시험 건너뜀({type(e).__name__})")
        return False


def test_runner_and_gil():
    print("\n[추론기] 버튼 모델 — 출력 이름 · 배치 축 · 추론 중 다른 스레드가 돈다(GIL 해제)")
    if not _device_ok():
        return
    r = HI.InferRunner(config.HEF_MODEL_PATH)
    try:
        x = np.zeros((1, config.YOLO_INPUT_SIZE, config.YOLO_INPUT_SIZE, 3), np.uint8)
        out = r.infer({r.input_name: x})
        name = r.output_names[0]
        check(name.endswith("yolov8_nms_postprocess") and out[name].shape[0] == 1, f"출력 {name} · 모양 {out[name].shape}")
        check(HI.nms_classes(config.HEF_MODEL_PATH) == 5, "클래스 5")

        def spin(sec):
            n, end = 0, time.monotonic() + sec
            while time.monotonic() < end:
                n += 1
            return n
        alone = spin(1.0)
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                r.infer({r.input_name: x})
        th = threading.Thread(target=loop)
        th.start()
        busy = spin(1.0)
        stop.set()
        th.join()
        check(busy >= 0.8 * alone, f"추론 중 다른 스레드 계산 {busy / alone * 100:.0f}% (지금 방식 InferVStreams 는 약 39%)")
    finally:
        r.close()


if __name__ == "__main__":
    test_parse_nms()
    test_runner_and_gil()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ InferModel 추론기 검증 통과")
