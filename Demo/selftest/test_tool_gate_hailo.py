"""공구 NPU 갈래(HailoToolGate) — 가짜 검출기로 바깥 인터페이스를 고정한다(시연 모델 설계 2026-10-07 §2.3).

실행: python3 Demo/selftest/test_tool_gate_hailo.py
"""
import os
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import numpy as np

import config
import tool_gate as TG

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _Det:
    NAMES = ("driver", "wrench", "pliers")

    def __init__(self, dets=None, boom=False):
        self.dets = dets if dets is not None else [(1, 0.9, 10, 20, 30, 40), (0, 0.6, 1, 2, 3, 4)]
        self.boom, self.calls, self.closed = boom, 0, False

    def detect(self, frame):
        self.calls += 1
        if self.boom:
            raise RuntimeError("장치 오류(시험)")
        return list(self.dets)

    def class_name(self, i):
        return self.NAMES[i]

    def close(self):
        self.closed = True


def _hef():
    p = os.path.join(tempfile.mkdtemp(), "t.hef")
    open(p, "wb").close()
    return p


def make(det=None, log=None):
    det = det or _Det()
    return TG.HailoToolGate(hef=_hef(), names=_Det.NAMES, conf=0.65, log=log, detector_factory=lambda: det), det


F = np.zeros((8, 8, 3), np.uint8)


def test_문턱_이름_손끝():
    print("\n[NPU 공구] 문턱으로 거름 · 이름 · 그 프레임의 손끝과 짝")
    g, _ = make()
    g.start()
    g.request(F, (5, 6))
    got = g.poll()
    check(got == ([("wrench", 0.9, 10.0, 20.0, 30.0, 40.0)], (5, 6)), f"{got}")
    check(g.poll() is None, "같은 결과는 한 번만")


def test_꺼져_있으면_추론하지_않음():
    print("\n[NPU 공구] start 전 · stop 뒤에는 추론·결과 없음")
    g, det = make()
    g.request(F, None)
    check(det.calls == 0 and g.poll() is None and not g.available, "start 전")
    g.start()
    check(g.available, "start 뒤 available")
    g.request(F, None)
    g.stop()
    check(g.poll() is None and not g.available, "stop 이 남은 결과를 버린다")


def test_적재_실패는_비활성_로그():
    print("\n[NPU 공구] 모델 파일이 없으면 비활성 + 로그 · CPU 로 안 바뀜")
    said = []
    g = TG.HailoToolGate(hef="/없는/모델.hef", names=_Det.NAMES, conf=0.65, log=said.append,
                         detector_factory=lambda: _Det())
    g.start()
    g.request(F, None)
    check(not g.available and g.poll() is None, "비활성")
    check(any("비활성" in s for s in said), f"로그 {said}")


def test_추론_예외는_그_요청만():
    print("\n[NPU 공구] 추론 예외 = 그 요청만 버리고 로그 · 예외가 밖으로 안 나감")
    said = []
    g, det = make(_Det(boom=True), log=said.append)
    g.start()
    try:
        g.request(F, None)
        ok = True
    except Exception:                                        # noqa: BLE001
        ok = False
    check(ok and g.poll() is None and any("추론 오류" in s for s in said), f"{said}")


def test_만드는_갈래():
    print("\n[NPU 공구] create_tool_gate — 설정대로 갈래를 고른다")
    old = config.TOOL_BACKEND, config.TOOL_HEF_PATH
    try:
        config.TOOL_BACKEND = "cpu"
        check(isinstance(TG.create_tool_gate(), TG.ToolGate), "cpu → ToolGate(종전 워커)")
        config.TOOL_BACKEND, config.TOOL_HEF_PATH = "hailo", "/없는/모델.hef"
        g = TG.create_tool_gate()
        check(isinstance(g, TG.HailoToolGate) and not g.available, "hailo → HailoToolGate(파일 없으면 비활성)")
    finally:
        config.TOOL_BACKEND, config.TOOL_HEF_PATH = old


if __name__ == "__main__":
    test_문턱_이름_손끝()
    test_꺼져_있으면_추론하지_않음()
    test_적재_실패는_비활성_로그()
    test_추론_예외는_그_요청만()
    test_만드는_갈래()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ NPU 공구 갈래 검증 통과")
