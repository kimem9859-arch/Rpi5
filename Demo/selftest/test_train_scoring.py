"""설정 비교 채점(학습/scoring.py)을 고정한다 — 8종 라벨 짝짓기 · score_lib 요약(오분류·오검출·NaN).

실행: python3 Demo/selftest/test_train_scoring.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §8
⚠️ 모델이 필요 없다(score_model 은 Task 13 실제 점검에서 확인).
"""
import os
import sys

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))
sys.path.insert(0, os.path.join(_RPI5, "Demo", "test"))

import scoring as SC

_fails = []
BTN = ["B1", "B2", "B3", "B4", "EMO"]


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_정답_예측_짝짓기():
    print("[1] 8종 라벨 → 무리 번호 · 다른 무리는 버림")
    g = SC.gts_from_lines(["0 0.5 0.5 0.25 0.25", "5 0.1 0.1 0.1 0.1", ""], BTN, 100, 200)
    check(g == [(0, 37.5, 75.0, 62.5, 125.0)], f"B1 하나만 · 픽셀 좌표 — {g}")
    t = SC.gts_from_lines(["7 0.5 0.5 0.5 0.5"], ["driver", "wrench", "pliers"], 10, 10)
    check(t == [(2, 2.5, 2.5, 7.5, 7.5)], f"pliers = 공구 번호 2 — {t}")
    p = SC.preds_from([[1, 2, 3, 4], [5, 6, 7, 8]], [0.9, 0.8], [0, 1], {0: "B1", 1: "driver"}, BTN)
    check(p == [(0, 0.9, 1.0, 2.0, 3.0, 4.0)], f"모델 이름으로 짝짓기 · 다른 무리 버림 — {p}")


def test_요약():
    print("[2] score_lib 요약 — 오분류 · 오검출 · 운용점 · 정답 없는 클래스")
    per = {"i1": ([(0, 0, 0, 10, 10)], [(0, 0.9, 0, 0, 10, 10)]),
           "i2": ([(1, 0, 0, 10, 10)], [(0, 0.9, 0, 0, 10, 10)]),     # B 를 A 로 — 오분류
           "i3": ([], [(1, 0.8, 50, 50, 60, 60)])}                     # 배경을 B 로 — 오검출
    s = SC.summarize(per, ["A", "B", "C"], 0.5)
    check(s["오분류"] == 1 and s["오검출"] == 1, f"오분류 1 · 오검출 1 — {s['오분류']} · {s['오검출']}")
    check((s["전체"]["tp"], s["전체"]["fp"], s["전체"]["fn"]) == (1, 2, 1), f"전체 TP1 FP2 FN1 — {s['전체']}")
    check(abs(s["전체"]["precision"] - 1 / 3) < 1e-9 and s["전체"]["recall"] == 0.5, "precision 1/3 · recall 0.5")
    check(s["AP50"]["C"] is None and s["AP50"]["A"] == 1.0 and abs(s["mAP50"] - 0.5) < 1e-9, f"정답 없는 C = None · mAP50 0.5 — {s['AP50']}")
    check(s["사진"] == 3 and s["정답박스"] == 2 and s["conf"] == 0.5, "사진 3 · 정답 2 · conf")


if __name__ == "__main__":
    test_정답_예측_짝짓기()
    test_요약()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 설정 비교 채점 검증 통과")
