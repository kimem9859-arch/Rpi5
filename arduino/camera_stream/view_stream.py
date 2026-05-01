import cv2
import numpy as np
import requests
import sys
import time
import threading
import os

# ESP32 IP 주소
url = "http://192.168.1.1/"
if len(sys.argv) > 1:
    url = f"http://{sys.argv[1]}/"

log_file = "/home/pi/claude-project/camera_stream/stream_log.txt"
save_dir = "/home/pi/claude-project/camera_stream/captured"
os.makedirs(save_dir, exist_ok=True)

# 이전 이미지 삭제
for f in os.listdir(save_dir):
    if f.endswith('.jpg'):
        os.remove(os.path.join(save_dir, f))

latest_frame = None
frame_lock = threading.Lock()
running = True
frame_count = 0
total_bytes = 0
corrupt_count = 0

def log(msg):
    t = time.strftime("%H:%M:%S")
    line = f"[{t}] {msg}"
    print(line)
    with open(log_file, "a") as f:
        f.write(line + "\n")

def receive_stream():
    global latest_frame, running, frame_count, total_bytes, corrupt_count
    buf = b''

    try:
        r = requests.get(url, stream=True, timeout=10)
        log(f"HTTP 응답: {r.status_code}")
        log(f"Content-Type: {r.headers.get('Content-Type', 'N/A')}")
    except Exception as e:
        log(f"연결 실패: {e}")
        running = False
        return

    log("스트림 수신 시작")
    start_time = time.time()

    try:
        for chunk in r.iter_content(chunk_size=4096):
            if not running:
                break
            total_bytes += len(chunk)
            buf += chunk

            while True:
                start = buf.find(b'\xff\xd8')
                end = buf.find(b'\xff\xd9')
                if start == -1 or end == -1 or end <= start:
                    break

                jpg_bytes = buf[start:end+2]
                buf = buf[end+2:]

                frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    corrupt_count += 1
                    continue

                frame = cv2.flip(frame, 0)
                with frame_lock:
                    latest_frame = frame
                frame_count += 1

                # 원본 JPEG 저장 (첫 5개, 이후 20프레임마다)
                if frame_count <= 5 or frame_count % 20 == 0:
                    save_path = os.path.join(save_dir, f"frame_{frame_count:04d}.jpg")
                    with open(save_path, 'wb') as f:
                        f.write(jpg_bytes)
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed if elapsed > 0 else 0
                    log(f"프레임 #{frame_count}: {frame.shape[1]}x{frame.shape[0]} / JPEG: {len(jpg_bytes)}B / FPS: {fps:.1f} / 저장됨")
                elif frame_count % 5 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed if elapsed > 0 else 0
                    log(f"프레임 #{frame_count}: FPS: {fps:.1f}")
    except Exception as e:
        log(f"수신 오류: {e}")
    finally:
        r.close()
        running = False

# 로그 초기화
with open(log_file, "w") as f:
    f.write(f"=== 스트림 로그 시작 {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

log(f"연결 중: {url}")
log(f"이미지 저장 경로: {save_dir}")

t = threading.Thread(target=receive_stream, daemon=True)
t.start()

log("종료: q 키")
while running:
    with frame_lock:
        frame = latest_frame

    if frame is not None:
        cv2.imshow("ESP32-S3 Camera", frame)

    key = cv2.waitKey(30) & 0xFF
    if key == ord('q'):
        log("사용자 종료 (q)")
        running = False
        break

log(f"=== 종료 ===")
log(f"총 프레임: {frame_count} / 깨진 프레임: {corrupt_count} / 총 수신: {total_bytes}B")
log(f"저장된 이미지: {save_dir}")
cv2.destroyAllWindows()
