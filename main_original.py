"""
=============================================================================
  Vision AI 기반 작업자 휴먼 에러 사전 예방 안전 콘솔
  - 메인 GUI 프로그램 (ROI 감시 모드: CUP/KEYBOARD/SOUND/MOUSE)
=============================================================================
  ROI 감시 모드에서는 MediaPipe로 손을 추적하고, 카메라 화면 위에 4개의 ROI 영역
  (CUP, KEYBOARD, SOUND, MOUSE)을 표시합니다. 손가락이 어떤 ROI에 진입하면
  자동으로 MONITORING → WARNING 전환을 수행합니다.

  구조:
    1) CameraThread  - 카메라 + MediaPipe 손 추적 + ROI 오버레이
    2) SafetyConsole - PyQt5 GUI + FSM 로직 + 손가락 ROI 감시
    3) main()        - 프로그램 실행 함수

  ROI 설정:
    - CUP: 좌측 상단 영역
    - KEYBOARD: 좌측 하단 영역
    - SOUND: 우측 상단 영역
    - MOUSE: 우측 하단 영역

  키보드 매핑:
    S = 작업 시작/선언
    G = 확인/진행
    5 = 리셋 (초기화)

  손가락 ROI 감시 로직:
    - 정답 ROI에 손 접근 → 자동 단계 완료 + 다음 단계 진행
    - 오답 ROI에 손 접근 → MONITORING (침묵 감시) → WARNING (경고)
    - 경고 중 손 이탈 → CAUTION (경계)
    - 경고 중 정답 ROI로 이동 → 행동 교정 + 단계 완료

  녹화 기능:
    - 프로그램 실행 시 자동으로 카메라 화면 녹화 시작
    - 저장 경로: C:/Users/kimem/Videos/abc
    - 파일명: YYYYMMDD_HHMMSS_recording.avi
=============================================================================
"""

# =============================================================================
# [Qt 플러그인 경로 수동 지정] - Windows에서 "Could not find Qt platform plugin" 오류 대응
# =============================================================================
import os
import sys

if sys.platform == "win32":
    for site_path in sys.path:
        plugin_path = os.path.join(site_path, "PyQt5", "Qt5", "plugins", "platforms")
        if os.path.exists(plugin_path):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path
            break

import socket
import struct
import time
from datetime import datetime

import cv2
import numpy as np

# ----- MediaPipe 임포트 (설치 안 되거나 버전/경로 문제 시에도 프로그램은 동작) -----
MEDIAPIPE_AVAILABLE = False
try:
    import mediapipe as mp
    # solutions API가 있는지 확인
    _test = mp.solutions.hands

    # =========================================================================
    # [Windows 한글 경로 문제 해결]
    # MediaPipe의 C++ 백엔드가 유니코드(한글 등) 경로를 인식하지 못하는 문제.
    # Windows 8.3 짧은 경로(Short Path Name)로 변환하여 우회합니다.
    # 예: "C:\Users\...\프로젝트\..." → "C:\Users\...\B74DE~1\..."
    # =========================================================================
    if sys.platform == "win32":
        import ctypes
        _mp_dir = os.path.dirname(mp.__file__)
        # 경로에 비ASCII 문자가 있으면 짧은 경로로 변환
        try:
            _mp_dir.encode("ascii")
        except UnicodeEncodeError:
            _kernel32 = ctypes.windll.kernel32
            _buf_size = _kernel32.GetShortPathNameW(_mp_dir, None, 0)
            if _buf_size > 0:
                _buf = ctypes.create_unicode_buffer(_buf_size)
                _kernel32.GetShortPathNameW(_mp_dir, _buf, _buf_size)
                _short = _buf.value
                if _short and _short != _mp_dir:
                    mp.__file__ = os.path.join(
                        _short, os.path.basename(mp.__file__)
                    )
                    if hasattr(mp, "__path__") and mp.__path__:
                        mp.__path__[0] = _short

    MEDIAPIPE_AVAILABLE = True
except (ImportError, AttributeError, Exception):
    MEDIAPIPE_AVAILABLE = False

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout,
    QLabel, QTextBrowser, QPushButton, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont


# =============================================================================
# [설정 상수] 화면 설정
# =============================================================================
WINDOW_WIDTH = 1280           # GUI 창 전체 가로 크기
WINDOW_HEIGHT = 720           # GUI 창 전체 세로 크기
CAMERA_FLIP_VERTICAL = True   # True: 상하 반전 (XIAO ESP32-S3 카메라 모듈 보정)

# =============================================================================
# [녹화 설정] 작업 화면 자동 녹화
# =============================================================================
RECORDING_ENABLED = True                       # True면 프로그램 시작 시 자동 녹화
RECORDING_SAVE_DIR = os.path.expanduser("~/Videos/recordings")  # 녹화 파일 저장 경로
RECORDING_FPS = 15.0                           # 녹화 FPS (카메라 FPS에 맞춤)
RECORDING_CODEC = "MJPG"                       # 녹화 코덱 (Linux 호환: MJPG=.avi)


# =============================================================================
# [FSM 상태 정의] 각 상태의 이름, 한글 설명, 배경색
# =============================================================================
FSM_STATES = {
    "IDLE": {
        "label": "대기",
        "color": "#2ecc71",
        "description": "초기 상태. 작업 대기 중.",
    },
    "RECIPE_LOAD": {
        "label": "준비",
        "color": "#3498db",
        "description": "작업 선언됨. [G]키로 레시피를 확인하세요.",
    },
    "RECIPE_LOADED": {
        "label": "준비 완료",
        "color": "#2980b9",
        "description": "레시피 로드 완료. [G]키로 작업을 시작하세요.",
    },
    "PROCESS_RUN": {
        "label": "작업 진행",
        "color": "#27ae60",
        "description": "작업 수행 중. 카메라로 손 위치를 감시합니다.",
    },
    "MONITORING": {
        "label": "감시 중",
        "color": "#f1c40f",
        "description": "오답 영역 진입 감지! 체류 시간 측정 중...",
    },
    "WARNING": {
        "label": "경고!",
        "color": "#e74c3c",
        "description": "경고 발생! 손을 떼세요!",
    },
    "CAUTION": {
        "label": "경계",
        "color": "#e67e22",
        "description": "위험 회피됨. 정답 ROI에 손을 가져가세요.",
    },
    "STEP_COMPLETE": {
        "label": "단계 완료",
        "color": "#9b59b6",
        "description": "정답 ROI 접근 완료! 1.5초 후 자동으로 다음 단계로 진행합니다.",
    },
}


