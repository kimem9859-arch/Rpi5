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
# "hailo"  : console_v2.hef + Hailo-8 가속 추론 (Phase B, 버튼 5클래스 B1~B4+EMO)
INFERENCE_BACKEND = "hailo"

PT_MODEL_PATH  = os.path.join(_BASE_DIR, 'models', 'best.pt')
# console_v2 = 파랑 스티커 B4 재학습 + DFC level 1·캘리브 652 (수치 = 상위 통합문서 §10.14·§10.15).
# ⚠️ B4 해결 여부는 아직 미판정 — 판정 기준·한계는 §10.16. v1과 대조하려면 이 줄을
#    console_v1.hef 로 바꾸거나, replay_raw.py 는 --hef 로 런타임 지정할 수 있다.
HEF_MODEL_PATH = os.path.join(_BASE_DIR, 'models', 'console_v2.hef')

# =============================================================================
# [YOLO 설정]
# =============================================================================
YOLO_CALIBRATION_PATH = os.path.join(_BASE_DIR, 'camera_calibration.npz')
YOLO_CONF_HIGH  = 0.65
YOLO_CONF_LOW   = 0.50
YOLO_IOU_MATCH  = 0.3
YOLO_MAX_MISS   = 5
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
try:
    with open(_CAMERA_IP_FILE) as _f:
        _cached_ip = _f.read().strip()
except OSError:  # 파일 없음·권한 등 — 기본 IP로 폴백(앱 기동은 막지 않는다)
    _cached_ip = None
CAMERA_TCP_HOST = _cached_ip if _cached_ip else "10.111.10.235"
CAMERA_TCP_PORT = 8888
TCP_RECV_TIMEOUT_SEC    = 10.0
TCP_RECONNECT_DELAY_SEC = 3.0
TCP_MAX_FRAME_BYTES     = 500000

# =============================================================================
# [인터락 설정] — 트랙 A 물리 차단 (FSM 콜백 → pyserial → Arduino 릴레이)
# 결선도 정본: ../dev/interlock/결선도_초안.md §5 (RUN/WARN/BLOCK + ACK)
# =============================================================================
INTERLOCK_ENABLED = True
INTERLOCK_PORT    = "/dev/ttyACM0"   # Arduino UNO R4 USB 시리얼
INTERLOCK_BAUD    = 115200
INTERLOCK_TIMEOUT = 1.0              # 시리얼 read/write 타임아웃(초), ACK 대기 포함
INTERLOCK_BLOCK_ACK_RETRIES = 2      # BLOCK 무ACK 시 재전송 횟수(초과 시 on_fault 알람)
INTERLOCK_RECONNECT_DELAY_SEC = 3.0 # 연결 실패/끊김 시 재연결 시도 간격

# =============================================================================
# [손 검출(HOI) 설정] — Hailo 팜검출 + 핸드랜드마크 21점
# MediaPipe 프레임워크는 Python 3.13/aarch64 휠이 없어 못 쓴다. 대신 **구글 MediaPipe의
# 모델 자체**(BlazePalm·BlazeHandLandmark)를 Hailo용 .hef 로 변환한 것을 쓴다 —
# hailo_platform+numpy+cv2 만 필요해 3.13 문제가 원천 소멸한다.
# 근거·실증 = docs/superpowers/specs/2026-07-21-HOI-경로-design.md
#
# ⚠️ 아래 경로가 없으면 손 검출은 **자동 비활성**되고 버튼 검출만 동작한다(기존과 동일).
#    모델·소스는 아직 repo 밖에 있다 — vendoring 여부는 별도 결정 사항.
# =============================================================================
HAND_ENABLED       = True
HAND_MODELS_DIR    = os.path.expanduser("~/hoi_probe/hailo8")
HAND_BLAZE_DIR     = os.path.expanduser("~/hoi_probe/blaze_app_python")
HAND_MIN_SCORE     = 0.5      # 랜드마크 신뢰도 하한. 미만이면 손 없음으로 본다
HAND_DRAW          = True     # 화면에 랜드마크·검지끝 표시

# =============================================================================
# [GPIO 입력 설정] — 물리 버튼 B1~B4·EMO → Pi GPIO → FSM (트랙 A 입력부)
# 결선도 정본: ../dev/interlock/결선도_초안.md §3.1
#   버튼 = active-low (INPUT_PULLUP, 눌림=LOW)
#   EMO  = NC쌍 fail-safe (INPUT_PULLUP, 평소 LOW=정상 / 누름·단선=HIGH=비상)
# 해제 버튼(WARNING/BLOCK 해제)은 터치 UI라 GPIO 불필요.
# =============================================================================
GPIO_INPUT_ENABLED = True
GPIO_BUTTON_PINS   = {"B1": 5, "B2": 6, "B3": 13, "B4": 19}  # BCM 번호
GPIO_EMO_PIN       = 26                                       # BCM, EMO NC
GPIO_BOUNCE_SEC    = 0.05                                     # 디바운스(기계식 채터링 제거)
