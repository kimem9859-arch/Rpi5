import queue
import select
import socket
import struct
import threading
import time
import os

import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from config import (
    CAMERA_FLIP_VERTICAL,
    CAMERA_TCP_HOST, CAMERA_TCP_PORT,
    TCP_RECV_TIMEOUT_SEC, TCP_RECONNECT_DELAY_SEC, TCP_MAX_FRAME_BYTES,
    YOLO_CALIBRATION_PATH,
    YOLO_CONF_HIGH, YOLO_IOU_MATCH, YOLO_MAX_MISS,
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
# [Detector] config.INFERENCE_BACKEND selects PyTorch or Hailo backend
# =============================================================================
DETECTOR_AVAILABLE = False
_detector = None

try:
    from detector import create_detector
    _detector = create_detector()
    DETECTOR_AVAILABLE = True
    print(f"[Detector] '{_detector.backend_name}' 백엔드 로드 완료.")
except Exception as e:
    print(f"[Detector] 로드 실패: {e}")


def close_detector():
    """Release detector backend resources (Hailo device, pipeline, etc.)."""
    if _detector is not None:
        _detector.close()

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
# [HOI — 손-객체 상호작용] 손끝이 들어있는 버튼 박스의 라벨을 반환 (통합문서 §7.2)
# =============================================================================
def roi_at_point(fx, fy, tracks):
    """손끝(fx, fy)이 들어있는 검출 버튼 박스의 라벨을 반환. 없으면 None.

    ROI는 고정 좌표가 아니라 **YOLO가 검출한 버튼 박스 그 자체**다(FPV에서 박스가
    버튼을 따라다니므로 화면이 움직여도 유효). 박스가 겹치면 더 작은(가까운)
    박스를 우선해 오판을 줄인다.
    """
    hit, hit_area = None, None
    for t in tracks:
        x1, y1, x2, y2 = t['box']
        if x1 <= fx <= x2 and y1 <= fy <= y2:
            area = (x2 - x1) * (y2 - y1)
            if hit_area is None or area < hit_area:
                hit, hit_area = t, area
    return _detector.class_name(hit['cls']) if hit is not None else None


# =============================================================================
# [캘리브레이션 헬퍼]
# =============================================================================
def _load_undistort_map(path, w, h):
    if not os.path.exists(path):
        return None, 'missing'
    data = np.load(path)
    if 'image_size' in data:
        iw, ih = int(data['image_size'][0]), int(data['image_size'][1])
        if iw != w or ih != h:
            return None, 'mismatch'
    cam_mat = data['camera_matrix']
    dist    = data['dist_coeffs']
    new_mat, _ = cv2.getOptimalNewCameraMatrix(cam_mat, dist, (w, h), 1, (w, h))
    map1, map2 = cv2.initUndistortRectifyMap(cam_mat, dist, None, new_mat, (w, h), cv2.CV_16SC2)
    return (map1, map2), 'ok'


# =============================================================================
# [CameraThread] ESP32-S3 TCP 스트림
# =============================================================================
class CameraThread(QThread):
    change_pixmap_signal      = pyqtSignal(QImage)
    log_signal                = pyqtSignal(str)
    yolo_detections_signal    = pyqtSignal(list)
    roi_signal                = pyqtSignal(str)   # 손끝이 든 버튼 ROI 라벨 ("" = 없음)
    raw_frame_signal          = pyqtSignal(object)
    calibration_needed_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running            = True
        self.sock                = None
        self._host               = CAMERA_TCP_HOST
        self._is_active          = True
        self._tracks             = []
        self._undistort_map      = None
        self._lock               = threading.Lock()
        self._calibration_active = False
        self._last_frame_wh      = None

        # 지연 개선: 수신 전용 스레드 → 최신 프레임만 유지
        self._latest_raw   = None
        self._raw_lock     = threading.Lock()
        self._raw_event    = threading.Event()
        self._recv_error   = False

        self._mediapipe_ok = False
        if MEDIAPIPE_AVAILABLE:
            try:
                self._mp_hands = mp.solutions.hands
                self._mp_draw  = mp.solutions.drawing_utils
                self._hands    = self._mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=1,
                    model_complexity=1,
                    min_detection_confidence=0.85,
                    min_tracking_confidence=0.7,
                )
                self._mediapipe_ok = True
            except Exception as e:
                print(f"[MediaPipe] init failed: {e}")

    def set_active(self, active):
        with self._lock:
            self._is_active = active
        if not active:
            self._tracks = []

    def set_host(self, host):
        with self._lock:
            self._host = host

    # =========================================================================
    # [캘리브레이션]
    # =========================================================================
    def _init_calibration(self, w, h):
        maps, status = _load_undistort_map(YOLO_CALIBRATION_PATH, w, h)
        self._undistort_map = maps
        if status == 'missing':
            self.log_signal.emit("[캘리브레이션] 파일 없음. 재캘리브레이션 필요.")
            self.calibration_needed_signal.emit()
        elif status == 'mismatch':
            self.log_signal.emit("[캘리브레이션] 해상도 불일치. 재캘리브레이션 필요.")
            self.calibration_needed_signal.emit()
        else:
            self.log_signal.emit("[캘리브레이션] 왜곡 보정 로드 완료.")

    def reload_calibration(self):
        if self._last_frame_wh is None:
            return
        w, h = self._last_frame_wh
        maps, status = _load_undistort_map(YOLO_CALIBRATION_PATH, w, h)
        self._undistort_map = maps
        if status == 'ok':
            self.log_signal.emit("[캘리브레이션] 재로드 완료.")
        else:
            self.log_signal.emit(f"[캘리브레이션] 재로드 실패: {status}")

    def _undistort(self, frame):
        if self._undistort_map is None:
            return frame
        return cv2.remap(frame, self._undistort_map[0], self._undistort_map[1], cv2.INTER_LINEAR)

    # =========================================================================
    # [YOLO 드로잉]
    # =========================================================================
    def _draw_yolo(self, frame, tracks):
        for t in tracks:
            cls_id = t['cls']
            x1, y1, x2, y2 = t['box']
            label = f"{_detector.class_name(cls_id)} {t['score']:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, label, (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        return frame

    # =========================================================================
    # [수신 전용 스레드 — 최신 프레임을 _latest_raw에 계속 덮어씀]
    # =========================================================================
    def _recv_worker(self):
        while self._running:
            data = self._recv_latest_frame()
            if data is None:
                self._recv_error = True
                self._raw_event.set()
                break
            with self._raw_lock:
                self._latest_raw = data
            self._raw_event.set()

    # =========================================================================
    # [스레드 메인 루프]
    # =========================================================================
    def run(self):
        if self._mediapipe_ok:
            self.log_signal.emit("[MediaPipe] 손 추적 모듈 로드 완료.")
        else:
            self.log_signal.emit("[MediaPipe] 사용 불가! pip install mediapipe==0.10.14")

        if DETECTOR_AVAILABLE:
            self.log_signal.emit(f"[Detector] '{_detector.backend_name}' 백엔드 로드 완료.")
        else:
            self.log_signal.emit("[Detector] 사용 불가!")

        calibration_initialized = False

        while self._running:
            self.sock = self._connect_tcp()
            if self.sock is None:
                if not self._running:
                    break
                self.log_signal.emit(f"[카메라] {TCP_RECONNECT_DELAY_SEC:.0f}초 후 재연결...")
                time.sleep(TCP_RECONNECT_DELAY_SEC)
                continue

            self._recv_error = False
            self._raw_event.clear()
            recv_thread = threading.Thread(target=self._recv_worker, daemon=True)
            recv_thread.start()

            try:
                while self._running:
                    if not self._raw_event.wait(timeout=TCP_RECV_TIMEOUT_SEC):
                        self.log_signal.emit("[카메라] 수신 타임아웃")
                        break
                    self._raw_event.clear()

                    if self._recv_error:
                        break

                    with self._raw_lock:
                        data = self._latest_raw

                    if data is None:
                        continue

                    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    if not calibration_initialized:
                        h, w = frame.shape[:2]
                        self._last_frame_wh = (w, h)
                        self._init_calibration(w, h)
                        calibration_initialized = True

                    if self._calibration_active:
                        self.raw_frame_signal.emit(frame.copy())

                    frame = self._process_frame(frame)

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    self.change_pixmap_signal.emit(
                        QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
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
                recv_thread.join(timeout=3)

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

        with self._lock:
            is_active = self._is_active

        if not is_active:
            return frame

        h, w, _ = frame.shape
        frame = self._undistort(frame)

        if DETECTOR_AVAILABLE:
            dets = _detector.detect(frame)
            self._tracks = _update_tracks(self._tracks, dets)
            frame = self._draw_yolo(frame, self._tracks)
            self.yolo_detections_signal.emit([
                (_detector.class_name(t['cls']), t['score'], *t['box']) for t in self._tracks
            ])

        fingertip = None
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
                    fingertip = (fx, fy)

        # HOI → FSM: 손끝이 든 버튼 ROI 라벨을 통지 (없으면 "")
        roi = roi_at_point(*fingertip, self._tracks) if fingertip else None
        self.roi_signal.emit(roi or "")

        return frame

    # =========================================================================
    # [TCP 연결]
    # =========================================================================
    def _connect_tcp(self):
        with self._lock:
            host = self._host
        try:
            self.log_signal.emit(f"[카메라] ESP32-S3 연결 시도: {host}:{CAMERA_TCP_PORT}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
            sock.settimeout(TCP_RECV_TIMEOUT_SEC)
            sock.connect((host, CAMERA_TCP_PORT))
            self.log_signal.emit(f"[카메라] 연결 성공! ({host}:{CAMERA_TCP_PORT})")
            return sock
        except Exception as e:
            self.log_signal.emit(f"[카메라] TCP 연결 실패: {e}")
            return None

    def _recv_latest_frame(self):
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
            try:
                readable, _, _ = select.select([self.sock], [], [], 0)
            except OSError:
                # Socket closed by stop() during shutdown.
                return None
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
            except OSError:
                # Socket closed by stop() during shutdown.
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def stop(self):
        self._running = False
        self._raw_event.set()
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
    roi_signal             = pyqtSignal(str)   # 손끝이 든 버튼 ROI 라벨 ("" = 없음)

    USB_DEVICE_INDEX = 0

    def __init__(self):
        super().__init__()
        self._running   = True
        self._is_active = False
        self._tracks    = []
        self._lock      = threading.Lock()

        self._mediapipe_ok = False
        if MEDIAPIPE_AVAILABLE:
            try:
                self._mp_hands = mp.solutions.hands
                self._mp_draw  = mp.solutions.drawing_utils
                self._hands    = self._mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=1,
                    model_complexity=1,
                    min_detection_confidence=0.85,
                    min_tracking_confidence=0.7,
                )
                self._mediapipe_ok = True
            except Exception as e:
                print(f"[MediaPipe/USB] init failed: {e}")

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

        if DETECTOR_AVAILABLE:
            dets = _detector.detect(frame)
            self._tracks = _update_tracks(self._tracks, dets)
            for t in self._tracks:
                x1, y1, x2, y2 = t['box']
                label = f"{_detector.class_name(t['cls'])} {t['score']:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, label, (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            self.yolo_detections_signal.emit([
                (_detector.class_name(t['cls']), t['score'], *t['box']) for t in self._tracks
            ])

        fingertip = None
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
                    fingertip = (fx, fy)

        roi = roi_at_point(*fingertip, self._tracks) if fingertip else None
        self.roi_signal.emit(roi or "")

        return frame

    def run(self):
        cap = cv2.VideoCapture(self.USB_DEVICE_INDEX)
        if not cap.isOpened():
            self.log_signal.emit("[CCTV] 웹캠 열기 실패")
            return
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
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
                QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
            )
        cap.release()
        self.log_signal.emit("[CCTV] USB 웹캠 해제")

    def stop(self):
        self._running = False
        self.wait()
