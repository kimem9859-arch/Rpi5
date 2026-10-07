"""시연 화면 쪽 측정 기록(측정 도구 정합 §4.3) — 사건 · 판정기 시점 · 끄면 폴더도 없음.

실행: python3 Demo/selftest/test_measure_console.py
"""
import csv
import json
import os
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import config
config.RECORDING_ENABLED = False
config.CAMERA_TCP_HOST = "127.0.0.1"
config.TCP_RECV_TIMEOUT_SEC = 0.3
config.TCP_RECONNECT_DELAY_SEC = 0.1
config.STATE_SHM_DIR = tempfile.mkdtemp(prefix="sop_state_test_")
config.GPIO_INPUT_ENABLED = False
config.INTERLOCK_ENABLED = False

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
_app = QApplication.instance() or QApplication([])

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def key(win, text):
    win.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, text))


def events(d):
    with open(os.path.join(d, "events.csv"), encoding="utf-8", newline="") as f:
        return [(float(r["t_ms"]), r["kind"], json.loads(r["data"])) for r in csv.DictReader(f)]


def make(measure_dir):
    if measure_dir:
        os.environ["SOP_MEASURE_DIR"] = measure_dir
    else:
        os.environ.pop("SOP_MEASURE_DIR", None)
    from safety_console import SafetyConsole
    return SafetyConsole()


def test_events_flow():
    print("\n[화면 기록] 작업 시작 · 누름 · 상태 · 위반 차단 · 판정기 시점")
    d = tempfile.mkdtemp()
    win = make(d)
    win._on_cta()
    t = time.monotonic()
    win._on_roi("B3", 2, t)                       # 1단계 차례에 B3 박스 안 → 판정기 시점 기록
    key(win, "3")                                 # 오답 누름 → 차단
    win.close()                                   # closeEvent 가 기록을 닫는다
    ev = events(d)
    kinds = [k for _t, k, _d in ev]
    check("run_start" in kinds, f"작업 시작 {kinds}")
    pr = [x for _t, k, x in ev if k == "press"]
    check(pr and pr[0]["button"] == "B3" and pr[0]["source"] == "keyboard" and pr[0]["expected"] == "B1",
          f"누름 {pr}")
    st = [x for _t, k, x in ev if k == "state" and x["new"] == "BLOCK"]
    check(bool(st), f"차단 상태 전이 {st}")
    check(kinds[-1] == "measure_end", f"끝 사건 {kinds[-1]}")
    with open(os.path.join(d, "fsm.csv"), encoding="utf-8", newline="") as f:
        fsm = list(csv.DictReader(f))
    check(fsm and fsm[0]["fsm_roi"] == "B3" and fsm[0]["expected"] == "B1", f"판정기 시점 {fsm[:1]}")
    check(fsm and float(fsm[0]["t_gui_ms"]) >= float(fsm[0]["t_recv_ms"]), f"판정 시각 ≥ 받은 시각 {fsm[:1]}")


def test_off_is_null():
    print("\n[화면 기록] 측정을 켜지 않으면 화면·카메라 모두 NullLog")
    win = make(None)
    check(not win._measure.enabled and not win.camera_thread._measure.enabled, "NullLog 둘")
    win._on_cta(); key(win, "3")                  # 끈 채로 흐름이 지금처럼 돈다(예외 없음)
    win.close()


class _Dev:
    def __init__(self, active):
        self.active_time, self.inactive_time = active, None


def _edges(active):
    import gpio_input
    got = []
    g = gpio_input.GpioInputController(on_button=lambda b: None, enabled=False,
                                       on_edge=lambda b, t, src: got.append((b, t, src)))
    t0 = time.monotonic()
    g._fire("B1", _Dev(active))
    return t0, got


def test_gpio_edge_time():
    print("\n[화면 기록] GPIO 엣지 시각 = 지금 − active_time")
    t0, got = _edges(0.25)
    check(len(got) == 1 and got[0][2] == "edge" and abs(got[0][1] - (t0 - 0.25)) < 0.05, f"엣지 {got}")


def test_gpio_edge_bad_clock():
    print("\n[화면 기록] active_time 이 엉뚱하면(다른 시계) 콜백 시각으로 대신하고 표시")
    for bad in (-3.0, 5000.0):
        t0, got = _edges(bad)
        check(got and got[0][2] == "callback" and abs(got[0][1] - t0) < 0.05, f"active_time={bad} → {got}")


if __name__ == "__main__":
    test_events_flow()
    test_off_is_null()
    test_gpio_edge_time()
    test_gpio_edge_bad_clock()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 시연 화면 측정 기록 검증 통과")
