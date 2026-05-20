import cv2
import numpy as np
import time
import threading
import os
import csv
from datetime import datetime

# =============================================================================
# USB Webcam / Path Config
# =============================================================================
USB_DEVICE_INDEX = 1  # 0=노트북 내장(Intel), 1=ABKO APC900 FHD USB 웹캠

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
video_dir = os.path.join(BASE_DIR, "recordings")
os.makedirs(video_dir, exist_ok=True)

SESSION_TS = time.strftime('%Y%m%d_%H%M%S')
video_path = os.path.join(video_dir, f"{SESSION_TS}_usb.avi")
log_dir = os.path.join(BASE_DIR, "logs", f"{SESSION_TS}_usb")
os.makedirs(log_dir, exist_ok=True)

YOLO_MODEL_PATH = r"D:\claude\claude-project\Demo\YOLO model\yolov8n.pt"

# =============================================================================
# State
# =============================================================================
writer = None
latest_frame = None
frame_lock = threading.Lock()
running = True
writer_lock = threading.Lock()

# Metrics buffers (1-second aggregation)
metrics_lock = threading.Lock()
buf_frame_count = 0
buf_detect_count = 0
buf_frames_with_detect = 0
buf_confs = []
buf_infer_ms = []
buf_capture_frames = 0
buf_capture_fails = 0
buf_frame_w = 0
buf_frame_h = 0
buf_track_obs = {}

capture_fail_total = 0
session_start = time.time()

# =============================================================================
# YOLO Load
# =============================================================================
YOLO_AVAILABLE = False
yolo_model = None
try:
    from ultralytics import YOLO
    yolo_model = YOLO(YOLO_MODEL_PATH)
    YOLO_AVAILABLE = True
    print(f"[YOLO] Model loaded: {YOLO_MODEL_PATH}")
except Exception as e:
    print(f"[YOLO] Load failed: {e}")

CONF_LOW = 0.50
CONF_HIGH = 0.65
IOU_MATCH = 0.3
MAX_MISS = 10
YOLO_INPUT_SIZE = 416
PERSON_CLASS_ID = 0

# =============================================================================
# MediaPipe Load
# =============================================================================
MEDIAPIPE_AVAILABLE = False
hands = None
mp_hands = None
mp_draw = None
try:
    import mediapipe as mp
    mp_hands = mp.solutions.hands
    mp_draw = mp.solutions.drawing_utils
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        model_complexity=1,
        min_detection_confidence=0.85,
        min_tracking_confidence=0.7,
    )
    MEDIAPIPE_AVAILABLE = True
    print("[MediaPipe] Hands loaded")
except Exception as e:
    print(f"[MediaPipe] Load failed: {e}")

# =============================================================================
# Tracking
# =============================================================================
tracks = []
_next_track_id = 1
_track_id_lock = threading.Lock()


