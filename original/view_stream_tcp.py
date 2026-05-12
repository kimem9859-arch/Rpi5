import cv2
import numpy as np
import socket
import struct
import sys
import time
import threading
import os

# ESP32 IP
ip = "10.220.25.235"
port = 8888
if len(sys.argv) > 1:
    ip = sys.argv[1]

video_dir = "/home/pi/claude-project/camera_stream_tcp/recordings"
os.makedirs(video_dir, exist_ok=True)

timestamp = time.strftime('%Y%m%d_%H%M%S')
video_path = os.path.join(video_dir, f"{timestamp}.avi")
writer = None

latest_frame = None
frame_lock = threading.Lock()
running = True
writer_lock = threading.Lock()


def recv_exact(sock, length):
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("소켓 연결 끊김")
        data += chunk
    return data


def receive_stream():
    global latest_frame, running

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(10)
        sock.connect((ip, port))
        print(f"[연결됨] {ip}:{port}")
    except Exception as e:
        print(f"[연결 실패] {e}")
        return

    try:
        while running:
            header = recv_exact(sock, 4)
            length = struct.unpack('<I', header)[0]

            if length == 0 or length > 200000:
                print(f"[비정상 프레임 크기] {length}")
                break

            data = recv_exact(sock, length)
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue

            frame = cv2.flip(frame, 0)
            with frame_lock:
                latest_frame = frame

            with writer_lock:
                if writer is not None:
                    writer.write(frame)

    except Exception as e:
        print(f"[수신 오류] {e}")
    finally:
        sock.close()


def stream_with_reconnect():
    global running
    while running:
        receive_stream()
        if not running:
            break
        print("[재연결] 3초 후 시도")
        time.sleep(3)


print(f"[시작] 서버 {ip}:{port}")
print(f"[녹화 저장] {video_path}")

t_stream = threading.Thread(target=stream_with_reconnect, daemon=True)
t_stream.start()

try:
    while running and latest_frame is None:
        time.sleep(0.05)
except KeyboardInterrupt:
    running = False

if latest_frame is not None:
    h, w = latest_frame.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    with writer_lock:
        writer = cv2.VideoWriter(video_path, fourcc, 15.0, (w, h))
    print(f"[녹화 시작] {w}x{h}")

print("[안내] q 키로 종료")
while running:
    with frame_lock:
        frame = latest_frame

    if frame is not None:
        cv2.imshow("ESP32-S3 TCP Stream", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        running = False
        break

with writer_lock:
    if writer is not None:
        writer.release()

print(f"[종료] 영상 저장: {video_path}")
cv2.destroyAllWindows()
