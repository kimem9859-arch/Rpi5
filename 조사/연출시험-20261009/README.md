# 연출 시험 — 시연영상 후처리 합성 (2026-10-09 · 파이1 · session 38167bc1)

> ⏩ **데스크톱에서 이어간다.** 이 폴더 = 파이에서 만든 연출 시험본의 재료와 인계 메모.
> 🔴 **설계 전이다** — 아래 「제안」은 brainstorming 에서 확정한다(CLAUDE.md §1: 비자명 작업은 brainstorming 부터).

## 1. 사용자가 정한 것

| 무엇 | 사용자 발화 |
|---|---|
| 시연영상은 **폰으로 촬영**(UHD · 60fps · 16:9) — 한이음 제출 영상 화질 피드백 때문 | 「시연영상 촬영은 핸드폰으로 촬영하는 것으로 하고(UHD, 60FPS, 16:9)」 |
| 박스·손 21점·UI 는 **촬영 뒤 합성** · 제출 영상에 **「합성」을 밝힌다** | 「제출 영상에는 합성이라고 밝힐 것이고」 |
| 연출 효과를 넣는다(UI·오버레이가 자연스럽게 나타나는 등) · **영상 생성 AI 는 쓰지 않는다** | 「UI가 없다가 자연스럽게 UI와 오버레이가 나온다던지」 · 「영상 생성 AI 편집 도구는 사용하지 않을것」 |
| 시험본 연출은 **의도한 방향과 비슷 — 몇 가지 수정** | 「의도한 방향과 비슷한데 몇가지 좀 더 수정해야 할 것 같아」 |
| 연출 도구 = **Remotion · 데스크톱에 설치** | 「데스크톱에 Remotion 설치하는 것으로 진행」 |

원칙(Claude 제안 · 사용자 이의 없음): 연출은 **보여 주는 방식만** 바꾼다 — 박스 위치·경고 시각·차단 여부는 모델·실제 기록 그대로 · 슬로 모션은 표기(경고 선행시간 오해 방지).

## 2. 시험본 (`Demo/recordings/시연영상/연출시험/연출시험_20261009.mp4` · 파이 · git 밖 · 10MB)

- 34.5초 · 1920×1080 · 30fps · 사용자에게 파일로 보냄.
- 바탕 = 10/6 정상 시연 원본 `Demo/recordings/시연영상/촬영본/20261006_212651_정상_오버레이켬/…_1인칭풀_오버레이끔.mp4` 의 7.5~42초(안경 카메라 768×1024 · 15fps).
- 박스·손 21점 = **지금 시연 모델**(B-full-base · T-full-base HEF · 손 Hailo)로 다시 검출 — 10/6 당시 화면과 다를 수 있다.
- 단계·누름 시각 = 당시 로그 `Demo/logs/20261006_212649_log.txt`(녹화 시작 21:26:53 = 0초 · 1초 단위) · 누름은 손끝이 박스 안에 든 구간(재검출)에 맞춤.
- 정상 시연이라 경고·차단 연출은 없다(일어나지 않은 경고는 넣지 않음).

| 시각(시험본) | 연출 |
|---|---|
| 0~2.5초 | 원본만 + 제목 페이드 |
| 2.5~3.7초 | 스캔 선이 위→아래 · 지나간 자리부터 박스가 모서리부터 그려지고 이름표 |
| 3~4초 | 배경·양옆 패널 슬라이드 인 · 단계 행 차례로 |
| 손 등장 | 손목부터 뼈대가 뻗고 점이 튀어나옴 · 검지 끝 노란 고리 맥박 |
| 다음 버튼 | 숨 쉬듯 빛남(서브 작업 중엔 끔) |
| 누름 | 파동 2겹 + 아래 알림 + 진행 게이지 10초 |
| 단계 진행 | 완료 행 초록 번쩍·체크 · 현재 막대가 아래로 미끄러짐 |
| 공구 단계 | 「렌치 찾는 중…」→ 렌치 박스 → 「렌치 쥠 · 확인」 초록 번쩍 |

배치 = 세로 영상 가운데(810×1080) + 양옆 패널 — 폰 세로 촬영본에도 그대로 맞는다. 장면 3장 = `장면_스캔.jpg` · `장면_B1누름.jpg` · `장면_렌치쥠.jpg`.

## 3. 파일

