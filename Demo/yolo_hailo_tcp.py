import cv2
import numpy as np
import socket
import struct
import sys
import time
import threading
import os
from datetime import datetime
from ultralytics import YOLO

try:
    import mediapipe as mp
    _mp_hands = mp.solutions.hands
    _mp_draw = mp.solutions.drawing_utils
    hands = _mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
    )
    MEDIAPIPE_AVAILABLE = True
    print("[MediaPipe] Loaded successfully.")
except Exception as e:
    MEDIAPIPE_AVAILABLE = False
    print(f"[MediaPipe] Not available: {e}")

ip = "10.220.25.235"
port = 8888
if len(sys.argv) > 1:
    ip = sys.argv[1]

MODEL_PATH = 'yolov8n.pt'
CONF_HIGH = 0.65
CONF_LOW  = 0.50
IOU_MATCH = 0.3
MAX_MISS  = 3
INPUT_SIZE = 320
CALIBRATION_PATH = 'camera_calibration.npz'

_camera_matrix = None
_dist_coeffs = None
_undistort_map = None

def load_calibration(w, h):
    global _camera_matrix, _dist_coeffs, _undistort_map
    if not os.path.exists(CALIBRATION_PATH):
        return False
    data = np.load(CALIBRATION_PATH)
    _camera_matrix = data['camera_matrix']
    _dist_coeffs = data['dist_coeffs']
    new_matrix, _ = cv2.getOptimalNewCameraMatrix(_camera_matrix, _dist_coeffs, (w, h), 1, (w, h))
    _undistort_map = cv2.initUndistortRectifyMap(_camera_matrix, _dist_coeffs, None, new_matrix, (w, h), cv2.CV_16SC2)
    print(f"[Calibration] Loaded: {CALIBRATION_PATH}")
    return True

def undistort(frame):
    if _undistort_map is None:
        return frame
    return cv2.remap(frame, _undistort_map[0], _undistort_map[1], cv2.INTER_LINEAR)

VIDEO_DIR = os.path.join(os.path.expanduser('~'), 'Videos', 'YOLOv8s_test_videos')
LOG_DIR   = os.path.join(os.path.expanduser('~'), 'Documents', 'YOLOv8s_test_Log')

COCO_CLASSES = [
    'person','bicycle','car','motorcycle','airplane','bus','train','truck','boat',
    'traffic light','fire hydrant','stop sign','parking meter','bench','bird','cat',
    'dog','horse','sheep','cow','elephant','bear','zebra','giraffe','backpack',
    'umbrella','handbag','tie','suitcase','frisbee','skis','snowboard','sports ball',
    'kite','baseball bat','baseball glove','skateboard','surfboard','tennis racket',
    'bottle','wine glass','cup','fork','knife','spoon','bowl','banana','apple',
    'sandwich','orange','broccoli','carrot','hot dog','pizza','donut','cake','chair',
    'couch','potted plant','bed','dining table','toilet','tv','laptop','mouse',
    'remote','keyboard','cell phone','microwave','oven','toaster','sink','refrigerator',
    'book','clock','vase','scissors','teddy bear','hair drier','toothbrush'
]

latest_frame = None
frame_lock = threading.Lock()
running = True
rx_count = 0
net_log_file = None


