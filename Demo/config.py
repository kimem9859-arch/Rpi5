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
# 체류시간 임계 (스침 vs 위반 경계) — §9.4 정본값 **0.3초**.
# 이력: 초안 1.0 → §9.4 PoC값 0.5(2026-07-22 오전) → **실물 재측정 0.3**(2026-07-22 오후).
# 🔴 0.5는 색-ROI PoC의 "스침 오탐 0%"만 보고 정한 값이라 **위반을 제때 잡는지는
#    측정한 적이 없었다.** 물리 버튼으로 위반 37건(2세션)을 실제로 눌러 재보니
#    0.5초는 **14%만** 잡았다. 0.3초에서 57%. 0.25 이하는 2%p만 늘고 헛경고만 는다.
#    사람이 버튼 위에 머무는 시간은 median 0.39~0.40초로, 의식적으로 천천히 눌러도
#    바뀌지 않았다(3회 재현) = 물리적 한계. 근거·수치 = §10.23.
FSM_DWELL_THRESHOLD_SEC = 0.3
# 갭메우기 (§9.4) — 손 검출이 이 시간 안에 다시 잡히면 이탈로 보지 않는다.
# 없으면 한 프레임만 놓쳐도 체류가 리셋된다. §10.22 실측: 0.3초만 넣어도
# 선행시간 median 0.38s → 0.55s, 개입 감지 85% → 92%.
FSM_GAP_FILL_SEC        = 0.3
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
# 랜드마크 신뢰도 하한. 미만이면 손 없음으로 본다.
# 🔴 0.5는 **정확한 검출까지 버리고 있었다** — 손끝이 버튼 중심 6~10px인 프레임의
#    flag가 0.11~0.13이었다(§10.22). flag는 손이 버튼을 누르느라 가려질 때 떨어지는데
#    그때가 정확히 관측이 필요한 순간이다. 0.2 아래로는 더 안 오른다(포화).
HAND_MIN_SCORE     = 0.2
# ROI 링(1단계) 폭 px — 검출 박스를 이만큼 넓힌 테두리가 '접근' 구역이다(roi_zones).
# 🔴 0으로 두면 도넛이 꺼지고 도입 전과 동일 동작 = 롤백 스위치.
# 25 = §10.22 무릎점(개입 감지 92%·오경보 분당 1.1회. 40px는 감지 그대로·오경보 2배)
HAND_ROI_RING_PX   = 25

# 창 기반 체류 누적 (2026-07-27) — 직전 관측을 유지할지를 **시간이 아니라 관측 횟수**로 판단.
# 종전 갭메우기는 시간 기준(FSM_GAP_FILL_SEC)이라 fps 가 7.7~11.3 으로 흔들리면 실제 창이
# 2.3~3.4 프레임으로 같이 흔들렸다. §10.29⑥ 이 "경계는 시간이 아니라 프레임 수"로 결론.
# 🔴 HAND_WINDOW_N = 0 이면 창이 꺼지고 종전 갭메우기 동작 = 롤백 스위치.
# 설계 = ../docs/superpowers/specs/2026-07-27-창판정-design.md §5
# 🔴 창 기반 체류 누적은 폐기됐다(2026-07-27) — M을 스윕해도 중단 규칙의 차단율
#    문턱을 못 넘었고, 가장 느슨한 설정조차 종전 갭메우기를 이기지 못했다.
#    경위·수치 = .superpowers/sdd/2026-07-27-창판정/task-6-report.md, 설계 §2.3,
#    통합문서 §10.
HAND_WINDOW_N      = 0      # 최근 몇 프레임을 보는가 (0 = 꺼짐, §10 스윕 미달로 폐기)
HAND_WINDOW_M      = 3      # 그중 몇 번 관측되면 '계속 있는 것'으로 보는가 (N=0이라 미사용)

# CCTV(USB 웹캠) 스레드 사용 여부.
# 🔴 False 로 두면 GUI 가 /dev/video0 을 점유하지 않는다 — 시나리오 촬영 때 웹캠을
#    3인칭 기록(ffmpeg)에 양보하기 위한 스위치. 이때 상단 'CCTV' 버튼은 무동작.
# 환경변수 SOP_USB_CAMERA=0 으로도 끌 수 있다(run_scenario.sh 가 이 경로를 쓴다).
USB_CAMERA_ENABLED = os.environ.get("SOP_USB_CAMERA", "1") != "0"
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
