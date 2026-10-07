"""c001 채점 스크립트 자체 시험 — 최종 리뷰(2026-10-08) 지적 I1 · I2 · M5 · M6 · M7 · M8 을 고정한다.

실행(python3): python3 selftest_c001.py   · 마지막 줄 = 통과 N / 실패 N
"""
import json
import sys
import tempfile
from pathlib import Path

import common as C

ok_n, bad_n = 0, 0


def check(cond, msg):
    global ok_n, bad_n
    print(("  ✅ " if cond else "  ❌ ") + msg)
    ok_n, bad_n = ok_n + bool(cond), bad_n + (not cond)


def t_i1_few_by_photos():
    """I1 — 「적음」은 칸의 사진 수(< 10)로 정한다(설계 §6) · 박스가 10개 넘어도 사진이 적으면 사진 목록."""
    import analyze as A
    info = {f"p{i}": {"장면": "1 콘솔전체", "밝기": "83 미만", "세션": "s"} for i in range(3)}
    gts = [[c, 100 + 60 * c, 100, 140 + 60 * c, 140] for c in range(4)]           # 버튼 4개 · 한 장
    recs = [{n: {"gt": gts, "pred": []} for n in info}]
    T, F = A.tally(recs, "button", info, {}, [1559.0, 2699.0])
    md = "\n".join(A.render("t", ["m"], T, F))
    row = next(l for l in md.splitlines() if l.startswith("| 83 미만 | 12"))
    check("p0" in row and "적음" in row, f"I1 정답 12 · 사진 3 → 사진 목록과 「적음」 — {row}")
    check(A.ser(T, F)["놓침"]["밝기"]["83 미만"]["사진수"] == 3, "I1 ser 에 칸 사진 수")


def t_m5_size_from_model0():
    """M5 — 크기·끝 칸은 모델 0(원본 좌표)으로 한 번 정해 모든 모델에 쓴다 · 늘린 좌표의 반올림으로 칸이 갈리지 않게."""
    import analyze as A
    info = {"p": {"장면": "x", "밝기": "83~115", "세션": "s"}}
    hef = {"p": {"gt": [[0, 100, 100, 130, 130]], "pred": [[0, 0.9, 100, 100, 130, 130]]}}       # 900 px² → 작음
    pt = {"p": {"wh": [640, 640], "gt": [[0, 100, 100, 140, 140]], "pred": []}}                # 늘린 좌표로는 중간
    T, _F = A.tally([hef, pt], "button", info, {}, [1559.0, 2699.0])
    check("중간" not in T["크기"] and T["크기"]["작음"][1] == [0, 1], f"M5 .pt 놓침도 모델 0 의 칸(작음)으로 — {dict(T['크기'])}")


def t_i2_freeze():
    """I2 — 다시 실행할 때 라벨이 고정본과 다르면 멈춘다(--refreeze 없이는) · 결과 건너뛰기는 라벨 지문까지 같을 때만."""
    import prep
    import score_pt
    frozen = {"a": "1", "b": "2"}
    check(prep.freeze_problems({"a": "1", "b": "2"}, frozen) == [], "I2 같으면 문제 없음")
    check(len(prep.freeze_problems({"a": "1", "b": "X"}, frozen)) == 1, "I2 내용이 바뀐 라벨 1")
    check(len(prep.freeze_problems({"a": "1"}, frozen)) == 1, "I2 빠진 라벨 1")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "o.json"
        p.write_text(json.dumps({"요약": {"사진": 3}, "라벨지문": "F1"}), encoding="utf-8")
        check(score_pt.up_to_date(p, 3, "F1"), "I2 사진 수 · 지문 같음 → 건너뜀")
        check(not score_pt.up_to_date(p, 3, "F2"), "I2 지문 다름 → 다시 채점")
        check(not score_pt.up_to_date(Path(d) / "없음.json", 3, "F1"), "I2 출력 없음 → 채점")


