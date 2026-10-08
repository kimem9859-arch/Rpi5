# `Demo/measure/` — 측정 기록 세션 폴더

> 측정 실행기(`Demo/run_measure.sh` · 바탕화면 「SOP 가디언 측정」)가 세션마다 폴더 하나를 만든다 — `<날짜_시각>_장소<n>_<세션>/`.
> 실제 시연 프로그램과 음성 데몬이 **측정할 때만** 여기에 적는다(`SOP_MEASURE_DIR`). 「시연」 바로가기는 아무것도 적지 않는다.
> 설계 = 상위 sop-project `docs/superpowers/specs/2026-09-27-측정도구-정합-design.md` §4.3 · 계획 = `docs/superpowers/plans/2026-10-07-측정도구-정합-1단계-가-적기.md`.

- 🔴 **git 에 넣지 않는다** — 이 README 만 들어간다(`Rpi5/.gitignore`). 결과는 `조사/` 의 README 에 요약해 남긴다.
- 🔴 **지우기 전에 확인한다** — 세기(1단계-나 보고 도구)는 언제든 이 원본을 다시 센다. 지울 폴더는 사용자에게 묻는다.
- 시각은 모두 **같은 단조 시계의 ms**(`time.monotonic()` × 1000) — 시연 프로그램과 음성 데몬이 같은 시계를 쓴다. 벽시계는 `session.json` 의 `시작_벽시계` 한 번뿐이다.
- 모든 CSV 는 **이어 쓴다**(비어 있을 때만 머리줄) — 음성 데몬이 세션 도중 다시 떠도 앞 기록이 남는다.
- 녹화·원본 사진 저장 없음(설계 D14) — 측정 중 녹화를 켜면 `events.csv` 에 `recording_on` 이 남고 그 세션의 속도 값은 쓰지 않는다.

## 파일과 칸 (1단계-나 보고 도구가 읽는 계약 — 바꾸면 계획서도 바꾼다)

| 파일 | 한 줄 = | 칸 |
| --- | --- | --- |
| `frames.csv` | 처리한 프레임 하나 | `frame,t_recv_ms,recv_seq,t_start_ms,t_done_ms,decode_ms,orient_ms,detect_ms,track_ms,hand_ms,tool_ms,zone_ms,tip_x,tip_y,tip_score,roi,level` — `recv_seq` = 그 프레임까지 받은 프레임 누적 수(처리 못 하고 버린 것 포함) · `t_done_ms` = 화면으로 넘긴 뒤 · 처리 오류 프레임은 줄이 없다(번호는 건너뛴다) |
| `boxes.csv` | 박스 하나 | `frame,t_recv_ms,kind,cls_name,score,x1,y1,x2,y2,confirmed` — `kind` = `raw`(원시 검출) · `track`(추적 · `confirmed` 1/0) |
| `fsm.csv` | 판정기가 본 프레임 하나 | `t_recv_ms,t_gui_ms,fsm_roi,fsm_level,state,expected` — 갭메우기 뒤 판정기가 보고 있는 버튼 · `t_recv_ms` 로 `frames.csv` 와 잇는다 |
| `env.csv` | 30프레임마다 | `frame,t_recv_ms,brightness,contrast,clip_pct,saturation,lab_a,lab_b` — 장소 환경 지표 |
| `events.csv` | 사건 하나 | `t_ms,kind,data`(JSON) — `run_start`·`run_end`·`run_reset` · `state` · `press` · `gpio_edge` · `step_done` · `sub` · `tool_scan` · `tool_sim`(키보드 우회 — 세기에서 뺀다) · `wrong_tool` · `confirm` · `release` · `camera` · `stream_reset` · `interlock_req` · `interlock` · `fps`·`res`(10초마다) · `recording_on` · `measure_end`(버린 수) |
| `voice_events.csv` | 음성 사건 하나 | `t_ms,kind,data` — `alert`·`alert_played`·`alert_clear` · `play_start`·`play_end`·`stop_sent` · `wake`·`emergency_ignored` · `stt` · `answer` · `uplink`(10초마다) · 음성 끔 세션에는 없다 |
| `session.json` | — | 입력(장소 · 세션 · 손 · 사람 **번호** · 조명 · 대본 · 펌웨어) · 시작 벽시계·단조 · 코드 버전 · 설정값(모델·공구 경로 포함) · 측정 기록 켬 여부 · 음성 켬 여부 |
| 대본 파일 | — | 실행기가 받은 파일을 원래 이름 그대로 복사(형식은 1단계-나) |

## 세기(1단계-나)가 알아야 할 것 — 최종 리뷰(2026-10-07)에서 확인

