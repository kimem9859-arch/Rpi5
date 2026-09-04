import os

_BASE_DIR = os.path.dirname(__file__)

# =============================================================================
# [UI 폰트] — 단일 정본. 여기 말고 다른 곳에서 폰트 이름을 쓰지 말 것.
# =============================================================================
# 🔴 2026-08-03 이전에는 QFont("Consolas") 를 7곳에 흩어 쓰고 있었는데 이 파이에
#    Consolas 가 없어 Qt 가 조용히 WenQuanYi Zen Hei Mono(중국어 폰트)로 대체했다.
#    요청과 실제가 어긋나도 아무 신호가 없어 3개월을 모르고 지냈다.
#    → 이름을 여기 한 곳에 두고, 기동 시 font_report() 를 로그에 남긴다.
#
# 설치(다른 환경): 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §2.4
UI_FONT_FAMILY = "Pretendard"

# 역할별 크기(pt). 화면 배치는 % 기준이지만 글자는 pt 로 둔다.
UI_FONT_SIZES = {
    "title":  13,   # 패널 제목 (공정 단계, 메뉴)
    "state":  15,   # 상태 라벨 (PROCESS RUN)
    "body":   12,   # 본문 (단계 이름, 메뉴 항목)
    "small":  10,   # 부가 라벨 (○ 콘솔 앞에 놓으면 확인됩니다)
    "banner": 16,   # 경고·차단 배너 제목
    "cta":    20,   # 작업 시작 (2026-08-19 자동 진행 이후 「작업 시작」 전용)
}

# 굵기: 400 본문 / 600 강조 / 700 제목 / 800 현재 단계
UI_FONT_WEIGHT_DEFAULT = 600


def font(role="body", weight=None):
    """역할 이름으로 QFont 를 만든다. 고정폭 숫자(tnum)가 켜져 있다.

    tnum 을 켜지 않으면 게이지가 '18/30s → 19/30s' 로 바뀔 때 폭이 흔들린다.
    ⚠️ QFont.setFeature 는 Qt 6.7+ 다. 없으면 조용히 건너뛴다(글꼴은 정상).
    """
    from PyQt6.QtGui import QFont

    f = QFont(UI_FONT_FAMILY)
    f.setPointSize(UI_FONT_SIZES.get(role, UI_FONT_SIZES["body"]))
    f.setWeight(weight if weight is not None else UI_FONT_WEIGHT_DEFAULT)
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return f


def font_report():
    """요청한 폰트와 실제 적용된 폰트를 한 줄로. 기동 로그용."""
    from PyQt6.QtGui import QFontInfo

    info = QFontInfo(font("body"))
    actual = info.family()
    mark = "OK" if actual.startswith(UI_FONT_FAMILY) else "🔴 폴백"
    return f"{UI_FONT_FAMILY} → {actual} ({mark})"


# =============================================================================
# [UI 애니메이션] — 정본: 상위 docs/superpowers/specs/2026-08-16-ui-애니메이션-design.md
# =============================================================================
# ✅ 성능 판정 완료 (2026-08-26, G6) — **FPS 영향 +0.8% 로 사실상 없다**(문턱 10%).
#    조건 = USB 웹캠·손 없는 정지 장면·ON/OFF 교차 6런. 상세 = 상위 통합문서 §10.48.
#    🔴 제품 경로(ESP32)로는 판정하지 못했다 — 공급 FPS 가 3~25 로 요동해 애니메이션
#       효과가 묻힌다. 재측정도 USB 로 할 것(`test/anim_fps_bench.py --camera usb`).
#    문제가 보이면 SOP_UI_ANIM=0 으로 끈다 — 코드를 고칠 필요 없다.
UI_ANIMATION = os.environ.get("SOP_UI_ANIM", "1") != "0"

# 실측 FPS 를 화면 우하단에 표시할지. 기본은 로그에만 남긴다(시연 화면을 더럽히지 않는다).
SHOW_FPS = os.environ.get("SOP_SHOW_FPS", "0") == "1"


