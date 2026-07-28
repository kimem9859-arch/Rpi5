# CLAUDE.md — Rpi5 (SOP 가디언 파이 런타임)

> SOP 가디언의 **라즈베리파이 런타임 코드** (PECVD 정비 SOP 순서위반 감시·차단).
> 작업 브랜치 = `feature/fsm-interlock`. **설계 정본은 상위 sop-project `docs/통합수행설계문서…`**
> (엄브렐러 클론 시 `../docs/…`). 사양은 거기서 읽고, 여기는 런타임 코드 맥락만 둔다.
> ⚠️ 코드 수정 → **이 repo(Rpi5)** push / 통합문서 수정 → **상위 sop-project** push.

## 시스템 흐름 (정본 §7~§9)
비전(버튼 검출 + 손) → 손-버튼 ROI 접촉 → §8 → **FSM 순서판정** → 물리 인터락(트랙 A)·안돈 피드백.

## 핵심 — FSM & 레시피 (fsm-interlock 작업으로 추가)
- **`fsm.py` `SafetyFSM`** — 6상태 `State`(IDLE/READY/PROCESS_RUN/MONITOR/WARNING/BLOCK). 콜백 `on_state_change`·**`on_interlock(bool)`**(→트랙 A 차단)·`on_feedback`. 주요 메서드: `load_recipe()`·`update_vision(roi, now)`·`press_button()`·EMO 처리·`release_warning()`/`release_block()`. 오답 ROI→타이머→WARNING/BLOCK, **EMO→즉시 BLOCK**(해제 시 기대단계=1 리셋, 위반 BLOCK 해제는 기대 유지). 단위테스트 `Demo/selftest/test_fsm.py`.
- **`recipe.py`/`recipe.json`** — 정답 순서 단일 출처. **PM 정비 4단계**: B1 클린·가스차단 → B2 펌프/퍼지 → B3 전극 냉각 → B4 챔버 벤트 (+EMO). `current_step_name`이 여기서 옴. (정본 §6.1과 동기화됨)
- 테스트 절차 전체: **`Demo/docs/TESTING_FSM.md`**. 실HW 테스트는 **라즈베리파이에서** 수행.

## 추론 백엔드 — `detector.py` (★ console_v1.hef 통합 지점)
- `BaseDetector` 인터페이스: `detect(frame)→[(cls_id, score, x1,y1,x2,y2)]`, `class_name(cls_id)`, `close()`.
- `PyTorchDetector`(Phase A, best.pt, ultralytics CPU) ↔ `HailoDetector`(Phase B, .hef, Hailo-8). `config.INFERENCE_BACKEND`로 전환.
- ✅ **console_v1.hef 배선 완료** (상세 [`../dev/ai_model/README.md`](../dev/ai_model/README.md)):
  - 입력 **uint8 640×640 RGB**(float 정규화 ❌, stretch 리사이즈), 출력 **HailoRT NMS 결과** 파싱(raw 텐서 ❌), **HailoRT 4.x**.
  - `class_name`/`_names` = **5클래스(0=B1·1=B2·2=B3·3=B4·4=EMO)** 매핑 완료(`detector.py:112`).
  - .hef(빌드 환경 `D:\Hailo_DFC\console_v1.hef`) → 파이 `Demo/models/console_v1.hef`(`config.HEF_MODEL_PATH`).
- 🆕 **`console_v2.hef` 배포됨(2026-07-16)** — `Demo/models/console_v2.hef`(4.4MB, 파랑 스티커 B4 재학습 + DFC level 1·캘리브 652. 수치 = 상위 통합문서 **§10.14·§10.15**). 규격은 v1과 동일(uint8 640·NMS on-chip·5클래스·HailoRT 4.x)이라 **코드 수정 불필요**.
  - ✅ **`config.HEF_MODEL_PATH` = `console_v2.hef`로 전환됨(2026-07-16, 사용자 요청)** — `bench_detector.py`·`run_demo.sh` 등 **config를 읽는 모든 경로가 v2로 동작**한다(이 둘엔 `--hef` 옵션이 없어 config가 유일한 선택 수단).
  - 🔴 **전환 = 검증이 아니다.** **B4 해결 여부는 여전히 미판정**(§10.16). 기본값이 v2라고 해서 "v2가 검증됐다"고 읽지 말 것.
  - **v1과 대조하려면**: `replay_raw.py`는 `--hef models/console_v1.hef`로 런타임 지정(권장) / `bench_detector.py`·데모는 **config를 `console_v1.hef`로 되돌려야** 한다(`--hef` 미지원).

