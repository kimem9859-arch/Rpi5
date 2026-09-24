"""헤드리스 재현 — 하드웨어·Hailo 없이 SafetyConsole 흐름만 본다(offscreen)."""
import os, sys, types, time
SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
# Hailo 검출기 로드를 막는다 — detector 모듈을 가짜로
fake = types.ModuleType("detector")
def _no(): raise RuntimeError("stub: no detector")
fake.create_detector = _no
sys.modules["detector"] = fake
import config
config.CAMERA_TCP_HOST = "127.0.0.1"; config.TCP_RECV_TIMEOUT_SEC = 0.3; config.TCP_RECONNECT_DELAY_SEC = 0.1
config.HAND_ENABLED = False; config.TOOL_ENABLED = False
config.GPIO_INPUT_ENABLED = False; config.INTERLOCK_ENABLED = False
config.RECORDING_ENABLED = False; config.DEMO_CAPTURE = False
config.LOG_SAVE_DIR = os.path.join(SP, "logs"); config.STATE_SHM_DIR = os.path.join(SP, "shm")
config.UI_ANIMATION = False
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from fsm import State
import safety_console
from safety_console import SafetyConsole

def make():
    w = SafetyConsole(); w.resize(1280, 720); w._relayout(); return w

def finish_sub_now(w):
    """서브 작업 시각을 앞당겨 time_done 으로 만든다."""
    w._sub._start -= 100; w._tick_sub()

def S(w): return f"state={w.fsm.state.value} step={w.fsm.expected_step} sub={'Y' if w._sub else 'N'} alert={w.alert.mode}"

print("== A: EMO during B3 sub, release before sub ends ==")
w = make(); w._on_cta()
for k in ("B1",):
    w._press_button(k); finish_sub_now(w)
w._press_button("B2"); w._sub.set_tool("wrench"); finish_sub_now(w)
print(" before B3:", S(w))
w._press_button("B3"); print(" B3 pressed:", S(w))
w._press_button("EMO"); print(" EMO:", S(w))
w._on_alert_release(); print(" released:", S(w))
finish_sub_now(w); print(" B3 sub completes:", S(w), "| violations:", w._stats._violations)
w.close()

print("== A2: EMO during B1 sub, release, sub completes ==")
w = make(); w._on_cta(); w._press_button("B1"); w._press_button("EMO"); w._on_alert_release()
print(" released:", S(w)); finish_sub_now(w); print(" B1 sub completes:", S(w))
w.close()

print("== A3: correct button pressed during violation BLOCK ==")
w = make(); w._on_cta(); w._press_button("B3"); print(" B3 wrong:", S(w))
w._press_button("B1"); print(" B1 during BLOCK:", S(w))
w._on_alert_release(); finish_sub_now(w); print(" release then sub done:", S(w))
w.close()

print("== B: EMO in IDLE -> release -> run without start; stats ==")
w = make(); w._on_cta()
for b in ("B1","B2","B3","B4"):
    w._press_button(b)
    if w._sub:
        if w._sub.needs_tool: w._sub.set_tool("wrench")
        finish_sub_now(w)
print(" run1 done:", S(w), "steps", len(w._stats._steps)); w._close_result()
w._press_button("EMO"); print(" EMO in IDLE:", S(w), "cta visible", not w.btn_cta.isHidden())
w._on_alert_release(); print(" released:", S(w), "cta visible", not w.btn_cta.isHidden(), "stats.running", w._stats.running)
for b in ("B1","B2","B3","B4"):
    w._press_button(b)
    if w._sub:
        if w._sub.needs_tool: w._sub.set_tool("wrench")
        finish_sub_now(w)
d = w._stats.finish() if False else None
print(" run2 result shown:", not w.result_panel.isHidden())
# 결과창 텍스트에서 누른 순서 줄
from PyQt6.QtWidgets import QLabel
txt = [l.text() for l in w.result_panel.findChildren(QLabel)]
print(" result lines:", [t for t in txt if "→" in t or t.startswith("총")][:3])
w.close()

print("== C: wrong tool held, then violation BLOCK ==")
w = make(); w._on_cta(); w._press_button("B1"); finish_sub_now(w)
w._press_button("B2"); w._sub.set_tool("driver"); w._tick_sub(); print(" wrong tool:", S(w))
w._press_button("B3"); print(" B3 -> BLOCK:", S(w))
w._tick_sub(); print(" 200ms later:", S(w), "release btn visible", not w.alert._release.isHidden())
w._sub.set_tool(None); w._tick_sub(); print(" tool put down:", S(w), "alert visible", not w.alert.isHidden(), "glow", w.glow.level)
w.close()

print("== C2: wrong tool held, then WARNING ==")
w = make(); w._on_cta(); w._press_button("B1"); finish_sub_now(w)
w._press_button("B2"); w._sub.set_tool("driver"); w._tick_sub()
t0 = time.time(); w.fsm.update_vision("B3", t0); w.fsm.update_vision("B3", t0+0.5); print(" dwell B3 -> ", S(w))
w._tick_sub(); print(" 200ms later:", S(w))
w._sub.set_tool("wrench"); finish_sub_now(w); print(" right tool + time:", S(w), "alert visible", not w.alert.isHidden())
w.close()

print("== D: 't' overwritten by next tool result ==")
w = make(); w._on_cta(); w._press_button("B1"); finish_sub_now(w)
w._press_button("B2"); w._sim_tool_grasped(); print(" after t: tool_ok", w._sub.tool_ok)
w._on_tool([], (100, 100)); print(" after empty tool result: tool_ok", w._sub.tool_ok)
w.close()