# =============================================================================
# [UI 테마] — ⚠️ 레거시. 새 코드는 `theme.py` 를 쓴다.
# =============================================================================
# 아래 상수들은 **다크 테마 한 벌**이라 테마 전환을 할 수 없다.
# 테마 2벌(다크·화이트) 정본 = `theme.py` (design §3).
# 여기 남아 있는 이유: main.py 의 앱 전역 스타일시트와, 글라스 UI 전환 전의
# safety_console.py 잔여 코드가 아직 참조한다. 그 코드가 사라지면 함께 지운다.
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

# 왜곡보정 출력 화각(`cv2.getOptimalNewCameraMatrix` 의 alpha).
#   0 = 유효한 화소만 남긴다(검은 여백 없음)  /  1 = 원본 화소를 하나도 안 버린다
# 🔴 **1 이면 영상 네 변의 가운데가 안쪽으로 4~6px 휜 검은 테두리가 생긴다.**
#    배럴 왜곡을 펴면 원본 사각형이 핀쿠션 모양이 되고 그 바깥이 비기 때문이며,
#    **캘리브레이션 값과 무관하다 — 무엇을 넣어도 alpha=1 이면 똑같이 나온다.**
#    2026-09-04 에 이 테두리를 「렌즈 굴곡」으로 보고 재캘리브레이션했으나
#    당연히 개선되지 않았다. 실측(촬영본 909프레임) = 모서리 0~1px · 중앙 4~6px 이고,
#    같은 파이프라인을 흰 화면으로 재현한 alpha=1 예측과 1~2px 안에서 일치했다.
# 대가는 작다 — 가로 화각 63.6°(alpha=1) → 62.8°(alpha=0), 0.8° 차이.
# ⚠️ 화각이 바뀌면 모델이 보는 그림과 ROI 좌표가 미세하게 달라진다.
# 🔴 이 값은 런타임(`camera_thread`)과 측정 도구(`test/tool_probe`)가 **함께** 읽는다.
#    한쪽에만 숫자를 박으면 도구가 런타임과 다른 보정을 쓰게 된다(전례 4회).
CALIB_ALPHA = 0
YOLO_CONF_HIGH  = 0.65
YOLO_CONF_LOW   = 0.50
YOLO_IOU_MATCH  = 0.3
YOLO_MAX_MISS   = 5
YOLO_INPUT_SIZE = 640

# =============================================================================
# [탐지 박스 표시] — 정본: 상위 specs/2026-08-19-자동진행-결과창-design.md §5
# =============================================================================
# 탐지 박스를 화면에 그릴지. 🔴 **표시만** 끈다 — 검출·판정은 그대로 돈다.
SHOW_DETECT_BOXES = True

# 🔴 여기는 **cv2 가 영상에 직접 그리는** 색이다. theme.py(Qt 오버레이 테마)와
#    성격이 다르고 테마 전환을 따르지 않는다 — 영상에는 테마가 없다.
# 버튼 색은 **실물 버튼 색 그대로**다(통합문서 §5.3). 화면과 손 앞의 물건이
# 같은 색이라야 "저 노란 버튼"이 바로 이어진다.
DETECT_BOX_COLORS = {
    "B1":  "#FFD400",   # 노랑
    "B2":  "#FFFFFF",   # 흰
    "B3":  "#FF69B4",   # 핑크
    "B4":  "#2E7DFF",   # 파랑 (파랑 원 스티커, 통합문서 §10.12)
    "EMO": "#FF3B30",   # 빨강 (비상정지)
}
# 공구는 위 5색과 겹치지 않게 고른다 — 겹치면 버튼과 헷갈린다.
TOOL_BOX_COLORS = {
    "driver": "#00E5FF",   # 시안
    "wrench": "#B36BFF",   # 보라
    "pliers": "#7CFF4F",   # 라임
}
DETECT_BOX_FALLBACK = "#00FF00"   # 표에 없는 클래스 — 죽지 않고 초록으로 그린다

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