## GUI·카메라·설정 (기존 모듈 — 현행 유효)
### `safety_console.py` (메인 GUI, QMainWindow)
- 좌: 카메라 영상 / 우: 상태(`state_label`)+로그(`log_browser`). 상단 `초소형카메라`/`CCTV`/`캘리브레이션`.
- `_switch_camera("esp32"|"usb")`. 시작 시 자동 녹화·종료 시 저장. 로그를 화면+`logs/` 동시 기록.
- `CalibrationDialog`: 체스보드(7×5) 20샘플 → `cv2.calibrateCamera()` → `camera_calibration.npz`.

### `camera_thread.py` (카메라 + 추론)
- `CameraThread`(QThread) — ESP32-S3 TCP 스트림: 4바이트 헤더+JPEG, 수신 전용 스레드+처리 루프 분리(최신 프레임만), 자동 재연결. 처리순서: 수직 플립 → undistort → detector(YOLO) → **손 검출(`hand_tracker`)** → `roi_at_point` → `roi_signal` → FSM.
- `UsbCameraThread` — USB 웹캠 동일 처리.
- `_update_tracks()` — IoU 간이 트래킹, `YOLO_MAX_MISS` 초과 제거(**가림 대응**). YOLO `try/except` 선택 로드.
- 🆕 **`hand_tracker.py`(2026-07-22)** — **MediaPipe 프레임워크는 안 쓴다**(Python 3.13/aarch64 휠 없음). 같은 **모델**(BlazePalm·BlazeHandLandmark)을 Hailo `.hef`로 돌린다. `detect(frame)` → 검지끝 좌표. 장치는 `hailo_device`의 **공유 VDevice**(여기서 VDevice를 만들면 버튼 모델과 충돌). ⚠️ 모델·소스가 없거나 `HAND_ENABLED=False`면 **조용히 비활성**되고 `detect()`가 None → 손 검출이 없던 종전과 동일 동작. 🔴 모델·blaze 소스가 **repo 밖**(`~/hoi_probe/`)이라 클론·sop-pi-2에선 자동 비활성(vendoring 미결).
- 🔴 **`safety_console`이 `camera_thread`에서 import하는 이름이 사라지면 GUI가 통째로 죽는다** — 실제로 발생(2026-07-22, `MEDIAPIPE_AVAILABLE`). 방어 = **`Demo/selftest/test_imports.py`**(GUI 진입점 import + AST로 import 이름 실재 대조). `camera_thread`의 최상위 이름을 바꾸면 **이 테스트를 반드시 돌릴 것**.
- 신호: `change_pixmap_signal`/`log_signal`/`yolo_detections_signal`/`raw_frame_signal`/`calibration_needed_signal`.

### `config.py` (전역 설정)
- 추론: `INFERENCE_BACKEND`, `PT_MODEL_PATH`(best.pt)/`HEF_MODEL_PATH`(console_v1.hef), `YOLO_CONF_HIGH(0.65)`/`YOLO_CONF_LOW(0.50)`, `YOLO_IOU_MATCH(0.3)`, `YOLO_MAX_MISS(5)`, `YOLO_INPUT_SIZE(640)`, `FSM_EMO_BUTTON`.
- TCP: `CAMERA_TCP_HOST`(`.camera_ip`에서 읽음)·`PORT(8888)`. 화면 1280×720·`CAMERA_FLIP_VERTICAL`. 녹화 `RECORDING_*`.
- ESP32 IP 변경: `Demo/.camera_ip` 텍스트 수정 후 재시작.

### 데이터 흐름
```
ESP32-S3(OV3660) ─TCP:8888→ CameraThread
   (_recv_worker → 수직플립 → undistort → detector → hand_tracker(손))
      ├─ change_pixmap_signal → SafetyConsole (화면)
      └─ 검출 → zone_at_point(roi_zones: 링1/안쪽2) → SafetyFSM.update_vision(roi, now, level)
         → 체류(§9.4 dwell 0.3·갭메우기 0.3) → 상태전이·on_interlock·피드백
USB 웹캠 ─ UsbCameraThread (동일 구조)
```

### `run_scenario.sh` (기능 검증 촬영 런처, 2026-07-22 신설)
> 🔴 **발표용 시연 녹화가 아니라 "HOI·FSM이 의도대로 도는가"를 눈으로 확인하는 도구**다. HOI는 미완성이므로(감지 천장 57~65%) 여기서 나온 영상은 **기능 확인용**이며 성능 근거로 인용하지 않는다.

