import os

_BASE_DIR = os.path.dirname(__file__)

# =============================================================================
# [UI 테마]
# =============================================================================
BG_PRIMARY   = "#0e0e0e"
BG_PANEL     = "#1a1a1a"
BG_SURFACE   = "#242424"
BG_LOG       = "#0a0a0a"

BORDER_COLOR = "#3a3a3a"

TEXT_PRIMARY   = "#e0e0e0"
TEXT_SECONDARY = "#888888"
TEXT_LOG       = "#9acd9a"

ACCENT       = "#e8a000"
BTN_ACTIVE   = "#1a5fb4"
BTN_INACTIVE = "#2a2a2a"
BTN_CALIB    = "#4a235a"

STATUS_OK      = "#00c853"
STATUS_WARNING = "#ff6d00"
STATUS_DANGER  = "#d50000"

# =============================================================================
# [추론 백엔드 설정]
# =============================================================================
# "pytorch": best.pt + ultralytics CPU 추론 (Phase A, 현재)
# "hailo"  : best.hef + Hailo-8 가속 추론 (Phase B, HEF 변환 완료 후)
INFERENCE_BACKEND = "pytorch"

PT_MODEL_PATH  = os.path.join(_BASE_DIR, 'models', 'best.pt')
HEF_MODEL_PATH = os.path.join(_BASE_DIR, 'models', 'best.hef')

# =============================================================================
# [YOLO 설정]
# =============================================================================
YOLO_CALIBRATION_PATH = os.path.join(_BASE_DIR, 'camera_calibration.npz')
YOLO_CONF_HIGH  = 0.65
YOLO_CONF_LOW   = 0.50
YOLO_IOU_MATCH  = 0.3
YOLO_MAX_MISS   = 3
YOLO_INPUT_SIZE = 640

# =============================================================================
# [FSM 판정 설정] — 통합 설계문서 §9.4 임계값 정본
# =============================================================================
# 공정 시퀀스 단계 수 (B1~B4, §6). 정답 ROI = f"B{기대단계}".
FSM_STEP_COUNT = 4
# 체류시간 임계 (스침 vs 위반 경계). §9.4: 0.8~1.0초 범위 → 데모 튜닝 시 단일값 확정.
FSM_DWELL_THRESHOLD_SEC = 1.0
# 비상정지 버튼 ID (즉시 BLOCK, 해제 시 기대단계=1 리셋)
FSM_EMO_BUTTON = "EMO"

# =============================================================================
# [화면 설정]
# =============================================================================
WINDOW_WIDTH  = 1280
WINDOW_HEIGHT = 720
CAMERA_FLIP_VERTICAL = True

# =============================================================================
# [녹화 설정]
# =============================================================================
RECORDING_ENABLED  = True
RECORDING_SAVE_DIR = os.path.join(_BASE_DIR, 'recordings')
RECORDING_FPS      = 15.0
RECORDING_CODEC    = "MJPG"

# =============================================================================
# [로그 설정]
# =============================================================================
LOG_SAVE_DIR = os.path.join(_BASE_DIR, 'logs')

# =============================================================================
# [ESP32-S3 TCP 카메라 설정]
# =============================================================================
_CAMERA_IP_FILE = os.path.join(_BASE_DIR, ".camera_ip")
_cached_ip      = open(_CAMERA_IP_FILE).read().strip() if os.path.exists(_CAMERA_IP_FILE) else None
CAMERA_TCP_HOST = _cached_ip if _cached_ip else "10.111.10.235"
CAMERA_TCP_PORT = 8888
TCP_RECV_TIMEOUT_SEC    = 10.0
TCP_RECONNECT_DELAY_SEC = 3.0
TCP_MAX_FRAME_BYTES     = 500000
