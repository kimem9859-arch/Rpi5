# CLAUDE.md — Rpi5 (SOP 가디언 파이 런타임)

> SOP 가디언의 **라즈베리파이 런타임 코드** (PECVD 정비 SOP 순서위반 감시·차단).
> 작업 브랜치 = **`main`** (2026-08-13 단일화 — `feature/*` 병합·삭제. `test-artifacts`만 측정
> 원자료 보관용으로 남김). **설계 정본은 상위 sop-project `docs/통합수행설계문서…`**
> (엄브렐러 클론 시 `../docs/…`). 사양은 거기서 읽고, 여기는 런타임 코드 맥락만 둔다.
> ⚠️ 코드 수정 → **이 repo(Rpi5)** push / 통합문서 수정 → **상위 sop-project** push.

## 시스템 흐름 (정본 §6~§8)
비전(버튼 검출 + 손) → 손-버튼 ROI 접촉 → §7.0 → **FSM 순서판정** → 물리 인터락(트랙 A)·안돈 피드백.

## 핵심 — FSM & 레시피 (fsm-interlock 작업으로 추가)
- **`fsm.py` `SafetyFSM`** — 6상태 `State`(IDLE/READY/PROCESS_RUN/MONITOR/WARNING/BLOCK). 콜백 `on_state_change`·**`on_interlock(bool)`**(→트랙 A 차단)·`on_feedback`. 주요 메서드: `load_recipe()`·`update_vision(roi, now)`·`press_button()`·EMO 처리·`release_warning()`/`release_block()`. 오답 ROI→타이머→WARNING/BLOCK, **EMO→즉시 BLOCK**(해제 시 기대단계=1 리셋, 위반 BLOCK 해제는 기대 유지). 단위테스트 `Demo/selftest/test_fsm.py`.
- **`recipe.py`/`recipe.json`** — 정답 순서 단일 출처. **PM 정비 4단계**: B1 클린·가스차단 → B2 펌프/퍼지 → B3 전극 냉각 → B4 챔버 벤트 (+EMO). `current_step_name`이 여기서 옴. (정본 §5.1과 동기화됨)
- 테스트 절차 전체: **`Demo/docs/TESTING_FSM.md`**. 실HW 테스트는 **라즈베리파이에서** 수행.

## 추론 백엔드 — `detector.py` (★ console_v1.hef 통합 지점)
- `PyTorchDetector`(Phase A, best.pt, ultralytics CPU) ↔ `HailoDetector`(Phase B, .hef, Hailo-8). `config.INFERENCE_BACKEND`로 전환.
- ✅ **console_v1.hef 배선 완료** (상세 [`../dev/ai_model/README.md`](../dev/ai_model/README.md)):
  - 입력 **uint8 640×640 RGB**(float 정규화 ❌, stretch 리사이즈), 출력 **HailoRT NMS 결과** 파싱(raw 텐서 ❌), **HailoRT 4.x**.
  - `class_name`/`_names` = **5클래스(0=B1·1=B2·2=B3·3=B4·4=EMO)** 매핑 완료(`detector.py:112`).
  - .hef(빌드 환경 `D:\Hailo_DFC\console_v1.hef`) → 파이 `Demo/models/console_v1.hef`(`config.HEF_MODEL_PATH`).
- **`console_v2.hef`** — `Demo/models/console_v2.hef`(4.4MB, 파랑 스티커 B4 재학습 + DFC level 1·캘리브 652. 수치 = 상위 통합문서 **§12.14·§12.15**). 규격은 v1과 동일(uint8 640·NMS on-chip·5클래스·HailoRT 4.x)이라 **코드 수정 불필요**.
  - ✅ **`config.HEF_MODEL_PATH` 의 현재 값은 `console_v2.hef`** — `bench_detector.py`·`run_demo.sh` 등 **config를 읽는 모든 경로가 v2로 동작**한다(이 둘엔 `--hef` 옵션이 없어 config가 유일한 선택 수단).
  - 🔴 **전환 = 검증이 아니다.** **B4 해결 여부는 여전히 미판정**(§12.16). 기본값이 v2라고 해서 "v2가 검증됐다"고 읽지 말 것.
  - **v1과 대조하려면**: `replay_raw.py`는 `--hef models/console_v1.hef`로 런타임 지정(권장) / `bench_detector.py`·데모는 **config를 `console_v1.hef`로 되돌려야** 한다(`--hef` 미지원).

## GUI·카메라·설정 (기존 모듈 — 현행 유효)
### `safety_console.py` (메인 GUI, QMainWindow)
- **캘리브레이션 = `test/calib_capture.py` 만** — GUI 창(`CalibrationDialog`)은 없앴다. 런타임 파일을 덮어쓰고 상하 반전 전 사진으로 계산해 렌즈 중심 cy 가 어긋났기 때문이다. 보정 파일은 **`camera_calibration_<w>x<h>.npz` 우선** → 없으면 `camera_calibration.npz` 를 `image_size` 가 맞을 때만 — 선택 규칙 정본 = `frame_orient.calibration_path`. 없으면 로그에 안내만 남기고 보정 없이 돈다.
  - ⚠️ **손에 들고 찍으면 안 된다** — 센서가 한 장을 줄 단위로 약 36ms 에 걸쳐 읽어(롤링 셔터) 평면 맞춤 오차가 1.7px 까지 커졌다. 카메라를 고정하고 체스보드(노트북 화면·인쇄 종이)를 놓아 두고 찍는다. 결과·한계 = 상위 §12.69.
