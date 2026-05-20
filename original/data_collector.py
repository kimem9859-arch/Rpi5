import cv2
import numpy as np
import socket
import struct
import sys
import time
import threading
import os

CAPTURE_INTERVAL = 5  # seconds

ip = "10.111.10.235"
port = 8888
if len(sys.argv) > 1:
    ip = sys.argv[1]

save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collected_images")
os.makedirs(save_dir, exist_ok=True)

latest_frame = None
frame_lock = threading.Lock()
running = True


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


def capture_loop():
    global running
    count = 0
    while running:
        time.sleep(CAPTURE_INTERVAL)
        if not running:
            break
        with frame_lock:
            frame = latest_frame.copy() if latest_frame is not None else None
        if frame is None:
            continue

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        path = os.path.join(save_dir, f"{timestamp}.jpg")
        cv2.imwrite(path, frame)
        count += 1
        print(f"[저장] ({count}) {path}")


print(f"[시작] {ip}:{port}  |  저장 폴더: {save_dir}")
print(f"[안내] {CAPTURE_INTERVAL}초마다 JPG 저장  |  q 키로 종료")

t_stream = threading.Thread(target=stream_with_reconnect, daemon=True)
t_stream.start()

t_capture = threading.Thread(target=capture_loop, daemon=True)
t_capture.start()

while running:
    with frame_lock:
        frame = latest_frame

    if frame is not None:
        cv2.imshow("ESP32-S3 Data Collector", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        running = False
        break

cv2.destroyAllWindows()
print("[종료]")
