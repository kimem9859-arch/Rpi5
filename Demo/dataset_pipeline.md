# console_v2 데이터셋 파이프라인 (촬영 → 라벨 → Roboflow)

> 다음에 데이터를 다시 만들 때(실콘솔 이관, test 세션 촬영, 데이터 보강) **이 문서만 따라가면** 된다.
> 배경·근거는 통합문서 §10.12(파랑 스티커)·§10.13(촬영 설계) 참조.

## 0. 전체 흐름

```
촬영            bench_detector.py --save-raw     → test/raw/<세션>/*.png + logs/<세션>_rawdet_log.csv
  ↓
중복 제거       dedupe_raw.py                    → dataset/images/<세션>/   (pHash, 38% 제거됨)
  ↓
프리라벨        export_labels.py                 → dataset/labels/<세션>/   (v1 검출 재사용, 42%)
  ↓
검수(선택)      review_labels.py                 → dataset/review/          (사람이 눈으로)
  ↓
업로드          upload_roboflow.py               → Roboflow (이미지 + 라벨)
  ↓
라벨링          Roboflow 웹 (사람)               → B4 추가·오분류 수정
  ↓
학습            (GPU) 증강 학습 → DFC → .hef
  ↓
평가            replay_raw.py --hef console_v2.hef  ← v1이 실패한 그 프레임에
```

---

## 1. 촬영

```bash
cd ~/sop-project/Rpi5/Demo
python3 -u test/bench_detector.py --source esp32 --frames 4000 --save-raw --no-video --raw-every 5
```

- `--raw-every 5` — 인접 프레임은 거의 같다. 전부 저장하면 낭비이자 **누출 위험**이다.
- 추론을 켠 채로 찍는다(끄지 않는다). `rawdet_log.csv`가 곧 **프리라벨**이 되기 때문이다.
  저장되는 PNG는 검출 오버레이가 없는 **깨끗한 원본**이다(오버레이는 mp4에만 들어가고, `--no-video`로 껐다).

### 🔑 촬영 중 지킬 것

**고유 프레임 수는 촬영 장수가 아니라 "자세를 얼마나 실제로 바꿨는가"로 결정된다.**
실측: 소극적 이동 → 200장 중 고유 39장(중복 80%) / 적극적 변화 → 800장 중 **고유 447장**.

- 각도(좌우 ±30°·상하), 거리(근↔원), **콘솔이 화면에서 기울어지게**(웨어러블은 롤 회전이 생긴다)
- 배경을 바꾼다 — **가장 효과가 크다.** 같은 방에서 더 찍어봐야 중복만 쌓인다.
- 손이 버튼을 가리는 장면(실사용에서 흔하다)
- 조건별로 **세션을 나눠** 찍는다(정반사·저조도 등). 세션 = 나중의 분할 단위.

### ⚠️ ESP32의 AE가 조명 조건을 방어한다
라이트를 비춰도 자동노출이 전체를 낮춰 정반사를 억제한다(강한 포화 프레임 1%뿐).
역광·저조도도 보정된다. **단 AE에도 한계는 있다** — 조명을 충분히 끄면 밝기가 37까지 떨어지고,
이때 **B3(핑크)가 완전히 죽는다**(§10.13). 극단 조건은 물리적으로 만들기보다 **증강으로 합성**하는 편이 통제하기 쉽다.

---

## 2. 중복 제거

```bash
python3 test/dedupe_raw.py test/raw/<세션1> test/raw/<세션2> --report      # 측정만
python3 test/dedupe_raw.py test/raw/*_esp32 --out dataset/images           # 실제 제거
```

**왜 분할 *전에* 해야 하나**: 연속 프레임이 낳는 문제는 둘이고 해법이 다르다.

| 문제 | 증상 | 해법 |
|---|---|---|
| **중복** | 같은 그림 여러 장 → 라벨링 낭비·과적합 | pHash 제거 |
| **누출** | train/test에 닮은 프레임 → **mAP가 거짓말** | **세션 단위 분할** |