# 장착 구도 회전 보정 — ESP32 가 시계방향 90° 로 돌아 붙어 반시계 90° 로 되돌린다
# (2026-08-26 구도 변경). 켜면 프레임이 640×480 → **480×640 세로**가 된다.
# 🔴 적용은 `frame_orient` 가 전담한다 — 여기 켜고 다른 곳에서 또 돌리지 말 것.
CAMERA_ROTATE_CCW90 = True

# 카메라 영역을 **채워서** 표시할지. 회전 뒤 프레임이 세로(480×640)라 가로 UI 에
# 그냥 넣으면 좌우에 검은 띠가 생긴다. 켜면 넘치는 만큼 잘라내 띠를 없앤다.
# 🔴 **표시 전용이다.** 검출·ROI 판정·녹화는 잘리지 않은 전체 프레임으로 돈다 —
#    시야를 버리지 않으려고 화면과 검출을 분리한 것이다(2026-08-26). 화면 가장자리
#    에서 검출 박스가 잘려 보여도 **시스템이 못 본 것이 아니다.**
#    끄면 종전처럼 전체가 보이고 검은 띠가 돌아온다.
CAMERA_DISPLAY_FILL = True

# =============================================================================
# [녹화 설정]
# =============================================================================
# 🔴 상시 자동 녹화를 폐기했다 (2026-08-04). 메뉴 → 녹화 에서 켤 때만 돈다.
#    근거: 실측에서 전체 부하 55.6% 중 **약 40%p 가 녹화**였다. GUI 스레드가
#    초당 15번 창 전체를 캡처하느라 화면이 버벅였다.
RECORDING_ENABLED  = False          # 기동 시 자동 시작 여부
RECORDING_SAVE_DIR = os.path.join(_BASE_DIR, 'recordings')
RECORDING_FPS      = 15.0

# 코덱 — H.264(.mp4). 실측(1280x720·15fps·10초):
#   MJPG 247MB/분(CPU 0.55x) / XVID 37MB/분(0.17x) / **H.264 4MB/분(0.64x)**
#   실제 화면 기준으로는 19.2 → 약 0.3 MB/분. 1시간 녹화가 1.2GB → 약 18MB.
#   .mp4 라 폰·웹에서 그대로 재생된다(발표·전송에 유리).
# ⚠️ Pi 5 에는 하드웨어 인코더가 없다 — 전부 소프트웨어 인코딩이다.
RECORDING_CODEC    = "avc1"
RECORDING_EXT      = "mp4"

# --- 시연영상 촬영 모드 -------------------------------------------------------
# 🔴 평소 실행과 완전히 분리된 경로다. SOP_DEMO_CAPTURE=1 일 때만 켜진다.
#    한 번 실행에 5개 영상을 동시에 남긴다(GUI전체·UI만·1인칭 오버레이 유/무·3인칭).
#    설계 = 상위 specs/2026-09-03-시연영상-촬영-design.md
DEMO_CAPTURE      = os.environ.get("SOP_DEMO_CAPTURE", "0") == "1"
DEMO_CAPTURE_DIR  = os.path.join(RECORDING_SAVE_DIR, '시연영상')
# 5개 영상 공통 규격(16:9). 🔴 **부하와 맞바꾸는 값이다** — 2026-09-03 실측:
#   1920x1080 → 촬영 중 GUI 15.6fps → **5.9fps** (CPU 여유 2%)
#   1280x720  → 촬영 중 GUI 15.6fps → **9.7fps** (CPU 여유 18%)
#   화면 캡처 x264 인코딩이 단독으로 CPU 136~172% 를 먹는다(4코어). Pi 5 에는
#   하드웨어 인코더가 없어 전부 소프트웨어다.
# 1280x720 은 GUI 설계 크기(WINDOW_WIDTH/HEIGHT)와 같아 배치가 가장 자연스럽다.
# 화질을 우선하려면 SOP_DEMO_SIZE=1920x1080 으로 올린다(촬영 중 화면이 더 끊긴다).
DEMO_CAPTURE_SIZE = tuple(
    int(v) for v in os.environ.get("SOP_DEMO_SIZE", "1280x720").split("x"))
