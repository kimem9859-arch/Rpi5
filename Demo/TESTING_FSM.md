# FSM 판정부 테스트 가이드 — `feature/fsm-interlock`

> 이 메모는 **라즈베리파이에서 Claude Code CLI로 이 브랜치를 테스트할 때 처음 읽는 문서**다.
> 무엇이 추가됐고, 어떻게 검증하고, 무엇을 주의할지 한 장에 정리한다.

## 0. 이 브랜치가 뭔가
- `feature/RPi5` 기반 + **작업 순서 위반 감지 FSM(판정부)** 와 그 배선을 추가한 브랜치.
- 목표: 통합 설계문서 **§9 FSM(6상태) + §8 인식→판정→제어**를 코드로 구현한 PoC.
- 핵심 시나리오: 단일 PECVD 콘솔에서 정해진 순서(B1→B2→B3→B4)를 어기면 감지·경고·차단.

## 1. FSM의 두 입력 — ⚠️ 키보드의 정체 (먼저 읽을 것)
FSM은 **서로 다른 두 사건**을 입력으로 받는다. 이 분리가 프로젝트의 핵심이다(§8·§9.3).

| 입력 | 무엇 | 실제 출처 | FSM 호출 |
|---|---|---|---|
| ① 손이 ROI 위에 있다 | 카메라가 본 손-버튼 근접(HOI) | ESP32 카메라 → 비전 | `update_vision(roi)` |
| ② 버튼을 **실제로 눌렀다** | **물리 아케이드 버튼 눌림** | 버튼 → **Arduino → Serial → RPi (PRO-20, 미구현)** | `press_button(btn)` |

- 손만 갖다 대고 머물면 → **WARNING**(아직 안 누름). 거기서 실제로 누르면 → 즉시 **BLOCK**.
- **버튼은 물리 아케이드 버튼이다.** 다만 ②의 진짜 출처인 Arduino Serial(PRO-20)이 아직 없어서,
  **키보드 `1`~`4`·`E`를 그 자리에 임시로 꽂은 대역(stub)** 이다.
- 하드웨어가 붙으면 Serial 리더가 **같은 `fsm.press_button("Bn")`** 을 호출한다 → FSM·로직은 그대로,
  입력원만 `키보드 → Serial`로 교체. (`safety_console._press_button` 주석 참조)

## 2. 추가/수정된 파일 (`Demo/`)
| 파일 | 역할 | 상태 |
|---|---|---|
| `fsm.py` | 순수 상태머신 (6상태·기대단계·체류타이머·해제2종·EMO) | 신규 |
| `recipe.json` | **정답 순서 단일 출처** (§6 4단계) | 신규 |
| `recipe.py` | 레시피 로더 + 검증 | 신규 |
| `check_model.py` | 모델 계약 검증 (클래스 B1~B4·detection) | 신규 |
| `test_fsm.py` / `test_hoi_sim.py` / `test_recipe.py` | 단위·통합 테스트 | 신규 |
| `camera_thread.py` | `roi_at_point`(HOI) + `roi_signal` 추가 | 수정 |
| `safety_console.py` | FSM 연결·상태표시·단계 매뉴얼 UI·키 입력(②대역) | 수정 |
| `config.py` | FSM 임계값 상수 | 수정 |

## 2.5 RPi에서 이 브랜치 펼치기 (worktree — 기존 코드와 충돌 없이)
기존 `feature/RPi5` 체크아웃은 **그대로 두고**, 옆에 별도 폴더로 이 브랜치를 펼친다.
```bash
cd ~/<기존_Rpi5_경로>          # 현재 feature/RPi5가 있는 저장소
git fetch origin
git worktree add ~/Rpi5-fsm feature/fsm-interlock   # 별도 폴더 + 별도 브랜치
cd ~/Rpi5-fsm/Demo
cat TESTING_FSM.md             # 이 문서
```
- `~/Rpi5-fsm`은 완전히 독립된 작업 디렉터리. 기존 폴더는 손대지 않는다.
- 테스트 종료 후 정리: `git worktree remove ~/Rpi5-fsm`
- 최신 변경 받기: `~/Rpi5-fsm`에서 `git pull` (또는 `git fetch && git reset --hard origin/feature/fsm-interlock`)
- Claude Code CLI는 `~/Rpi5-fsm`에서 띄우면 이 문서를 참조해 테스트를 돕는다.

## 3. 빠른 검증 — 하드웨어·카메라 없이 (약 1분)
```bash
cd Demo
python test_fsm.py        # FSM 전이 11종  → "11/11 passed"
python test_hoi_sim.py    # 인식→판정 4종  → "4/4 passed"
python test_recipe.py     # 레시피 5종     → "5/5 passed"
python recipe.py          # 레시피 내용 출력 확인
```
이 4개는 PyQt6/카메라 없이도 돈다(`test_hoi_sim`은 무거운 라이브러리를 스텁으로 막음).
**코드를 고치면 이 테스트부터 통과 유지할 것.**