console_v1은 같은 영상 2개를 **프레임 랜덤 분할**해 mAP 0.993이 나왔지만 실추론 B4는 **0%**였다.
파일명에 세션명이 박히므로(`<세션>__f00123.png`) 출처를 잃지 않는다.

---

## 3. 프리라벨 (v1 검출 재사용)

```bash
for d in dataset/images/*/; do s=$(basename $d)
  python3 test/export_labels.py "$d" --logs test/logs --out "dataset/labels/$s"
done
printf 'B1\nB2\nB3\nB4\nEMO\n' > dataset/classes.txt
```

console_v1이 B1·B2·B3·EMO를 잡아준다(달성률 **42%**). 배경 오탐은 크기·종횡비 필터로 걸러진다
(실측: 버튼 bbox 폭 19~94px·종횡비 ~1.0. 제빙기 뚜껑은 116px).

**남는 수작업**:
- **B4(파랑 스티커)** — v1은 검정 버튼으로 학습돼 **하나도 못 잡는다**. 전량 수동.
- **저조도 B3** — 어두우면 검출 0%.
- **정반사 오분류** — 색이 날아가면 B1·B3를 B2로 잡는다. **수정 필수**.

> ❌ **색 기반 자동 라벨러(`autolabel.py`)는 쓰지 않기로 했다.** 달성률은 79%로 오르지만
> **EMO↔B3 오분류가 122건** 발생한다(빨강과 핑크는 Hue가 인접). 틀린 라벨은 없는 라벨보다 해롭다.
> 참고용으로 코드는 남겨두되, 학습 데이터에는 v1 프리라벨을 쓴다.

---

## 4. Roboflow 업로드 ⭐

```bash
cd ~/sop-project/Rpi5
cp .env.example .env          # ROBOFLOW_API_KEY 입력 (.env는 gitignore)
.rfvenv/bin/python Demo/test/upload_roboflow.py --dry-run   # 계획 확인
.rfvenv/bin/python Demo/test/upload_roboflow.py             # 실행
```

첫 실행 전 준비:
```bash
python3 -m venv .rfvenv                       # 시스템 pip은 PEP 668로 막혀 있다
.rfvenv/bin/pip install roboflow python-dotenv
```

### 🔴 두 번 물린 함정 — 반드시 지킬 것

**① `annotation_labelmap` 을 넘겨라.**
YOLO 라벨은 클래스를 **숫자로만** 적는다(`0 0.38 0.90 …`). 매핑을 안 주면 Roboflow가
`"0"`, `"1"` 을 **클래스명 그대로** 쓴다.

```python
LABELMAP = {"0": "B1", "1": "B2", "2": "B3", "3": "B4", "4": "EMO"}
```

**② `annotation_overwrite=True` 를 켜라.**
Roboflow는 **이미지 해시로 어노테이션을 캐시**한다. 프로젝트를 지워도 캐시가 남아,
재업로드 시 `{"warn": "already annotated"}` 로 **스킵하고 옛 라벨을 그대로 쓴다.**
이걸 몰라서 프로젝트를 새로 만들어도 계속 숫자 클래스가 붙었다.

**③ 전량 업로드 전에 3장으로 검증하라.**
`images_search` 로 클래스명이 `B1`·`B2`… 로 들어갔는지 눈으로 확인한 뒤 나머지를 올린다.
848장을 곧장 돌렸다가 두 번 다시 만들었다.

```python
project.single_upload(
    image_path=img,
    annotation_path=lbl,
    annotation_labelmap=LABELMAP,     # ①
    annotation_overwrite=True,        # ②
    split=split,                      # ④ 아래
    tag_names=[sess],
    batch_name=sess,
)
```

**④ split 을 업로드 시점에 명시하라. Roboflow의 자동 랜덤 분할을 절대 쓰지 마라.**
프레임을 섞으면 train/test에 닮은 프레임이 들어가 mAP가 부풀려진다(v1의 함정).

