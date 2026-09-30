# 누름 카메라 확인 — 관문 기록(2026-09-30)

설계 = 상위 `docs/superpowers/specs/2026-09-30-누름-카메라확인-design.md` · 계획 = `docs/superpowers/plans/2026-09-30-누름-카메라확인.md`

| 파일 | 무엇 |
| --- | --- |
| `fsm_gate_before.txt` | 구현 전 `python3 Demo/test/fsm_sim.py --gate` 출력(기준선) |
| `fsm_gate_after.txt` | 구현 뒤 같은 명령 출력 — 기준선과 `diff` 빈 출력 = **판정기 전이 무변경** |
| `holdout_sha256.txt` | 건드리지 않을 12개 파일(음성·상태 공개·카메라·구역·인터락·GPIO·fsm_sim·레시피) sha256 — 구현 뒤 `sha256sum -c` 12/12 성공 |

관문 결과(Task 5) — `run_all.py` SELFTEST 40 pass / 0 fail · fsm_sim --gate 기준선과 같음 · 홀드아웃 12/12.
최종 리뷰·실물 확인 결과는 상위 작업로그(2026-09-30 블록)에 적는다.
