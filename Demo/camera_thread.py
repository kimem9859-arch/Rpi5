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

import config
from config import (
    CAMERA_FLIP_VERTICAL,
    CAMERA_TCP_HOST, CAMERA_TCP_PORT,
    TCP_RECV_TIMEOUT_SEC, TCP_RECONNECT_DELAY_SEC, TCP_MAX_FRAME_BYTES,
    CONNECT_MAX_TRIES,
    YOLO_CALIBRATION_PATH,
    YOLO_CONF_HIGH, YOLO_IOU_MATCH, YOLO_MAX_MISS,
)

# =============================================================================
# [손 검출]
# =============================================================================
from hand_tracker import HandTracker
import roi_zones

# =============================================================================
# [공구 검출] — 서브 작업(wait_tool) 동안만 도는 CPU 추론 (A-2)
# 설계 = ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md
# ⚠️ HandTracker 와 같은 방침 — 없으면 조용히 비활성되고 종전과 같이 동작한다.
# =============================================================================
try:
    from tool_gate import ToolGate
    TOOL_GATE_AVAILABLE = True
except Exception:                                    # noqa: BLE001
    ToolGate = None
    TOOL_GATE_AVAILABLE = False

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
def _labeled_boxes(tracks):
    """트랙 → [(라벨, x1, y1, x2, y2)] — roi_zones 가 받는 형식.

    디텍터 로드 실패 시엔 라벨을 붙일 수 없으므로 빈 목록. (그 경우 트랙도 안 쌓이지만,
    예전 코드가 '히트가 있을 때만' class_name 을 부르던 견고함을 유지한다.)
    """
    if _detector is None:
        return []
    return [(_detector.class_name(t['cls']), *t['box']) for t in tracks]


def zone_at_point(fx, fy, tracks, ring=None):
    """손끝(fx, fy) → (버튼 라벨, 단계). 2=박스 안 / 1=링 안 / (None, None)=밖.

    판정 규칙 정본은 `roi_zones.zone_at_point` 하나뿐이다 — 여기서 다시 구현하지 말 것.
    """
    if ring is None:
        ring = getattr(config, "HAND_ROI_RING_PX", 0)
    return roi_zones.zone_at_point(fx, fy, _labeled_boxes(tracks), ring)


def roi_at_point(fx, fy, tracks):
    """손끝이 들어있는 검출 버튼 박스의 라벨. 없으면 None. (링 없이 = 박스 안만)

    ⚠️ 시그니처를 유지한 호환용 얇은 래퍼다. 단계가 필요하면 `zone_at_point` 를 쓸 것.
    """
    return roi_zones.zone_at_point(fx, fy, _labeled_boxes(tracks), 0)[0]


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


def box_bgr(name, tool=False):
    """클래스 이름 → cv2 색(BGR).

    🔴 16진수를 뒤집는 곳은 **여기 하나뿐이다.** 두 군데가 되면 반드시 한쪽이
       틀린다(cv2 는 RGB 가 아니라 BGR 이다).
    색표 정본 = config.DETECT_BOX_COLORS · TOOL_BOX_COLORS (설계 §5.1)
    """
    table = config.TOOL_BOX_COLORS if tool else config.DETECT_BOX_COLORS
    h = table.get(name, config.DETECT_BOX_FALLBACK).lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


