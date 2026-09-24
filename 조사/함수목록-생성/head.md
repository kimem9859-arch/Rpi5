# 함수 목록 — 실제 시연 프로그램(런타임)의 모든 함수

> `run_demo.sh` → `main.py` 로 뜨는 **실제 시연 프로그램**과, 따로 뜨는 음성비서(`run_voice.sh`)의 함수를 전부 모은 파악 문서다(2026-09-24 작성).
> 대상 = `Rpi5/Demo/` 최상위 모듈 **34개 · 클래스 41 · 함수·메서드 394 · 8,526줄**. 측정·촬영 도구는 [`도구목록.md`](도구목록.md) 에 있다.
>
> - **채운 방법** — 함수 이름·위치·부르는 곳·쓰는 설정값은 **코드를 분석해 기계로** 뽑았다(빠짐 없음). 한 줄 설명은 함수 코드를 읽고 썼다. 파일과 줄은 작성 시점 기준이라 코드가 바뀌면 어긋난다.
> - **부르는 곳** — `직접` = 코드에서 이름으로 부름 · `연결` = Qt 신호·콜백으로 이어짐 · `이름 후보` = 같은 이름의 메서드가 여러 클래스에 있어 어느 쪽인지 코드만으로 확정하지 못함 · `Qt` = Qt 가 화면 이벤트로 부름 · `없음` = 이 프로그램 안에서는 아무도 부르지 않음(도구·테스트가 쓰거나 남은 코드).
> - 이 문서는 **코드를 고치지 않았다.** 파악하며 보인 것은 끝의 4절에 목록으로만 남긴다.

## 1. 전체 흐름 — 한 프레임이 판정이 되기까지

```
[ESP32 카메라] ─TCP:8888─▶ camera_thread.CameraThread
   _recv_worker          최신 JPEG 만 받아 둔다(나머지는 버림)
   run                   JPEG 풀기 → _process_frame
   _process_frame        frame_orient.flip → (왜곡보정 remap) → frame_orient.rotate
                         → detector.HailoDetector.detect (640×640 늘려서 Hailo 추론)
                         → _update_tracks (+ _one_per_class · 가려도 5프레임 유지)
                         → _draw_yolo (화면 표시 켜져 있으면 박스를 그림)
                         → hand_tracker.HandTracker.detect (검지 끝 좌표)  ⚠ 박스가 그려진 프레임을 받는다(4절)
                         → zone_at_point → roi_zones.zone_at_point (손끝이 든 버튼·구역 단계)
                         → 신호: change_pixmap_signal · roi_signal · hand_signal · tool_signal …
                                    │
                                    ▼
safety_console.SafetyConsole (GUI, 메인 스레드)
   _on_roi               fsm.SafetyFSM.update_vision(roi, 시각, 단계)   ← 순서 판정의 입력
   _press_button  ◀── gpio_input.GpioInputController (버튼 B1~B4·EMO)
                         fsm.SafetyFSM.press_button
   _tick_sub (200ms)     sub_task.SubTask(대기·공구 서브 작업) · tool_state.ToolState
   _on_tool      ◀── tool_gate.ToolGate ◀─ /dev/shm ─▶ tool_worker(별도 프로세스, rfenv · ultralytics)
                                    │
             fsm.SafetyFSM 콜백 ────┼─────────────────────────────────────────┐
   _on_fsm_state (화면·결과창)  _on_interlock → interlock.set_interlock      _on_feedback → interlock.set_feedback
                                    │                 (Serial → Arduino 릴레이 · 타워램프)
                                    ▼
   overlay · overlay_menu · overlay_result (글라스 UI)   session_stats (결과창 재료)
   state_publisher ─ /dev/shm ─▶ voice_assistant (별도 프로세스 · ~/env/tts)
   demo_recorder · demo_ffmpeg (시연영상 촬영 때만)
```

## 2. 모듈 역할

| 묶음 | 모듈 | 하는 일 |
|---|---|---|
| **시작** | `main` | Qt 앱을 만들고 `SafetyConsole` 창을 띄운다 |
| | `config` | 모든 설정값의 정본(임계·경로·포트·색·녹화 등) |
| **입력** | `camera_thread` | ESP32 영상 수신 → 방향 처리 → 버튼 검출 → 추적 → 손 → 구역 판정을 한 스레드에서 돈다 |
| | `gpio_input` | 실물 버튼 B1~B4·EMO 를 Pi GPIO 로 읽어 GUI 에 알린다 |
| | `serial_ports` | 시리얼 장치를 USB 신원으로 찾는다(포트 번호를 믿지 않기 위해) |
| **인식** | `detector` | 버튼 검출 모델(Hailo `.hef`) 추론 — 640×640 으로 늘려 넣는다 |
| | `hailo_device` | 여러 모델이 Hailo 장치 하나를 함께 쓰게 한다 |
| | `hand_tracker` | 손 검출(팜 + 랜드마크 21점) → 검지 끝 좌표 |
| | `frame_orient` | 반전·왜곡보정·회전과 해상도별 보정 파일·링 크기의 단일 출처 |
| | `roi_zones` | 손끝이 어느 버튼의 어느 구역(박스 안·링)에 있는가 — 판정 규칙의 단일 출처 |
| | `tool_gate` · `tool_worker` · `tool_state` | 공구 검출을 별도 프로세스로 돌리고(워커), GUI 에서 켜고 끄며(게이트), 쥐었는지 판정한다(상태) |
| **판정** | `fsm` | 순서 위반 감지 상태기계(IDLE·READY·PROCESS_RUN·MONITOR·WARNING·BLOCK) |
| | `recipe` | 정답 순서(`recipe.json`)를 읽는다 |
| | `sub_task` | 버튼 사이의 서브 작업(대기·공구)을 관리한다 |
| **출력** | `interlock` | FSM 판정을 Arduino 릴레이·타워램프로 보낸다 |
| | `safety_console` | 메인 GUI — 모든 부품을 연결하고 화면·로그·점검·녹화를 맡는다 |
| | `overlay` · `overlay_menu` · `overlay_result` | 영상 위 글라스 UI(상태·게이지·경고·연결 막대) · 메뉴·알림·설정·점검·녹화 창 · 완료 결과창 |
| | `anim` · `theme` | 화면 애니메이션 · 다크/화이트 색 토큰 |
| **점검·기록** | `precheck` | 기동·작업 시작·수동 점검 규칙 |
| | `session_stats` | 한 번의 작업에서 일어난 일을 모은다(결과창 재료) |
| | `fps` | 프레임 도착 간격에서 FPS 를 낸다(중앙값) |
| | `state_publisher` | GUI 상태를 `/dev/shm` 파일로 내보낸다(음성비서가 읽음) |
| **촬영** | `demo_recorder` · `demo_ffmpeg` | 시연영상 촬영 때 영상 3개를 동시에 남긴다 |
| **음성(별도 프로세스)** | `voice_assistant` | 음성비서 데몬 — 호출어 → 띠링 → 질문 → 공구 안내 |
| | `voice_lib` · `voice_card` · `voice_llm` · `voice_tts` | 판정 로직(순수 함수) · LLM 에게 줄 사실 카드 · ollama 호출 · 문장 음성 합성 |

## 3. 함수 목록 (모듈별)