- **`anim.py`** — 오버레이 전환 애니메이션(설계 = 상위 `specs/2026-08-16-ui-애니메이션-design.md`). 🔴 **갱신 함수는 `_sub_timer`가 200ms 주기로 반복 호출한다** — 애니메이션은 반드시 「직전 상태와 달라졌을 때만」 건다(비교 없이 걸면 초당 5번 재시작). 🔴 **QGraphicsEffect 계열 금지**(`overlay.py:73` 페인터 충돌 사고). 끄기 = `SOP_UI_ANIM=0`. ✅ **성능 판정 완료(2026-08-26, G6)** — FPS 영향 **+0.8%**(문턱 10% 이내)라 기본 True 유지. 조건 = **USB 웹캠**·손 없는 정지 장면·ON/OFF 교차 6런(§12.48). 🔴 **USB 웹캠은 제거됐다** — 재측정 도구 `test/anim_fps_bench.py` 는 ESP32 뿐이고, 공급 FPS 가 3~25 로 요동해 효과가 묻히는 한계를 결과와 함께 적는다. FPS 화면 표시 = `SOP_SHOW_FPS=1`.
- **`fps.py` 의 `fps_stale()`** — 🔴 **프레임이 끊겨도 FPS 가 마지막 값으로 계속 찍히던 결함**을 막는다(`fps_from_intervals` 가 중앙값이라 남은 간격이 같은 값을 영원히 낸다 → **화면은 멈췄는데 FPS 는 정상으로 보인다**). 표본을 버리는 자리는 **두 곳**이다 — `_update_conn_bar`(끊긴 채 유지) · `_note_frame`(끊겼다 복구). ⚠️ **끊김 임계 2.0 초는 2차 점검 「영상 수신」(`precheck`)과 같은 값을 쓴다** — 두 곳이 다른 숫자를 쓰면 표시와 점검이 서로 다른 말을 한다.

### `camera_thread.py` (카메라 + 추론)
- `CameraThread`(QThread) — ESP32-S3 TCP 스트림: 4바이트 헤더+JPEG, 수신 전용 스레드+처리 루프 분리(최신 프레임만), 자동 재연결. 처리순서: **수직 플립 → undistort → 회전(CCW90)** → detector(YOLO) → **손 검출(`hand_tracker`)** → `roi_at_point` → `roi_signal` → FSM.
  - **`frame_orient.py`** — 방향 보정(반전·회전)의 **단일 출처**. ESP32 장착 구도가 시계방향 90° 로 바뀌어 반시계 90° 보정이 붙었고, 프레임이 **세로**가 된다(VGA 640×480 → 480×640 · XGA 1024×768 → 768×1024). 런타임과 측정 도구(`test/tool_live`·`test/bench_detector`)가 같은 모듈을 쓴다 — `roi_zones` 와 같은 이유(도구가 Qt·Hailo 를 못 끌어온다).
  - 🔴 **회전은 반드시 undistort 뒤다.** 앞에 두면 가로세로가 뒤바뀌어 `_init_calibration` 이 보정 파일(센서 원본 해상도 전용)을 'mismatch' 로 판단해 **왜곡보정을 조용히 끈다**(로그 한 줄만 남고 화면은 멀쩡해 보인다).
  - **해상도는 런타임이 첫 프레임으로 맞춘다** — 보정 파일 선택과 픽셀 설정(링 = `HAND_ROI_RING_PX_VGA` 25 × `frame_orient.px_scale` → XGA 40px)이 첫 프레임 크기를 따른다. 펌웨어만 VGA↔XGA 로 바꿔 구우면 된다. 로그 `[캘리브레이션] <파일> 로드 (<w>×<h>) · 링 <n>px` 로 확인.
  - ⚠️ **검출 정확도 영향 미측정** — `detector.py` 는 프레임을 정사각 640×640 으로 **늘려서** 넣는다. 종전 4:3(세로 1.33배 늘림) → 회전 후 3:4(**가로** 1.33배 늘림)로 바뀌어 배포 모델이 보는 그림이 달라진다. 콘솔을 화면에 넣고 재측정할 것.