## 4. 의존성 (GUI 실행 시)
```bash
pip install PyQt6 opencv-python numpy mediapipe ultralytics
```
- 없을 때 동작: `mediapipe`·`ultralytics`는 `try/except`라 없어도 앱은 뜨지만 손검출/추론이 빠짐.
  `PyQt6`·`opencv`·`numpy`는 필수(없으면 `main.py` import 실패).

## 5. 모델 (중요)
- 현재 `models/best.pt` = **person 1클래스** → 버튼을 검출하지 못해 **ROI가 안 잡힘**(비전 전이 없음).
- 버튼 시연하려면 **`console_v1.pt`** 필요. 계약: **YOLOv8 detection, 클래스 이름 정확히 `B1 B2 B3 B4`, imgsz 640**.
- 준비 확인: `python check_model.py console_v1.pt` → "✅ 끼워넣기 가능"
- 끼우기: `console_v1.pt`를 `models/`에 두고 `config.PT_MODEL_PATH` 지정(또는 `best.pt`로 이름 변경).
- 모델이 없어도 **키보드(②대역)만으로 FSM 흐름 전체를 시연**할 수 있다.

## 6. GUI 실행 & 시연
```bash
python main.py
```
조작:
1. **"공정 시작 (레시피 로드)"** → 상태 `IDLE → PROCESS RUN`, 매뉴얼에 1단계 강조(▶)
2. 손을 버튼 위로 → 모델이 `B1~B4` 검출 시 로그에 `[HOI] 손 진입: Bn` (입력①)
3. **키보드** `1`~`4` = B1~B4 **눌림**, `E` = EMO (입력② 대역 — 실제로는 물리버튼)
4. 위반/차단 시 **"WARNING 해제" / "BLOCK 해제"** 버튼으로 복구

### 시연 시나리오
- **정상 진행**: (1단계) 키 `1` → 2단계 → 키 `2` → … → 키 `4` → 공정 완료(IDLE)
- **순서 위반(체류)**: 1단계에서 손을 B3 위에 **1초 이상** 체류 → `WARNING`(현재행 주황 ⚠)
- **순서 위반(강행)**: 위반 ROI에서 키 `3`(오답 버튼) → 즉시 `BLOCK`(빨강 ⛔, 인터록 ON 로그)
- **비상정지**: 키 `E` → 즉시 BLOCK → "BLOCK 해제" → **기대단계 1로 리셋**(처음부터)
- **위반 BLOCK 해제**: 오답 강행 BLOCK은 해제해도 **기대단계 유지**(EMO와 다름)

## 7. 알려진 한계 / 디버깅 포인트
- **카메라 미연결**: ESP32(초소형카메라) 안 붙으면 프레임 0 → 비전 전이 없음. 상단 **CCTV**로 USB 웹캠 전환 가능.
- **MediaPipe 없음**: 손끝 미검출 → ROI 항상 빈값 → 비전으로 MONITOR 진입 불가(키보드는 됨).
- **FPV 깜빡임**: 손/박스가 프레임마다 들락거리면 체류 타이머가 리셋돼 WARNING이 안 뜰 수 있음(디바운스 미적용 — 실측 후 튜닝 대상).
- **키 입력 안 먹음**: 메인창에 포커스가 있어야 함(버튼/로그 클릭 후엔 창을 한번 클릭).
- **Phase B(Hailo)**: `detector.py`의 `HailoDetector._names`가 `{0:"person"}` 하드코딩 → HEF 전환 시 `B1~B4`로 수정 필요.

### 로그로 상태 확인
- `[레시피] 'PECVD 기동 시퀀스' 로드 — 4단계` → 레시피 OK
- `[시스템] MediaPipe 사용 가능: True/False`
- `[Detector] '...' 백엔드 로드 완료` 또는 `사용 불가`
- `[HOI] 손 진입: Bn` → ROI 판정(입력①) 동작 중
- `[버튼] Bn 눌림` → 입력② 동작 중
- `[FSM] ... → ...`, `[인터록] 전기 신호 차단/복구`

## 8. Claude Code CLI 참고
- **정본 설계 문서**(이 저장소 밖, 사용자 보유): 통합 설계문서 §6(시퀀스)·§8(연결)·§9(FSM 6상태·임계값). 이 브랜치 코드는 그 §9의 구현체.
- FSM 로직 수정 시 §9.3 전이 시나리오와 `test_fsm.py`를 기준으로 검증.
- 정답 순서·단계 이름을 바꾸려면 **`recipe.json`만** 수정(코드 X).
- 다음 큰 작업: **PRO-20 Arduino Serial 리더**(키보드 대역 → 실제 버튼) + **`_on_interlock`을 실제 릴레이 차단**으로 연결.
