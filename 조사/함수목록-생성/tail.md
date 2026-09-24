
## 4. 파악하며 보인 것 (조치하지 않음)

> ✅ = 코드에서 직접 다시 확인함 · 나머지는 함수를 읽으며 적은 메모(4.2 표)이고 **재확인 전**이다. 고칠지·어떻게 고칠지는 정하지 않았다.

### 4.1 동작에 영향이 있을 수 있는 것

| # | 무엇 | 어디 | 확인 |
|---|---|---|---|
| 1 | **손 검출이 버튼 박스가 그려진 프레임을 입력으로 받는다** — 「표시만 바꾼다」는 설정(박스 표시)이 손 검출 입력을 바꾼다. 시연 촬영 중에는 박스가 늘 그려진다 | `camera_thread._process_frame`(박스 그림 → 손 검출) · `set_draw_boxes` 설명 | ✅ |
| 2 | **EMO 로 차단돼도 배너가 「순서 위반이 계속되어 인터락이 작동했습니다」라고 쓴다** — 바로 위 주석은 「EMO 는 순서 위반이 아니다」 | `safety_console._on_fsm_state` → `overlay.AlertBanner.show_block()`(인자 없음) | ✅ |
| 3 | **공구를 쥐었는지 판정하는 주 규칙이 지금 모델에서 동작하지 않는다** — `-in-hand` 클래스를 기대하는데(`tool_v4` 용 · 미채택) 쓰는 모델은 `tool_v3.pt`(driver·wrench·pliers). 손끝이 공구 박스 안에 드는 보조 규칙만 쥠을 판정한다 | `tool_state.ToolState._in_hand_tool` · `config.TOOL_MODEL_PATH` | ✅ |
| 4 | **설정 창에 「4단계 지정 공구」가 박혀 있다** — `recipe.json` 에서 공구 서브 작업은 **2단계(B2)** | `overlay_menu.SettingsPanel.__init__` | ✅ |
| 5 | **음성비서에게 넘기는 공구가 설정에서 바꾼 공구를 반영하지 않는다** — 레시피 원본을 읽는다(판정용 `_sub_spec_for` 는 반영한다) | `safety_console._publish_state` | ✅ |
| 6 | **WARNING 중에 정답 버튼을 눌러도 무시된다**(MONITOR·PROCESS_RUN 에서만 단계 완료) — 설계 의도인지는 미확인 | `fsm.SafetyFSM.press_button` | ✅(동작) · 의도 미확인 |
| 7 | 호출어 판정이 설명과 다르다 — 「앞 두 글자 접두 매칭」이라 적혀 있으나 실제는 **문장 어디든 포함**이면 호출로 본다 | `voice_lib.is_wake` | ✅ |
| 8 | 음성 녹음 파일(`마이크_전체.wav`)을 닫는 함수를 아무도 부르지 않는다 — 파일이 제대로 마무리되지 않을 수 있다 | `voice_assistant.AudioLog.close` | ✅ |
| 9 | 체류 임계값이 두 곳(config 0.3 · `recipe.json`)에 있다 — 런타임은 레시피 값을 쓰고, 값이 없으면 `recipe` 는 1.0 으로 통과시키나 GUI 는 기본값 없이 읽어 오류가 날 수 있다 | `recipe._validate` · `safety_console.__init__` | 메모 |
| 10 | 1인칭 녹화 둘 중 하나가 죽으면 나머지도 조용히 멈춘다 | `demo_recorder._feed` · `demo_ffmpeg.FfmpegSet.start` | 메모 |

### 4.2 이 프로그램 안에서 아무도 부르지 않는 함수

| 함수 | 비고 | 확인 |
|---|---|---|
| `precheck.run_stage2`(+ `_probe_hand` · `summary`) | 「작업 시작 점검(2차)」— GUI 는 `run_stage1` 만 쓴다. 자가 테스트만 부른다 | ✅ |
| `CameraThread.set_active` · `set_host` | 웹캠 제거 전 카메라 전환용으로 보인다 · `set_active` 가 없으니 `_process_frame` 의 비활성 분기는 실행될 일이 없다 | ✅ |
| `hailo_device.shutdown` | 「평상시엔 부를 필요 없다」고 적혀 있다 | ✅ |
| `interlock.InterlockController.gave_up` | 점검은 카메라 쪽 `gave_up` 만 읽는다 | 메모 |
| `frame_orient._selftest` | 측정 도구 몇 곳이 부른다(런타임은 안 부름) | ✅ |
| `camera_thread.roi_at_point` · `CameraThread.draw_boxes` · `frame_orient.undistort_map` · `frame_orient.apply` | 자가 테스트·측정 도구 전용 호환 함수 | ✅ |
| `detector.PyTorchDetector` | 백엔드가 `hailo` 라 쓰이지 않는다 | 메모 |
| `anim.Pulse.active` · `TextPulse.active` | 자가 테스트 전용 | ✅ |

### 4.3 설정(config)을 따르지 않고 값을 따로 적은 곳 (메모)

- 버튼 클래스 이름표(`detector.HailoDetector`) · 손 모델 파일 이름(`hand_tracker`) · 수신 버퍼 1MB(`camera_thread`) · 끊김 임계 2.0초(`fps` 와 `precheck`) · `.camera_ip` 경로·공구 공유 폴더(음성비서) · 녹화 기본 크기 `(640, 480)`(회전 뒤는 세로 — `config.DEMO_FPV_SIZE` 와 다름) · 점검 문구의 「console_v2 로드됨」.
