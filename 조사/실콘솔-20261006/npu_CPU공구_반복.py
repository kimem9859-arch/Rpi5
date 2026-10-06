import sys, time, cv2
from ultralytics import YOLO
img = cv2.imread(sys.argv[1]); m = YOLO("/home/pi/data/학습실험/E0c-tool-f120/best.pt")
m.predict(img, conf=0.65, verbose=False)
open(sys.argv[2], "w").write("ready\n")
n = 0; t0 = time.time()
while True:          # 시연 tool_worker 처럼 1초에 한 번(TOOL_SCAN_INTERVAL_SEC) · 파일 읽기는 뺌
    t = time.time(); m.predict(img, conf=0.65, verbose=False); n += 1
    with open(sys.argv[2], "a") as f: f.write(f"{(time.time()-t)*1000:.0f}\n")
    time.sleep(max(0, 1.0 - (time.time() - t)))
