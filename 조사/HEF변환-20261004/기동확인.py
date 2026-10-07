import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
import config
config.GPIO_INPUT_ENABLED = False      # 실제 버튼·EMO 를 읽지 않는다
config.INTERLOCK_ENABLED = False       # 실제 릴레이에 명령을 보내지 않는다
config.CAMERA_TCP_HOST = "127.0.0.1"   # 카메라 없음(즉시 거절)
config.TCP_RECONNECT_DELAY_SEC = 0.1
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
app = QApplication([])
from safety_console import SafetyConsole
win = SafetyConsole()
win.show()
t0 = time.time()
while time.time() - t0 < 3:
    app.processEvents(); time.sleep(0.05)
lines = win.log_browser.toPlainText().splitlines()
for l in lines:
    if any(k in l for k in ("[Detector]", "공구", "손 검출", "[시스템] 공구", "HOI")):
        print(l)
win.close()
app.processEvents()
print("창 닫음 · 종료", flush=True)
sys.exit(0)
