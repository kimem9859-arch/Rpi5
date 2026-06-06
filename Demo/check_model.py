"""console_v1.pt 모델 계약 검증 — 학습된 모델이 코드에 '그대로 끼워지는지' 점검.

코드(detector.py·fsm.py·camera_thread.roi_at_point)가 모델에 요구하는 조건을
한 번에 확인한다. 모델 완성 후 실행하면 통과/실패를 즉시 알려준다.

실행: python Demo/check_model.py [모델경로]
      (인자 없으면 config.PT_MODEL_PATH 사용)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config

REQUIRED_LABELS = {f"B{i}" for i in range(1, config.FSM_STEP_COUNT + 1)}  # {B1,B2,B3,B4}


def check(model_path):
    print(f"[검증] 모델: {model_path}")
    print(f"[검증] 요구 클래스 이름: {sorted(REQUIRED_LABELS)}  (정확히 일치해야 함)")

    if not os.path.exists(model_path):
        print(f"  ❌ 파일 없음: {model_path}")
        return False

    try:
        from ultralytics import YOLO
    except ImportError:
        print("  ⚠ ultralytics 미설치 — 학습/실행 환경에서 실행하세요 (pip install ultralytics)")
        return False

    model = YOLO(model_path)
    names = set(model.names.values())
    print(f"  · 모델 클래스 이름: {sorted(names)}")
    print(f"  · 태스크: {getattr(model, 'task', '?')}")

    ok = True

    # 1) 필수 클래스 이름 B1~B4 존재
    missing = REQUIRED_LABELS - names
    if missing:
        ok = False
        print(f"  ❌ 누락된 필수 클래스: {sorted(missing)}")
        print("     → 학습 data.yaml의 names를 B1,B2,B3,B4로 맞추거나 매핑이 필요합니다.")
    else:
        print("  ✅ 필수 클래스 B1~B4 모두 존재")

    # 2) detection 태스크
    if getattr(model, "task", "detect") != "detect":
        ok = False
        print(f"  ❌ 태스크가 detect가 아님: {model.task} (seg/pose 불가)")
    else:
        print("  ✅ detection 태스크")

    # 3) 참고: 잉여 클래스 안내 (오류 아님)
    extra = names - REQUIRED_LABELS
    if extra:
        print(f"  ℹ 추가 클래스(무시됨, ROI 판정엔 미사용): {sorted(extra)}")

    print()
    print("  결과:", "✅ 끼워넣기 가능 — config.PT_MODEL_PATH만 이 파일로 두면 됩니다."
          if ok else "❌ 계약 불충족 — 위 항목을 수정해야 합니다.")
    return ok


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else config.PT_MODEL_PATH
    sys.exit(0 if check(path) else 1)
