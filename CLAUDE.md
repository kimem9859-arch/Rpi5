# CLAUDE.md — Rpi5 (SOP 가디언 파이 런타임)

> SOP 가디언의 **라즈베리파이 런타임 코드** (PECVD 정비 SOP 순서위반 감시·차단).
> 작업 브랜치 = `feature/fsm-interlock`. **설계 정본은 상위 sop-project `docs/통합수행설계문서…`**
> (엄브렐러 클론 시 `../docs/…`). 사양은 거기서 읽고, 여기는 런타임 코드 맥락만 둔다.
> ⚠️ 코드 수정 → **이 repo(Rpi5)** push / 통합문서 수정 → **상위 sop-project** push.

## 시스템 흐름 (정본 §7~§9)
비전(버튼 검출 + 손) → 손-버튼 ROI 접촉 → §8 → **FSM 순서판정** → 물리 인터락(트랙 A)·안돈 피드백.

## 핵심 — FSM & 레시피 (fsm-interlock 작업으로 추가)
- **`fsm.py` `SafetyFSM`** — 6상태 `State`(IDLE/READY/PROCESS_RUN/MONITOR/WARNING/BLOCK). 콜백 `on_state_change`·**`on_interlock(bool)`**(→트랙 A 차단)·`on_feedback`. 주요 메서드: `load_recipe()`·`update_vision(roi, now)`·`press_button()`·EMO 처리·`release_warning()`/`release_block()`. 오답 ROI→타이머→WARNING/BLOCK, **EMO→즉시 BLOCK**(해제 시 기대단계=1 리셋, 위반 BLOCK 해제는 기대 유지). 단위테스트 `test_fsm.py`.
- **`recipe.py`/`recipe.json`** — 정답 순서 단일 출처. **PM 정비 4단계**: B1 클린·가스차단 → B2 펌프/퍼지 → B3 전극 냉각 → B4 챔버 벤트 (+EMO). `current_step_name`이 여기서 옴. (정본 §6.1과 동기화됨)
- 테스트 절차 전체: **`TESTING_FSM.md`**. 실HW 테스트는 **라즈베리파이에서** 수행.

## 추론 백엔드 — `detector.py` (★ console_v1.hef 통합 지점)
- `BaseDetector` 인터페이스: `detect(frame)→[(cls_id, score, x1,y1,x2,y2)]`, `class_name(cls_id)`, `close()`.
- `PyTorchDetector`(Phase A, best.pt, ultralytics CPU) ↔ `HailoDetector`(Phase B, .hef, Hailo-8). `config.INFERENCE_BACKEND`로 전환.
- ⚠️ **console_v1.hef 배선 시** (상세 [`../dev/ai_model/README.md`](../dev/ai_model/README.md)):
  - 입력 **uint8 640×640 RGB**(float 정규화 ❌), 출력 **HailoRT NMS 결과** 파싱(raw 텐서 ❌), **HailoRT 4.x**.
  - `class_name`/`_names`를 **5클래스(0=B1·1=B2·2=B3·3=B4·4=EMO)** 로 — 현재 `{0:"person"}` 하드코딩이라 **수정 필요**.
  - .hef(빌드 환경 `D:\Hailo_DFC\console_v1.hef`)를 파이로 옮겨 `Demo/YOLO model/` 또는 지정 경로에.

## GUI·카메라·설정 (기존 모듈 — 현행 유효)
### `safety_console.py` (메인 GUI, QMainWindow)
- 좌: 카메라 영상 / 우: 상태(`state_label`)+로그(`log_browser`). 상단 `초소형카메라`/`CCTV`/`캘리브레이션`.
- `_switch_camera("esp32"|"usb")`. 시작 시 자동 녹화·종료 시 저장. 로그를 화면+`logs/` 동시 기록.
- `CalibrationDialog`: 체스보드(7×5) 20샘플 → `cv2.calibrateCamera()` → `camera_calibration.npz`.

### `camera_thread.py` (카메라 + 추론)
- `CameraThread`(QThread) — ESP32-S3 TCP 스트림: 4바이트 헤더+JPEG, 수신 전용 스레드+처리 루프 분리(최신 프레임만), 자동 재연결. 처리순서: 수직 플립 → undistort → detector(YOLO) → MediaPipe 손.
- `UsbCameraThread` — USB 웹캠 동일 처리.
- `_update_tracks()` — IoU 간이 트래킹, `YOLO_MAX_MISS` 초과 제거(**가림 대응**). YOLO/MediaPipe `try/except` 선택 로드.
- 신호: `change_pixmap_signal`/`log_signal`/`yolo_detections_signal`/`raw_frame_signal`/`calibration_needed_signal`.

### `config.py` (전역 설정)
- 추론: `INFERENCE_BACKEND`, `YOLO_MODEL_PATH`, `YOLO_CONF_HIGH(0.65)`/`YOLO_CONF_LOW(0.50)`, `YOLO_IOU_MATCH(0.3)`, `YOLO_MAX_MISS(3)`, `FSM_EMO_BUTTON`.
- TCP: `CAMERA_TCP_HOST`(`.camera_ip`에서 읽음)·`PORT(8888)`. 화면 1280×720·`CAMERA_FLIP_VERTICAL`. 녹화 `RECORDING_*`.
- ESP32 IP 변경: `Demo/.camera_ip` 텍스트 수정 후 재시작.

### 데이터 흐름
```
ESP32-S3(OV3660) ─TCP:8888→ CameraThread
   (_recv_worker → 수직플립 → undistort → detector → MediaPipe)
      ├─ change_pixmap_signal → SafetyConsole (화면)
      └─ 검출 → 손-버튼 ROI/HOI → SafetyFSM.update_vision → 상태전이·on_interlock·피드백
USB 웹캠 ─ UsbCameraThread (동일 구조)
```

## 워크플로
- ESP32 펌웨어(.ino) = **Arduino CLI**(IDE 아님), **라즈베리파이에서만** 편집·컴파일(Windows엔 미설치).
- `original/` = 참고용 구버전(`yolo_hailo_tcp.py`=RPi Hailo 추론 핵심, `provision_wifi.py` 등 RPi 전용).

## 다음
1. ✅ console_v1.hef 통합·실추론 완료 — B1~B3·EMO 검출, B4 미탐지 → console_v2 재학습 확정.
2. ✅ **트랙 A 인터락 코드 완료(2026-06-13)** — 출력부 `interlock.py`(pyserial→Arduino UNO R4 **Minima** 릴레이, RUN/WARN/BLOCK+ACK, 실연결·ACK 검증) + 입력부 `gpio_input.py`(버튼 B1~B4·EMO→FSM, gpiozero Mock 검증) + GUI `⏻ 시스템 종료`(안전종료). 결선도·전원부 = 상위 `../dev/interlock/`(`결선도_초안.md` §3·§5·§8). **▶ 다음 = 실물 결선 + E2E**(버튼 GPIO·릴레이·타워램프, 사용자).
3. **▶ 최우선 = console_v2 재학습**(B4 미탐지, GPU 환경) → DFC 변환·파이 재통합.