`./run_scenario.sh <번호>` — **GUI + 화면녹화 + 웹캠(3인칭)녹화를 한 번에** 띄우고, GUI를 닫으면 녹화도 정리한다. 산출물은 `Demo/scenario/<시각>_s<번호>/`에 4종(`screen.mp4`·`webcam.mp4`·`app_log.txt`·`esp32_fpv.avi`). 따로 켜면 시작 시각이 어긋나 대조가 안 되므로 묶었다. `scenario/`는 gitignore(1080p 두 갈래라 4분에 약 580MB).

🔴 **함정 2개** (둘 다 실제로 물렸음):
1. **GUI가 USB 웹캠을 점유한다** — `UsbCameraThread.run()`이 CCTV 버튼과 무관하게 시작 즉시 `/dev/video0`을 연다. 웹캠을 외부 녹화에 쓰려면 **`config.USB_CAMERA_ENABLED=False`**(환경변수 `SOP_USB_CAMERA=0`)로 양보시킨다. 런처가 자동 설정.
2. **OpenCV로 웹캠을 열면 1080p가 5fps** — 기본 **GStreamer 백엔드**에서 FOURCC 설정이 `unhandled property`로 무시돼 YUYV로 떨어진다. **`cv2.VideoCapture(0, cv2.CAP_V4L2)`를 명시**해야 MJPG 1080p30이 나온다(실측). 그래서 런처의 녹화는 **ffmpeg가 v4l2를 직접** 연다.

※ `SOP_FULLSCREEN=1`이면 GUI가 `showMaximized`로 모니터를 채운다. `showFullScreen`은 쓰지 않는다 — 제목표시줄이 사라져 창을 닫을 수 없는데 **녹화 종료가 GUI 종료에 묶여 있다**.

## 워크플로
- ESP32 펌웨어(.ino) = **Arduino CLI**(IDE 아님), **라즈베리파이에서만** 편집·컴파일(Windows엔 미설치).
- `original/` = 참고용 구버전(`yolo_hailo_tcp.py`=RPi Hailo 추론 핵심, `provision_wifi.py` 등 RPi 전용).
- **⭐ console_v2 데이터 파이프라인 = `Demo/docs/dataset_pipeline.md`** · **라벨링 기준 = `Demo/docs/labeling_guide.md`** (촬영 → 중복제거 → 프리라벨 → Roboflow 업로드 → 라벨링 → 학습. **재현 절차서**). 도구: `test/dedupe_raw.py`(pHash 중복제거·**분할 전에** 실행) · `test/export_labels.py`(v1 검출을 프리라벨로) · `test/review_labels.py`(검수 시각화) · `test/upload_roboflow.py`(Roboflow 업로드).
  - 🔴 **Roboflow 함정 2개**(둘 다 물렸음): ①`annotation_labelmap` 없으면 클래스가 **숫자("0","1")로** 올라감 ②`annotation_overwrite=True` 없으면 이미지 해시 캐시 때문에 `already annotated`로 **스킵되고 옛 라벨이 남음**. 전량 업로드 전 **3장으로 검증** 필수.
  - ⚠️ **분할은 업로드 시점에 명시**(Roboflow 자동 랜덤분할 금지 — 프레임 섞으면 누출 → mAP 거짓 상승). 세션 단위 분할이 기본이나, **세션마다 촬영 변화 축이 다르면 세션마다 나눠 할당**한다(통째로 떼면 그 축이 학습에서 빠짐 — `dataset_pipeline.md` §8).
  - **프리라벨 소스 = 로그를 만든 모델**(`export_labels.py`는 모델을 가리지 않음). ~~B4는 v1이 못 잡아 전량 수동~~ → **v2 소스에서는 B4 포함 달성률 92%**(2026-07-20 클린룸). 검수 우선순위 = ①빠진 박스(가림은 제외) ②클래스 오류 ③박스 타이트함.
  - 🔴 **평가용 test 셋엔 프리라벨 금지** — 평가 대상 모델로 정답을 만들면 순환논리다(§10.19).
  - ❌ 색 기반 자동라벨러(`test/autolabel.py`)는 **채택 안 함** — 달성률 79%로 오르나 **EMO↔B3 오분류 122건**(Hue 인접). 틀린 라벨은 없는 라벨보다 해롭다. 참고용 보존.
