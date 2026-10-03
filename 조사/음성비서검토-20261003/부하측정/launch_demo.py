# 일회용 — 실제 시연 프로그램(main.py)을 저장소 변경 없이 띄운다: 인터락 끔(환경) · GPIO 끔 · 카메라 = 모의(127.0.0.1)
import os, sys, runpy
DEMO = "/home/pi/sop-project/Rpi5/Demo"
os.environ["SOP_INTERLOCK"] = "0"
os.chdir(DEMO); sys.path.insert(0, DEMO); sys.argv = ["main.py"]
import config
config.CAMERA_TCP_HOST = "127.0.0.1"
config.GPIO_INPUT_ENABLED = False
runpy.run_path("main.py", run_name="__main__")
