"""ARCAD 공구 모델을 ESP32 촬영 프레임에 일괄 추론 — 도메인 갭 사전 측정.

목적: 학습·DFC 변환에 며칠을 태우기 전에 "외부 데이터셋 모델이 우리 카메라
      화질에서 공구를 잡기는 하는가"를 먼저 확인한다.

🔴 이 스크립트가 내는 값은 **성능 지표가 아니다.**
   프레임 분모에 공구가 안 보이는 프레임이 섞여 있어 오염된다
   (CLAUDE.md 「프레임 단위 검출률을 성능 지표로 쓰지 말 것」과 같은 함정).
   판정은 라벨을 붙인 부분집합으로 따로 한다.

출력: preds.json (프레임별 검출 전량) + 표준출력 요약

⚠️ 이 파이에서 실행 환경 만들기 — 함정 2건 (2026-08-10 실측, 정본 §10.35-(7)):
    ① `inference` 는 Python <3.13 을 요구하는데 이 파이는 3.13.5 다(MediaPipe 와 같은 문제).
    ② 기본 설치가 NVIDIA CUDA 스택을 끌어와 디스크 5GB 를 잠식한다 — 파이엔 GPU 가 없다.
    두 함정을 같이 피하는 방법:

    ✅ **이미 만들어 둔 환경이 `~/env/rfenv` 에 있다** — `~/env/rfenv/bin/python run_tool_infer.py <디렉터리>`
    없으면 다시 만든다:
        uv venv --python 3.12 ~/env/rfenv
        VIRTUAL_ENV=~/env/rfenv uv pip install --torch-backend cpu inference ultralytics

⚠️ 모델 ID 는 `TOOL_MODEL_ID` 환경변수로 바꾼다. **데이터셋 최신 버전 ≠ 모델 버전** —
   모델이 없는 버전을 부르면 404 다. 어느 버전에 모델이 붙었는지는 아래로 확인:
       https://api.roboflow.com/<워크스페이스>/<프로젝트>?api_key=<키>
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

# ⚠️ 데이터셋 최신 버전 ≠ 모델 버전. 모델이 붙은 버전으로 불러야 한다(아니면 404).
#    ⛔ tools-detection-b2xjk/1 은 쓰지 말 것 — 현재 12클래스와 무관한 옛 클래스
#       체계(Roller·Hands)로 학습된 유물이라 자기 원본 이미지에서도 공구를 못 잡는다.
MODEL_ID = os.environ.get("TOOL_MODEL_ID", "mmmxd/1")
KEY_FILE = os.path.expanduser("~/sop-project/dev/ai_model/Dataset_API_Key/api_key")
CONF = 0.20          # 낮게 연다 — "전혀 안 잡히나"를 보려는 것이므로 임계는 사후에 건다


def load_key():
    import re
    with open(KEY_FILE) as f:
        text = f.read()
    m = re.search(r'\b[A-Za-z0-9_\-]{16,}\b', text)
    if not m:
        sys.exit(f"API 키를 못 찾음: {KEY_FILE}")
    return m.group(0)


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: run_tool_infer.py <프레임_디렉터리> [출력.json]")
    frame_dir = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "preds.json"

    os.environ["ROBOFLOW_API_KEY"] = load_key()
    from inference import get_model

    print(f"모델 로드: {MODEL_ID} (최초 1회는 가중치 다운로드로 오래 걸린다)")
    model = get_model(model_id=MODEL_ID)

    files = sorted(
        glob.glob(os.path.join(frame_dir, "*.png"))
        + glob.glob(os.path.join(frame_dir, "*.jpg"))
    )
    if not files:
        sys.exit(f"프레임이 없음: {frame_dir}")
    print(f"프레임 {len(files)}장 추론 시작 (conf≥{CONF})\n")

    records = {}
    cls_counter = Counter()          # 검출 건수
    frames_with = defaultdict(set)   # 클래스별 검출된 프레임
    best_conf = defaultdict(float)

    for i, path in enumerate(files, 1):
        try:
            res = model.infer(path, confidence=CONF)[0]
        except Exception as e:
            print(f"  ⚠️ {os.path.basename(path)} 실패: {e}")
            continue
        dets = [
            {"cls": p.class_name, "conf": round(float(p.confidence), 4),
             "x": round(float(p.x)), "y": round(float(p.y)),
             "w": round(float(p.width)), "h": round(float(p.height))}
            for p in res.predictions
        ]
        records[os.path.basename(path)] = dets
        for d in dets:
            cls_counter[d["cls"]] += 1
            frames_with[d["cls"]].add(os.path.basename(path))
            best_conf[d["cls"]] = max(best_conf[d["cls"]], d["conf"])
        if i % 50 == 0:
            print(f"  {i}/{len(files)} …")

    with open(out_path, "w") as f:
        json.dump(records, f, indent=1)

    n = len(records)
    hit = sum(1 for v in records.values() if v)
    print("\n" + "=" * 56)
    print(f"프레임 {n}장 · 검출이 1건 이상 난 프레임 {hit}장 ({hit/n*100:.1f}%)")
    print("=" * 56)
    if not cls_counter:
        print("🔴 어떤 클래스도 검출되지 않음 — 도메인 갭이 크다는 신호")
    else:
        print(f"{'클래스':<22}{'검출건수':>8}{'검출프레임':>10}{'최고conf':>9}")
        for cls, cnt in cls_counter.most_common():
            print(f"{cls:<22}{cnt:>8}{len(frames_with[cls]):>10}{best_conf[cls]:>9.3f}")
    print(f"\n저장: {out_path}")
    print("🔴 위 비율은 성능이 아니다 — 공구가 안 보이는 프레임이 분모에 섞여 있다.")


if __name__ == "__main__":
    main()