- **줄 순서 ≠ 시각 순서** — `events.csv`·`voice_events.csv` 는 큐에 넣은 순서로 쌓이고, `gpio_edge`·`interlock`·`stt` 의 `t_ms` 는 실제로 일어난 시각이라 넣은 때보다 앞선다. **세기는 `t_ms` 로 정렬한다.**
- **`frames.csv` 의 `t_start_ms` 는 디코드 뒤** — 한 프레임 처리 시간 = `decode_ms` + (`t_done_ms` − `t_start_ms`).
- **`voice_events.csv` 에는 `measure_end` 가 여러 줄일 수 있다** — 음성 데몬이 세션 도중 다시 뜨면 닫을 때마다 하나씩. 세션 끝 SIGTERM 에도 닫는다(측정 중일 때만 `exit_on_sigterm`). 사건은 밀린 것이 없으면 곧바로 디스크에 쓴다.
- **`measure_end` 의 `failed` 는 거의 늘 `false`** — 쓰기가 실패하면 그 뒤 줄(끝 사건 포함)은 디스크에 못 간다. 쓰기 실패는 시연 로그의 `[측정] 측정 기록 쓰기 실패` 줄과 「끝 사건이 없음」으로 안다. `dropped` = 큐가 넘쳐 버린 수 + JSON 으로 못 쓴 사건 수.
- **`interlock` 의 `t_ack_ms`** — `ack=false` 면 응답 기다림이 끝난(시간 초과) 시각이다 · 미연결·보내기 실패면 비어 있다. BLOCK 을 재시도하면 마지막 시도의 `t_send_ms` 만 남는다(`tries` = 재시도 수).
- **`gpio_edge` 의 `src`** — `edge` = 장치의 엣지 시각 · `callback` = 콜백 시각으로 대신(시계가 어긋남 · 콜백이 늦어 이미 뗀 버튼 · 켤 때 이미 HIGH 인 EMO 발사).
- **`tip_score`** — 메뉴 → 점검(손 검출)이 화면 스레드에서 같은 손 검출기를 부르는 동안에는 몇 프레임의 값이 점검 쪽 값으로 덮일 수 있다(점검 중에만 · 손끝 좌표는 영향 없음).
- 처리 오류 프레임은 `frames`·`boxes`·`env` 어디에도 줄이 없다(번호만 건너뛴다).
- 판 나누기 = `run_start`(그 판의 전이보다 먼저) ~ `run_end`(완주) · `run_reset`(작업 초기화 · EMO 해제).

## 대본 형식(1단계-나 · 설계 상위 `docs/superpowers/specs/2026-10-09-측정도구-정합-1단계-나-세기-design.md` §5)

- **CSV 한 파일**(UTF-8 · 엑셀 저장의 BOM 도 된다) · 머리줄 `판,행동,대상,기대,메모` · 한 줄 = 한 시도 · 같은 판 안에서는 **적은 순서대로** 짝짓는다(시각은 적지 않는다).
- `판` = 그 세션의 몇 번째 판(1부터 · 「작업 시작」 순서).

| 행동 | 대상 | 기대 | 쓰는 값 |
| --- | --- | --- | --- |
| `정상` | (비움) | (비움) | 그 판 전체가 정상 판 — 16 · 2 · V2 헛알림 · 18 |
| `위반` | 누를 버튼(B1~B4) | (비움) | 3 · 18 |
| `머묾` | 머물 버튼 | (비움) | 23 · 3 |
| `틀린공구` | 쥘 공구 이름 | (비움) | 17ⓐ — 🔴 **틀린 공구만 쥐고 15초 기다린 뒤 작업 초기화**(맞는 공구를 쥐지 않는다) |
| `호출` | (비움) | (비움) | V5(다음 판) |
| `질문` | 말할 문장 | 기대 답의 요점 | V6 · V7(다음 판) |
| `비상질문` | 말할 문장 | (비움) | V8(다음 판) |

예(위반 세션 앞부분):

```csv
판,행동,대상,기대,메모
1,위반,B3,,1단계에서 B3
1,머묾,B4,,누르지 않고 2초
2,틀린공구,드라이버,,B2 공구 단계
3,정상,,,
```

- 행동 철자·판 숫자가 틀리면 세기가 **몇째 줄인지 말하고 멈춘다** — 고쳐서 다시 센다(`python3 test/measure_report.py <세션 폴더>`).

## 세기(보고 도구) — `test/measure_report.py`

- 시연을 닫으면 측정 실행기가 자동으로 돈다(기록 켬 회차) · 손으로 = `python3 test/measure_report.py <세션 폴더>` → 그 폴더에 `report.md`·`report.json`.
- 여러 세션 통합값 = `python3 test/measure_report.py <폴더1> <폴더2> … --out measure/합계_<날짜>.md` · 발표 곡선 참고 기준 = `--curve 0.80,0.90`(정본 = 발표 설계 M8).
- 목표 = 통합문서 §4.1 표에서 읽는다(못 읽으면 판정하지 않는다) · 체류·갭메우기·누름 확인 여유 = 그 세션 `session.json` 「설정」 · FPS 창·끊김 = `fps.py` · EMO = `recipe.json`.
- 값 함수 = `test/measure_count.py`(순수 · 판정을 다시 하지 않는다) · 시험 = `selftest/test_measure_count.py`·`test_measure_report.py`(관문 ⑤).