- **벤치·B4 대조 실험** = `Demo/test/bench_detector.py`. `--source {esp32,usb}`로 **카메라만 변수**로 두고 대조 측정. `_rawdet_log.csv`(트래킹 이전 raw 검출 ≥`YOLO_CONF_LOW`)가 **B4 저신뢰 구간**을 드러냄 — `_detection_log.csv`(confirmed 트랙 ≥`YOLO_CONF_HIGH`)만 보면 놓친다. 종료 시 **B4 집중 분석**(score 분포·B4↔EMO 오인) 출력. 산출물은 소스 태그 파일명(`{ts}_{src}_*.csv`), `logs/`·`videos/`는 gitignore → `test-artifacts` 브랜치로 보관.
- **벤치 로그 DB** = `Demo/test/db_import.py` — `test/logs/` CSV 전량 + `replay_raw.py` 검출 CSV(`logs/replay/`, 기본 켬·`--no-csv`로 끔)를 `test/bench.db`(SQLite, gitignore)로 재구축. 세션 간 비교·집계는 SQL로(요약 수치 정본은 여전히 통합문서 §10). 시각화 = `db_report.py` → `bench_report.html`(자립형·미추적, 조건별 검출률·v1↔v2·B4 confidence·FPS).
- 🆕 **HOI 분석 DB(2026-07-26)** = `test/hoi.db` — **버튼 DB와 별개 파일**(분석 단위가 프레임 vs **눌림 이벤트**로 다르고, `db_import.py`의 INSERT가 컬럼 수에 고정돼 있어 손대면 그쪽이 깨진다). **서로를 참조하지 않는다.** 설계 = 상위 `docs/superpowers/specs/2026-07-26-HOI-DB-design.md`.
  - **2단계로 나뉜다** — ① `hoi_probe_batch.py --thresh 0.5`(팜 추론 캐시, 22세션 **약 40분**·중단·재개 가능·`--force`로 재생성) → ② `hoi_import.py`(DB 재구축, 수 초). **팜 추론은 raw가 정본이라 안 바뀌고, DB는 규칙이 바뀌면 다시 만든다** — 묶으면 아무도 재구축하지 않는다.
  - 테이블 4개: `sessions`(자세·근접도·구도) · **`presses`(눌림 1회 = 1행, `gap_frames`·`button_y` = §10.26·§10.29의 지배 변수)** · `palm_frames`(**팜 임계·링 폭이 행 안에** — 0.5/0.2 공존) · `button_boxes`(눌림 ±15프레임).
  - 🔴 **ROI 구역 판정은 적재 시에 `roi_zones.zone_at_point()`로 계산**해 `zone_label`·`zone_level`에 넣는다. **SQL에 링 규칙을 다시 쓰지 말 것** — `roi_zones.py`가 단일 출처다.
  - **지표(사전 감지율 등)는 저장하지 않는다** — 질의로 계산(판정 생산이 바뀌면 stale). 예시 질의 4개 = `hoi_import.py` docstring.
  - ⚠️ **`sqlite3` CLI가 이 파이에 없다** — 질의는 `python3 -c "import sqlite3 ..."`로.
  - ⚠️ **수동 매핑 표 2개**(`_POSTURE`·`_VIOLATION_RULE`)가 코드에 있다. 세션이 늘면 갱신할 것 — 미등록 세션은 NULL이 되고 임포터가 그 목록을 **보고**한다.
  - ✅ **검증 = 코드가 아니라 결과로** — §10.28·§10.29 값과 대조해 4건 전부 통과(눌림 503건 일치 · `far-high-r1` 85.7% · `far-low` B4 20.5→77.3% · 속도 계단 58/92/94/96%).