def recv_exact(sock, length):
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def receive_stream():
    global latest_frame, running, rx_count
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(10)
        sock.connect((ip, port))
        print(f"[TCP] Connected: {ip}:{port}")
    except Exception as e:
        print(f"[TCP] Connection failed: {e}")
        running = False
        return

    prev_done = None
    lat_sum = 0.0
    gap_sum = 0.0
    n = 0
    WINDOW = 30

    try:
        while running:
            t_start = time.perf_counter()
            header = recv_exact(sock, 4)
            length = struct.unpack('<I', header)[0]
            if length == 0 or length > 200000:
                print(f"[TCP] Invalid frame size: {length}")
                break
            data = recv_exact(sock, length)
            t_done = time.perf_counter()

            recv_ms = (t_done - t_start) * 1000.0
            gap_ms = (t_start - prev_done) * 1000.0 if prev_done else 0.0
            prev_done = t_done

            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            frame = cv2.flip(frame, 0)
            with frame_lock:
                latest_frame = frame
            rx_count += 1

            if net_log_file is not None:
                ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                net_log_file.write(f'{ts},{rx_count},{length},{recv_ms:.2f},{gap_ms:.2f}\n')

            lat_sum += recv_ms
            gap_sum += gap_ms
            n += 1
            if n >= WINDOW:
                avg_recv = lat_sum / n
                avg_gap = gap_sum / n
                kbps = (length * 8 / 1024) / (recv_ms / 1000.0) if recv_ms > 0 else 0
                print(f"[NET] #{rx_count} avg recv:{avg_recv:.1f}ms gap:{avg_gap:.1f}ms size:{length//1024}KB speed:{kbps:.0f}kbps")
                lat_sum = gap_sum = 0.0
                n = 0
    except Exception as e:
        print(f"[TCP] Receive error: {e}")
    finally:
        sock.close()
        running = False


def process_mediapipe(frame):
    if not MEDIAPIPE_AVAILABLE:
        return frame, None
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    rgb.flags.writeable = False
    results = hands.process(rgb)
    rgb.flags.writeable = True

    fingertip_pos = None
    if results.multi_hand_landmarks:
        for hand_lm in results.multi_hand_landmarks:
            _mp_draw.draw_landmarks(
                frame, hand_lm, _mp_hands.HAND_CONNECTIONS,
                _mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3),
                _mp_draw.DrawingSpec(color=(255, 255, 255), thickness=2),
            )
            tip = hand_lm.landmark[_mp_hands.HandLandmark.INDEX_FINGER_TIP]
            fx, fy = int(tip.x * w), int(tip.y * h)
            fingertip_pos = (fx, fy)
            cv2.circle(frame, (fx, fy), 12, (255, 0, 255), -1)
            cv2.circle(frame, (fx, fy), 14, (255, 255, 255), 2)
    return frame, fingertip_pos


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


def update_tracks(tracks, detections):
    used = [False] * len(detections)
    for t in tracks:
        best_i, best_iou = -1, IOU_MATCH
        for i, d in enumerate(detections):
            if used[i] or d[0] != t['cls']:
                continue
            box = (d[2], d[3], d[4], d[5])
            v = iou(t['box'], box)
            if v > best_iou:
                best_iou, best_i = v, i
        if best_i >= 0:
            d = detections[best_i]
            t['box'] = (d[2], d[3], d[4], d[5])
            t['score'] = d[1]
            t['miss'] = 0
            if d[1] >= CONF_HIGH:
                t['confirmed'] = True
            used[best_i] = True
        else:
            t['miss'] += 1
    for i, d in enumerate(detections):
        if used[i]:
            continue
        if d[1] >= CONF_HIGH:
            tracks.append({
                'cls': d[0],
                'box': (d[2], d[3], d[4], d[5]),
                'score': d[1],
                'miss': 0,
                'confirmed': True,
            })
    tracks[:] = [t for t in tracks if t['miss'] <= MAX_MISS and t['confirmed']]
    return tracks


