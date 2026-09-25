"""G8 사진 — 경고·차단 때 화면(오프스크린 1280×720). 공동 확인에서 사용자에게 보인다.

실행: cd Rpi5/Demo && python3 ../조사/GUI수정-20260925/g8_screenshot.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "Demo"))

import config
config.RECORDING_ENABLED = False
config.CAMERA_TCP_HOST = "127.0.0.1"
config.TCP_RECV_TIMEOUT_SEC = 0.3
config.TCP_RECONNECT_DELAY_SEC = 0.1
config.GPIO_INPUT_ENABLED = False
config.INTERLOCK_ENABLED = False
config.UI_ANIMATION = False

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from safety_console import SafetyConsole

win = SafetyConsole()
win.resize(1280, 720)
win._relayout()
win.show(); app.processEvents()
win._on_cta()
win._press_button("B1")
t0 = time.time()
for i in range(6):
    win.fsm.update_vision("B3", t0 + i * 0.1)        # 오답 머묾 → 경고
win._relayout(); app.processEvents()
win.grab().save(os.path.join(HERE, "g8_warning.png"))
win._press_button("B3")                              # 경고 중 오답 → 차단
win._relayout(); app.processEvents()
win.grab().save(os.path.join(HERE, "g8_block.png"))
print("saved", sorted(f for f in os.listdir(HERE) if f.endswith(".png")))
win.close()