DEMO_CAPTURE_FPS  = 15.0
# 1인칭 원본 프레임 크기 — ESP32 640x480 이 회전(CCW90) 뒤 480x640 세로가 된다.
# 🔴 첫 프레임이 있으면 그 크기를 쓰고, 이것은 10초 폴백 경로의 기본값이다.
DEMO_FPV_SIZE     = (480, 640)
# 3인칭 웹캠 저장 규격. 카메라는 1920x1080 으로 열고 이 크기로 인코딩한다.
# 🔴 1080p 는 분당 약 230MB 다(2026-09-04 실측) — 회차를 여러 번 가면 디스크가 찬다.
#    편집에서 3인칭은 대개 작게 쓰여 720p 로 충분하다는 사용자 판단(2026-09-04).
DEMO_WEBCAM_SIZE  = (1280, 720)
# 첫 카메라 프레임을 이만큼 기다렸다 없으면 그냥 시작한다.
# ESP32 가 안 붙었을 때 영영 시작 못 하는 것을 막는다.
DEMO_CAPTURE_START_TIMEOUT = 10.0
# 🔴 카메라 영상 자리를 검정으로 그린다(「UI만」 회차).
#    ①에서 파생할 수 없어 회차를 나눈다 — 이 UI 는 **모든 UI 가 영상 위에 떠 있는**
#    글라스 구조라, 녹화본에서 영상 영역을 덧칠하면 UI 까지 함께 지워진다
#    (2026-09-03 실측: 거의 새까만 영상이 나왔다).
#    🔴 표시만 바뀐다 — 검출·판정·1인칭 녹화는 그대로 돈다.
DEMO_HIDE_VIDEO = os.environ.get("SOP_DEMO_HIDE_VIDEO", "0") == "1"
DEMO_SCENARIO = os.environ.get("SOP_DEMO_SCENARIO", "정상")   # 정상 | 오답
DEMO_OVERLAY  = os.environ.get("SOP_DEMO_OVERLAY", "켬")      # 켬 | 끔

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

# 🔴 연결 재시도 상한 — 무한 재시도는 로그를 계속 불린다(3분에 약 60줄).
#    이 횟수만큼 실패하면 자동 재시도를 멈추고 알림을 띄운다.
#    다시 붙이려면 메뉴 → 점검(연결) 에서 수동으로 시도한다.
CONNECT_MAX_TRIES = 5

# =============================================================================
# [인터락 설정] — 트랙 A 물리 차단 (FSM 콜백 → pyserial → Arduino 릴레이)
# 결선도 정본: ../dev/interlock/결선도_초안.md §5 (RUN/WARN/BLOCK + ACK)
# =============================================================================
# 🔴 포트 번호를 박지 않는다 — 꽂는 순서에 따라 ttyACM0/1 이 뒤바뀐다.
#    2026-09-01 에 이 값이 "/dev/ttyACM0" 으로 박혀 있었고, 그 자리를 ESP32 가
#    차지하고 있어 **인터록이 ESP32 에게 RUN 을 보내고 「연결됨」이라고 보고**했다.
#    (실기동 로그: `[인터락] → RUN (ACK 없음: '[녹음] 신호음 3번 뒤 …')`)
#
# 🔴 못 찾으면 「아무 포트나」가 아니라 **연결하지 않는다.**
#    모르는 장치에 안전 명령을 보내면 안전장치가 없는데 있다고 믿게 된다.
#    그것이 연결 실패보다 훨씬 위험하다 — 연결 실패는 화면에 보이지만
#    잘못된 연결은 정상으로 보인다.
#
# ⚠️ 인터록 Arduino 의 USB 신원(vid/pid)은 아직 확인하지 못했다(보드가 없어서).
#    지금 규칙은 「ESP32 가 아닌 시리얼 장치가 정확히 하나면 그것」이다.
#    보드를 꽂아 신원을 확인하면 그 vid/pid 로 좁힐 것.
def _resolve_interlock_port():
    """인터록 Arduino 의 경로. 확신할 수 없으면 None."""
    forced = os.environ.get("SOP_INTERLOCK_PORT")
    if forced:
        print(f"[config] 인터록 포트 강제 지정: {forced}")
        return forced
    try:
        from serial.tools import list_ports
        from serial_ports import ESP32_S3          # 상수를 복제하지 않는다
        cands = [p.device for p in list_ports.comports()
                 if p.vid is not None and (p.vid, p.pid) != ESP32_S3]
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            print(f"[config] ⚠️ 인터록 후보가 여럿이라 고를 수 없다: {cands}")
        else:
            print("[config] ⚠️ 인터록 장치를 못 찾았다 (ESP32 는 인터록이 아니다)")
    except Exception as e:
        print(f"[config] ⚠️ 포트 해석 실패: {e}")
    print("[config] → 인터록을 비활성화한다. 강제하려면 SOP_INTERLOCK_PORT=/dev/ttyACMx")
    return None

