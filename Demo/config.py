import os

# =============================================================================
# [YOLO 설정]
# =============================================================================
YOLO_MODEL_PATH       = os.path.join(os.path.dirname(__file__), 'yolov8n.pt')
YOLO_CALIBRATION_PATH = os.path.join(os.path.dirname(__file__), 'camera_calibration.npz')
YOLO_CONF_HIGH  = 0.65
YOLO_CONF_LOW   = 0.50
YOLO_IOU_MATCH  = 0.3
YOLO_MAX_MISS   = 3
YOLO_INPUT_SIZE = 320

# =============================================================================
# [화면 설정]
# =============================================================================
WINDOW_WIDTH  = 1280
WINDOW_HEIGHT = 720
CAMERA_FLIP_VERTICAL = True   # XIAO ESP32-S3 카메라 상하 반전 보정

# =============================================================================
# [녹화 설정]
# =============================================================================
RECORDING_ENABLED  = True
RECORDING_SAVE_DIR = os.path.expanduser("~/Videos/recordings")
RECORDING_FPS      = 15.0
RECORDING_CODEC    = "MJPG"   # Linux 호환 코덱

# =============================================================================
# [ESP32-S3 TCP 카메라 설정]
# =============================================================================
_CAMERA_IP_FILE = os.path.join(os.path.dirname(__file__), ".camera_ip")
_cached_ip      = open(_CAMERA_IP_FILE).read().strip() if os.path.exists(_CAMERA_IP_FILE) else None
CAMERA_TCP_HOST = _cached_ip if _cached_ip else "100.97.0.91"
CAMERA_TCP_PORT = 8888
TCP_RECV_TIMEOUT_SEC   = 10.0
TCP_RECONNECT_DELAY_SEC = 3.0
TCP_MAX_FRAME_BYTES    = 200000

# =============================================================================
# [FSM 상태 정의]
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
# rect = (x비율, y비율, 너비비율, 높이비율) — 해상도 독립적
# =============================================================================
ROI_THRESHOLD_SEC = 2.0   # 오답 ROI 체류 시 경고까지의 시간 (초)

BUTTON_ROIS = [
    {"id": "cup",      "label": "CUP",      "rect": (0.0119, 0.5003, 0.2065, 0.1946)},
    {"id": "keyboard", "label": "KEYBOARD", "rect": (0.2267, 0.4993, 0.4890, 0.2573)},
    {"id": "mouse",    "label": "MOUSE",    "rect": (0.7683, 0.5307, 0.1245, 0.2422)},
    {"id": "sound",    "label": "SOUND",    "rect": (0.5736, 0.1235, 0.1717, 0.2557)},
]

# =============================================================================
# [공정 레시피]
# =============================================================================
DEMO_RECIPE = [
    {"step": 1, "name": "CUP 접근",      "correct_roi": "cup"},
    {"step": 2, "name": "KEYBOARD 접근", "correct_roi": "keyboard"},
    {"step": 3, "name": "SOUND 접근",    "correct_roi": "sound"},
    {"step": 4, "name": "MOUSE 접근",    "correct_roi": "mouse"},
]
