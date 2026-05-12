# Project: Vision AI 작업자 안전 콘솔

ESP32-S3 카메라(OV3660)로 작업자 손 위치를 추적하여 휴먼 에러를 사전 예방하는 PyQt5 GUI 애플리케이션.

- **현재 상태**: 프로토타입 / Windows 테스트 단계
- **최종 타겟**: Raspberry Pi 5 + Hailo AI 가속기

---

## Demo/ 파일 구조 (실제 동작 코드만)

```
Demo/
├── main.py               앱 진입점
├── safety_console.py     메인 GUI 창
├── camera_thread.py      카메라 수신 + AI 추론
├── config.py             전역 설정 상수
├── YOLO model/
│   ├── yolov8n.pt        기본 사용 모델 (config에서 지정)
│   └── yolov8s.pt        대체 모델
├── chessboard.png        캘리브레이션용 체스보드 이미지
├── .camera_ip            ESP32 IP 저장 파일 (텍스트, 직접 수정 가능)
├── .env                  WiFi SSID/PW 목록 (WIFI_1_SSID 형식)
├── recordings/           자동 녹화 저장 폴더
└── logs/                 로그 파일 저장 폴더
```

---

## 모듈별 역할

### main.py — 앱 진입점
- PyQt5 `QApplication` 생성, 전역 다크 테마 적용
- `SafetyConsole` 윈도우 실행

### safety_console.py — 메인 GUI

**`SafetyConsole`** (QMainWindow)
- 좌측: 카메라 영상 표시 (`camera_label`)
- 우측: 상태 표시 (`state_label`) + 로그 (`log_browser`)
- 상단 버튼: `초소형카메라` / `CCTV` / `캘리브레이션`
- 카메라 전환: `_switch_camera("esp32" | "usb")`
- 앱 시작 시 자동 녹화 시작 (`RECORDING_ENABLED=True`), 종료 시 자동 저장
- 로그를 화면 + `logs/` 파일에 동시 기록

**`CalibrationDialog`** (QDialog)
- 체스보드(7×5) 20샘플 자동 캡처 → `cv2.calibrateCamera()` 실행
- 결과를 `camera_calibration.npz`로 저장
- `CameraThread.raw_frame_signal`로 실시간 프레임 수신

### camera_thread.py — 카메라 + AI 추론

**`CameraThread`** (QThread) — ESP32-S3 TCP 스트림
- TCP 소켓으로 ESP32에 연결, 4바이트 헤더(길이) + JPEG 데이터 수신
- 수신 전용 스레드(`_recv_worker`) + 메인 처리 루프 분리 → 최신 프레임만 유지해 지연 최소화
- 연결 실패/끊김 시 자동 재연결 (`TCP_RECONNECT_DELAY_SEC`)
- 프레임 처리 순서: 수직 플립 → 왜곡 보정(undistort) → YOLO → MediaPipe
- 신호: `change_pixmap_signal` / `log_signal` / `yolo_detections_signal` / `raw_frame_signal` / `calibration_needed_signal`

**`UsbCameraThread`** (QThread) — USB 웹캠(CCTV)
- `cv2.VideoCapture(0)` 으로 웹캠 열기
- 동일한 YOLO + MediaPipe 처리 적용
- `CameraThread`와 동일한 신호 구조

**공통 AI 추론 함수**
- `_run_yolo_shared(frame)`: 공유 YOLO 모델로 추론 (스레드 락 사용)
- `_update_tracks(tracks, detections)`: IoU 기반 간이 트래킹, `YOLO_MAX_MISS` 초과 시 제거
- `_load_undistort_map()`: `camera_calibration.npz` 로드, 해상도 불일치 시 재캘리브레이션 요청
- YOLO / MediaPipe 모두 `try/except`로 선택적 로드 — 없으면 해당 기능만 스킵

### config.py — 전역 설정

| 항목 | 주요 상수 |
|------|----------|
| UI 테마 | `BG_PRIMARY`, `ACCENT`, `STATUS_OK/WARNING/DANGER` 등 |
| YOLO | `YOLO_MODEL_PATH`, `YOLO_CONF_HIGH(0.65)`, `YOLO_CONF_LOW(0.50)`, `YOLO_IOU_MATCH(0.3)`, `YOLO_MAX_MISS(3)` |
| 화면 | `WINDOW_WIDTH(1280)`, `WINDOW_HEIGHT(720)`, `CAMERA_FLIP_VERTICAL(True)` |
| TCP | `CAMERA_TCP_HOST`(.camera_ip에서 읽음), `CAMERA_TCP_PORT(8888)`, 타임아웃/재연결 딜레이 |
| 녹화 | `RECORDING_ENABLED(True)`, `RECORDING_FPS(15)`, `RECORDING_CODEC("MJPG")` |
| 경로 | `YOLO_MODEL_PATH`, `YOLO_CALIBRATION_PATH`, `RECORDING_SAVE_DIR`, `LOG_SAVE_DIR` |

---

## 데이터 흐름

```
ESP32-S3 (OV3660)
  └─ TCP:8888 ──► CameraThread
                    ├─ _recv_worker (수신 전용 스레드)
                    └─ _process_frame
                         ├─ 수직 플립
                         ├─ undistort (camera_calibration.npz)
                         ├─ YOLOv8 추론 + IoU 트래킹
                         └─ MediaPipe 손 랜드마크
                              ├─ change_pixmap_signal ──► SafetyConsole (화면 표시)
                              ├─ yolo_detections_signal ──► SafetyConsole (로그)
                              └─ raw_frame_signal ──► CalibrationDialog (캘리브레이션 중만)

USB 웹캠
  └─ UsbCameraThread (동일 구조)
```

---

## ESP32 IP 변경 방법 (Windows)

`.camera_ip` 파일을 텍스트 에디터로 열어 IP를 직접 수정 후 앱 재시작.

---

## RPi Reference (original/ 폴더 — 참고용 구버전)

| 파일 | 설명 |
|------|------|
| `main_original.py` | 초기 단일 파일 버전 |
| `yolo_hailo_tcp.py` | Hailo AI 추론 (RPi 프로덕션 핵심) |
| `view_stream_tcp.py` | TCP 스트림 단독 뷰어 (RPi 경로 하드코딩) |
| `calibrate_camera.py` | 구버전 터미널 캘리브레이션 (CalibrationDialog로 대체됨) |
| `wifi_dialog.py` | WiFi 프로비저닝 GUI (시리얼 `/dev/ttyACM0`, RPi 전용) |
| `provision_wifi.py` | WiFi 프로비저닝 스크립트 (RPi 전용) |

## Workflow Notes

- **ESP32 펌웨어(.ino) 작업**: Arduino CLI 사용 (Arduino IDE 아님)
- **ESP32 코드 편집/컴파일 위치**: Raspberry Pi에서만 수행 (Windows 노트북에는 Arduino CLI 미설치)
- **Windows 노트북**: Demo/ 의 Python GUI 개발 / 테스트 전용