_INTERLOCK_PORT_RESOLVED = _resolve_interlock_port()

# 🔴 포트를 못 고르면 인터록 자체를 끈다 — 위 주석의 이유.
INTERLOCK_ENABLED = _INTERLOCK_PORT_RESOLVED is not None
INTERLOCK_PORT    = _INTERLOCK_PORT_RESOLVED or "/dev/ttyACM0"  # 표시용 기본값
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
HAND_MODELS_DIR    = os.path.expanduser("~/lab/hoi/hailo8")
HAND_BLAZE_DIR     = os.path.expanduser("~/lab/hoi/blaze_app_python")
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

# 기동 시 어느 카메라로 시작하는가 — "esp32"(기본) | "usb".
# 🔴 기본값은 바꾸지 않는다. 시연·운용은 그대로 ESP32 로 뜬다.
#    측정 전용 스위치다 — ESP32 는 무선·전원·장면(프레임 크기)이 함께 흔들려
#    「애니메이션만 변수」인 대조(G6)를 만들 수 없다(2026-08-26 실측). 그때는
#    SOP_CAMERA=usb 로 공급을 고정하고 잰다.
CAMERA_SOURCE = os.environ.get("SOP_CAMERA", "esp32")
HAND_DRAW          = True     # 화면에 랜드마크·검지끝 표시

# =============================================================================
# [공구 검출 설정] — 서브 작업(wait_tool)의 공구 지참 판정 (A-2, 2026-08-14)
# 설계 = ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md
#
# 🔴 CPU 추론이다. GUI(시스템 파이썬)엔 ultralytics·torch 가 **없다** — rfenv 안에만
#    있다. 그래서 rfenv 파이썬으로 워커 프로세스를 띄우고 /dev/shm 파일로 주고받는다.
#    .hef 가 생기면 tool_gate.py 안만 갈아끼우고 tool_worker.py 는 삭제한다.
#
# ⚠️ 모델·rfenv 가 없으면 공구 감지는 **자동 비활성**된다(손 검출과 같은 방침).
#    🔴 그 경우 2단계 게이트가 영영 안 열리므로 로그에 눈에 띄게 남는다.
# =============================================================================
TOOL_ENABLED           = os.environ.get("SOP_TOOL", "1") != "0"
# 🔴 YOLO_CONF_HIGH 와 값이 같지만 목적이 달라 따로 둔다 — 묶으면 한쪽을 조정할 때
#    다른 쪽이 딸려간다. 0.65 = §10.42 에서 시연 3종이 잘 잡힌 구간(0.66~0.81).
TOOL_CONF              = 0.65
# 공구 판정은 상시 작업이 아니다 — 서브 대기 중에만 돈다. 추론 약 0.5초의 2배 여유.
TOOL_SCAN_INTERVAL_SEC = 1.0
# 🗑️ TOOL_PLACED_COUNT 는 2026-08-16 에 사라졌다 — 「넣음」 마디를 없애면서
#    연속 미검출을 셀 일이 없어졌다(경위 = 통합문서 §10.44).
TOOL_MODEL_PATH        = os.path.join(_BASE_DIR, 'models', 'tool_v3.pt')
TOOL_WORKER_PYTHON     = os.path.expanduser("~/env/rfenv/bin/python")
TOOL_SHM_DIR           = "/dev/shm/sop_tool"

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
