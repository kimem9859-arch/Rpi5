# 초벌 박스 조사 (2026-09-28)

> 쓰는 곳 = spec `docs/superpowers/specs/2026-09-28-반자동라벨링-design.md` §5.1 (상위 sop-project) · 측정 절 = 저널 §12 새 절(작업 마무리 때 기록)
> 🔴 **일회용 조사 스크립트다** — 정식 초벌 도구는 계획서에서 따로 만든다. 경로는 파이(`/home/pi/sop-project`) 기준으로 적혀 있다.

| 무엇 | 파일 | 결과 |
|---|---|---|
| 초벌 박스가 버튼 윤곽보다 얼마나 큰지 — 지금(XGA 세로) vs 7월 VGA 가로(학습과 같은 늘림 방향) | `box_fit.py` | `결과_박스여유_지금vs7월.txt` |
| 같은 사진에 초벌 4가지(지금 · 조각 · 정사각형 여백 · 높이 0.87배) — 박스 맞음 · 장면별 버튼 개수 · 같은 버튼 2개 | `fit_spike.py` (Hailo 사용 · `Rpi5/Demo` 에서 실행) | `결과_초벌방식4가지.txt` |
| 윤곽 문턱별로 다시 재기 — 「여유 약 10%」가 측정 기준에 달린 값인지 | `thr_july.py` · `thr_tile.py` | `결과_7월_윤곽문턱별.txt` · `결과_지금vs조각_윤곽문턱별.txt` |
| 좌우이동 3장 — 지금 방식 vs 조각 방식 그림 | `compare_vis.py` | `tile_vs_now.jpg` |
| 실험 1 준비 — 50장 뽑기 · 초벌 대조(맞음·틀림·가짜·놓침 + 자리 규칙 적중) · 초벌 미리보기 | `exp1_select.py` · `exp1_compare.py` · `prelabel_preview.py` | 사진·초벌은 `~/data/label_exp1*` · `~/data/prelabel_preview` (git 밖) |

- 버튼 윤곽 = 박스 주변 테두리 색 중앙값과의 색 거리 > 문턱(기본 45)인 연결 영역. **B4 는 검정 몸통이 판과 구분되지 않아 뺐다.**
- `compare_vis.py` 는 그림을 쓴 뒤 종료할 때 Hailo 정리 단계에서 세그멘테이션 오류가 난다(그림은 정상 저장).
- 사진 원본 = `Demo/test/raw/20260923_*_xga-rt-*` · `20260923_193013_esp32_tool-free-r1` · `20260720_15*_cleanroom-fluorescent` · 검출 기록 = `Demo/test/logs/*_rawdet_log.csv`.