def draw(frame, detections, fps, fingertip_pos, recording):
    for cls_id, score, x1, y1, x2, y2 in detections:
        label = f"{COCO_CLASSES[cls_id]} {score:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, label, (x1, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    cv2.putText(frame, f"Objects: {len(detections)}", (10, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
    mp_status = "MediaPipe: ON" if MEDIAPIPE_AVAILABLE else "MediaPipe: OFF"
    mp_color = (0, 255, 255) if MEDIAPIPE_AVAILABLE else (0, 0, 255)
    cv2.putText(frame, mp_status, (10, 94),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, mp_color, 2)
    if fingertip_pos:
        cv2.putText(frame, f"Finger: {fingertip_pos}", (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
    if recording:
        cv2.circle(frame, (300, 20), 10, (0, 0, 255), -1)
        cv2.putText(frame, "REC", (270, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return frame


os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
video_path = os.path.join(VIDEO_DIR, f'{timestamp}_tcp.avi')
log_path   = os.path.join(LOG_DIR,   f'{timestamp}_tcp.csv')
net_log_path = os.path.join(LOG_DIR, f'{timestamp}_tcp_network.csv')

net_log_file = open(net_log_path, 'w')
net_log_file.write('time,frame,size(B),recv_ms,gap_ms\n')
print(f"Network log: {net_log_path}")

rx_thread = threading.Thread(target=receive_stream, daemon=True)
rx_thread.start()

print("Waiting for first frame...")
wait_start = time.time()
while latest_frame is None and running and (time.time() - wait_start) < 10:
    time.sleep(0.1)

if latest_frame is None:
    print("Frame receive failed, exiting")
    running = False
    sys.exit(1)

with frame_lock:
    h, w = latest_frame.shape[:2]
print(f"Frame size: {w}x{h}")

calibration_loaded = load_calibration(w, h)
if not calibration_loaded:
    print("[Calibration] No calibration file found. Run calibrate_camera.py first.")

model = YOLO(MODEL_PATH)

fourcc = cv2.VideoWriter_fourcc(*'XVID')
writer = cv2.VideoWriter(video_path, fourcc, 15.0, (w, h))

log_file = open(log_path, 'w')
log_file.write('time,frame,fps,class,confidence,x1,y1,x2,y2,finger_x,finger_y\n')

print(f"YOLOv8n + MediaPipe + ESP32 TCP started - press 'q' to quit")
print(f"Video: {video_path}")
print(f"Log: {log_path}")

fps = 0.0
prev_time = time.perf_counter()
frame_count = 0
last_rx_processed = -1
tracks = []

try:
    while running:
        with frame_lock:
            if rx_count == last_rx_processed or latest_frame is None:
                frame = None
            else:
                frame = latest_frame.copy()
                last_rx_processed = rx_count

        if frame is None:
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            continue

        frame = undistort(frame)

        results = model(frame, imgsz=INPUT_SIZE, verbose=False)[0]
        detections = []
        for box in results.boxes:
            cls_id = int(box.cls[0])
            score = float(box.conf[0])
            if score < CONF_LOW:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append((cls_id, score, x1, y1, x2, y2))

        frame, fingertip_pos = process_mediapipe(frame)

        cur_time = time.perf_counter()
        dt = cur_time - prev_time
        fps = 1.0 / dt if dt > 0 else 0.0
        prev_time = cur_time

        update_tracks(tracks, detections)

        display_dets = [
            (t['cls'], t['score'], *t['box']) for t in tracks
        ]
        frame = draw(frame, display_dets, fps, fingertip_pos, recording=True)
        writer.write(frame)

        now = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        fx = fingertip_pos[0] if fingertip_pos else ''
        fy = fingertip_pos[1] if fingertip_pos else ''
        if display_dets:
            for cls_id, score, x1, y1, x2, y2 in display_dets:
                log_file.write(
                    f'{now},{frame_count},{fps:.1f},'
                    f'{COCO_CLASSES[cls_id]},{score:.3f},{x1},{y1},{x2},{y2},{fx},{fy}\n'
                )
        else:
            log_file.write(f'{now},{frame_count},{fps:.1f},,,,,,{fx},{fy}\n')

        frame_count += 1
        cv2.imshow('YOLOv8n + MediaPipe + ESP32 TCP', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    running = False
    if MEDIAPIPE_AVAILABLE:
        hands.close()
    writer.release()
    log_file.close()
    if net_log_file is not None:
        net_log_file.close()
    cv2.destroyAllWindows()

    print(f"\nDone - total inference frames: {frame_count} / TCP received: {rx_count}")
    print(f"Video: {video_path}")
    print(f"Inference log: {log_path}")
    print(f"Network log: {net_log_path}")