def _new_track_id():
    global _next_track_id
    with _track_id_lock:
        tid = _next_track_id
        _next_track_id += 1
    return tid


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    return inter / ((ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)


def update_tracks(detections):
    """detections: list of (score, x1, y1, x2, y2). person class only."""
    global tracks
    used = [False] * len(detections)
    for t in tracks:
        best_i, best_v = -1, IOU_MATCH
        for i, d in enumerate(detections):
            if used[i]:
                continue
            v = iou(t['box'], (d[1], d[2], d[3], d[4]))
            if v > best_v:
                best_v, best_i = v, i
        if best_i >= 0:
            d = detections[best_i]
            t['box'] = (d[1], d[2], d[3], d[4])
            t['score'] = d[0]
            t['miss'] = 0
            if d[0] >= CONF_HIGH:
                t['confirmed'] = True
            used[best_i] = True
        else:
            t['miss'] += 1
    for i, d in enumerate(detections):
        if used[i]:
            continue
        if d[0] >= CONF_HIGH:
            tracks.append({
                'id': _new_track_id(),
                'box': (d[1], d[2], d[3], d[4]),
                'score': d[0],
                'miss': 0,
                'confirmed': True,
                'first_seen': time.time(),
                'miss_total': 0,
            })
    for t in tracks:
        if t['miss'] > 0:
            t['miss_total'] += 1
    tracks = [t for t in tracks if t['miss'] <= MAX_MISS and t['confirmed']]
    return tracks


# =============================================================================
# YOLO Inference
# =============================================================================
def run_yolo(frame):
    if yolo_model is None:
        return [], 0.0
    t0 = time.time()
    results = yolo_model(frame, imgsz=YOLO_INPUT_SIZE, verbose=False)[0]
    infer_ms = (time.time() - t0) * 1000.0
    dets = []
    for box in results.boxes:
        cls_id = int(box.cls[0])
        if cls_id != PERSON_CLASS_ID:
            continue
        score = float(box.conf[0])
        if score < CONF_LOW:
            continue
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        dets.append((score, x1, y1, x2, y2))
    return dets, infer_ms


# =============================================================================
# Frame Processing
# =============================================================================
def process_frame(frame):
    global buf_frame_count, buf_detect_count, buf_frames_with_detect
    global buf_confs, buf_infer_ms, buf_track_obs

    h, w = frame.shape[:2]

    if YOLO_AVAILABLE:
        dets, infer_ms = run_yolo(frame)
        active_tracks = update_tracks(dets)

        with metrics_lock:
            buf_frame_count += 1
            buf_infer_ms.append(infer_ms)
            if len(active_tracks) > 0:
                buf_frames_with_detect += 1
            for t in active_tracks:
                buf_detect_count += 1
                buf_confs.append(t['score'])
                x1, y1, x2, y2 = t['box']
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                bw, bh = (x2 - x1), (y2 - y1)
                buf_track_obs.setdefault(t['id'], []).append((cx, cy, bw, bh))

        for t in active_tracks:
            x1, y1, x2, y2 = t['box']
            label = f"person#{t['id']} {t['score']:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, label, (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    if MEDIAPIPE_AVAILABLE:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = hands.process(rgb)
        rgb.flags.writeable = True
        if results.multi_hand_landmarks:
            for hand_lm in results.multi_hand_landmarks:
                mp_draw.draw_landmarks(
                    frame, hand_lm, mp_hands.HAND_CONNECTIONS,
                    mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3),
                    mp_draw.DrawingSpec(color=(255, 255, 255), thickness=2),
                )
                idx_tip = hand_lm.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP]
                fx = int(idx_tip.x * w)
                fy = int(idx_tip.y * h)
                cv2.circle(frame, (fx, fy), 12, (255, 0, 255), -1)
                cv2.circle(frame, (fx, fy), 14, (255, 255, 255), 2)

    return frame


# =============================================================================
# USB Webcam Capture
# =============================================================================
def capture_loop():
    global latest_frame, running, buf_capture_frames, buf_capture_fails
    global buf_frame_w, buf_frame_h, capture_fail_total

    cap = cv2.VideoCapture(USB_DEVICE_INDEX)
    if not cap.isOpened():
        print(f"[USB] 웹캠 열기 실패 (index={USB_DEVICE_INDEX})")
        running = False
        return
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    print(f"[USB] 웹캠 연결 성공 (index={USB_DEVICE_INDEX})")

    while running:
        ret, frame = cap.read()
        if not ret:
            with metrics_lock:
                buf_capture_fails += 1
                capture_fail_total += 1
            time.sleep(0.03)
            continue

        h, w = frame.shape[:2]

        with metrics_lock:
            buf_capture_frames += 1
            buf_frame_w = w
            buf_frame_h = h

        with frame_lock:
            latest_frame = frame

    cap.release()
    print("[USB] 웹캠 해제")


# =============================================================================
# CSV Logger
# =============================================================================
INFER_CSV = os.path.join(log_dir, "inference_log.csv")
OBJECT_CSV = os.path.join(log_dir, "object_log.csv")
TRACKING_CSV = os.path.join(log_dir, "tracking_log.csv")
CAPTURE_CSV = os.path.join(log_dir, "capture_log.csv")


def init_csvs():
    with open(INFER_CSV, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            'date', 'time', 'detected_class', 'frame_count', 'detect_count',
            'avg_conf', 'max_conf', 'min_conf', 'avg_infer_ms', 'detection_rate',
        ])
    with open(OBJECT_CSV, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            'date', 'time', 'track_id',
            'avg_center_x', 'avg_center_y',
            'avg_bbox_w', 'avg_bbox_h', 'avg_bbox_area',
        ])
    with open(TRACKING_CSV, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            'date', 'time', 'track_id', 'duration_sec', 'miss_count',
        ])
    with open(CAPTURE_CSV, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            'date', 'time', 'capture_fps', 'frame_width', 'frame_height',
            'capture_fail_1s', 'capture_fail_total',
        ])