이 스크립트의 분할:
- **train/valid** = 세션 내 **시간순** 80/20. 세션을 통째로 떼면 그 조건(저조도 등)이
  학습에서 완전히 빠지므로, 시간순으로 나눠 모든 조건을 양쪽에 남긴다.
  인접 프레임 누출은 pHash 중복제거로 이미 막혀 있다.
- **test** = **비워둔다.** valid는 같은 방·같은 조명이라 낙관적일 수밖에 없다.
  **정직한 성능은 다른 날·다른 조명에서 찍은 별도 세션으로만** 잴 수 있다.

test 세션을 찍은 뒤:
```bash
.rfvenv/bin/python Demo/test/upload_roboflow.py --only <세션명> --split test
```

### 기타 제약
- **무료 워크스페이스는 public 프로젝트만** 만들 수 있다(라이선스: MIT 등).
- `projects_get` 의 이미지 카운트는 **지연 반영**된다. 실제 확인은 `images_search` 로.
- MCP에는 **프로젝트/이미지 삭제 도구가 없다.** 잘못 올렸으면 웹에서 지워야 한다.

---

## 5. Roboflow 웹에서 (사람이 할 일)

1. **B4(파랑 원) 박스 추가** — 프리라벨이 전무하다
2. **배경 오탐 삭제** — 흰 접시·제빙기 뚜껑이 B2로 잡힌 것
3. **정반사 프레임 수정** — B1·B3가 B2로 오분류된 것
   > **정답은 "진짜 버튼 정체"다.** 노란 버튼이 하얗게 보여도 **B1**로 라벨링해야
   > 모델이 색 이외의 단서(위치·맥락·테두리)를 배운다.
4. **저조도 세션** — 놓친 B3·EMO 보충

⚠️ 버전 생성 시 **Preprocessing/Augmentation의 자동 split 재조정을 끄고**, 업로드 때 지정한 split을 유지한다.

---

## 6. 증강은 Roboflow가 아니라 학습 코드에서

Roboflow 증강(x2·x3)은 **오프라인**이라 데이터셋을 물리적으로 복제하고, 매 epoch 같은 증강본을 본다.
학습 시 **실시간 증강(Albumentations)** 이 매 epoch 다른 변형을 보여 훨씬 효과적이다.

그리고 우리에게 필요한 증강이 Roboflow에 **없다**:

| 필요 | Roboflow | 근거 |
|---|---|---|
| 블러 σ0~2.0 | 있음 | B4 사멸점 σ0.8 (§10.9) |
| **JPEG 압축 q30~100** | **없음** | B4 사멸점 q50 |
| **저해상도 다운스케일** | **없음** | 5% 축소로도 사멸 |
| **정반사 하이라이트 합성** | **없음** | B1·B3 → B2 오분류 (§10.8) |
| 색조(hue) | — | **억제 유지** (B3↔EMO 혼동 방지) |

> **증강의 목적은 양 보완이 아니라 강건성 학습이다.** v1의 실패 원인이
> "B4 표현이 고주파 경계에만 의존"이었고, 블러·압축·저해상도 증강이 **바로 그 처방**이다.
> 증강으로 양을 3배 늘려도 새로운 정보가 생기는 것은 아니다 — 양이 부족하면 **더 찍어야** 한다.

---

## 7. 현황 (2026-07-13)

| 항목 | 값 |
|---|---|
| 촬영 | ESP32 4세션 · 6,800프레임 |
| 저장(`--raw-every 5`) | 1,360장 |
| **중복 제거 후** | **848장** (38% 제거) |
| 프리라벨 | 1,787개 (달성률 42%) |
| Roboflow | `eung-min/console_v2-mjefr` · train 677 / valid 171 / **test 0** |

**🔴 test 세션 미촬영.** 반드시 **다른 날·다른 조명**으로 별도 촬영하고 **학습에 단 한 장도 넣지 않는다.**
이것이 없으면 v2의 성능을 정직하게 알 수 없다 — v1이 mAP 0.993을 찍고도 실전 0%였던 이유가 이것이다.
