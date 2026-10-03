# 일회용 — 공구 단계 흉내: 실제 tool_worker(rfenv)를 따로 띄우고 1초마다 요청 사진을 넣는다(런타임 JPEG 품질 80)
import cv2, glob, os, subprocess, sys, time
DEMO = "/home/pi/sop-project/Rpi5/Demo"; SHM = "/dev/shm/sop_tool_probe"
os.makedirs(SHM, exist_ok=True)
for f in os.listdir(SHM): os.remove(os.path.join(SHM, f))
w = subprocess.Popen([os.path.expanduser("~/env/rfenv/bin/python"), "tool_worker.py", SHM, "models/tool_v3.pt", "0.65"], cwd=DEMO)
fs = sorted(glob.glob(DEMO + "/test/raw/20260923_185802_esp32_xga-rt-s6-r1_console_v2/*.png"))[:120]
while not os.path.exists(os.path.join(SHM, "ready")): time.sleep(0.2)
print("[tool] 워커 준비", flush=True)
seq = 0
try:
    while True:
        im = cv2.imread(fs[seq % len(fs)]); ok, b = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 80])
        tmp = os.path.join(SHM, "req.tmp"); open(tmp, "wb").write(b.tobytes())
        os.replace(tmp, os.path.join(SHM, f"req_{seq}.jpg")); seq += 1; time.sleep(1.0)
finally:
    w.terminate()
