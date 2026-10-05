"""탐색기(학습/tune.py) 순수 부분을 고정한다 — 제안 · 작업 · 끝 판단 · 이어가기 · 중단 규칙 · 상위 고르기.

실행: python3 Demo/selftest/test_train_tune.py
정본 설계: 상위 docs/superpowers/specs/2026-10-04-학습파라미터-체계-1-2단계-design.md §5
⚠️ optuna 없이 돈다 — tune.py 는 optuna 를 main() 안에서만 import 한다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import trainconf as TC
import tune as TU

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class FakeTrial:
    def __init__(self):
        self.calls = []

    def suggest_float(self, k, lo, hi, log=False):
        self.calls.append((k, "float", log))
        return lo

    def suggest_categorical(self, k, ch):
        self.calls.append((k, "cat"))
        return ch[-1]


def test_제안과_작업():
    print("[1] 범위 → 제안 · 작업 id·학습 인자·바꾼것")
    sp = {"lr0": ["log", 0.0002, 0.003], "cos_lr": ["cat", [False, True]]}
    tr = FakeTrial()
    p = TU.suggest(tr, sp)
    check(p == {"lr0": 0.0002, "cos_lr": True} and ("lr0", "float", True) in tr.calls, f"{p}")
    tmpl = {"id": "E8-tool-T1t000", "group": "tool", "train_kwargs": {"lr0": 0.001, "epochs": 120}, "바꾼것": "epochs=120 · lr0=0.001",
            "설정": {"id": "E8-tool-T1t000", "train": {}}}
    j = TU.job_for(tmpl, "T1", 7, p)
    check(j["id"] == "E8-tool-T1t007" and j["train_kwargs"]["lr0"] == 0.0002 and j["train_kwargs"]["epochs"] == 120
          and tmpl["train_kwargs"]["lr0"] == 0.001, "틀은 그대로 · 사본만 바꿈")
    check(TC.ID_RE.match(j["id"]) is not None and "lr0=0.0002" in j["바꾼것"], f"id 형식 · 바꾼것 — {j['바꾼것']}")
    check("epochs=120" in j["바꾼것"] and "lr0=0.001" not in j["바꾼것"], f"틀의 바꾼것(epochs)은 남기고 탐색 값으로 덮인 것만 바꿈 — {j['바꾼것']}")
    try:
        TU.suggest(FakeTrial(), {"x": ["lin", 0, 1]})
        bad = False
    except ValueError:
        bad = True
    check(bad, "모르는 범위 종류 → ValueError")


def test_멈춤과_고르기():
    print("[2] 첫 10회 중단 규칙 · 상위 고르기(검증 정밀도 아래는 뺌)")
    ok = [{"번호": i, "상태": "끝", "목표": 0.7 + i / 100, "검증P": 0.9} for i in range(10)]
    check(TU.should_stop(ok, 0.65) is None, "정상 → 계속")
    bad = ok[:7] + [{"번호": i, "상태": "이상", "목표": None, "검증P": None} for i in range(7, 10)]
    check("이상" in (TU.should_stop(bad, 0.65) or ""), "이상 3 → 멈춤")
    low = [{**r, "목표": 0.5} for r in ok]
    check("아래" in (TU.should_stop(low, 0.65) or ""), "모두 기준 아래 → 멈춤")
    check(TU.should_stop(ok[:5], 0.65) is None, "10회 전에는 판단 안 함")
    rows = ok + [{"번호": 10, "상태": "끝", "목표": 0.99, "검증P": 0.5}]
    check([r["번호"] for r in TU.pick_top(rows, 3, 0.85)] == [9, 8, 7], "정밀도 아래(0.5)는 1등이어도 뺌")


def test_이어가기():
    print("[3] 끊겼다 다시 뜨면 기록에서 진행 중 시도를 되살린다(Review Focus 1)")
    log = [{"번호": 0, "id": "a", "상태": "걸음"}, {"번호": 1, "id": "b", "상태": "걸음"},
           {"번호": 0, "id": "a", "상태": "끝", "목표": 0.7, "검증P": 0.9}]
    check([r["id"] for r in TU.pending(log)] == ["b"], "끝난 a 는 빼고 b 만")


def test_끝_판단():
    print("[4] 요약과 검증 채점이 모두 있어야 끝(Review Focus 2) · 이상은 검증 없이 끝")
    with tempfile.TemporaryDirectory() as t:
        rd = Path(t)
        check(TU.finished(rd) is None, "아무것도 없음 → 아직")
        (rd / "요약.json").write_text(json.dumps({"이상": False, "검증목표": 0.7, "검증P": 0.9}), encoding="utf-8")
        check(TU.finished(rd) is None, "요약만 → 아직(검증 채점 전)")
        (rd / "채점_검증.json").write_text("{}", encoding="utf-8")
        check(TU.finished(rd) == {"상태": "끝", "목표": 0.7, "검증P": 0.9}, "둘 다 → 끝")
        (rd / "요약.json").write_text(json.dumps({"이상": True}), encoding="utf-8")
        check(TU.finished(rd)["상태"] == "이상", "이상 → 끝(실패)")


def test_기준_최저():
    print("[5] 기준(E0c) 검증 최저 — 검증 채점이 없으면 멈춤")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        for i, (v, p) in enumerate([(0.7, 0.9), (0.66, 0.92), (0.72, 0.88)]):
            rd = root / "runs" / f"E0c-x{i}"
            rd.mkdir(parents=True)
            (rd / "요약.json").write_text(json.dumps({"이상": False, "검증목표": v, "검증P": p}), encoding="utf-8")
            (rd / "채점_검증.json").write_text("{}", encoding="utf-8")
        check(TU.base_floor(root, ["E0c-x0", "E0c-x1", "E0c-x2"]) == (0.66, 0.88), "최저 목표 0.66 · 최저 정밀도 0.88")
        try:
            TU.base_floor(root, ["E0c-x0", "없음"])
            bad = False
        except ValueError:
            bad = True
        check(bad, "검증 채점 없는 기준 → ValueError")


def test_다시_뜨기():
    print("[6] 다시 뜨기 — 반쯤 쓴 요약은 아직 · 샘플러 저장·복원 · 탐색기는 하나만(잠금) · 기록 없는 걸린 시도 찾기(1-2 최종 리뷰 I1·I2·m1·m2)")
    with tempfile.TemporaryDirectory() as t:
        rd = Path(t) / "run"; rd.mkdir()
        (rd / "요약.json").write_text('{"검증목표": 0.9', encoding="utf-8")
        check(TU.finished(rd) is None, "반쯤 쓴 요약.json → 아직(JSONDecodeError 로 죽지 않음)")
        sp = Path(t) / "sampler.pkl"
        a = TU.load_or_new(sp, lambda: {"새것": 1})
        check(a == {"새것": 1}, "저장본 없음 → 새로 만듦")
        TU.save_obj(sp, {"이어감": 2})
        check(TU.load_or_new(sp, lambda: {"새것": 1}) == {"이어감": 2} and not sp.with_name(sp.name + ".tmp").exists(), "저장본 있음 → 그대로 복원 · 임시 파일 안 남음")
        lk = Path(t) / "탐색.lock"
        h1 = TU.acquire_lock(lk)
        h2 = TU.acquire_lock(lk)
        check(h1 is not None and h2 is None, "두 번째 탐색기는 잠금을 못 잡는다")
        h1.close()
        check(TU.acquire_lock(lk) is not None, "첫째가 끝나면 다시 잡힌다")
    rows = [{"번호": 0, "상태": "끝"}, {"번호": 1, "상태": "걸음"}]
    check(TU.orphans([1, 2, 3], rows) == [2, 3], "study 에는 걸렸는데 기록이 없는 시도 = 고아(실패로 정리)")

if __name__ == "__main__":
    test_제안과_작업()
    test_멈춤과_고르기()
    test_이어가기()
    test_끝_판단()
    test_기준_최저()
    test_다시_뜨기()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 탐색기 검증 통과")