- 🆕 **사전 감지율·FSM 시뮬레이터(2026-07-27)** = `test/hoi_metrics.py` + `test/fsm_sim.py`. `hoi.db`(눌림 단위 DB)를 실제 FSM에 먹여 「창 기반 체류 누적」 실험을 위해 신설. 설계 = `docs/superpowers/specs/2026-07-27-창판정-design.md`.
  - **`hoi_metrics.py`** = 사전 감지율 판정 규칙의 **단일 출처**. `dwell_probe`·구 SQL 예시·즉석 질의 세 군데서 각각 다르게 계산되던 것을 여기 하나로 모았다. 「능력 상한」(창 안에 그 버튼 구역 프레임이 하나라도 있으면 성공)만 담당 — 실제 FSM 판정은 `fsm_sim.py`가 한다.
  - **`fsm_sim.py`** = FSM 오프라인 시뮬레이터. `palm_frames`·`presses`를 시간순으로 재생해 「런타임 거울」 사전 감지율·위반 사전 차단율·E2E 오경보(정상 세션 WARNING 발생률)를 낸다.
  - 🔴 **함정 ① — 재구현하지 않는다.** `fsm_sim.py`는 **실제 `SafetyFSM`을 import**해서 프레임을 먹이는 얇은 껍데기다. 체류·갭메우기·발화 규칙을 여기 다시 쓰면 정본이 둘이 되고 측정이 런타임을 대표하지 못한다 — `dwell_probe`가 config를 안 따라 네 번 물렸던 전례(§10.23)의 근본 해결.
  - 🔴 **함정 ② — `--gate`가 검증 관문이다.** `python3 test/fsm_sim.py --gate`가 실패하면 **그 상태로는 어떤 수치도 쓰지 않는다**(§10.23 재현 실패 → 재정의 경위 = §10.31). 관문은 두 독립 경로(런타임 거울 vs dwell_probe 사전 감지율)의 항등식 대조다.
  - ⚠️ 시뮬레이터의 시뮬레이션 정책(BLOCK·WARNING 즉시 자동 해제, 기대단계 사전 주입, IDLE 시 자동 다음 주기)은 **실제 GUI 운용과 다르다** — 산출 수치는 그 병기 없이 인용 금지.
  - 🔴 **결과 = 「창 기반 체류 누적」 폐기**(§5.7 중단 규칙 발동, `HAND_WINDOW_N=0`) + **E2E 오경보 15.46회/분 첫 측정**. 상세 = 통합문서 §10.31.

