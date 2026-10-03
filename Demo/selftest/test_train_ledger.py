"""실험 장부(학습/ledger.py)를 고정한다 — E0 범위 · ↑↓= 판정 · 기준 부족 · 이상 종료 · 결과 폴더에서 다시 만들기.

실행: python3 Demo/selftest/test_train_ledger.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §8 · §10
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import ledger as L

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def btn(i, P, R, bad=False):
    su = {"id": i, "group": "button", "입력": "늘리기640", "바꾼것": "없음", "종료이유": "점수0" if bad else "일찍멈춤",
          "이상": bad, "에폭": 40, "best_epoch": 20, "분": 12.0}
    return su, (None if bad else {"전체": {"precision": P, "recall": R}, "오분류": 0, "오검출": 1, "클래스": {}})


def tool(i, d, w, p, P):
    su = {"id": i, "group": "tool", "입력": "늘리기640", "바꾼것": "없음", "종료이유": "포화", "이상": False, "에폭": 60, "best_epoch": 30, "분": 9.0}
    return su, {"전체": {"precision": P, "recall": 0}, "오분류": 0, "오검출": 0,
                "클래스": {"driver": {"recall": d}, "wrench": {"recall": w}, "pliers": {"recall": p}}}


RES = [btn("E0-button-s0", 0.90, 0.80), btn("E0-button-s1", 0.92, 0.82), btn("E0-button-s2", 0.91, 0.81),
       btn("E3-button-mosaic05", 0.95, 0.81), btn("E4a-button-lr0005", 0.89, 0.79), btn("E5-button-freeze10", 0, 0, bad=True),
       tool("E0-tool-s0", 0.7, 0.7, 0.6, 0.9), tool("E0-tool-s1", 0.72, 0.71, 0.62, 0.92), tool("E3-tool-mosaic05", 0.8, 0.7, 0.6, 0.9)]


def test_범위와_판정():
    print("[1] E0 범위 · ↑↓= · 기준 부족")
    r = L.baseline_ranges(RES, "button")
    check(r == {"P": (0.90, 0.92), "R": (0.80, 0.82)}, f"버튼 범위 — {r}")
    check(L.judge(RES[3][1], r, "button") == "P↑ R=", f"E3 — {L.judge(RES[3][1], r, 'button')}")
    check(L.judge(RES[4][1], r, "button") == "P↓ R↓", "E4a — P↓ R↓")
    check(L.baseline_ranges(RES, "tool") is None, "공구 E0 2개 → 범위 없음")
    check(L.judge(RES[8][1], None, "tool") == "기준 부족", "기준 부족")


def test_렌더():
    print("[2] 장부 렌더 — id 순 · 기준 · 이상 종료 🔴")
    md = L.render(RES)
    rows = [l for l in md.splitlines() if l.startswith("| E")]
    check(len(rows) == 9 and rows[0].startswith("| E0-button-s0 "), f"9 줄 · id 순 — {len(rows)}")
    check("기준" in rows[0] and "🔴" in [x for x in rows if "E5-button" in x][0], "E0 = 기준 · 이상 = 🔴")
    check("장소1 참고값" in md, "인용 조건 머리말")


def test_다시_만들기():
    print("[3] 결과 폴더 → 장부.md")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / "결과"
        for su, sc in RES[:3]:
            d = root / su["id"]
            d.mkdir(parents=True)
            (d / "요약.json").write_text(json.dumps(su, ensure_ascii=False), encoding="utf-8")
            (d / "채점.json").write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
        (root / "E9-button-sat").mkdir()
        (root / "E9-button-sat" / "요약.json").write_text(json.dumps(btn("E9-button-sat", 1, 1)[0]), encoding="utf-8")
        L.rebuild(root, Path(t) / "장부.md")
        md = (Path(t) / "장부.md").read_text(encoding="utf-8")
        check(md.count("| E0-button-") == 3 and "E9-" not in md, "E0 3줄 · 점검(E9) 제외")


if __name__ == "__main__":
    test_범위와_판정()
    test_렌더()
    test_다시_만들기()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 실험 장부 검증 통과")
