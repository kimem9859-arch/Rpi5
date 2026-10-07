# c001 채점 — 처음 보는 장소2 사진으로 시연 모델·학습 설정·장소1 후보 채점 (2026-10-08 · 세션 1cec94d7)

> 설계 = 상위 sop-project `docs/superpowers/specs/2026-10-08-c001채점-design.md` · 계획 = `docs/superpowers/plans/2026-10-08-c001채점.md`
> 결과 = 이 폴더 `결과.md`(결론 · 오류 유형 · 2단계에 넘길 것 · 한계) · 표 = `판정.md` · `오류분석.md` · 그림 = `그림/`
> 🔴 이 폴더의 수치는 조사 기록이다 — 정본 인용은 저널 §12.93 · 통합문서 §12 `[CURRENT]` 로.

## 1. 무엇을 왜

- 지금 시연 모델(`B-full-base-s0_ours-L2` · `T-full-base-albu-s0_ours-L2`)과 그 학습 설정은 장소1(2026-09-23) 사진으로만 골랐다. c001(장소2 · 2026-10-06)은 어떤 학습 모델도 배우지 않은 장소의 첫 채점이다. c001 사진은 2단계 학습에 들어가므로 이 채점은 지금 모델들에만 한 번 쓴다.
- 사용자 원문 — 「짧은 설계가 아닌 자세하게 측정 설계를 하는 것으로 하자」(10-07) · 옛 설정 = 「학습 설계가 부족한 모델」 → 대조군만(10-07) · 범위 「후보도 다시 채점」(10-08) · 「장소2 … 장소1보다 어둔 장면도 포함」(10-08) · 「각 모델 학습 이미지 수와 비율 … 기록 · 4 방법 … 자세히 잘 확인하고 검증된 상태에서 진행」(10-08) · 「모델 채점에 대한 그래프와 표 이미지」(10-08).
- 묻는 것 — Q1 시연 모델의 장소2 값 · Q2 HEF 변환 손실 · Q3 지금 기준 ↔ 옛 설정 · Q4 장소1 후보 다시 보기(표시만) · Q5 무엇을 틀리나.

## 2. 사진·라벨

| 묶음 | 사진 | 정답 박스 | 쓰임 | 라벨 고정 지문 |
|---|---|---|---|---|
| c001 | 194(9세션 · 장면 1·2·3·4·6) | 535 — 버튼 277(B1 56 · B2 56 · B3 55 · B4 62 · EMO 48) · 공구 258(driver 82 · wrench 88 · pliers 88) | 주 채점 | `4664fe4a5efef980` |
| 보조(어두운 조명 세션 `20261006_191942_장소2_1` 라벨 전부) | 22(c001 과 3장 겹침) | 96 — **버튼만**(B1 19 · B2 19 · B3 22 · B4 18 · EMO 18) · 공구 0 | 참고(판정 안 함) | `47bcc2176de83ecc` |
| 장소1 채점 292장(`place1_v1` test) | 292 | 657 | 관문 ① 에만 | `10aa538f488905e8` |

- 사진 = 안경 스트림 PNG 원본(`~/data/capture/…` · 시연과 같은 처리 — 상하 반전 → 왜곡 보정 → 반시계 90° · 768×1024).
- 라벨 = c001·보조는 `~/data/label_dataset/place2/labels/`, 292장은 학습 때 보낸 사본 `~/data/학습실험/stage/place1/labels8/` — 채점 시작 때 작업 폴더로 복사해 고정 · 파일마다 sha256 = `라벨고정.json` 「묶음」.
- c001 라벨 = 초벌(버튼 `button_r1` · 공구 `T-full-in1024-s0`) → 라벨러 검토 → 사용자 재검토 → c001 1회차 사용자 = **사진마다 2명 · 총 3회**. 보조 22장 중 19장은 2회(라벨러 + 사용자).
- ⚠️ **보조 22장에 공구 정답이 없다** — 어두운 조명 세션에서 라벨이 된 사진에 공구가 없었다. 어두운 조명의 공구는 「잘못 찾음」만 볼 수 있다.
- 쥠/놓임(공구 정답 258개 · 결과를 보기 전 · Claude 육안 1명) = 놓임 173 · 쥠 77 · 애매 8 — `쥠놓임.json`(기준 문구 포함 · 손이 안 보인 72개는 사진 전체로 다시 봄 `crops.py --full`).

## 3. 모델

- `.pt` 60개 = 설정 20 × 시드 3(설계 §3.1·§3.2 · 목록 = `common.py` `SETTINGS`) · HEF 4개(시연 2 + 옛 2 · `common.py` `HEFS`).
- 모델마다 학습 사진 수·비율 = `라벨고정.json` 「학습구성」(설계 §3.4 표와 같음을 실행 때 다시 확인) · 그림 `그림/F5_학습구성.png` · 표 `그림/T3_학습사진.png`.
  - 학습 때 라벨 = 지금 사본 — 지문 같음 18설정 · 기록 전 2설정(`B-early-base` · `T-early-base` — 1단계 초기 · 사진 목록은 같음).
  - HEF 보정 사진 = 1,022(`B-full-base-s0`) · 634(`T-full-base-albu-s0`) · 1,024(`B-early-base-s0`) · 634(`T-full-base-s0`) — 모두 장소1 학습 몫.