## 다음
1. ✅ console_v1.hef 통합·실추론 완료 — B1~B3·EMO 검출, B4 미탐지 → console_v2 재학습 확정. ※ **B4 미탐지 원인 정정(2026-07-03)**: 양자화 반증(에뮬서 int8 .hef가 B4 검출·USB 웹캠선도 검출) → **카메라 입력 품질(OV3660) 주가설·미확정**(sop-project 통합문서 §10.7).
2. ✅ **트랙 A 인터락 코드 완료(2026-06-13)** — 출력부 `interlock.py`(pyserial→Arduino UNO R4 **Minima** 릴레이, RUN/WARN/BLOCK+ACK, 실연결·ACK 검증) + 입력부 `gpio_input.py`(버튼 B1~B4·EMO→FSM, gpiozero Mock 검증) + GUI `⏻ 시스템 종료`(안전종료). 결선도·전원부 = 상위 `../dev/interlock/`(`결선도_초안.md` §3·§5·§8). ✅ **실물 결선 + E2E 검증 완료(2026-07-15, 상세 = 상위 통합문서 §12)** — 전 구간(버튼 GPIO·릴레이·12V 타워램프) + 폴트 3종 통과. 조치: 펌웨어 재업로드, **EMO 비상 중 BLOCK 해제 거부 추가**(`gpio_input.emo_active()` 레벨 체크 + `safety_console._release_block()`).
3. ✅ **console_v2 학습·`.hef` 변환 완료(2026-07-16, 데스크톱)** — 파랑 스티커 B4 데이터셋 652장 재학습(§10.14) → DFC level 1·캘리브 652로 변환(§10.15) → `Demo/models/console_v2.hef` 배포 완료. HAR 검증(uint8·NMS·5클래스) 통과.
4. **▶ 최우선 = ⑤ replay 평가 (파이에서 수행)** — ⚠️ **"싸게 파국을 거르는 안전핀"이지 성능 측정이 아니다.** 몇 분이면 끝나고, **실패 시에만 강한 정보**를 준다(아래 비대칭성). **최종 판정은 여기서 안 난다 — test 세션에서만 난다.**

   #### 실행 (cwd 중요)
   ```bash
   cd ~/sop-project/Rpi5 && git pull            # console_v2.hef 받기
   cd ~/sop-project/Rpi5/Demo                   # 🔴 반드시 Demo/ 에서 — 아래 경로가 전부 상대경로
   ls models/console_v2.hef                     # 배포 확인 (4.4MB)
   ls test/raw/                                 # 🔴 raw는 git에 없다 — 파이 로컬에만 존재. 없으면 ⑤ 불가

   python3 test/replay_raw.py test/raw/20260713_180016 --hef models/console_v2.hef   # 저조도
   python3 test/replay_raw.py test/raw/20260713_175129 --hef models/console_v2.hef   # 정반사
   python3 test/replay_raw.py test/raw/20260713_174153 --hef models/console_v2.hef   # 각도·거리 (비교 기준선)
   ```
   > `--hef`가 런타임에 `config.HEF_MODEL_PATH`를 덮어쓰므로 **config 수정 불필요**(`replay_raw.py:143`). 세 번째(174153)를 꼭 같이 돌려야 **세션 간 비교**가 된다.
   > ※ **HailoRT는 4.x여야 한다**(DFC 3.33.1로 만든 `.hef` 호환 / 5.x 금지). 이 파이는 v1을 4.x로 돌리고 있으므로 **손대지 않았다면 그대로**다. 버전을 올린 적 있다면 먼저 확인할 것.

   #### 🔴 판정 기준 정본 = 통합문서 **§10.16**. "v1 대비 검출률 상승"을 쓰지 말 것 (2026-07-16 정정)
   `test/raw/<세션>`이 곧 **652장 학습 데이터의 출처**라(`Demo/docs/dataset_pipeline.md`) **학습에 쓴 장면으로 시험 보는 구조**다. 게다가 v1은 **파랑 스티커를 학습한 적이 없어**(§10.12 "v1으론 여전히 0% — 학습 분포 밖, **당연**") 0%가 예정돼 있고, v2는 이 프레임으로 학습했다. → **"v1 0회 → v2 N회"는 자동으로 나오고 아무것도 증명하지 않는다.**
   ⚠️ **두 개의 "B4 0%"를 혼동 금지**: ①§10.6의 0회(6월·**검정** B4·원인=카메라 입력 품질) ②파랑 프레임에서 v1의 0%(단순 분포 밖). **다른 현상이다.**

   #### ✅ 이것만 본다 (셋 다 파이에서 가능)
   1. **하한선** — v2가 **자기 학습 데이터에서조차** B4를 못 잡으면 → **즉시 중단·원인 재분석**. **실패=강한 증거 / 통과=약한 증거인 비대칭 테스트.**
   2. **⭐ 세션 간 비교 (핵심)** — 누출이 4세션에 **균등**해 상쇄된다. **저조도(`180016`)만 다른 세션(`174153` 기준선) 대비 무너지면 = 조명 탓**(진짜 신호). §10.13 **"저조도 파랑 B4 생존 미측정"**에 답하는 **유일한 경로**.
   3. **rawdet를 볼 것** — B4는 **트래킹 이전 raw 검출**에서만 저신뢰 구간이 드러난다. confirmed 트랙만 보면 놓친다(위 벤치 항목 참조).

   #### ❌ ⑤로 답할 수 없는 것
   - **`replay_raw.py`엔 정답(ground truth)이 없다** — 출력은 검출 수·프레임율·median/max confidence뿐(precision/recall/mAP 없음). **"B4 검출"이 올바른 위치·클래스인지 알 수 없다.**
   - 실전 성능·일반화 — 같은 날·조명·모조 콘솔, 실시간 AE·움직임 없음, `--raw-every 5`라 트래킹 연속성도 없다.
   - ※ **`.hef` vs `.pt` 양자화 손실 대조는 파이에서 불가**(`replay_raw`는 `--hef`만 받고 `create_detector()`가 `config.INFERENCE_BACKEND`를 읽는다. 파이엔 `console_v2.pt`도 없다). 필요하면 **데스크톱에서 DFC 에뮬레이션**으로 — §10.7이 그 방식으로 v1 양자화를 반증했다.

   #### 결과 처리
   - 🔴 **`.pt` mAP(§10.14)·`.hef` HAR 검증·⑤ 통과 그 무엇으로도 "B4 해결"을 선언하지 말 것** — v1도 앞 두 관문은 전부 통과했고 에뮬레이션서 B4를 고신뢰로 검출했으나 파이 실추론에선 0회였다(수치 §10.5~§10.7). **최종 판정의 유일한 근거 = 미촬영 `test` 세션**(다른 날·조명·실콘솔, 🔴**파랑 스티커 동일 사양 필수**).
   - ※ `config.HEF_MODEL_PATH`는 **이미 v2로 전환됨**(2026-07-16) — ⑤ 결과와 무관하게 바꾼 것이니 **전환을 검증으로 오해하지 말 것**. ⑤가 하한선에서 실패하면 **config를 v1로 되돌리고** 원인 재분석.
   - 통과 시 → 결과를 통합문서 §10에 기록(수치 정본). **그 다음 할 일은 "완료 선언"이 아니라 test 세션 촬영이다.**