# =============================================================================
# [ROI 설정] 카메라 화면 위의 가상 버튼 영역
# =============================================================================
# 각 ROI의 rect는 (x비율, y비율, 너비비율, 높이비율) - 카메라 해상도에 대한 비율
# 이렇게 하면 해상도가 바뀌어도 ROI 위치가 자동으로 조정됩니다.
ROI_THRESHOLD_SEC = 2.0       # ROI 체류 시 경고까지의 시간 (초)

# cup, keyboard, sound, mouse 4개 ROI 정의
# YOLO 형식 좌표를 ROI 형식으로 변환 (x_center, y_center, width, height) → (x_left, y_top, width, height)
# 객체 순서: ['cup', 'keyboard', 'mouse', 'sound']
# 변환 공식: x_left = x_center - width/2, y_top = y_center - height/2
BUTTON_ROIS = [
    # cup (0): x_center=0.1151, y_center=0.5976, width=0.2065, height=0.1946
    # x_left = 0.1151 - 0.2065/2 = 0.0119, y_top = 0.5976 - 0.1946/2 = 0.5003
    {"id": "cup", "label": "CUP", "rect": (0.0119, 0.5003, 0.2065, 0.1946)},
    # keyboard (1): x_center=0.4712, y_center=0.6280, width=0.4890, height=0.2573
    # x_left = 0.4712 - 0.4890/2 = 0.2267, y_top = 0.6280 - 0.2573/2 = 0.4993
    {"id": "keyboard", "label": "KEYBOARD", "rect": (0.2267, 0.4993, 0.4890, 0.2573)},
    # mouse (2): x_center=0.8305, y_center=0.6518, width=0.1245, height=0.2422
    # x_left = 0.8305 - 0.1245/2 = 0.7683, y_top = 0.6518 - 0.2422/2 = 0.5307
    {"id": "mouse", "label": "MOUSE", "rect": (0.7683, 0.5307, 0.1245, 0.2422)},
    # sound (3): x_center=0.6595, y_center=0.2513, width=0.1717, height=0.2557
    # x_left = 0.6595 - 0.1717/2 = 0.5736, y_top = 0.2513 - 0.2557/2 = 0.1235
    {"id": "sound", "label": "SOUND", "rect": (0.5736, 0.1235, 0.1717, 0.2557)},
]


# =============================================================================
# [시뮬레이션 공정 단계] 레시피 정의 (ROI 감시 모드)
# =============================================================================
# correct_roi: 해당 단계에서 접근해야 하는 정답 ROI의 id
# ROI 감시 모드에서는 모든 ROI를 감시하며, 손이 다가가면 반응합니다.
DEMO_RECIPE = [
    {"step": 1, "name": "CUP 접근", "correct_roi": "cup"},
    {"step": 2, "name": "KEYBOARD 접근", "correct_roi": "keyboard"},
    {"step": 3, "name": "SOUND 접근", "correct_roi": "sound"},
    {"step": 4, "name": "MOUSE 접근", "correct_roi": "mouse"},
]


# =============================================================================
# [카메라 소스 설정] - ESP32-S3 TCP 스트림
# =============================================================================
# camera_stream_tcp.ino가 동작하는 ESP32-S3의 IP/포트
# 시리얼 모니터에서 IP 확인 후 변경하세요.
CAMERA_TCP_IP   = "10.220.25.235"
CAMERA_TCP_PORT = 8888
TCP_RECV_TIMEOUT_SEC = 10.0       # 소켓 수신 타임아웃
TCP_RECONNECT_DELAY_SEC = 3.0     # 끊김 시 재연결 대기 시간
TCP_MAX_FRAME_BYTES = 200000      # 비정상 프레임 차단 임계값


