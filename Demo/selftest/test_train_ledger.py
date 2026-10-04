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
    check(L.judge(RES[3][1], r, "button") == "P↑+0.0300 R=", f"E3 — 넘은 만큼 붙임 — {L.judge(RES[3][1], r, 'button')}")
    check(L.judge(RES[4][1], r, "button") == "P↓-0.0100 R↓-0.0100", f"E4a — {L.judge(RES[4][1], r, 'button')}")
    tiny = btn("E9-x", 0.8997, 0.81)[1]
    check(L.judge(tiny, r, "button") == "P↓-0.0003 R=", f"0.0005 보다 작게 벗어나도 0 으로 보이지 않는다 — {L.judge(tiny, r, 'button')}")
    tinier = btn("E9-y", 0.89998, 0.81)[1]
    check(L.judge(tinier, r, "button") == "P↓-0.00002 R=", f"0.0001 보다 작으면 다섯째 자리 — {L.judge(tinier, r, 'button')}")
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


def test_기준_조건():
    print("[4] 운용 조건(멈춤 규칙·나눔·conf·판)이 다른 E0 는 기준이 아니다 — E0 뒤 포화 문턱을 바꾼 경우(최종 리뷰 C1)")
    old, new = {"포화_향상": 0.005}, {"포화_향상": 0.002}
    def c(x, m):
        return {**x[0], "조건": {"멈춤": m}}, x[1]
    e0 = [c(btn(f"E0-button-s{i}", 0.90 + i / 100, 0.80), old) for i in range(3)]
    e1 = c(btn("E1-button-in1024", 0.95, 0.80), new)
    md = L.render(e0 + [e1])
    row = [l for l in md.splitlines() if l.startswith("| E1-button")][0]
    check("기준 다름" in row, f"E0 문턱 0.005 · 실험 0.002 → 기준 다름 — {row.split('|')[-2]}")
    e0b = [c(btn(f"E0b-button-s{i}", 0.90 + i / 100, 0.80), new) for i in range(3)]
    md = L.render(e0 + e0b + [e1])
    rows = md.splitlines()
    row = [l for l in rows if l.startswith("| E1-button")][0]
    check("P↑+0.0300 R=" in row, f"조건이 같은 E0b 3개로 판정 — {row.split('|')[-2]}")
    check(all("기준 |" in l for l in rows if l.startswith("| E0b-")), "E0b = 기준")
    check("후보 표시" in md and "함정⑤" in md, "머리말 — ↑↓ 는 후보 표시 · epochs 일정 함정")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t) / "E0-button-s0"
        d.mkdir()
        (d / "요약.json").write_text(json.dumps({**btn("E0-button-s0", 0.9, 0.8)[0], "나눔": {"해시": "h"}, "conf": 0.65, "판": {"ultralytics": "8.4.171"}}), encoding="utf-8")
        (d / "채점.json").write_text(json.dumps(btn("E0-button-s0", 0.9, 0.8)[1]), encoding="utf-8")
        (d / "설정.json").write_text(json.dumps({"멈춤": new}), encoding="utf-8")
        su = L.load_results(t)[0][0]
        check(su.get("조건") == {"멈춤": new, "나눔": "h", "conf": 0.65, "판": {"ultralytics": "8.4.171"}}, f"결과 폴더에서 조건 읽기 — {su.get('조건')}")


def test_이어서():
    print("[5] 끊겨서 이어 학습한 실험 — 장부에 🔁 표시 · 판정 안 함 · 기준(E0)으로 쓰지 않음(patience 를 처음부터 다시 셈 · 최종 리뷰 M1)")
    e0 = [btn(f"E0-button-s{i}", 0.90 + i / 100, 0.80) for i in range(3)]
    r0 = ({**e0[0][0], "이어서": True}, e0[0][1])
    ex = ({**btn("E3-button-x", 0.99, 0.80)[0], "이어서": True}, btn("E3-button-x", 0.99, 0.80)[1])
    md = L.render([r0, e0[1], e0[2], btn("E0-button-s3", 0.91, 0.80), ex])
    row = [l for l in md.splitlines() if l.startswith("| E3-button-x")][0]
    check("🔁" in row and row.rstrip().endswith("— |"), f"이어서 = 🔁 · 판정 — — {row.split('|')[5:10]}")
    check(L.baseline_ranges([r0, e0[1], e0[2]], "button") is None, "이어서 한 E0 는 기준에서 뺀다(3개 미만)")


def test_사소_2차():
    print("[6] 2차 리뷰 사소 — 기준이 모두 이어서면 「기준 부족」 · 머리말에 🔁 설명")
    e0 = [({**btn(f"E0-button-s{i}", 0.90 + i / 100, 0.80)[0], "이어서": True}, btn(f"E0-button-s{i}", 0.9, 0.8)[1]) for i in range(3)]
    md = L.render(e0 + [btn("E3-button-x", 0.95, 0.80)])
    row = [l for l in md.splitlines() if l.startswith("| E3-button-x")][0]
    check("기준 부족" in row, f"이어서 E0 만 있으면 기준 부족 — {row.split('|')[-2]}")
    check(any(l.startswith(">") and "🔁" in l for l in md.splitlines()), "머리말에 🔁 = 이어 학습 설명")


def test_채택():
    print("[7] 채택 판정 규칙 — 후보 최저 > 기준 최고 · 아래로 갈림 없음(1-2단계 설계 §3)")
    base = [tool(f"E0-tool-s{i}", d, w, p, P)[1] for i, (d, w, p, P) in enumerate([(36/47, 31/49, 25/30, .86), (32/47, 33/49, 19/30, .884), (33/47, 30/49, 23/30, .915)])]
    good = [tool(f"E4-tool-s{i}", d, w, p, P)[1] for i, (d, w, p, P) in enumerate([(38/47, 34/49, 24/30, .897), (32/47, 35/49, 24/30, .892), (35/47, 34/49, 22/30, .919)])]
    v, ok = L.adopt(good, base, "tool")
    check(ok and v["wR"] == "위로 갈림" and v["dR"] == "겹침", f"렌치만 위로 갈림 → 채택 — {v}")
    worse = [tool(f"E5-tool-s{i}", .5, w, .5, .9)[1] for i, w in enumerate([20/49, 21/49, 22/49])]
    v, ok = L.adopt(worse, base, "tool")
    check(not ok and v["wR"] == "아래로 갈림", f"아래로 갈린 지표 → 기각 — {v}")
    try:
        L.adopt(good[:2], base, "tool")
        bad = False
    except ValueError:
        bad = True
    check(bad, "3회 미만이면 판정하지 않는다")


if __name__ == "__main__":
    test_범위와_판정()
    test_렌더()
    test_다시_만들기()
    test_기준_조건()
    test_이어서()
    test_사소_2차()
    test_채택()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 실험 장부 검증 통과")
