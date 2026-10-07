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
