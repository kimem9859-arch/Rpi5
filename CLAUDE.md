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
- ✅ **console_v1.hef 배선 완료** (상세 [`../dev/ai_model/README.md`](../dev/ai_model/README.md)):
  - 입력 **uint8 640×640 RGB**(float 정규화 ❌, stretch 리사이즈), 출력 **HailoRT NMS 결과** 파싱(raw 텐서 ❌), **HailoRT 4.x**.
  - `class_name`/`_names` = **5클래스(0=B1·1=B2·2=B3·3=B4·4=EMO)** 매핑 완료(`detector.py:112`).
  - .hef(빌드 환경 `D:\Hailo_DFC\console_v1.hef`) → 파이 `Demo/models/console_v1.hef`(`config.HEF_MODEL_PATH`).
- 🆕 **`console_v2.hef` 배포됨(2026-07-16)** — `Demo/models/console_v2.hef`(4.4MB, 파랑 스티커 B4 재학습 + DFC level 1·캘리브 652. 수치 = 상위 통합문서 **§10.14·§10.15**). 규격은 v1과 동일(uint8 640·NMS on-chip·5클래스·HailoRT 4.x)이라 **코드 수정 불필요**.
  - ⚠️ **`config.HEF_MODEL_PATH`는 아직 v1 그대로다**(의도적). **B4 해결 여부가 미판정**이라 데모 기본값을 미검증 모델로 바꾸지 않았다. → **⑤ replay 평가 통과 후 v2로 전환**할 것.
  - **⑤ 평가는 config 변경 없이 가능**: `python3 test/replay_raw.py test/raw/20260713_180016 --hef models/console_v2.hef`(`--hef`가 런타임에 `config.HEF_MODEL_PATH`를 덮어씀).

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
- 추론: `INFERENCE_BACKEND`, `PT_MODEL_PATH`(best.pt)/`HEF_MODEL_PATH`(console_v1.hef), `YOLO_CONF_HIGH(0.65)`/`YOLO_CONF_LOW(0.50)`, `YOLO_IOU_MATCH(0.3)`, `YOLO_MAX_MISS(5)`, `YOLO_INPUT_SIZE(640)`, `FSM_EMO_BUTTON`.
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
- **⭐ console_v2 데이터 파이프라인 = `Demo/dataset_pipeline.md`** · **라벨링 기준 = `Demo/labeling_guide.md`** (촬영 → 중복제거 → 프리라벨 → Roboflow 업로드 → 라벨링 → 학습. **재현 절차서**). 도구: `test/dedupe_raw.py`(pHash 중복제거·**분할 전에** 실행) · `test/export_labels.py`(v1 검출을 프리라벨로) · `test/review_labels.py`(검수 시각화) · `test/upload_roboflow.py`(Roboflow 업로드).
  - 🔴 **Roboflow 함정 2개**(둘 다 물렸음): ①`annotation_labelmap` 없으면 클래스가 **숫자("0","1")로** 올라감 ②`annotation_overwrite=True` 없으면 이미지 해시 캐시 때문에 `already annotated`로 **스킵되고 옛 라벨이 남음**. 전량 업로드 전 **3장으로 검증** 필수.
  - ⚠️ **분할은 세션 단위·업로드 시점에 명시**(Roboflow 자동 랜덤분할 금지 — 프레임 섞으면 누출 → mAP 거짓 상승). ⚠️ **B4는 파랑 스티커라 v1이 못 잡음 → 전량 수동**.
  - ❌ 색 기반 자동라벨러(`test/autolabel.py`)는 **채택 안 함** — 달성률 79%로 오르나 **EMO↔B3 오분류 122건**(Hue 인접). 틀린 라벨은 없는 라벨보다 해롭다. 참고용 보존.
- **벤치·B4 대조 실험** = `Demo/test/bench_detector.py`. `--source {esp32,usb}`로 **카메라만 변수**로 두고 대조 측정. `_rawdet_log.csv`(트래킹 이전 raw 검출 ≥`YOLO_CONF_LOW`)가 **B4 저신뢰 구간**을 드러냄 — `_detection_log.csv`(confirmed 트랙 ≥`YOLO_CONF_HIGH`)만 보면 놓친다. 종료 시 **B4 집중 분석**(score 분포·B4↔EMO 오인) 출력. 산출물은 소스 태그 파일명(`{ts}_{src}_*.csv`), `logs/`·`videos/`는 gitignore → `test-artifacts` 브랜치로 보관.

## 다음
1. ✅ console_v1.hef 통합·실추론 완료 — B1~B3·EMO 검출, B4 미탐지 → console_v2 재학습 확정. ※ **B4 미탐지 원인 정정(2026-07-03)**: 양자화 반증(에뮬서 int8 .hef가 B4 검출·USB 웹캠선도 검출) → **카메라 입력 품질(OV3660) 주가설·미확정**(sop-project 통합문서 §10.7).
2. ✅ **트랙 A 인터락 코드 완료(2026-06-13)** — 출력부 `interlock.py`(pyserial→Arduino UNO R4 **Minima** 릴레이, RUN/WARN/BLOCK+ACK, 실연결·ACK 검증) + 입력부 `gpio_input.py`(버튼 B1~B4·EMO→FSM, gpiozero Mock 검증) + GUI `⏻ 시스템 종료`(안전종료). 결선도·전원부 = 상위 `../dev/interlock/`(`결선도_초안.md` §3·§5·§8). ✅ **실물 결선 + E2E 검증 완료(2026-07-15, 상세 = 상위 통합문서 §12)** — 전 구간(버튼 GPIO·릴레이·12V 타워램프) + 폴트 3종 통과. 조치: 펌웨어 재업로드, **EMO 비상 중 BLOCK 해제 거부 추가**(`gpio_input.emo_active()` 레벨 체크 + `safety_console._release_block()`).
3. ✅ **console_v2 학습·`.hef` 변환 완료(2026-07-16, 데스크톱)** — 파랑 스티커 B4 데이터셋 652장 재학습(§10.14) → DFC level 1·캘리브 652로 변환(§10.15) → `Demo/models/console_v2.hef` 배포 완료. HAR 검증(uint8·NMS·5클래스) 통과.
4. **▶ 최우선 = ⑤ replay 평가 (파이에서 수행)** — **B4 판정은 오직 여기서만 가능하다.**
   ```bash
   python3 test/replay_raw.py test/raw/20260713_180016 --hef models/console_v2.hef   # 저조도 — B3·B4 살아났나
   python3 test/replay_raw.py test/raw/20260713_175129 --hef models/console_v2.hef   # 정반사 — B2 중복 회귀 없나
   ```
   - **판정 기준**: v1 대비 **저조도 B3·B4 검출률 상승** · **정반사 B2 중복 오분류 무회귀**.
   - 🔴 **`.pt` mAP(0.995)나 `.hef` HAR 검증 통과로 B4 해결을 주장하지 말 것** — **v1도 그 관문은 전부 통과했고 에뮬레이션서 B4를 0.95로 검출했으나 파이 실추론에선 0회**였다(§10.5~§10.7). 실패 지점은 **실제 ESP32 입력**이었고 `replay_raw`만이 그 조건을 재현한다.
   - ⚠️ **저조도 파랑 B4 생존은 이때 처음 측정**된다(v1이 파랑을 못 잡아 프리라벨 0 → §10.13 미측정 플래그).
   - 통과하면 → `config.HEF_MODEL_PATH`를 `console_v2.hef`로 전환 + 결과를 통합문서 §10에 기록.
