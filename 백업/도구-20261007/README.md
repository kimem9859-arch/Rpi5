# 백업한 도구 — 2026-10-07

> 지금 설계·계획에서 쓰지 않는 도구를 지우지 않고 여기 모았다(사용자 요청 2026-10-07 · 설계 상위 sop-project `docs/superpowers/specs/2026-10-07-도구정리-design.md` §4).
> 🔴 **여기서는 실행되지 않는다** — 원래 자리(`Demo/test/`)의 모듈·config 를 상대 경로로 불러 쓰는 도구들이다. 쓰려면 원래 자리로 되돌린다.
> 되돌리기(Rpi5 저장소 뿌리에서) = `git mv 백업/도구-20261007/<파일> Demo/test/<파일>` · 이력은 `git log --follow` 로 이어진다.

| 파일 | 원래 자리 | 왜 뺐나 | 되돌릴 때 같이 할 것 |
| --- | --- | --- | --- |
| `verdict.py` | `Demo/test/` | 7월 클린룸 중단 규칙 판정(추적 없는 raw · `CONF_WARN 0.70` 복제) — 새 관문 = `test/measure_check.py`(측정 도구 정합 1단계-가) | `Demo/run_bench_test.sh` 끝의 「자동 판정」 블록을 다시 넣는다(git 이력 2026-10-07 앞) |
| `thermal_probe.py` | 〃 | 30분 연속 가동 측정을 뺐다(측정 도구 정합 D13) · 온도는 1단계 `res` 사건 | — |
| `cam_timing_calc.py` | 〃 | 카메라 사양 확정(통합 펌웨어 `glass_voice` · 2026-10-07) — 계산기 | — |
| `tool_live.py` | 〃 | 보고값 금지 뷰어(왜곡보정 없음 · conf 0.60 하드코딩) — 같은 확인 = `test/tool_probe.py` | — |
| `db_report.py` | 〃 | `bench.db` 열람 HTML 시험판(정본 아님) — `bench.db` 는 옛 데이터 전용 | — |
| `anim_fps_bench.py` | 〃 | UI 애니메이션 FPS 판정(G6) 끝 · 측정값 목록에 없다 · 🔴 시연 로그가 ms 로 바뀌면(측정 도구 정합 D15) 시각 정규식 `_TS` 를 `\[(\d\d):(\d\d):(\d\d)(?:\.\d{3})?\]` 로 고쳐야 돈다 | 정규식 |
| `export_labels.py` | 〃 | 로그 검출을 그대로 라벨로 — 반자동 라벨링(초벌 → 사람 검토 → 회수)으로 대체 · 검토 없는 라벨 경로라 지금 라벨 규칙과 맞지 않는다 | — |
| `upload_roboflow.py` | 〃 | Roboflow 업로드 — 라벨은 X-AnyLabeling · 학습은 `학습/` 로 옮겼다 | — |