- USB 웹캠(`UsbCameraThread`·CCTV 전환·시연/촬영/음성 녹화의 3인칭·`bench_detector --source usb`)은 **제거됐다** — 백업 태그 `backup/webcam-before-removal-20260923`(꺼낼 때 `git checkout <태그> -- <파일>`).
- `_update_tracks()` — IoU 간이 트래킹, `YOLO_MAX_MISS` 초과 제거(**가림 대응**). YOLO `try/except` 선택 로드.
- **`hand_tracker.py`** — **MediaPipe 프레임워크는 안 쓴다**(Python 3.13/aarch64 휠 없음). 같은 **모델**(BlazePalm·BlazeHandLandmark)을 Hailo `.hef`로 돌린다. `detect(frame)` → 검지끝 좌표. 장치는 `hailo_device`의 **공유 VDevice**(여기서 VDevice를 만들면 버튼 모델과 충돌). ⚠️ 모델·소스가 없거나 `HAND_ENABLED=False`면 **조용히 비활성**되고 `detect()`가 None → 손 검출이 없던 종전과 동일 동작. 🔴 모델·blaze 소스가 **repo 밖**(`~/lab/hoi/`)이라 클론·sop-pi-2에선 자동 비활성(vendoring 미결).
- 🔴 **`safety_console`이 `camera_thread`에서 import하는 이름이 사라지면 GUI가 통째로 죽는다** — 실제로 발생(2026-07-22, `MEDIAPIPE_AVAILABLE`). 방어 = **`Demo/selftest/test_imports.py`**(GUI 진입점 import + AST로 import 이름 실재 대조). `camera_thread`의 최상위 이름을 바꾸면 **이 테스트를 반드시 돌릴 것**.

### `config.py` (전역 설정)
- 추론·TCP·화면·녹화 설정은 **`config.py` 를 직접 본다** — 값을 여기 복제하지 않는다(설계값 정본 = 통합문서 §7.4).
- ESP32 IP 변경: `Demo/.camera_ip` 텍스트 수정 후 재시작.

#### 🔴 ESP32 실HW 함정 (둘 다 실제로 물릴 뻔했다)
- 🔴 **개체는 «시리얼번호»로 식별한다. `ttyACM` 번호를 믿지 말 것** — 꽂는 순서로 뒤바뀐다.
  **더 위험한 것은 sn 자체가 서로 닮았다는 점이다:**
  `3C:0F:02:DD:5E:`**`58`** = 메인(안경·카메라) / `3C:0F:02:DD:5E:`**`40`** = 서브(마이크) — **마지막 바이트만 다르다.**
  (`44:1B:F6:80:3A:DC` = 예비. BAT+ 패드 손상으로 배터리 불가.)
  굽기 전 `python3 -c "from serial.tools import list_ports; [print(p.device, p.serial_number) for p in list_ports.comports() if p.vid]"` 로 확인한다.
  **잘못 구우면 다른 작업 세션의 펌웨어가 통째로 날아간다.** 남의 보드를 빌려 쓸 때는 **8MB 전체 백업 + `verify-flash`** 부터(`~/lab/esp32-link/RESTORE.md`).
- 🔴 **촬영 직전 `arduino/read_esp32_ip.sh` 를 한 번 돌린다(10초).**
  `192.168.1.x` = 공유기(정상) / `10.47.16.x` = **폰 핫스팟으로 샜다** → ESP32만 전원 재투입.
  이유 = 우선순위 스캔은 **부팅 시 연결에 성공하면 끝나고 다시 돌지 않는다.** 공유기(무선 30~60초)보다 ESP32(약 2초)가 먼저 뜨면 폰에 붙어 **그날 내내 고착**된다.
  🔴 **이 고장은 조용하다** — 영상도 GUI도 정상으로 보이고 FPS만 떨어진다. 경위·처방 = 통합문서 §12.60-(4).

### 데이터 흐름
```
ESP32-S3(OV3660) ─TCP:8888→ CameraThread
   (_recv_worker → 수직플립 → undistort → **회전CCW90** → detector → hand_tracker(손))
      ├─ change_pixmap_signal → SafetyConsole (화면)
      └─ 검출 → zone_at_point(roi_zones: 링1/안쪽2 · 링 = VGA 25px × px_scale) → SafetyFSM.update_vision(roi, now, level)
         → 체류(§7.4 dwell 0.3·갭메우기 0.3) → 상태전이·on_interlock·피드백
```

## 워크플로

- ESP32 펌웨어(.ino) = **Arduino CLI**(IDE 아님), **라즈베리파이에서만** 편집·컴파일(Windows 엔 미설치).
- `original/` = 참고용 구버전(`yolo_hailo_tcp.py` = RPi Hailo 추론 핵심, `provision_wifi.py` 등 RPi 전용).
- **촬영·런처 함정** = `../.claude/skills/촬영/` · **데이터셋·라벨링** = `../.claude/skills/데이터셋/` · **벤치·DB·시뮬레이터** = `../.claude/skills/측정도구/`
  - 파이프라인 문서 = `Demo/docs/dataset_pipeline.md` · 라벨링 기준 = `Demo/docs/labeling_guide.md` · FSM 테스트 = `Demo/docs/TESTING_FSM.md`

## 다음

> 🔴 **여기에 진행 상황을 쓰지 않는다.** 「지금 어디까지·다음 할 일」은 `../docs/작업로그.md` 의 `⏸`/`▶` 가 정본이다.
> replay 평가 절차·판정 논리 = `../.claude/skills/측정도구/replay평가.md`
