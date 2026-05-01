import select
import socket
import struct
import threading
import time
import os

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from config import (
    CAMERA_FLIP_VERTICAL, FSM_STATES, BUTTON_ROIS,
    CAMERA_TCP_HOST, CAMERA_TCP_PORT,
    TCP_RECV_TIMEOUT_SEC, TCP_RECONNECT_DELAY_SEC, TCP_MAX_FRAME_BYTES,
    YOLO_MODEL_PATH, YOLO_CALIBRATION_PATH,
    YOLO_CONF_HIGH, YOLO_CONF_LOW, YOLO_IOU_MATCH, YOLO_MAX_MISS, YOLO_INPUT_SIZE,
)

# =============================================================================
# [MediaPipe]
# =============================================================================
MEDIAPIPE_AVAILABLE = False
try:
    import mediapipe as mp
    _test = mp.solutions.hands
    MEDIAPIPE_AVAILABLE = True
except Exception:
    pass

# =============================================================================
# [YOLO] 모델을 모듈 수준에서 한 번만 로드해서 두 스레드가 공유
# =============================================================================
YOLO_AVAILABLE = False
_shared_yolo_model = None
_yolo_lock = threading.Lock()

try:
    from ultralytics import YOLO as YOLOModel
    _shared_yolo_model = YOLOModel(YOLO_MODEL_PATH)
    YOLO_AVAILABLE = True
    print("[YOLO] Model loaded (shared).")
except Exception as e:
    print(f"[YOLO] Load failed: {e}")


def _run_yolo_shared(frame):
    if _shared_yolo_model is None:
        return []
    with _yolo_lock:
        results = _shared_yolo_model(frame, imgsz=YOLO_INPUT_SIZE, verbose=False)[0]
    detections = []
    for box in results.boxes:
        score = float(box.conf[0])
        if score < YOLO_CONF_LOW:
            continue
        cls_id = int(box.cls[0])
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        detections.append((cls_id, score, x1, y1, x2, y2))
    return detections

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