# =============================================================================
# [CameraThread] ESP32-S3 TCP 스트림
# =============================================================================
class CameraThread(QThread):
    change_pixmap_signal      = pyqtSignal(QImage)
    log_signal                = pyqtSignal(str)
    yolo_detections_signal    = pyqtSignal(list)
    roi_signal                = pyqtSignal(str, int)  # (버튼 ROI 라벨, 단계) — ""·0 = 없음
                                                     # 단계 2=박스 안(위험) / 1=링(접근). roi_zones 참조
    raw_frame_signal          = pyqtSignal(object)
    calibration_needed_signal = pyqtSignal()
    connect_failed_signal     = pyqtSignal(int)   # 연속 실패 횟수 — 알림용
    tool_signal               = pyqtSignal(list, object)  # (dets, fingertip) — A-2 공구 판정 입력
                                                 # dets = [(클래스명, 점수, x1,y1,x2,y2), ...]
                                                 # fingertip = 그 프레임의 손끝 (x,y) 또는 None
                                                 # 🔴 @pyqtSlot(list, object) 와 짝을 맞출 것
    hand_signal                = pyqtSignal(bool)      # 이 프레임에서 손이 검출됐는가 (집계 전용)

    def __init__(self):
        super().__init__()
        self._running            = True
        self.sock                = None
        self._host               = CAMERA_TCP_HOST
        self._is_active          = True
        self._draw_boxes         = config.SHOW_DETECT_BOXES
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

        # 재연결 제한 — 무한 재시도로 로그가 쌓이는 것을 막는다.
        self._fail_count   = 0
        self._give_up      = False
        self._retry_event  = threading.Event()

        # 손 검출 — MediaPipe 프레임워크는 Python 3.13/aarch64 휠이 없어 못 쓴다.
        # 대신 같은 모델(BlazePalm·BlazeHandLandmark)을 Hailo에서 돌린다(hand_tracker).
        # 모델이 없으면 조용히 비활성되고 detect()가 None을 주므로, 손 검출이 없던
        # 종전과 정확히 같게 동작한다.
        self._hand = HandTracker(log=lambda m: self.log_signal.emit(m))

        # 공구 검출(A-2) — 서브 작업(wait_tool) 동안에만 돈다. 상시 작업이 아니다.
        # ⚠️ UsbCameraThread 에는 넣지 않았다 — 시연은 ESP32 1인칭 기준이다.
        self._tool_gate = (ToolGate(log=lambda m: self.log_signal.emit(m))
                           if (TOOL_GATE_AVAILABLE and config.TOOL_ENABLED) else None)
        self._tool_scan = False
        self._tool_last = 0.0
        self._tool_dets = []          # 마지막 검출 결과 — 화면 표시용
        self._tool_dets_at = 0.0      # 그 결과가 온 시각(오래되면 지운다)

    def set_tool_scan(self, on):
        """공구 추론을 켜고 끈다 — `wait_tool` 서브 작업 동안에만 켠다.

        🔴 끄는 것을 빠뜨리면 워커가 계속 CPU 를 먹는다. 서브 작업이 끝나거나
           중단되는 **모든 경로**에서 꺼야 한다(safety_console 쪽 책임).
        """
        if self._tool_gate is None:
            if on:
                self.log_signal.emit("[공구] ⚠️ 비활성 — 공구 지참 단계가 "
                                     "자동으로 넘어가지 않습니다.")
            return
        self._tool_scan = bool(on)
        if on:
            self._tool_last = 0.0
            self._tool_gate.start()
        else:
            self._tool_gate.stop()
            self._tool_dets = []

    def set_active(self, active):
        with self._lock:
            self._is_active = active
            if not active:
                self._tracks = []

    def set_draw_boxes(self, on):
        """탐지 박스·손 랜드마크를 그릴지. 🔴 **표시만** 바뀐다 — 검출·판정은 그대로."""
        with self._lock:
            self._draw_boxes = bool(on)

    def draw_boxes(self):
        with self._lock:
            return self._draw_boxes

    def retry_connect(self):
        """수동 재연결 — 메뉴 → 점검(연결) 에서 부른다.

        자동 재시도를 포기한 뒤 다시 붙일 수 있는 **유일한 수단**이다.
        """
        self._fail_count = 0
        self._give_up = False
        self._retry_event.set()
        self.log_signal.emit("[카메라] 수동 재연결 시도")

    @property
    def gave_up(self):
        return self._give_up

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
            name = _detector.class_name(cls_id)
            color = box_bgr(name)
            label = f"{name} {t['score']:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        return frame

    def _draw_tools(self, frame):
        """공구 검출 박스를 그린다 — **표시 전용**.

        ⚠️ 박스 좌표는 최대 약 1초 전 프레임의 것이다(추론이 그만큼 걸린다).
           손이 움직이면 실물과 어긋나 보이는 것이 정상이며, 이 그림은 판정에
           쓰이지 않는다(판정 = tool_state, 입력 = 오버레이 없는 사본).
        🔴 공구는 **종류별 색**이고 버튼 5색과 겹치지 않는다(설계 §5.1).
        🔑 판정 단계(찾기/쥠)는 여기 그리지 않는다 — 게이지 패널이 한글·테마로
           맡는다(overlay.GaugePanel). cv2 는 한글을 못 그린다.
        """
        if time.time() - self._tool_dets_at > config.TOOL_SCAN_INTERVAL_SEC * 2:
            self._tool_dets = []      # 결과가 끊기면 유령 박스를 남기지 않는다

        for name, score, x1, y1, x2, y2 in self._tool_dets:
            p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
            color = box_bgr(name, tool=True)
            cv2.rectangle(frame, p1, p2, color, 2)
            cv2.putText(frame, f"{name} {score:.2f}", (p1[0], p1[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
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
        if not self._hand.available:
            self.log_signal.emit("[손검출] 비활성 — 버튼 검출만 동작합니다.")

        if DETECTOR_AVAILABLE:
            self.log_signal.emit(f"[Detector] '{_detector.backend_name}' 백엔드 로드 완료.")
        else:
            self.log_signal.emit("[Detector] 사용 불가!")

        calibration_initialized = False

        while self._running:
            # 🔴 무한 재시도 금지 — 3초마다 영원히 돌면 로그가 계속 쌓인다(3분에 약 60줄).
            #    CONNECT_MAX_TRIES 회 실패하면 멈추고 신호를 낸다. 다시 시도하려면
            #    메뉴 → 점검(연결) 에서 retry_connect() 를 부른다.
            if self._give_up:
                self._retry_event.wait(timeout=0.5)
                self._retry_event.clear()
                continue

            self.sock = self._connect_tcp()
            if self.sock is None:
                if not self._running:
                    break
                self._fail_count += 1
                if self._fail_count >= CONNECT_MAX_TRIES:
                    self._give_up = True
                    self.log_signal.emit(
                        f"[카메라] 🔴 {CONNECT_MAX_TRIES}회 연결 실패 — 자동 재시도를 멈춥니다. "
                        f"메뉴 → 점검(연결) 에서 다시 시도하세요.")
                    self.connect_failed_signal.emit(CONNECT_MAX_TRIES)
                    continue
                self.log_signal.emit(
                    f"[카메라] {TCP_RECONNECT_DELAY_SEC:.0f}초 후 재연결... "
                    f"({self._fail_count}/{CONNECT_MAX_TRIES})")
                time.sleep(TCP_RECONNECT_DELAY_SEC)
                continue

            self._fail_count = 0          # 붙었으면 카운터를 되돌린다

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
                        QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
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
            draw = self._draw_boxes

        if not is_active:
            return frame

        h, w, _ = frame.shape
        frame = self._undistort(frame)

        # 🔴 공구 추론에는 **오버레이가 없는 사본**을 보낸다 — 아래에서 버튼 박스와
        #    손 랜드마크가 frame 에 직접 그려지고, 그 선이 공구 위에 겹치면 검출이
        #    달라진다. 스캔 중일 때만 복사한다(매 프레임 복사는 낭비).
        tool_frame = (frame.copy()
                      if (self._tool_scan and self._tool_gate is not None) else None)

        if DETECTOR_AVAILABLE:
            dets = _detector.detect(frame)
            with self._lock:
                self._tracks = _update_tracks(self._tracks, dets)
                tracks = self._tracks
            if draw:
                frame = self._draw_yolo(frame, tracks)
            self.yolo_detections_signal.emit([
                (_detector.class_name(t['cls']), t['score'], *t['box']) for t in tracks
            ])

        # 손 검출 → 검지 끝. 랜드마크 표시는 hand_tracker 가 frame 에 직접 그린다.
        # 🔴 draw_on=None 이어도 검출은 그대로 한다 — 반환값(손끝)은 ROI 판정에 쓴다.
        fingertip = self._hand.detect(frame, draw_on=frame if draw else None)

        # 🔴 집계 전용이다 — 판정에 쓰지 않는다. roi_signal 은 ROI 라벨만 주므로
        #    「ROI 밖의 손」과 「손 없음」이 구별되지 않는다(설계 §3.6).
        self.hand_signal.emit(fingertip is not None)

        # 공구 검출(A-2) — 서브 작업 동안만. 🔑 손끝을 **같은 프레임의 것**으로
        # 함께 보낸다(§4.6 — 결과가 약 0.5초 뒤에 오므로 짝을 맞춰야 한다).
        if self._tool_scan and self._tool_gate is not None:
            now = time.time()
            if tool_frame is not None and now - self._tool_last >= config.TOOL_SCAN_INTERVAL_SEC:
                self._tool_last = now
                self._tool_gate.request(tool_frame, fingertip)
            # 🔴 request 는 1초에 한 번, poll 은 매 프레임이다 — poll 을 스로틀
            #    안에 넣으면 결과가 1초씩 더 늦는다.
            got = self._tool_gate.poll()
            if got is not None:
                self._tool_dets = got[0]
                self._tool_dets_at = now
                self.tool_signal.emit(got[0], got[1])
            if draw:
                frame = self._draw_tools(frame)

        # HOI → FSM: 손끝이 든 버튼 ROI 라벨을 통지 (없으면 "")
        roi, level = zone_at_point(*fingertip, self._tracks) if fingertip else (None, None)
        self.roi_signal.emit(roi or "", level or 0)

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
    roi_signal             = pyqtSignal(str, int)  # (버튼 ROI 라벨, 단계) — ""·0 = 없음
    hand_signal            = pyqtSignal(bool)      # 이 프레임에서 손이 검출됐는가 (집계 전용)

    USB_DEVICE_INDEX = 0

    def __init__(self):
        super().__init__()
        self._running   = True
        self._is_active = False
        self._draw_boxes = config.SHOW_DETECT_BOXES
        self._tracks    = []
        self._lock      = threading.Lock()

        # 손 검출 — Hailo 팜+핸드(MediaPipe 모델). 상세 = hand_tracker.py
        self._hand = HandTracker(log=lambda m: self.log_signal.emit(m))

    def set_active(self, active):
        with self._lock:
            self._is_active = active
            if not active:
                self._tracks = []

    def set_draw_boxes(self, on):
        """탐지 박스·손 랜드마크를 그릴지. 🔴 **표시만** 바뀐다 — 검출·판정은 그대로."""
        with self._lock:
            self._draw_boxes = bool(on)

    def draw_boxes(self):
        with self._lock:
            return self._draw_boxes

    def _process_frame(self, frame):
        with self._lock:
            is_active = self._is_active
            draw = self._draw_boxes

        if not is_active:
            return frame

        h, w, _ = frame.shape

        if DETECTOR_AVAILABLE:
            dets = _detector.detect(frame)
            with self._lock:
                self._tracks = _update_tracks(self._tracks, dets)
                tracks = self._tracks
            if draw:
                for t in tracks:
                    x1, y1, x2, y2 = t['box']
                    name = _detector.class_name(t['cls'])
                    color = box_bgr(name)
                    label = f"{name} {t['score']:.2f}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, y1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            self.yolo_detections_signal.emit([
                (_detector.class_name(t['cls']), t['score'], *t['box']) for t in self._tracks
            ])

        # 손 검출 → 검지 끝. 랜드마크 표시는 hand_tracker 가 frame 에 직접 그린다.
        # 🔴 draw_on=None 이어도 검출은 그대로 한다 — 반환값(손끝)은 ROI 판정에 쓴다.
        fingertip = self._hand.detect(frame, draw_on=frame if draw else None)

        # 🔴 집계 전용이다 — 판정에 쓰지 않는다. roi_signal 은 ROI 라벨만 주므로
        #    「ROI 밖의 손」과 「손 없음」이 구별되지 않는다(설계 §3.6).
        self.hand_signal.emit(fingertip is not None)

        roi, level = zone_at_point(*fingertip, self._tracks) if fingertip else (None, None)
        self.roi_signal.emit(roi or "", level or 0)

        return frame

    def run(self):
        # 🔴 이 스레드는 시작하자마자 /dev/video0 을 **점유**한다(CCTV 버튼과 무관).
        #    시나리오 촬영처럼 웹캠을 3인칭 기록용으로 따로 써야 할 때는
        #    config.USB_CAMERA_ENABLED=False 로 두어 장치를 놓아준다.
        if not getattr(config, "USB_CAMERA_ENABLED", True):
            self.log_signal.emit("[CCTV] 비활성(USB_CAMERA_ENABLED=False) — 웹캠을 외부에 양보")
            return
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
