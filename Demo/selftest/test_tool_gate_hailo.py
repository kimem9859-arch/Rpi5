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
    # 🔴 공유 파일은 임시 폴더에 — 진짜 /dev/shm/sop_tool 은 돌고 있는 음성비서가 읽는다(공구 구간 설계 D2)
    return TG.HailoToolGate(hef=_hef(), names=_Det.NAMES, conf=0.65, log=log, detector_factory=lambda: det,
                            shm_dir=tempfile.mkdtemp()), det


def test_음성비서_공유파일():
    print("\n[D2] NPU 결과를 음성비서가 읽는 파일로 — 꺼지면 지운다(공구 구간 설계 D2)")
    import json
    import voice_lib
    d = tempfile.mkdtemp()
    g = TG.HailoToolGate(hef=_hef(), names=_Det.NAMES, conf=0.65, detector_factory=lambda: _Det(), shm_dir=d)
    g.start()
    g.request(F, (1, 2))
    p = os.path.join(d, "resp.json")
    check(os.path.isfile(p), "검사하면 resp.json 이 생긴다")
    data = json.load(open(p))
    check(data["dets"] == [["wrench", 0.9, 10.0, 20.0, 30.0, 40.0]] and isinstance(data["seq"], int), f"모양 {data}")
    dets, fresh = voice_lib.read_tool_dets(p)
    check(fresh and dets and dets[0][0] == "wrench", f"음성비서가 신선하게 읽는다 {dets} {fresh}")
    seq1 = data["seq"]
    g.request(F, None)
    check(json.load(open(p))["seq"] == seq1 + 1, "검사마다 seq 가 오른다")
    g.stop()
    check(not os.path.exists(p), "끄면 지운다(낡은 검출을 남기지 않는다)")
    g.start()
    g.request(F, None)
    g.close()
    check(not os.path.exists(p), "닫아도 지운다")


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
    check(not g.available and g.poll() is None, "start 뒤에도 비활성")
    check(not g.loaded and "/없는/모델.hef" in g.reason, f"적재 상태·사유 {g.loaded} {g.reason!r}")
    n = sum("비활성" in s for s in said)
    check(n >= 2, f"start 때 다시 알린다(생성 때 로그는 화면에 안 붙어 있을 수 있다 — 리뷰 I-1) {said}")


def test_적재_성공_상태():
    print("\n[NPU 공구] 적재 성공 = loaded · 사유에 파일 이름(시작 로그가 쓴다)")
    g, _ = make()
    check(g.loaded and "t.hef" in g.reason and "NPU" in g.reason, f"{g.loaded} {g.reason!r}")


def test_추론_도중_꺼짐():
    print("\n[NPU 공구] 추론 도중 stop(·다시 start) — 그 결과는 새 서브 작업으로 새지 않는다(리뷰 m3·m4)")
    holder = {}

    class _Mid(_Det):
        def detect(self, frame):
            holder["g"].stop()
            if holder.get("restart"):
                holder["g"].start()
            return super().detect(frame)

    for restart in (False, True):
        holder["restart"] = restart
        g, _ = make(_Mid())
        holder["g"] = g
        g.start()
        g.request(F, (1, 1))
        check(g.poll() is None, f"{'stop→start' if restart else 'stop'} 사이 끝난 추론은 버린다")


def test_문턱_경고():
    print("\n[NPU 공구] 공구 문턱이 검출기 하한(YOLO_CONF_LOW)보다 낮으면 경고(리뷰 m5)")
    said = []
    TG.HailoToolGate(hef=_hef(), names=_Det.NAMES, conf=config.YOLO_CONF_LOW - 0.1, log=said.append,
                     detector_factory=lambda: _Det())
    g = TG.HailoToolGate(hef=_hef(), names=_Det.NAMES, conf=config.YOLO_CONF_LOW - 0.1, detector_factory=lambda: _Det())
    check(any("YOLO_CONF_LOW" in s for s in said) and "YOLO_CONF_LOW" in g.reason, f"로그·사유(시작 줄이 적는다) {said}")


def test_오류_로그_줄임():
    print("\n[NPU 공구] 추론 오류가 이어져도 로그는 5초에 한 번(리뷰 m6)")
    said = []
    g, _ = make(_Det(boom=True), log=said.append)
    g.start()
    for _ in range(3):
        g.request(F, None)
    check(sum("추론 오류" in s for s in said) == 1, f"{[s for s in said if '추론 오류' in s]}")


def test_닫은_뒤():
    print("\n[NPU 공구] close 뒤에는 쓸 수 없다(리뷰 m12)")
    g, det = make()
    g.close()
    g.start()
    g.request(F, None)
    check(det.closed and not g.available and g.poll() is None and det.calls == 0 and not g.loaded, "닫힘")


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
        said = []
        config.TOOL_BACKEND = "npu"
        g = TG.create_tool_gate(log=said.append)
        g.start()
        check(isinstance(g, TG.DisabledToolGate) and not g.loaded and not g.available and g.poll() is None
              and "TOOL_BACKEND" in g.reason and sum("TOOL_BACKEND" in s for s in said) >= 2,
              f"모르는 값 → 꺼진 갈래 · 사유가 남는다(오타가 NPU 로 가지 않게 · 리뷰 m7·후속 m2) {said}")
    finally:
        config.TOOL_BACKEND, config.TOOL_HEF_PATH = old


if __name__ == "__main__":
    test_음성비서_공유파일()
    test_문턱_이름_손끝()
    test_꺼져_있으면_추론하지_않음()
    test_적재_실패는_비활성_로그()
    test_적재_성공_상태()
    test_추론_도중_꺼짐()
    test_문턱_경고()
    test_오류_로그_줄임()
    test_닫은_뒤()
    test_추론_예외는_그_요청만()
    test_만드는_갈래()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ NPU 공구 갈래 검증 통과")