def t_m6_modes_from_trainconf():
    """M6 — 입력 방식 표는 학습/trainconf.py INPUT_MODES 를 그대로 쓴다(복제 금지)."""
    import score_pt
    import trainconf as TC
    check(score_pt.MODES is TC.INPUT_MODES, "M6 score_pt.MODES = trainconf.INPUT_MODES")


def t_m7_draft_bias_mixed():
    """M7 — 초벌 편향 표시는 「엇갈림」에도 붙는다(설계 §5.3)."""
    import judge
    check("초벌 편향" in judge.label("Q4", "T-full-in1024", {"dR": "위로 갈림", "P": "아래로 갈림"}), "M7 엇갈림 + 초벌 편향")
    check("초벌 편향" not in judge.label("Q4", "T-full-blur", {"dR": "위로 갈림", "P": "아래로 갈림"}), "M7 다른 후보에는 안 붙음")


def t_m8_pan():
    """M8 — 같은 판끼리 비교(Q4)·다른 판끼리 비교(판 확인)를 요약.json 「판」으로 확인한다."""
    import judge
    comp = [("판", "A1", "B1", ""), ("Q4", "A2", "A1", ""), ("Q3", "A1", "B1", "")]
    check(judge.pan_problems(comp, {"A1": False, "A2": False, "B1": True}) == [], "M8 맞음 → 문제 없음")
    check(len(judge.pan_problems(comp, {"A1": False, "A2": True, "B1": True})) == 1, "M8 Q4 판 다름 → 1")
    check(len(judge.pan_problems(comp, {"A1": True, "A2": True, "B1": True})) == 1, "M8 판 확인인데 같은 판 → 1")
    check(judge.pan_problems(C.COMPARE, judge.pan_of_settings()) == [], "M8 실제 COMPARE · 요약.json 판 → 문제 없음")


def t_m9_model_info():
    """M9 — 모델마다 종료이유 · 에폭 · conf · 판 · 이상 · 이어서(설계 §3.2 「결과에 함께 남긴다」)."""
    import judge
    info = judge.model_info()
    check(set(info) == set(C.all_ids()), f"M9 모델 60개 모두 — {len(info)}")
    check(all(v["conf"] == 0.65 and not v["이상"] and not v["이어서"] for v in info.values()), "M9 conf 0.65 · 이상·이어서 없음")
    check({info[i]["종료이유"] for i in C.setting("B-full-base")[2]} == {"최대에폭"}, "M9 B-full-base 종료이유 = 최대에폭")


def t_r3_pair_disagree():
    """리뷰 제안 3 — 짝 단위 불일치: 같은 사진·같은 종류에서 HEF 만 놓침 / .pt 만 놓침(참고 · 판정 규칙 아님)."""
    import judge
    hef = {"p": {"gt": [[0, 10, 10, 50, 50], [2, 100, 100, 150, 150]], "pred": [[0, 0.9, 10, 10, 50, 50]]}}
    pt = {"p": {"gt": [[0, 8, 6, 42, 31], [2, 83, 62, 125, 94]], "pred": [[2, 0.9, 83, 62, 125, 94]]}}
    check(judge.pair_disagree(hef, pt, C.NAMES["button"]) == (1, 1, [("p", "B3")], [("p", "B1")]), "R3 HEF 만 B3 · .pt 만 B1")


if __name__ == "__main__":
    for t in (t_i1_few_by_photos, t_m5_size_from_model0, t_i2_freeze, t_m6_modes_from_trainconf, t_m7_draft_bias_mixed, t_m8_pan, t_m9_model_info, t_r3_pair_disagree):
        print(f"[{t.__name__}]")
        try:
            t()
        except Exception as e:                       # noqa: BLE001 — 없는 함수도 실패로 센다
            check(False, f"{t.__name__} 예외 {type(e).__name__}: {e}")
    print(f"SELFTEST {ok_n} pass / {bad_n} fail")
    sys.exit(1 if bad_n else 0)