## 4. 방법 (설계 §4 — 코드 줄 단위로 확인)

| 길 | 스크립트 | 계산 |
|---|---|---|
| `.pt`(파이 CPU · rfenv ultralytics 8.4.117) | `score_pt.py` | 설정.json 「입력」대로(640 늘리기 / 원본 768×1024) → `predict(conf 0.001)` → `학습/scoring.py` `gts_from_lines` · `preds_from` · `summarize` — `score_model` 과 같은 순서 + 사진별 기록 |
| HEF(파이 Hailo-8) | `score_hef_c001.py` | `detector.create_detector()`(시연 검출기 · 640 늘리기 · HEF 안 NMS 0.25/0.7 · 0.50 미만 버림) → `score_hef.load_labels`(무리별 라벨) → `summarize` · conf 훑기 · HEF 마다 프로세스 하나 · NPU 를 다른 프로세스가 쓰면 멈춤 |
| 정답 맞추기 | `Demo/test/score_lib.py` | 종류별 · 점수 순 · IoU ≥ 0.5 짝 · 운용점 0.65 · 혼동표(오분류 = 대각선 밖) |
| 판정 | `judge.py` | `학습/ledger.py` `adopt`(시드 3개 · 후보 최저 > 기준 최고 = 위로 갈림) · 규칙 = 설계 §5(채점 전 고정) · 자체 시험 12종 |
| 오류 분석 | `analyze.py` | 사진 한 장씩 `score_lib` → 축(종류 · 장면 · 밝기 · 크기 · 끝 · 쥠/놓임 · 가위 세션 · 공구 없는 사진) · 🔴 사후 층화(원인 분석용) · 자체 시험 |
| 그림 | `charts.py` | 판정.json · 오류분석.json · 라벨고정.json → `그림/` (dataviz 기준 팔레트 · 검사기 통과) |

## 5. 관문 — 모두 ✅ (2026-10-08)

| 관문 | 결과 | 원출력 |
|---|---|---|
| ① `.pt` 재현 — 장소1 292장에서 이 스크립트 = 학습 체계 `채점.json` | ✅ 세 모델(`E15-button-base` · `E13-tool-base` · `E1c-tool-f120in1024`) 모두 종류별 tp·fp·fn **차이 0** · 오분류·오검출 같음(판·장치가 달라도) | `관문1.txt` |
| ② HEF 경로 — c001 에서 이 스크립트 = `score_hef.py` | ✅ 네 HEF 모두 종류별 tp·fp·fn · 오분류 같음 | `관문2.txt` |
| ③ 사진·라벨 | ✅ 194 · 22 · 292장 모두 768×1024 · 라벨 1:1 · 번호 범위 · c001 박스 구성 = 설계 §2.1 | `라벨고정.json` 「관문」 |
| ④ 누출 | ✅ 60개 모델의 나눔에 장소2 이름 0 | 같은 곳 |
| ⑤ 모델 파일 | ✅ `.pt` 60 sha256 = 요약.json · HEF 4 sha256 = 변환.json | 같은 곳 |

## 6. 재현

```bash
cd ~/sop-project/Rpi5/조사/c001채점-20261008
python3 prep.py                                      # 작업 폴더 · 라벨 고정 · 관문 ③④⑤ (약 20초)
python3 crops.py && python3 crops.py --check         # 쥠/놓임 모음 사진 · 표시 검사(표시는 쥠놓임.json)
~/env/rfenv/bin/python score_pt.py --set place1_292 --ids E15-button-base E13-tool-base E1c-tool-f120in1024 && python3 gate1.py   # 관문 ① (약 6분)
for h in B-full-base-s0_ours-L2 T-full-base-albu-s0_ours-L2 B-early-base-s0_ours-L2 T-full-base-s0_ours-L2; do python3 score_hef_c001.py --hef $h --set c001; python3 score_hef_c001.py --hef $h --set dark; done
python3 gate2.py                                     # 관문 ②
~/env/rfenv/bin/python score_pt.py --set c001 && ~/env/rfenv/bin/python score_pt.py --set dark   # .pt 60 × 2 (약 1시간 40분 · 끊기면 다시 — 끝난 모델은 건너뜀)
python3 judge.py --self-test && python3 judge.py     # 판정.md · 판정.json
python3 analyze.py --self-test && python3 analyze.py # 오류분석.md · 오류분석.json · 오류 사진
~/env/rfenv/bin/python charts.py                     # 그림/
```

## 7. 작업 폴더 (저장소 밖 · `~/data/c001채점/`)

| 자리 | 무엇 |
|---|---|
| `sets/<c001·dark·place1_292>/` | `names.txt` · `orig/`(원본 링크) · `s640/`(늘린 사진) · `labels8/`(고정본) · `labels_button/` · `labels_tool/` |
| `prep.json` | 이 폴더 `라벨고정.json` 의 원본 |
| `쥠놓임/` | 모음 사진 `sheet_NN.jpg` · 사진 전체 `full_NN.jpg` · `index.json` |
| `out/pt/<묶음>/<결과 폴더>.json` · `out/hef/<묶음>/<HEF>.json` | 모델별 요약 + 사진별 기록(정답 · 0.25 이상 예측) |
| `밝기.json` · `오류사진/<HEF>/sheet_NN.jpg` | 사진 회색 평균 · 시연 HEF 오류 사진 모음 |
