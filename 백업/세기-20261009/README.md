# 백업한 옛 세기(계산) 도구 — 2026-10-09

> 측정 도구 정합 1단계-나(세기)가 시연 기록(`Demo/measure/<세션>/` 의 CSV)으로 대신 세는 옛 계산 도구를 지우지 않고 여기 모았다(사용자 요청 2026-10-09 · 설계 상위 sop-project `docs/superpowers/specs/2026-10-09-세기도구정리-design.md` §4).
> 🔴 **여기서는 실행되지 않는다** — 원래 자리(`Demo/test/`)의 `config`·`roi_zones` 등을 상대 경로로 불러 쓴다. 쓰려면 원래 자리로 되돌린다.
> 되돌리기(Rpi5 저장소 뿌리에서) = `git mv 백업/세기-20261009/<파일> Demo/test/<파일>`(`test_hoi_import_scale.py` 만 `Demo/selftest/`) · 이력은 `git log --follow` 로 이어진다.
> 옛 데이터(`Demo/test/hoi.db` · `bench.db` · `raw/` · `logs/`)는 그 자리에 그대로 있다 — §12 에 인용된 옛 값을 다시 낼 때는 필요한 도구를 함께 되돌린다.

| 파일 | 원래 자리 | 왜 뺐나 | 되돌릴 때 같이 볼 것 |
| --- | --- | --- | --- |
| `dwell_probe.py` | `Demo/test/` | 체류·선행·사전 감지 근사(판정기 아님 · 추적 없음 · 갭메우기 재구현) — 세기가 `frames`·`fsm`·`events` 로 센다 | 함수 `analyze_presses` · `segments` 는 `Demo/test/hoi_metrics.py` 로 옮겼다(이 파일은 거기서 불러 쓴다 · 글자 그대로) |
| `hoi_probe.py` | 〃 | Hailo 손 검출 부품 — 빌려 쓰던 `dwell_probe` · `hoi_probe_batch` 가 함께 백업 · 시연은 `hand_tracker` | 손 모델·blaze 소스 = `~/lab/hoi/`(저장소 밖) |
| `hoi_probe_batch.py` | 〃 | 옛 `hoi.db` 1단계(손 캐시) — 7월 모조 콘솔 VGA 데이터 전용 | `hoi_probe` 도 되돌린다 |
| `hoi_import.py` | 〃 | 옛 `hoi.db` 2단계(DB 재구축) | 자가 테스트 `test_hoi_import_scale.py` 도 되돌린다 |
| `fsm_sim.py` | 〃 | 옛 `hoi.db` 를 실제 판정기에 재생 · `--gate`(옛 데이터 관문) — 새 기록 관문 = `Demo/test/measure_check.py` · 재생은 측정 도구 정합 2단계 | `--gate` 는 `dwell_probe` 를 부른다 · 조사 스크립트 `조사/판정수정-20260925/current_metrics.py` · `preview_variants.py` 가 이 도구를 부른다 · `Demo/config.py` 의 인터록 안내 문구는 이 도구 출력이 담아 관문이 비교한다(글자를 바꾸지 말 것) |
| `db_import.py` | 〃 | 벤치 CSV → `bench.db`(옛 데이터) | `Demo/test/bench_detector.py` · `replay_raw.py` 가 쓰는 파일 이름 규약(`_LOG_RE`)과 묶여 있다 — 둘 중 하나를 바꿨으면 맞춘다 |
| `slide_charts.py` | 〃 | 8월 발표 차트(옛 `hoi.db` 로 계산) — 산출물은 sop-project `media/발표차트/` 에 그대로 | `hoi_metrics` 의 DB 층을 쓴다 |
| `test_hoi_import_scale.py` | `Demo/selftest/` | 위 `hoi_import` 의 자가 테스트 — 러너(`selftest/run_all.py`)에서 빠진다 | — |