| 파일 | 무엇 | 어디서 |
|---|---|---|
| `extract.py` | 원본 영상 → 프레임별 버튼(확정 트랙)·공구(문턱 0.65)·손 21점 → JSON. 런타임 모듈 그대로(`detector.HailoDetector` · `hand_tracker` · `camera_thread` 추적 함수는 소스에서 꺼내 실행) | **파이만**(Hailo NPU) |
| `dets.json` | 위 결과 — `{"src","fps","rows":[{"f",btn:[[이름,점수,x1,y1,x2,y2]],tool:[…],hand:[[x,y]×21]|null}]}` · 프레임 45~629 · 원본 좌표 | 데스크톱에서 Remotion 시험 데이터로 쓸 수 있음 |
| `render.py` | Python(OpenCV·Pillow·NumPy) + FFmpeg 시험 렌더러 — **연출 타이밍·색·배치의 참고용**. 경로가 파이 고정(`/home/pi/…`) | Remotion 으로 대체 예정 |

다시 만들기(파이): `python3 extract.py <원본> dets.json 45 630` → `python3 render.py <원본> dets.json out.mp4` (`STILLS=100,297` 로 그 프레임 jpg 저장).

### 🔴 Hailo 함정 2 (도구를 새로 만들 때 · 2026-10-09 실측)
- `camera_thread` 를 import 한 프로세스에서 새로 만든 `HailoDetector` 의 **첫 추론이 멈춘다**(faulthandler: `pyhailort.infer`). 그래서 추적 함수만 AST 로 꺼내 쓴다.
- 공구 검출기를 **손 추적기보다 먼저** 올리면 공구 추론이 멈춘다 — 버튼 → 손 → 공구 순서만 됐다.
- 프로세스 종료 때 `Bus error`(135)가 난다 — 결과 파일은 정상.

## 4. 폰 촬영본 (임시 1인칭 · 2026-10-08 촬영)

- 파이: `Demo/recordings/시연영상/폰시험/핸드폰 촬영 영상.zip`(2.5GB · deflate · **압축 안 풂** — 파이 여유 0.76GB). PyAV 로 zip 안을 바로 읽을 수 있다(`zipfile.open` → `av.open` · 두 번째 파일은 여는 데 약 95초).
- 원본은 데스크톱에 있다(사용자가 데스크톱 → Taildrop 으로 보냄).

| 파일 | 규격 | 길이 |
|---|---|---|
| `20261008_202315 (1).mp4` | HEVC 3840×2160 · 회전 -90(세로) · **30fps** · AAC | 52.5초 |
| `20261008_202509.mp4` | 같음 | 154.8초 |

- ⚠️ 계획(60fps)과 달리 **30fps** — 본 촬영 전 폰 설정 확인(사용자).
- 아직 안 한 것: 폰 영상에서 검출이 되는지(모델은 ESP32 사진만 학습) — 파이에서 `extract.py` 를 zip 읽기로 바꿔 돌린다.

## 5. 데스크톱에서 할 일 (순서)

1. Remotion 설치(사용자 승인됨) — Node.js(없으면) → 프로젝트(`npx create-video`) → 공식 스킬 `npx skills add remotion-dev/skills`. 공식 스킬만 쓴다(개인 배포 스킬 안 씀).
2. **brainstorming** — 입력: 사용자 수정 사항(아직 안 받음 · 먼저 묻는다) · 이 README · Remotion 구조. 정할 것(제안): 파이 = 검출 JSON(작음) · 데스크톱 = 폰 원본 + JSON → 4K 렌더 / 실제 시스템 기록 → UI 상태 / 「합성」 표기 위치 / 가로·세로 배치.
3. 폰 촬영본 검출 확인(파이 세션) → 시험본(Remotion) → 사용자 피드백 반복.
- 이미 있는 스킬 `impeccable`·`frontend-design` 으로 UI 패널 디자인을 점검할 수 있다(Remotion = HTML/CSS).
- Remotion 라이선스: 개인 · 직원 3명 이하 영리 단체 · 비영리 = 무료(원문에 학생 항목은 없음).

## 6. 출처

- Remotion 공식 Agent Skills — https://www.remotion.dev/docs/ai/skills
- Remotion 라이선스 — https://github.com/remotion-dev/remotion/blob/main/LICENSE.md
- Remotion arm64(Chrome Headless Shell) — https://www.remotion.dev/docs/chrome-headless-shell
- 예시 영상 = 공식 쇼케이스 목록 원본 `packages/docs/src/data/showcase-videos.tsx`(remotion-dev/remotion) · 재생 = `https://stream.mux.com/<muxId>/high.mp4`
- 대안 HyperFrames(HeyGen · Apache 2.0) — https://github.com/heygen-com/hyperframes