# =============================================================================
# [YOLO 트래킹 헬퍼]
# =============================================================================
def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    return inter / ((ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter)


def _update_tracks(tracks, detections):
    used = [False] * len(detections)
    for t in tracks:
        best_i, best_v = -1, YOLO_IOU_MATCH
        for i, d in enumerate(detections):
            if used[i] or d[0] != t['cls']:
                continue
            v = _iou(t['box'], (d[2], d[3], d[4], d[5]))
            if v > best_v:
                best_v, best_i = v, i
        if best_i >= 0:
            d = detections[best_i]
            t['box'] = (d[2], d[3], d[4], d[5])
            t['score'] = d[1]
            t['miss'] = 0
            if d[1] >= YOLO_CONF_HIGH:
                t['confirmed'] = True
            used[best_i] = True
        else:
            t['miss'] += 1
    for i, d in enumerate(detections):
        if used[i]:
            continue
        if d[1] >= YOLO_CONF_HIGH:
            tracks.append({
                'cls': d[0], 'box': (d[2], d[3], d[4], d[5]),
                'score': d[1], 'miss': 0, 'confirmed': True,
            })
    tracks[:] = [t for t in tracks if t['miss'] <= YOLO_MAX_MISS and t['confirmed']]
    return tracks


# =============================================================================
# [캘리브레이션 헬퍼]
# =============================================================================
def _load_undistort_map(path, w, h):
    if not os.path.exists(path):
        return None
    data = np.load(path)
    cam_mat = data['camera_matrix']
    dist    = data['dist_coeffs']
    new_mat, _ = cv2.getOptimalNewCameraMatrix(cam_mat, dist, (w, h), 1, (w, h))
    map1, map2 = cv2.initUndistortRectifyMap(cam_mat, dist, None, new_mat, (w, h), cv2.CV_16SC2)
    return (map1, map2)


# =============================================================================
# [CameraThread] ESP32-S3 TCP 스트림
# =============================================================================
class CameraThread(QThread):
    change_pixmap_signal   = pyqtSignal(QImage)
    log_signal             = pyqtSignal(str)
    finger_roi_signal      = pyqtSignal(str)
    yolo_detections_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self._running   = True
        self.sock       = None
        self._host      = CAMERA_TCP_HOST
        self._is_active = True
        self._tracks               = []
        self._undistort_map        = None

        # MediaPipe
        self._mediapipe_ok = False
        if MEDIAPIPE_AVAILABLE:
            try:
                self._mp_hands = mp.solutions.hands
                self._mp_draw  = mp.solutions.drawing_utils
                self._hands    = self._mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=1,
                    min_detection_confidence=0.7,
                    min_tracking_confidence=0.5,
                )
                self._mediapipe_ok = True
            except Exception as e:
                print(f"[MediaPipe] init failed: {e}")

        # YOLO (공유 모델 사용)

        self._roi_lock          = threading.Lock()
        self._correct_roi_id    = ""
        self._roi_active        = False
        self._current_fsm_state = "IDLE"

    def set_active(self, active):
        with self._roi_lock:
            self._is_active = active
        if not active:
            self._tracks = []

    def _init_calibration(self, w, h):
        self._undistort_map = _load_undistort_map(YOLO_CALIBRATION_PATH, w, h)
        if self._undistort_map:
            self.log_signal.emit("[캘리브레이션] 왜곡 보정 로드 완료.")
        else:
            self.log_signal.emit("[캘리브레이션] 파일 없음. 보정 미적용.")

    def _undistort(self, frame):
        if self._undistort_map is None:
            return frame
        return cv2.remap(frame, self._undistort_map[0], self._undistort_map[1], cv2.INTER_LINEAR)

    def _draw_yolo(self, frame, tracks):
        for t in tracks:
            cls_id = t['cls']
            x1, y1, x2, y2 = t['box']
            label = f"{COCO_CLASSES[cls_id]} {t['score']:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, label, (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        return frame

    # =========================================================================
    # [메인 스레드에서 호출]
    # =========================================================================
    def set_host(self, host):
        with self._roi_lock:
            self._host = host
        self._consecutive_failures = 0
        self._failure_signal_sent  = False

    def set_roi_config(self, correct_roi_id, active):
        with self._roi_lock:
            self._correct_roi_id = correct_roi_id
            self._roi_active     = active

    def set_fsm_state(self, state):
        with self._roi_lock:
            self._current_fsm_state = state

    # =========================================================================
    # [스레드 메인 루프]
    # =========================================================================
    def run(self):
        if self._mediapipe_ok:
            self.log_signal.emit("[MediaPipe] 손 추적 모듈 로드 완료.")
        else:
            self.log_signal.emit("[MediaPipe] 사용 불가! pip install mediapipe==0.10.14")

        if YOLO_AVAILABLE:
            self.log_signal.emit("[YOLO] 모델 로드 완료.")
        else:
            self.log_signal.emit("[YOLO] 사용 불가!")

        calibration_initialized = False

        while self._running:
            self.sock = self._connect_tcp()
            if self.sock is None:
                if not self._running:
                    break
                self.log_signal.emit(f"[카메라] {TCP_RECONNECT_DELAY_SEC:.0f}초 후 재연결...")
                time.sleep(TCP_RECONNECT_DELAY_SEC)
                continue

            try:
                while self._running:
                    data = self._recv_latest_frame()
                    if data is None:
                        break

                    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    if not calibration_initialized:
                        h, w = frame.shape[:2]
                        self._init_calibration(w, h)
                        calibration_initialized = True

                    frame = self._process_frame(frame)

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    self.change_pixmap_signal.emit(
                        QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
                    )

            except Exception as e:
                if self._running:
                    self.log_signal.emit(f"[카메라] 수신 오류: {e}")
            finally:
                if self.sock is not None:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                    self.sock = None

            if self._running:
                self.log_signal.emit(f"[카메라] 스트림 끊김. {TCP_RECONNECT_DELAY_SEC:.0f}초 후 재연결...")
                time.sleep(TCP_RECONNECT_DELAY_SEC)

        self.log_signal.emit("[카메라] 카메라 자원이 해제되었습니다.")

    # =========================================================================
    # [프레임 처리]
    # =========================================================================
    def _process_frame(self, frame):
        if CAMERA_FLIP_VERTICAL:
            frame = cv2.flip(frame, 0)

        with self._roi_lock:
            is_active       = self._is_active
            roi_active      = self._roi_active
            correct_roi_id  = self._correct_roi_id
            state           = self._current_fsm_state

        h, w, _ = frame.shape
        finger_in_roi = ""
        fingertip_pos = None

        if is_active:
            frame = self._undistort(frame)

            if YOLO_AVAILABLE:
                dets = _run_yolo_shared(frame)
                self._tracks = _update_tracks(self._tracks, dets)
                frame = self._draw_yolo(frame, self._tracks)
                self.yolo_detections_signal.emit([
                    (COCO_CLASSES[t['cls']], t['score'], *t['box']) for t in self._tracks
                ])

            if self._mediapipe_ok:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                results = self._hands.process(rgb)
                rgb.flags.writeable = True

                if results.multi_hand_landmarks:
                    for hand_lm in results.multi_hand_landmarks:
                        self._mp_draw.draw_landmarks(
                            frame, hand_lm, self._mp_hands.HAND_CONNECTIONS,
                            self._mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3),
                            self._mp_draw.DrawingSpec(color=(255, 255, 255), thickness=2),
                        )
                        idx_tip = hand_lm.landmark[self._mp_hands.HandLandmark.INDEX_FINGER_TIP]
                        fx = int(idx_tip.x * w)
                        fy = int(idx_tip.y * h)
                        fingertip_pos = (fx, fy)
                        cv2.circle(frame, (fx, fy), 12, (255, 0, 255), -1)
                        cv2.circle(frame, (fx, fy), 14, (255, 255, 255), 2)

        if not roi_active:
            self.finger_roi_signal.emit("")
            return frame

        for roi in BUTTON_ROIS:
            rx, ry, rw, rh = roi["rect"]
            x1, y1 = int(rx * w), int(ry * h)
            x2, y2 = int((rx + rw) * w), int((ry + rh) * h)

            is_correct  = (roi["id"] == correct_roi_id)
            is_hovered  = False
            if fingertip_pos is not None:
                fx, fy = fingertip_pos
                if x1 <= fx <= x2 and y1 <= fy <= y2:
                    is_hovered    = True
                    finger_in_roi = roi["id"]

            color      = (0, 200, 0) if is_correct else (0, 0, 200)
            label_text = f"{roi['label']} [정답]" if is_correct else roi["label"]

            overlay = frame.copy()
            alpha   = 0.30 if is_hovered else 0.12
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if is_hovered else 1)
            cv2.putText(frame, label_text, (x1 + 5, y1 + 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        if state == "WARNING" and int(time.time() * 4) % 2 == 0:
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 8)
        if state == "MONITORING":
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 255, 255), 4)

        if state and state != "IDLE":
            state_label  = FSM_STATES.get(state, {}).get("label", state)
            display_text = f"[{state_label}] {state}"
            text_size    = cv2.getTextSize(display_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            cv2.rectangle(frame, (8, 8), (18 + text_size[0], 18 + text_size[1]), (0, 0, 0), -1)
            cv2.putText(frame, display_text, (12, 12 + text_size[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        self.finger_roi_signal.emit(finger_in_roi)
        return frame

    # =========================================================================
    # [TCP 연결]
    # =========================================================================
    def _connect_tcp(self):
        with self._roi_lock:
            host = self._host
        try:
            self.log_signal.emit(f"[카메라] ESP32-S3 연결 시도: {host}:{CAMERA_TCP_PORT}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(TCP_RECV_TIMEOUT_SEC)
            sock.connect((host, CAMERA_TCP_PORT))
            self.log_signal.emit(f"[카메라] 연결 성공! ({host}:{CAMERA_TCP_PORT})")
            return sock
        except Exception as e:
            self.log_signal.emit(f"[카메라] TCP 연결 실패: {e}")
            return None

    def _recv_latest_frame(self):
        """Drain stale buffered frames, return only the most recent JPEG data."""
        while True:
            header = self._recv_exact(4)
            if header is None:
                return None
            length = struct.unpack('<I', header)[0]
            if length == 0 or length > TCP_MAX_FRAME_BYTES:
                self.log_signal.emit(f"[카메라] 비정상 프레임 크기({length}). 재연결합니다.")
                return None
            data = self._recv_exact(length)
            if data is None:
                return None
            readable, _, _ = select.select([self.sock], [], [], 0)
            if not readable:
                return data

    def _recv_exact(self, length):
        data = b''
        while len(data) < length:
            if not self._running:
                return None
            try:
                chunk = self.sock.recv(length - len(data))
            except socket.timeout:
                self.log_signal.emit("[카메라] 수신 타임아웃")
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def stop(self):
        self._running = False
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.wait()


# =============================================================================
# [UsbCameraThread] USB 웹캠 (CCTV)
# =============================================================================
class UsbCameraThread(QThread):
    change_pixmap_signal   = pyqtSignal(QImage)
    log_signal             = pyqtSignal(str)
    yolo_detections_signal = pyqtSignal(list)

    USB_DEVICE_INDEX = 0

    def __init__(self):
        super().__init__()
        self._running   = True
        self._is_active = False
        self._tracks    = []
        self._lock      = threading.Lock()

        # MediaPipe
        self._mediapipe_ok = False
        if MEDIAPIPE_AVAILABLE:
            try:
                self._mp_hands = mp.solutions.hands
                self._mp_draw  = mp.solutions.drawing_utils
                self._hands    = self._mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=1,
                    min_detection_confidence=0.7,
                    min_tracking_confidence=0.5,
                )
                self._mediapipe_ok = True
            except Exception as e:
                print(f"[MediaPipe/USB] init failed: {e}")

        # YOLO (공유 모델 사용)

    def set_active(self, active):
        with self._lock:
            self._is_active = active
        if not active:
            self._tracks = []

    def _process_frame(self, frame):
        with self._lock:
            is_active = self._is_active

        if not is_active:
            return frame

        h, w, _ = frame.shape

        if YOLO_AVAILABLE:
            dets = _run_yolo_shared(frame)
            self._tracks = _update_tracks(self._tracks, dets)
            for t in self._tracks:
                x1, y1, x2, y2 = t['box']
                label = f"{COCO_CLASSES[t['cls']]} {t['score']:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            self.yolo_detections_signal.emit([
                (COCO_CLASSES[t['cls']], t['score'], *t['box']) for t in self._tracks
            ])

        if self._mediapipe_ok:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = self._hands.process(rgb)
            rgb.flags.writeable = True
            if results.multi_hand_landmarks:
                for hand_lm in results.multi_hand_landmarks:
                    self._mp_draw.draw_landmarks(
                        frame, hand_lm, self._mp_hands.HAND_CONNECTIONS,
                        self._mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3),
                        self._mp_draw.DrawingSpec(color=(255, 255, 255), thickness=2),
                    )
                    idx_tip = hand_lm.landmark[self._mp_hands.HandLandmark.INDEX_FINGER_TIP]
                    fx = int(idx_tip.x * w)
                    fy = int(idx_tip.y * h)
                    cv2.circle(frame, (fx, fy), 12, (255, 0, 255), -1)
                    cv2.circle(frame, (fx, fy), 14, (255, 255, 255), 2)

        return frame

    def run(self):
        cap = cv2.VideoCapture(self.USB_DEVICE_INDEX)
        if not cap.isOpened():
            self.log_signal.emit("[CCTV] 웹캠 열기 실패")
            return
        self.log_signal.emit("[CCTV] USB 웹캠 연결 성공")
        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.03)
                continue
            frame = cv2.flip(frame, 1)
            frame = self._process_frame(frame)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            self.change_pixmap_signal.emit(
                QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
            )
        cap.release()
        self.log_signal.emit("[CCTV] USB 웹캠 해제")

    def stop(self):
        self._running = False
        self.wait()
