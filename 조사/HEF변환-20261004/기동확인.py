"""기동 확인 — 실제 시연 화면을 화면·카메라·GPIO·인터락 없이 만들어, 시작 로그에 시연 모델이 올라왔는지 보고
창 닫기 경로로 정상 종료되는지 확인한다(시연 모델 전환 계획 2026-10-07 Task 3 Step 3).

사용(Rpi5/Demo 에서 · 시스템 python3 · Hailo):
  python3 ../조사/HEF변환-20261004/기동확인.py
판정 = 시작 로그에 ①`[Detector] … 백엔드 로드 완료 — <config.HEF_MODEL_PATH 파일 이름>`
       ②`[시스템] 공구 검출: 사용 가능` (NPU 갈래면 `NPU 적재 — <TOOL_HEF_PATH 파일 이름>` 도) 가 있으면 종료 0 · 없으면 1.
🔴 실제 릴레이·버튼·카메라를 건드리지 않는다(GPIO·인터락 끔 · 카메라 127.0.0.1) · 상태 공개 파일은 임시 폴더로.
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
import config                                          # noqa: E402
config.GPIO_INPUT_ENABLED = False      # 실제 버튼·EMO 를 읽지 않는다
config.INTERLOCK_ENABLED = False       # 실제 릴레이에 명령을 보내지 않는다
config.CAMERA_TCP_HOST = "127.0.0.1"   # 카메라 없음(즉시 거절)
config.TCP_RECONNECT_DELAY_SEC = 0.1
config.STATE_SHM_DIR = tempfile.mkdtemp(prefix="sop_state_boot_")   # 음성비서가 읽는 /dev/shm 을 건드리지 않게
from PyQt6.QtWidgets import QApplication             # noqa: E402

app = QApplication([])
from safety_console import SafetyConsole             # noqa: E402

win = SafetyConsole()
win.show()
t0 = time.time()
while time.time() - t0 < 3:
    app.processEvents()
    time.sleep(0.05)
lines = win.log_browser.toPlainText().splitlines()
want = [f"백엔드 로드 완료 — {os.path.basename(config.HEF_MODEL_PATH)}", "[시스템] 공구 검출: 사용 가능"]
if config.TOOL_BACKEND == "hailo":
    want.append(f"NPU 적재 — {os.path.basename(config.TOOL_HEF_PATH)}")
for l in lines:
    if any(k in l for k in ("[Detector]", "[시스템] 공구", "[시스템] 손 검출")):
        print(l)
missing = [w for w in want if not any(w in l for l in lines)]
win.close()
app.processEvents()
print("판정:", "✅ 시작 로그에 시연 모델" if not missing else f"❌ 없는 줄 {missing}", "· 창 닫음", flush=True)
sys.exit(1 if missing else 0)