# =============================================================================
# [클래스] CameraThread - 카메라 + MediaPipe 손 추적 + ROI 오버레이
# =============================================================================
class CameraThread(QThread):
    """
    카메라 프레임을 읽고, MediaPipe로 손을 추적하며, ROI 오버레이를 그리는 스레드.
    - change_pixmap_signal: 처리된 프레임(QImage)을 GUI에 전달
    - log_signal: 로그 메시지를 GUI에 전달
    - finger_roi_signal: 검지 끝이 위치한 ROI id를 GUI에 전달 (없으면 빈 문자열)
    """

    change_pixmap_signal = pyqtSignal(QImage)
    log_signal = pyqtSignal(str)
    finger_roi_signal = pyqtSignal(str)    # 검지가 어느 ROI에 있는지 (매 프레임)

    def __init__(self):
        super().__init__()
        self._running = True
        self.sock = None
        self._last_log_time = 0

        # ----- MediaPipe 초기화 (한글 경로 등 런타임 오류 대비 try-except) -----
        self._mediapipe_ok = False
        if MEDIAPIPE_AVAILABLE:
            try:
                self._mp_hands = mp.solutions.hands
                self._mp_draw = mp.solutions.drawing_utils
                self._mp_draw_styles = mp.solutions.drawing_styles
                self._hands = self._mp_hands.Hands(
                    static_image_mode=False,
                    max_num_hands=1,
                    min_detection_confidence=0.7,
                    min_tracking_confidence=0.5,
                )
                self._mediapipe_ok = True
            except Exception as e:
                print(f"[MediaPipe 초기화 실패] {e}")
                self._mediapipe_ok = False

        # ----- ROI 설정 (메인 스레드에서 쓰고 카메라 스레드에서 읽음 → Lock 보호) -----
        import threading
        self._roi_lock = threading.Lock()
        self._correct_roi_id = ""
        self._roi_active = False
        self._current_fsm_state = "IDLE"

    # =========================================================================
    # [메인 스레드에서 호출] ROI 및 상태 설정 함수들
    # =========================================================================
    def set_roi_config(self, correct_roi_id, active):
        with self._roi_lock:
            self._correct_roi_id = correct_roi_id
            self._roi_active = active

    def set_fsm_state(self, state):
        with self._roi_lock:
            self._current_fsm_state = state

    # =========================================================================
    # [스레드 메인 루프] - ESP32-S3 TCP 스트림 수신
    # =========================================================================
    def run(self):
        """ESP32-S3에 TCP 연결하고 프레임을 수신하여 처리한 뒤 시그널로 전달합니다."""
        if self._mediapipe_ok:
            self.log_signal.emit("[MediaPipe] 손 추적 모듈 로드 완료.")
        else:
            self.log_signal.emit(
                "[MediaPipe] 사용 불가! (미설치 또는 버전 문제) "
                "pip install mediapipe==0.10.14"
            )

        while self._running:
            # ----- TCP 연결 시도 -----
            self.sock = self._connect_tcp()
            if self.sock is None:
                if not self._running:
                    break
                self.log_signal.emit(
                    f"[카메라] 재연결 {TCP_RECONNECT_DELAY_SEC:.0f}초 후 재시도..."
                )
                time.sleep(TCP_RECONNECT_DELAY_SEC)
                continue

            # ----- 프레임 수신 루프 -----
            try:
                while self._running:
                    # 4바이트 헤더(JPEG 길이) 수신
                    header = self._recv_exact(4)
                    if header is None:
                        break

                    length = struct.unpack('<I', header)[0]
                    if length == 0 or length > TCP_MAX_FRAME_BYTES:
                        self.log_signal.emit(
                            f"[카메라] 비정상 프레임 크기({length}). 재연결합니다."
                        )
                        break

                    # JPEG 데이터 수신
                    data = self._recv_exact(length)
                    if data is None:
                        break

                    # JPEG → numpy 디코딩
                    frame = cv2.imdecode(
                        np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR
                    )
                    if frame is None:
                        # 깨진 프레임은 건너뜀
                        continue

                    # ====================================================
                    # [핵심] 프레임 처리: 반전 → MediaPipe 손 추적 → ROI 그리기
                    # ====================================================
                    frame = self._process_frame(frame)

                    # BGR → RGB 변환 후 QImage로 전달
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(
                        rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888
                    )
                    self.change_pixmap_signal.emit(qt_image)
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
                self.log_signal.emit(
                    f"[카메라] 스트림 끊김. {TCP_RECONNECT_DELAY_SEC:.0f}초 후 재연결..."
                )
                time.sleep(TCP_RECONNECT_DELAY_SEC)

        self.log_signal.emit("[카메라] 카메라 자원이 해제되었습니다.")

    # =========================================================================
    # [프레임 처리] MediaPipe 손 추적 + ROI 오버레이
    # =========================================================================
    def _process_frame(self, frame):
        """
        한 프레임에 대해 다음을 수행합니다:
        1) 좌우 반전 (셀카 모드 대응)
        2) MediaPipe로 손 감지 및 뼈대 그리기
        3) 검지 끝 좌표 추출
        4) ROI 박스 그리기 (정답=초록, 오답=빨강)
        5) 검지가 어느 ROI에 있는지 판별하여 시그널 전송
        6) 현재 FSM 상태에 따른 시각 효과 (WARNING 시 빨간 테두리 점멸)

        Returns:
            처리된 프레임 (numpy array, BGR)
        """
        # ----- 1) 상하 반전 (ESP32-S3 카메라 방향 보정) -----
        if CAMERA_FLIP_VERTICAL:
            frame = cv2.flip(frame, 0)

        h, w, _ = frame.shape
        finger_in_roi = ""       # 검지가 위치한 ROI id (없으면 빈 문자열)
        fingertip_pos = None     # 검지 끝 좌표 (x, y)

        # ----- 2) MediaPipe 손 감지 -----
        if self._mediapipe_ok:
            # MediaPipe는 RGB 입력을 요구함
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False    # 성능 최적화 (복사 방지)
            results = self._hands.process(rgb)
            rgb.flags.writeable = True

            if results.multi_hand_landmarks:
                for hand_lm in results.multi_hand_landmarks:
                    # ----- 손 뼈대 그리기 -----
                    self._mp_draw.draw_landmarks(
                        frame, hand_lm, self._mp_hands.HAND_CONNECTIONS,
                        # 관절 점: 초록색 원
                        self._mp_draw.DrawingSpec(
                            color=(0, 255, 0), thickness=2, circle_radius=3
                        ),
                        # 연결선: 흰색 선
                        self._mp_draw.DrawingSpec(
                            color=(255, 255, 255), thickness=2
                        ),
                    )

                    # ----- 검지 끝(INDEX_FINGER_TIP, id=8) 좌표 추출 -----
                    idx_tip = hand_lm.landmark[
                        self._mp_hands.HandLandmark.INDEX_FINGER_TIP
                    ]
                    fx = int(idx_tip.x * w)
                    fy = int(idx_tip.y * h)
                    fingertip_pos = (fx, fy)

                    # 검지 끝에 보라색 원 + 흰색 테두리 표시
                    cv2.circle(frame, (fx, fy), 12, (255, 0, 255), -1)
                    cv2.circle(frame, (fx, fy), 14, (255, 255, 255), 2)

        # ----- 3) ROI 박스 그리기 및 충돌 검사 (공유 변수를 Lock으로 읽음) -----
        with self._roi_lock:
            roi_active = self._roi_active
            correct_roi_id = self._correct_roi_id
            state = self._current_fsm_state

        if roi_active:
            for roi in BUTTON_ROIS:
                rx, ry, rw, rh = roi["rect"]
                x1, y1 = int(rx * w), int(ry * h)
                x2, y2 = int((rx + rw) * w), int((ry + rh) * h)

                is_correct = (roi["id"] == correct_roi_id)

                # 검지가 이 ROI 안에 있는지 확인
                is_hovered = False
                if fingertip_pos is not None:
                    fx, fy = fingertip_pos
                    if x1 <= fx <= x2 and y1 <= fy <= y2:
                        is_hovered = True
                        finger_in_roi = roi["id"]

                # --- 색상 결정 ---
                if is_correct:
                    color = (0, 200, 0)      # 초록 = 정답
                    label_text = f"{roi['label']} [정답]"
                else:
                    color = (0, 0, 200)      # 빨강 = 오답
                    label_text = roi["label"]

                # --- 반투명 배경 채우기 ---
                overlay = frame.copy()
                alpha = 0.30 if is_hovered else 0.12
                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
                frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

                # --- 테두리 (호버 시 두꺼워짐) ---
                thickness = 3 if is_hovered else 1
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

                # --- 라벨 텍스트 ---
                cv2.putText(
                    frame, label_text, (x1 + 5, y1 + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2
                )

        # ROI 비활성 상태(IDLE 등)면 시그널만 보내고 종료
        if not roi_active:
            self.finger_roi_signal.emit("")
            return frame

        # ----- 4) WARNING 시각 효과: 화면 테두리 빨간색 점멸 -----
        if state == "WARNING":
            # 4Hz로 깜빡임 (0.25초 간격)
            if int(time.time() * 4) % 2 == 0:
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 8)

        # ----- 5) MONITORING 시각 효과: 노란색 테두리 -----
        if state == "MONITORING":
            cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 255, 255), 4)

        # ----- 6) 상태 텍스트 오버레이 (좌상단) -----
        if state and state != "IDLE":
            state_label = FSM_STATES.get(state, {}).get("label", state)
            display_text = f"[{state_label}] {state}"
            # 검정 배경 박스
            text_size = cv2.getTextSize(
                display_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
            )[0]
            cv2.rectangle(
                frame, (8, 8), (18 + text_size[0], 18 + text_size[1]),
                (0, 0, 0), -1
            )
            cv2.putText(
                frame, display_text, (12, 12 + text_size[1]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
            )

        # ----- 7) 검지 ROI 정보 시그널 전송 -----
        self.finger_roi_signal.emit(finger_in_roi)

        return frame

    # =========================================================================
    # [TCP 연결] ESP32-S3 카메라 서버에 접속
    # =========================================================================
    def _connect_tcp(self):
        """ESP32-S3에 TCP 연결을 시도합니다. 실패 시 None 반환."""
        try:
            self.log_signal.emit(
                f"[카메라] ESP32-S3 TCP 연결 시도: {CAMERA_TCP_IP}:{CAMERA_TCP_PORT}"
            )
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(TCP_RECV_TIMEOUT_SEC)
            sock.connect((CAMERA_TCP_IP, CAMERA_TCP_PORT))
            self.log_signal.emit(
                f"[카메라] ESP32-S3 연결 성공! ({CAMERA_TCP_IP}:{CAMERA_TCP_PORT})"
            )
            return sock
        except Exception as e:
            self.log_signal.emit(f"[카메라] TCP 연결 실패: {e}")
            return None

    def _recv_exact(self, length):
        """소켓에서 정확히 length 바이트를 읽어 반환합니다. 끊기면 None."""
        data = b''
        while len(data) < length:
            if not self._running:
                return None
            try:
                chunk = self.sock.recv(length - len(data))
            except socket.timeout:
                # 타임아웃이 나면 None을 반환해 재연결 트리거
                self.log_signal.emit("[카메라] 수신 타임아웃")
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def stop(self):
        """스레드를 안전하게 종료합니다."""
        self._running = False
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.wait()


# =============================================================================
# [클래스] SafetyConsole - 메인 GUI + FSM 로직 + 손가락 ROI 감시
# =============================================================================
class SafetyConsole(QMainWindow):
    """
    메인 윈도우 클래스.
    - 좌측: 카메라 영상 (MediaPipe 손 뼈대 + ROI 오버레이)
    - 우측: FSM 상태 라벨 + 단계 표시 + 로그 + 키 안내 + 버튼
    - 손가락 ROI 감시: MONITORING → WARNING → CAUTION 자동 전환
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Vision AI 안전 콘솔 - ROI 감시 모드 (CUP/KEYBOARD/SOUND/MOUSE)")
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        # =====================================================================
        # [FSM 변수]
        # =====================================================================
        self.current_state = "IDLE"
        self.recipe = []
        self.current_step_index = 0

        # =====================================================================
        # [모니터링 변수] 손가락 ROI 체류 시간 감시용
        # =====================================================================
        self._current_finger_roi = ""        # 현재 검지가 위치한 ROI id
        self._monitoring_start_time = None   # 오답 ROI 진입 시각 (time.time())
        self._monitoring_roi_id = ""         # 감시 중인 오답 ROI id

        # ----- 모니터링 타이머: 100ms마다 체류 시간을 체크 -----
        self._monitor_timer = QTimer()
        self._monitor_timer.setInterval(100)
        self._monitor_timer.timeout.connect(self._check_monitoring_timeout)

        # ----- 자동 진행 타이머: 단계 완료 후 잠시 뒤 자동으로 다음 단계 진행 -----
        self._auto_advance_timer = QTimer()
        self._auto_advance_timer.setSingleShot(True)       # 한 번만 실행
        self._auto_advance_timer.setInterval(1500)          # 1.5초 후 자동 진행
        self._auto_advance_timer.timeout.connect(self._auto_advance_to_next_step)

        # =====================================================================
        # [녹화 변수] GUI 창 전체를 녹화하기 위한 변수
        # =====================================================================
        self._video_writer = None         # cv2.VideoWriter 객체
        self._recording = False           # 녹화 진행 중 여부
        self._recording_path = ""         # 현재 녹화 파일 경로

        # ----- 녹화 타이머: RECORDING_FPS에 맞춰 창 캡처 -----
        self._recording_timer = QTimer()
        recording_interval = int(1000 / RECORDING_FPS)  # ms 단위 (예: 15fps → 약 66ms)
        self._recording_timer.setInterval(recording_interval)
        self._recording_timer.timeout.connect(self._capture_window_frame)

        # ----- UI 구성 -----
        self._init_ui()

        # ----- 카메라 스레드 생성 및 시작 -----
        self.camera_thread = CameraThread()
        self.camera_thread.change_pixmap_signal.connect(self._update_camera_frame)
        self.camera_thread.log_signal.connect(self._append_log)
        self.camera_thread.finger_roi_signal.connect(self._on_finger_roi_update)
        self.camera_thread.start()

        # ----- 시작 로그 -----
        self._append_log("[시스템] Vision AI 안전 콘솔 시작 (ROI 감시 모드)")
        self._append_log(f"[시스템] 시뮬레이션 모드: {IS_SIMULATION}")
        self._append_log(f"[시스템] MediaPipe 사용 가능: {MEDIAPIPE_AVAILABLE}")
        self._append_log(f"[시스템] ROI 경고 임계 시간: {ROI_THRESHOLD_SEC}초")
        self._append_log(
            f"[시스템] ESP32-S3 카메라: {CAMERA_TCP_IP}:{CAMERA_TCP_PORT} (TCP)"
        )
        self._append_log("─" * 40)
        self._append_log("[ROI 설정] 감시 대상:")
        for roi in BUTTON_ROIS:
            self._append_log(f"  - {roi['label']} ({roi['id']})")
        self._append_log("─" * 40)
        self._append_log("[안내] 조작법:")
        self._append_log("  [S] 작업 시작  →  [G] 확인/진행  →  [5] 리셋")
        self._append_log("[안내] ROI 감시 모드:")
        self._append_log("  - 정답 ROI에 손 접근 → 자동으로 단계 완료 + 다음 단계 진행")
        self._append_log("  - 오답 ROI에 손 접근 → 경고 발생!")
        self._append_log("─" * 40)

        # ----- 녹화 자동 시작 (창이 표시된 직후 시작하도록 0.5초 딜레이) -----
        if RECORDING_ENABLED:
            QTimer.singleShot(500, self._start_recording)

    # =========================================================================
    # [UI 초기화] - Phase 2와 동일한 레이아웃
    # =========================================================================
    def _init_ui(self):
        """GUI 레이아웃 초기화."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        # ----- 왼쪽: 카메라 영상 (70%) -----
        self.camera_label = QLabel("카메라 연결 대기 중...")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setStyleSheet(
            "background-color: #1a1a2e; color: #aaaaaa; font-size: 18px;"
            "border: 2px solid #333333; border-radius: 8px;"
        )
        self.camera_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ----- 오른쪽 영역 -----
        right_layout = QVBoxLayout()

        # 1) 상태 라벨
        self.state_label = QLabel()
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setFont(QFont("Noto Sans CJK KR", 20, QFont.Bold))
        self.state_label.setFixedHeight(100)
        self._apply_state_style()

        # 2) 단계 정보 라벨
        self.step_label = QLabel("작업 대기 중")
        self.step_label.setAlignment(Qt.AlignCenter)
        self.step_label.setFont(QFont("Noto Sans CJK KR", 13))
        self.step_label.setFixedHeight(50)
        self.step_label.setStyleSheet(
            "background-color: #1e3a5f; color: #d4d4d4;"
            "border-radius: 6px; padding: 6px;"
        )

        # 3) 로그 창
        self.log_browser = QTextBrowser()
        self.log_browser.setFont(QFont("Consolas", 10))
        self.log_browser.setStyleSheet(
            "background-color: #0d1117; color: #58a6ff;"
            "border: 1px solid #30363d; border-radius: 6px; padding: 8px;"
        )
        self.log_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 4) 키 안내 라벨
        self.key_guide_label = QLabel()
        self.key_guide_label.setAlignment(Qt.AlignCenter)
        self.key_guide_label.setFont(QFont("Noto Sans CJK KR", 11))
        self.key_guide_label.setFixedHeight(36)
        self.key_guide_label.setStyleSheet(
            "background-color: #1a1a2e; color: #888888;"
            "border-radius: 4px; padding: 4px;"
        )
        self._update_key_guide()

        # 5) 제어 버튼
        button_layout = QHBoxLayout()
        btn_style = (
            "font-size: 13px; font-weight: bold;"
            "padding: 10px 6px; border-radius: 8px; color: white;"
        )

        self.btn_start = QPushButton("S 작업 시작")
        self.btn_start.setStyleSheet(btn_style + "background-color: #e74c3c;")
        self.btn_start.clicked.connect(self._on_key_s)

        self.btn_confirm = QPushButton("G 확인/진행")
        self.btn_confirm.setStyleSheet(btn_style + "background-color: #3498db;")
        self.btn_confirm.clicked.connect(self._on_key_g)

        self.btn_reset = QPushButton("5 리셋")
        self.btn_reset.setStyleSheet(btn_style + "background-color: #e67e22;")
        self.btn_reset.clicked.connect(self._on_key_5)

        button_layout.addWidget(self.btn_start)
        button_layout.addWidget(self.btn_confirm)
        button_layout.addWidget(self.btn_reset)

        # ----- 레이아웃 조립 -----
        right_layout.addWidget(self.state_label)
        right_layout.addWidget(self.step_label)
        right_layout.addWidget(self.log_browser)
        right_layout.addWidget(self.key_guide_label)
        right_layout.addLayout(button_layout)

        main_layout.addWidget(self.camera_label, stretch=7)
        main_layout.addLayout(right_layout, stretch=3)

    # =========================================================================
    # [슬롯] 카메라 프레임 업데이트
    # =========================================================================
    @pyqtSlot(QImage)
    def _update_camera_frame(self, qt_image):
        """카메라 프레임을 라벨에 표시합니다."""
        scaled_image = qt_image.scaled(
            self.camera_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.camera_label.setPixmap(QPixmap.fromImage(scaled_image))

    # =========================================================================
    # [슬롯] 로그 메시지 추가
    # =========================================================================
    @pyqtSlot(str)
    def _append_log(self, message):
        """로그 창에 타임스탬프와 함께 메시지를 추가하고, 최신 로그로 자동 스크롤합니다."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_browser.append(f"[{timestamp}] {message}")
        # 스크롤바를 맨 아래로 이동 (최신 로그가 항상 보이도록)
        scrollbar = self.log_browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # =========================================================================
    # [FSM 핵심] 상태 전환 함수
    # =========================================================================
    def _change_state(self, new_state):
        """
        FSM 상태를 전환합니다.
        - 상태 라벨 업데이트
        - 로그 기록
        - 카메라 스레드에 상태 전달 (시각 효과용)
        - 키 안내 업데이트
        """
        old_state = self.current_state
        self.current_state = new_state

        self._apply_state_style()

        state_info = FSM_STATES[new_state]
        self._append_log(
            f"[FSM] {old_state} → {new_state} ({state_info['label']})"
        )
        self._append_log(f"  ↳ {state_info['description']}")

        # 카메라 스레드에 현재 상태 전달 (WARNING 점멸 등 시각 효과)
        self.camera_thread.set_fsm_state(new_state)

        self._update_key_guide()

    def _apply_state_style(self):
        """현재 상태에 맞게 상태 라벨의 텍스트와 색상을 적용합니다."""
        state_info = FSM_STATES[self.current_state]
        self.state_label.setText(
            f"{state_info['label']}\n{self.current_state}"
        )
        self.state_label.setStyleSheet(
            f"background-color: {state_info['color']};"
            "color: white; border-radius: 10px; padding: 10px;"
        )

    def _update_step_label(self):
        """현재 진행 중인 단계 정보를 표시합니다."""
        if not self.recipe:
            self.step_label.setText("작업 대기 중")
            self.step_label.setStyleSheet(
                "background-color: #1e3a5f; color: #d4d4d4;"
                "border-radius: 6px; padding: 6px;"
            )
            return

        if self.current_step_index >= len(self.recipe):
            self.step_label.setText("모든 단계 완료!")
            self.step_label.setStyleSheet(
                "background-color: #1e5a3a; color: #2ecc71;"
                "border-radius: 6px; padding: 6px; font-weight: bold;"
            )
            return

        step = self.recipe[self.current_step_index]
        total = len(self.recipe)
        # 정답 ROI 이름도 표시 (어떤 버튼을 눌러야 하는지)
        correct_roi_label = ""
        for roi in BUTTON_ROIS:
            if roi["id"] == step.get("correct_roi", ""):
                correct_roi_label = roi["label"]
                break
        self.step_label.setText(
            f"[{step['step']}/{total}] {step['name']}  →  {correct_roi_label}"
        )
        self.step_label.setStyleSheet(
            "background-color: #1e3a5f; color: #d4d4d4;"
            "border-radius: 6px; padding: 6px;"
        )

    def _update_key_guide(self):
        """현재 FSM 상태에서 안내 메시지를 표시합니다."""
        guide_map = {
            "IDLE":           "▶ [S] 작업 시작",
            "RECIPE_LOAD":    "▶ [G] 레시피 확인",
            "RECIPE_LOADED":  "▶ [G] 작업 시작",
            "PROCESS_RUN":    "▶ 정답 ROI에 손을 가져가세요 (오답 ROI 접근 시 경고!)",
            "MONITORING":     "▶ 오답 ROI 감시 중... 손을 떼세요!",
            "WARNING":        "▶ 경고! 오답 ROI 체류 초과! 정답 ROI로 이동하세요!",
            "CAUTION":        "▶ 위험 회피됨. 정답 ROI에 손을 가져가세요.",
            "STEP_COMPLETE":  "▶ 단계 완료! 다음 단계로 자동 진행 중...",
            "ERROR_LOG":      "▶ [5] 리셋 필요",
        }
        guide_text = guide_map.get(self.current_state, "")
        if self.current_state != "IDLE":
            guide_text += "  |  [5] 리셋"
        self.key_guide_label.setText(guide_text)

    # =========================================================================
    # [카메라 ROI 설정 갱신] 단계 변경 시 카메라 스레드에 정답 ROI 전달
    # =========================================================================
    def _update_camera_roi(self):
        """
        현재 레시피 단계에 맞게 카메라 스레드의 ROI 설정을 갱신합니다.
        PROCESS_RUN 상태일 때만 ROI 감시를 활성화합니다.
        """
        if self.recipe and self.current_step_index < len(self.recipe):
            step = self.recipe[self.current_step_index]
            correct_roi = step.get("correct_roi", "")
            # PROCESS_RUN 관련 상태에서만 ROI 표시 활성화
            active = self.current_state in (
                "PROCESS_RUN", "MONITORING", "WARNING", "CAUTION"
            )
            self.camera_thread.set_roi_config(correct_roi, active)
        else:
            self.camera_thread.set_roi_config("", False)

    # =========================================================================
    # [Phase 3 핵심] 손가락 ROI 감시 로직
    # =========================================================================
    # =========================================================================
    # [헬퍼] ROI id로 라벨 이름을 가져오는 함수
    # =========================================================================
    def _get_roi_label(self, roi_id):
        """ROI id에 해당하는 라벨 이름을 반환합니다."""
        for roi in BUTTON_ROIS:
            if roi["id"] == roi_id:
                return roi["label"]
        return ""

    @pyqtSlot(str)
    def _on_finger_roi_update(self, roi_id):
        """
        카메라 스레드에서 매 프레임마다 전달되는 검지 위치 ROI 정보를 처리합니다.
        ROI가 변경되었을 때만 실제 로직을 수행합니다 (매 프레임 중복 처리 방지).

        핵심 로직:
        - 정답 ROI 진입 → 자동으로 단계 완료 + 다음 단계 진행
        - 오답 ROI 진입 → MONITORING (침묵 감시) → WARNING (경고)
        - WARNING 후 이탈 → CAUTION (경계) → PROCESS_RUN 복귀
        """
        # ROI가 바뀌지 않았으면 무시 (성능 최적화)
        if roi_id == self._current_finger_roi:
            return

        self._current_finger_roi = roi_id

        state = self.current_state

        # 작업 관련 상태가 아니면 무시
        if state not in ("PROCESS_RUN", "MONITORING", "WARNING", "CAUTION"):
            return

        # 현재 단계의 정답 ROI 확인
        correct_roi = ""
        if self.recipe and self.current_step_index < len(self.recipe):
            correct_roi = self.recipe[self.current_step_index].get("correct_roi", "")

        # ROI 이름 가져오기 (로그용)
        roi_label = self._get_roi_label(roi_id)

        # =====================================================================
        # [PROCESS_RUN] 작업 중
        #   - 정답 ROI 진입 → 자동 단계 완료
        #   - 오답 ROI 진입 → MONITORING 시작
        # =====================================================================
        if state == "PROCESS_RUN":
            if roi_id == correct_roi:
                # ★ 정답 ROI에 손이 진입 → 자동으로 단계 완료!
                self._append_log(f"[정답 접근] 정답 ROI '{roi_label}'에 접근 성공!")
                self._auto_complete_step()
            elif roi_id != "":
                # 오답 ROI에 손이 진입 → MONITORING 시작 (경고 대기)
                self._monitoring_start_time = time.time()
                self._monitoring_roi_id = roi_id
                self._monitor_timer.start()
                self._append_log(f"[감시 시작] 오답 ROI '{roi_label}' 접근 감지. 감시 중...")
                self._change_state("MONITORING")
                self._update_camera_roi()

        # =====================================================================
        # [MONITORING] 감시 중
        #   - ROI 이탈 → 필터링 (Near Miss) → PROCESS_RUN 복귀
        #   - 정답 ROI로 이동 → 자동 단계 완료
        #   - 다른 오답 ROI로 이동 → 감시 대상 변경
        # =====================================================================
        elif state == "MONITORING":
            if roi_id == "":
                # 오답 ROI에서 빠져나감 → 필터링 (의도 없는 접근으로 판단)
                elapsed = time.time() - self._monitoring_start_time
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                prev_roi_label = self._get_roi_label(self._monitoring_roi_id)
                self._append_log(
                    f"[필터링] ROI '{prev_roi_label}' 이탈 ({elapsed:.1f}초). "
                    "Near Miss(유형 1: 망설임)로 기록."
                )
                self._change_state("PROCESS_RUN")
                self._update_camera_roi()
            elif roi_id == correct_roi:
                # ★ 감시 중 정답 ROI로 이동 → 행동 교정 + 자동 단계 완료
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                self._append_log(f"[교정] 감시 중 정답 ROI '{roi_label}'로 이동 → 행동 교정됨.")
                self._auto_complete_step()
            elif roi_id != self._monitoring_roi_id:
                # 다른 오답 ROI로 이동 → 감시 대상 변경
                elapsed = time.time() - self._monitoring_start_time
                prev_roi_label = self._get_roi_label(self._monitoring_roi_id)
                self._monitoring_start_time = time.time()
                self._monitoring_roi_id = roi_id
                self._append_log(
                    f"[ROI 변경] '{prev_roi_label}' → '{roi_label}' ({elapsed:.1f}초 체류)"
                )

        # =====================================================================
        # [WARNING] 경고 중
        #   - ROI 이탈 → CAUTION (위험 회피)
        #   - 정답 ROI로 이동 → 행동 교정 + 자동 단계 완료
        # =====================================================================
        elif state == "WARNING":
            if roi_id == "":
                # 경고 후 ROI에서 이탈 → 위험 회피
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                prev_roi_label = self._get_roi_label(self._monitoring_roi_id)
                self._append_log(f"[회피] 경고 후 ROI '{prev_roi_label}'에서 이탈. 위험을 회피했습니다.")
                self._change_state("CAUTION")
                self._update_camera_roi()
            elif roi_id == correct_roi:
                # ★ 경고 중 정답 ROI로 이동 → 행동 교정 + 자동 단계 완료
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                self._append_log(f"[교정] 경고 중 정답 ROI '{roi_label}'로 이동 → 행동 교정됨.")
                self._auto_complete_step()

        # =====================================================================
        # [CAUTION] 경계 중
        #   - 정답 ROI 진입 → 자동 단계 완료
        #   - 오답 ROI 재진입 → MONITORING 재시작
        # =====================================================================
        elif state == "CAUTION":
            if roi_id == correct_roi:
                # ★ 경계 중 정답 ROI로 이동 → 자동 단계 완료
                self._append_log(f"[정답 접근] 경계 중 정답 ROI '{roi_label}'에 접근 성공!")
                self._auto_complete_step()
            elif roi_id != "":
                # 오답 ROI에 다시 진입 → MONITORING 재시작
                self._monitoring_start_time = time.time()
                self._monitoring_roi_id = roi_id
                self._monitor_timer.start()
                self._append_log(f"[재진입] 오답 ROI '{roi_label}'에 다시 진입. 감시 재시작.")
                self._change_state("MONITORING")
                self._update_camera_roi()

    def _check_monitoring_timeout(self):
        """
        모니터링 타이머 콜백: 100ms마다 호출되어 체류 시간을 확인합니다.
        임계 시간(ROI_THRESHOLD_SEC)을 초과하면 WARNING으로 전환합니다.
        """
        if self.current_state != "MONITORING":
            self._monitor_timer.stop()
            return

        if self._monitoring_start_time is None:
            self._monitor_timer.stop()
            return

        elapsed = time.time() - self._monitoring_start_time

        if elapsed >= ROI_THRESHOLD_SEC:
            self._monitor_timer.stop()
            
            # 현재 감시 중인 ROI 이름 가져오기
            roi_label = ""
            for roi in BUTTON_ROIS:
                if roi["id"] == self._monitoring_roi_id:
                    roi_label = roi["label"]
                    break
            
            self._append_log(
                f"[경고] ROI '{roi_label}' 체류 {elapsed:.1f}초 → 임계값({ROI_THRESHOLD_SEC}초) 초과!"
            )
            self._change_state("WARNING")
            self._update_camera_roi()

    # =========================================================================
    # [자동 단계 완료] 정답 ROI 접근 시 자동으로 단계를 완료하는 함수
    # =========================================================================
    def _auto_complete_step(self):
        """
        정답 ROI에 손이 진입했을 때 호출됩니다.
        현재 단계를 완료 처리하고, 1.5초 후 자동으로 다음 단계로 진행합니다.
        """
        # 모니터링 타이머가 동작 중이면 정리
        self._monitor_timer.stop()
        self._monitoring_start_time = None

        # 레시피 범위 확인 (방어적 코딩)
        if not self.recipe or self.current_step_index >= len(self.recipe):
            return

        step = self.recipe[self.current_step_index]
        roi_label = self._get_roi_label(step.get("correct_roi", ""))

        self._append_log(
            f"[정답] 단계 [{step['step']}] '{step['name']}' "
            f"- 정답 ROI '{roi_label}' 접근 성공!"
        )

        # STEP_COMPLETE 상태로 전환 (시각적 피드백)
        self._change_state("STEP_COMPLETE")
        self._update_camera_roi()

        # 1.5초 후 자동으로 다음 단계 진행
        self._auto_advance_timer.start()

    def _auto_advance_to_next_step(self):
        """
        단계 완료 후 자동으로 다음 단계로 진행하는 함수입니다.
        _auto_advance_timer(1.5초)에 의해 호출됩니다.
        """
        # STEP_COMPLETE 상태가 아니면 무시 (리셋 등으로 이미 변경된 경우)
        if self.current_state != "STEP_COMPLETE":
            return

        self.current_step_index += 1

        # ----- 모든 단계 완료 -----
        if self.current_step_index >= len(self.recipe):
            self._append_log("=" * 40)
            self._append_log("[완료] 모든 공정 단계를 성공적으로 완료했습니다!")
            self._append_log("=" * 40)
            self._update_step_label()
            self.camera_thread.set_roi_config("", False)
            self._change_state("IDLE")
            self.recipe = []
            self.current_step_index = 0
        else:
            # ----- 다음 단계로 자동 진행 -----
            next_step = self.recipe[self.current_step_index]
            next_roi_label = self._get_roi_label(next_step.get("correct_roi", ""))
            self._append_log(
                f"[진행] 다음 단계: [{next_step['step']}] {next_step['name']} "
                f"→ 정답 ROI: '{next_roi_label}'"
            )
            # 손가락 ROI 상태 초기화 (다음 단계 진입 감지를 위해)
            self._current_finger_roi = ""
            self._change_state("PROCESS_RUN")
            self._update_step_label()
            self._update_camera_roi()

    # =========================================================================
    # [키 핸들러] S키 - 작업 시작/선언 (빨강 LED)
    # =========================================================================
    def _on_key_s(self):
        """S키: IDLE → RECIPE_LOAD"""
        if self.current_state == "IDLE":
            self._change_state("RECIPE_LOAD")
        else:
            self._append_log(
                f"[입력 무시] S키는 IDLE 상태에서만 사용 가능. (현재: {self.current_state})"
            )

    # =========================================================================
    # [키 핸들러] G키 - 확인/작업 시작 (파랑 LED)
    # =========================================================================
    def _on_key_g(self):
        """G키: 레시피 로드 / 작업 시작 (단계 진행은 ROI 감시로 자동 수행)"""
        state = self.current_state

        if state == "RECIPE_LOAD":
            # 레시피 로드
            self.recipe = DEMO_RECIPE.copy()
            self.current_step_index = 0
            self._append_log(f"[레시피] {len(self.recipe)}단계 공정 로드 완료.")
            self._change_state("RECIPE_LOADED")
            self._update_step_label()

        elif state == "RECIPE_LOADED":
            # 작업 시작 → PROCESS_RUN (이후 ROI 감시로 자동 진행)
            first_step = self.recipe[self.current_step_index]
            first_roi_label = self._get_roi_label(first_step.get("correct_roi", ""))
            self._append_log(
                f"[시작] 첫 단계: [{first_step['step']}] {first_step['name']} "
                f"→ 정답 ROI: '{first_roi_label}'"
            )
            self._current_finger_roi = ""
            self._change_state("PROCESS_RUN")
            self._update_step_label()
            self._update_camera_roi()
        else:
            self._append_log(
                f"[입력 무시] G키는 현재 상태에서 사용 불가. (현재: {self.current_state})"
            )

    # =========================================================================
    # [키 핸들러] 5키 - 리셋 (주황 LED)
    # =========================================================================
    def _on_key_5(self):
        """5키: 전체 리셋. 어떤 상태에서든 IDLE로 되돌립니다."""
        if self.current_state == "IDLE":
            self._append_log("[리셋] 이미 IDLE 상태입니다.")
            return

        self._append_log("[리셋] 시스템을 초기화합니다...")
        # 모니터링 타이머 정리
        self._monitor_timer.stop()
        self._auto_advance_timer.stop()
        self._monitoring_start_time = None
        self._current_finger_roi = ""

        self.recipe = []
        self.current_step_index = 0
        self.camera_thread.set_roi_config("", False)  # ROI 비활성화
        self._change_state("IDLE")
        self._update_step_label()

    # =========================================================================
    # [키보드 이벤트]
    # =========================================================================
    def keyPressEvent(self, event):
        """키보드 입력을 처리합니다. (S=시작, G=확인, 5=리셋만 사용)"""
        key = event.key()
        if key == Qt.Key_S:
            self._on_key_s()
        elif key == Qt.Key_G:
            self._on_key_g()
        elif key == Qt.Key_5:
            self._on_key_5()

    # =========================================================================
    # [녹화 제어] GUI 창 전체 녹화
    # =========================================================================
    def _start_recording(self):
        """
        GUI 창 전체 녹화를 시작합니다.
        저장 경로에 폴더가 없으면 자동으로 생성합니다.
        파일명: YYYYMMDD_HHMMSS_recording.avi
        """
        try:
            # 저장 폴더가 없으면 생성
            if not os.path.exists(RECORDING_SAVE_DIR):
                os.makedirs(RECORDING_SAVE_DIR)
                self._append_log(f"[녹화] 저장 폴더 생성: {RECORDING_SAVE_DIR}")

            # 파일명 생성 (타임스탬프 기반)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_recording.avi"
            self._recording_path = os.path.join(RECORDING_SAVE_DIR, filename)

            # VideoWriter 생성 (GUI 창 전체 크기로 설정)
            fourcc = cv2.VideoWriter_fourcc(*RECORDING_CODEC)
            self._video_writer = cv2.VideoWriter(
                self._recording_path,
                fourcc,
                RECORDING_FPS,
                (WINDOW_WIDTH, WINDOW_HEIGHT)
            )

            if self._video_writer.isOpened():
                self._recording = True
                self._recording_timer.start()
                self._append_log(f"[녹화] 창 전체 녹화 시작! 저장 위치: {self._recording_path}")
            else:
                self._append_log("[녹화] VideoWriter 생성 실패! 녹화를 시작할 수 없습니다.")
                self._video_writer = None
                self._recording = False

        except Exception as e:
            self._append_log(f"[녹화] 녹화 시작 오류: {e}")
            self._recording = False

    def _capture_window_frame(self):
        """
        녹화 타이머 콜백: GUI 창 전체를 캡처하여 영상 파일에 기록합니다.
        QWidget.grab()으로 창 전체를 캡처한 뒤 OpenCV 형식으로 변환합니다.
        """
        if not self._recording or self._video_writer is None:
            return

        try:
            # GUI 창 전체를 QPixmap으로 캡처
            pixmap = self.grab()

            # QPixmap → QImage → numpy array → OpenCV BGR 변환
            qimage = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
            width = qimage.width()
            height = qimage.height()
            ptr = qimage.bits()
            ptr.setsize(height * width * 3)
            frame = np.array(ptr).reshape(height, width, 3)

            # RGB → BGR (OpenCV는 BGR 형식)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # 녹화 해상도에 맞게 리사이즈 (창 크기와 다를 수 있음)
            if frame_bgr.shape[1] != WINDOW_WIDTH or frame_bgr.shape[0] != WINDOW_HEIGHT:
                frame_bgr = cv2.resize(frame_bgr, (WINDOW_WIDTH, WINDOW_HEIGHT))

            self._video_writer.write(frame_bgr)

        except Exception as e:
            print(f"[녹화 프레임 캡처 오류] {e}")

    def _stop_recording(self):
        """녹화를 안전하게 종료합니다."""
        self._recording_timer.stop()
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            self._recording = False
            self._append_log(f"[녹화] 녹화 종료! 파일 저장 완료: {self._recording_path}")

    # =========================================================================
    # [종료 처리]
    # =========================================================================
    def closeEvent(self, event):
        """윈도우 닫을 때 녹화와 카메라 스레드를 안전하게 종료합니다."""
        self._stop_recording()
        self._monitor_timer.stop()
        self._auto_advance_timer.stop()
        self._append_log("[시스템] 카메라 스레드 종료 중...")
        self.camera_thread.stop()
        event.accept()


# =============================================================================
# [메인 함수]
# =============================================================================
def main():
    """PyQt5 애플리케이션을 생성하고 SafetyConsole 윈도우를 실행합니다."""
    app = QApplication(sys.argv)

    app.setStyleSheet("""
        QMainWindow { background-color: #16213e; }
        QWidget { background-color: #16213e; }
    """)

    window = SafetyConsole()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
