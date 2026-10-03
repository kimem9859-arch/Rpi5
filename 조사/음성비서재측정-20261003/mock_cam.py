# 일회용 — 모의 ESP32 카메라: 9/23 관문 S6 저장 사진(런타임 처리 뒤 세로)을 ESP32 원본 방향(가로)으로 되돌려
# 4바이트 길이(<I) + JPEG 로 127.0.0.1:8888 에 약 20fps 로 흘린다.
import cv2, glob, socket, struct, sys, time
SRC = "/home/pi/sop-project/Rpi5/Demo/test/raw/20260923_185802_esp32_xga-rt-s6-r1_console_v2"
N, FPS, Q = 600, 20.0, 60
frames = []
for p in sorted(glob.glob(SRC + "/*.png"))[:N]:
    im = cv2.imread(p)
    im = cv2.flip(cv2.rotate(im, cv2.ROTATE_90_CLOCKWISE), 0)   # 런타임 rotate(CCW)·flip(0) 의 역
    ok, b = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, Q]); frames.append(b.tobytes())
print(f"[cam] {len(frames)}장 · 평균 {sum(map(len,frames))/len(frames)/1024:.1f}KB · {im.shape[1]}x{im.shape[0]}", flush=True)
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 8888)); srv.listen(1)
while True:
    c, _ = srv.accept(); print("[cam] 연결됨", flush=True)
    i, t = 0, time.monotonic()
    try:
        while True:
            f = frames[i % len(frames)]; c.sendall(struct.pack("<I", len(f)) + f); i += 1
            t += 1 / FPS; d = t - time.monotonic()
            if d > 0: time.sleep(d)
            else: t = time.monotonic()
    except OSError:
        print("[cam] 끊김", flush=True); c.close()
