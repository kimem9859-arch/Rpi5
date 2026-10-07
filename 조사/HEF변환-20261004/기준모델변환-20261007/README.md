# 기준 모델 HEF 변환 — 시연 기준 모델 전환 (2026-10-07 · 세션 76dd2d3d)

> 계획 = 상위 sop-project `docs/superpowers/plans/2026-10-07-시연모델-재학습HEF.md` Task 2 · 설계 = `specs/2026-10-07-시연모델-재학습HEF-design.md` §1.1
> 사용자 결정 — 시연 버튼·공구 모델 = 재학습 HEF · NPU · 「최고로 성능이 좋은 모델」 → 지금 학습 기준 설정(s0 · 시드는 규칙으로).
> 🔴 장소1 조건부(§12.88·§12.90) — 이 기록은 「변환해도 `.pt` 와 같은 자리를 잡는가」 관문이지 성능 판정이 아니다. 장소2 채점(c001)·최종(장소3)은 따로.

## 모델

| 변환 모델(새 이름) | 원본 | 보정 | HEF sha256(앞 16) | 변환 시간(최적화 · 데스크톱 CPU) |
|---|---|---|---|---|
| `T-full-base-albu-s0_ours-L2` | `E13-tool-base/best.pt` | 학습 몫 634장 전부 | `fcbf9d77cc6a61fa` | 1,343초 |
| `B-full-base-s0_ours-L2` | `E15-button-base/best.pt` | 학습 몫 **1,022장 전부**(나눔 `place1_v2b` — 결정표 1024 보다 적어 「있는 만큼 전부」 · Rpi5 `6979a30`) | `79c3180727fb0659` | 2,045초 |

변환 기록 = `학습/결과/<id>/변환.json`(DFC 3.33.1 · 수준 2 · 미세 학습 켬).

## 관문(§12.89 방식) — 둘 다 ✅

| 관문 | 공구 | 버튼 |
|---|---|---|
| `hailortcli parse-hef` | HAILO8 · UINT8 640×640×3 · NMS by class 3종 | HAILO8 · UINT8 640×640×3 · NMS by class 5종 |
| 해시 = 변환 기록 | ✅ | ✅ |
| 292장 채점(conf 0.65 · IoU 0.5 · 파이 Hailo · `score_hef.py`) ↔ `.pt` `채점.json` | HEF 맞게 96 · 잘못 11 · 놓침 30 · 오분류 1 ↔ `.pt` 95 · 12 · 31 · 1(종류별 = 렌치 1개 차이) | HEF 530 · 2 · 1 · 오분류 0 ↔ `.pt` 531 · 1 · 0 · 0 |
| 사진 1장 `.pt` ↔ HEF(`0923-184709__f00051` · `한장비교.py`) | — | 5개 같은 이름 · 최저 IoU 0.952(기준 0.9) |

- 원출력 = 이 폴더 `공구_*.txt` · `버튼_*.txt` · `한장_버튼_*.json` · `parse-hef_<id>.txt`.
- 🔴 **mAP 는 비교하지 않는다 — 운용점(0.65)만** — `score_hef` 는 시연 검출기 그대로라 0.50(`YOLO_CONF_LOW`) 미만을 버리고, `.pt` 의 `채점.json`(`학습/scoring.py`)은 0.001 까지 센다. 곡선이 잘린 HEF 쪽 AP 가 낮게 나오므로 원출력의 mAP 차이를 「양자화 손실」로 인용하지 않는다(§12.89 와 같은 원칙).
- ⚠️ 채점 292장은 장소1(2026-09-23) · 학습과 같은 날 — 성능 수치로 인용하지 않는다(§12.89 와 같은 조건).

## 시연 배치 (계획 Task 3)

- `Demo/models/B-full-base-s0_ours-L2.hef`(sha `79c3180727fb0659`) · `T-full-base-albu-s0_ours-L2.hef`(sha `fcbf9d77cc6a61fa`) — 변환 결과와 같다 · git 추적.
- config — `HEF_MODEL_PATH` = 새 버튼 HEF(되돌리기 = `console_v2.hef` 주석 줄) · `TOOL_BACKEND = "hailo"` · `TOOL_HEF_PATH` = 새 공구 HEF.
- 시연 경로 대조(`../시연경로대조.py` · 관문 모드 = 덮어쓰기 없음 · 10-06 장소2 R3 원본 7장) ✅ 모두 같음 — 원출력 `시연경로대조.txt`.
- 기동(`../기동확인.py` · 화면 없이 · 카메라·GPIO·인터락 없이) ✅ — GUI 로그 `[Detector] 'hailo' 백엔드 로드 완료 — B-full-base-s0_ours-L2.hef` · `[시스템] 공구 검출: 사용 가능 — NPU 적재 — T-full-base-albu-s0_ours-L2.hef · 문턱 0.65` · 창 닫기 → 종료 코드 0.
- 자가 테스트 67/0.
- ⏸ 실물 시연(콘솔 · 안경 · B2 렌치 「쥠」) — 다음 콘솔 작업.