def flush_one_second():
    global buf_frame_count, buf_detect_count, buf_frames_with_detect
    global buf_confs, buf_infer_ms, buf_track_obs
    global buf_capture_frames, buf_capture_fails, buf_frame_w, buf_frame_h

    now = datetime.now()
    d_str = now.strftime('%Y-%m-%d')
    t_str = now.strftime('%H:%M:%S')

    with metrics_lock:
        fc = buf_frame_count
        dc = buf_detect_count
        fwd = buf_frames_with_detect
        confs = list(buf_confs)
        infer = list(buf_infer_ms)
        cap_f = buf_capture_frames
        cap_fail = buf_capture_fails
        fw = buf_frame_w
        fh = buf_frame_h
        track_obs = {k: list(v) for k, v in buf_track_obs.items()}

        buf_frame_count = 0
        buf_detect_count = 0
        buf_frames_with_detect = 0
        buf_confs = []
        buf_infer_ms = []
        buf_capture_frames = 0
        buf_capture_fails = 0
        buf_track_obs = {}

        active_tracks_snapshot = [
            (t['id'], time.time() - t['first_seen'], t['miss_total'])
            for t in tracks
        ]
        cap_fail_tot = capture_fail_total

    avg_conf = sum(confs) / len(confs) if confs else 0.0
    max_conf = max(confs) if confs else 0.0
    min_conf = min(confs) if confs else 0.0
    avg_infer = sum(infer) / len(infer) if infer else 0.0
    det_rate = (fwd / fc) if fc > 0 else 0.0

    with open(INFER_CSV, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            d_str, t_str, 'person', fc, dc,
            f"{avg_conf:.4f}", f"{max_conf:.4f}", f"{min_conf:.4f}",
            f"{avg_infer:.2f}", f"{det_rate:.4f}",
        ])

    if track_obs:
        with open(OBJECT_CSV, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            for tid, obs in track_obs.items():
                if not obs:
                    continue
                cxs = [o[0] for o in obs]
                cys = [o[1] for o in obs]
                ws = [o[2] for o in obs]
                hs = [o[3] for o in obs]
                avg_cx = sum(cxs) / len(cxs)
                avg_cy = sum(cys) / len(cys)
                avg_w = sum(ws) / len(ws)
                avg_h = sum(hs) / len(hs)
                avg_area = avg_w * avg_h
                w.writerow([
                    d_str, t_str, tid,
                    f"{avg_cx:.1f}", f"{avg_cy:.1f}",
                    f"{avg_w:.1f}", f"{avg_h:.1f}", f"{avg_area:.1f}",
                ])

    if active_tracks_snapshot:
        with open(TRACKING_CSV, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            for tid, dur, miss in active_tracks_snapshot:
                w.writerow([d_str, t_str, tid, f"{dur:.2f}", miss])

    with open(CAPTURE_CSV, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            d_str, t_str, cap_f, fw, fh, cap_fail, cap_fail_tot,
        ])


def csv_logger_loop():
    next_tick = time.time() + 1.0
    while running:
        sleep_for = next_tick - time.time()
        if sleep_for > 0:
            time.sleep(sleep_for)
        try:
            flush_one_second()
        except Exception as e:
            print(f"[로그 오류] {e}")
        next_tick += 1.0


# =============================================================================
# Main
# =============================================================================
init_csvs()
print(f"[시작] USB 웹캠 index={USB_DEVICE_INDEX}")
print(f"[녹화 저장] {video_path}")
print(f"[로그 저장] {log_dir}")

t_capture = threading.Thread(target=capture_loop, daemon=True)
t_capture.start()

t_logger = threading.Thread(target=csv_logger_loop, daemon=True)
t_logger.start()

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
        frame = latest_frame.copy() if latest_frame is not None else None

    if frame is not None:
        frame = process_frame(frame)
        with writer_lock:
            if writer is not None:
                writer.write(frame)
        cv2.imshow("USB Webcam (YOLO+MediaPipe)", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        running = False
        break

try:
    flush_one_second()
except Exception:
    pass

with writer_lock:
    if writer is not None:
        writer.release()

print(f"[종료] 영상 저장: {video_path}")
print(f"[종료] 로그 저장: {log_dir}")
cv2.destroyAllWindows()
