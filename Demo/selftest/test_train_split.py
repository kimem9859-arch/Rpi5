"""학습 나눔(학습/split.py)을 고정한다 — 세 몫 · 빈 구간 36 · 채점 목록 검사 · 배경 줄이기 · 나눔 파일 해시.

실행: python3 Demo/selftest/test_train_split.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §5
⚠️ 사진·모델이 필요 없다.
"""
import json
import os
import sys
import tempfile

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import split as SP

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _names():
    a = [f"0923-100000__f{i:05d}" for i in range(0, 1000, 10)]   # 100장 · 프레임 0~990
    b = [f"0923-200000__f{i:05d}" for i in range(0, 100, 10)]    # 10장(작은 세션)
    return a, b


def _test_list():
    return [f"0923-100000__f{i:05d}" for i in range(800, 900, 10)] + ["0923-200000__f00080"]


def test_세_몫과_빈_구간():
    print("[1] 세 몫 · 빈 구간 36 · 작은 세션")
    a, b = _names()
    w = SP.three_way(a + b, _test_list())
    for k, n in (("train", 72), ("val", 7), ("test", 11), ("gap", 9), ("unused", 11)):
        check(len(w[k]) == n, f"{k} {n}장 — {len(w[k])}")
    check(w["val"][0] == "0923-100000__f00700" and w["val"][-1] == "0923-100000__f00760", "학습 중 검증 = f700~f760(f770~f790 은 빈 구간)")
    check("0923-100000__f00660" in w["train"] and "0923-100000__f00670" in w["gap"], "학습 끝 = f660 · f670 은 빈 구간")
    check("0923-200000__f00040" in w["train"] and "0923-200000__f00050" in w["gap"], "작은 세션 — 검증 없이 떼어 둔 몫 앞 빈 구간")
    check(not any(n.startswith("0923-200000") for n in w["val"]), "20장 미만 세션은 학습 중 검증을 떼지 않는다")
    allp = sum((w[k] for k in w), [])
    check(len(allp) == len(set(allp)) == 110, "몫끼리 겹치지 않고 빠짐 없음")


def test_채점_목록_검사():
    print("[2] 채점 목록 — 원본에 없거나 떼어 둔 20% 밖이면 멈춘다")
    a, b = _names()
    for bad, why in ((["0923-100000__f00100"], "떼어 둔 20% 밖"), (["0923-999999__f00001"], "원본에 없는 이름")):
        try:
            SP.three_way(a + b, bad)
            check(False, f"{why} → ValueError")
        except ValueError:
            check(True, f"{why} → ValueError")


def test_배경_줄이기():
    print("[3] 배경 10% · 시드 고정")
    train = [f"p{i:03d}" for i in range(90)] + [f"b{i:03d}" for i in range(50)]
    kept, dropped = SP.cap_background(train, lambda n: n.startswith("b"))
    check(len(kept) == 100 and len(dropped) == 40, f"남김 100 · 뺌 40 — {len(kept)} · {len(dropped)}")
    check(SP.cap_background(train, lambda n: n.startswith("b")) == (kept, dropped), "같은 시드 = 같은 결과")
    _, d2 = SP.cap_background([f"p{i}" for i in range(90)] + ["b1"], lambda n: n.startswith("b"))
    check(d2 == [], "배경이 이미 적으면 그대로")


def test_나눔_파일():
    print("[4] 나눔 파일 — 무리별 배경 · 해시 · 덮어쓰기 금지 · 손으로 고치면 멈춤")
    a, b = _names()
    lab = lambda n, g: ["0 0.5 0.5 0.1 0.1"] if g == "button" or SP.frame_no(n) < 300 else []
    d = SP.make_split("place9_v1", a + b, _test_list(), lab)
    check(d["button"]["bg_dropped"] == [], "버튼 = 배경 없음 → 그대로")
    check(len(d["tool"]["bg_dropped"]) == 33, f"공구 = 배경 37 중 33 뺌 — {len(d['tool']['bg_dropped'])}")
    tr, va, te = SP.lists_for(d, "tool")
    check(te == d["공통"]["test"] and va == d["공통"]["val"] and tr == d["tool"]["train"], "몫 꺼내기")
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "나눔", "place9_v1.json")
        SP.save_split(d, p)
        check(SP.load_split(p)["해시"] == d["해시"], "저장·읽기 해시 같음")
        try:
            SP.save_split(d, p)
            check(False, "덮어쓰기 → FileExistsError")
        except FileExistsError:
            check(True, "덮어쓰기 → FileExistsError")
        j = json.load(open(p, encoding="utf-8"))
        j["공통"]["val"].pop()
        open(p, "w", encoding="utf-8").write(json.dumps(j, ensure_ascii=False))
        try:
            SP.load_split(p)
            check(False, "고친 파일 → ValueError")
        except ValueError:
            check(True, "고친 파일 → ValueError")


if __name__ == "__main__":
    test_세_몫과_빈_구간()
    test_채점_목록_검사()
    test_배경_줄이기()
    test_나눔_파일()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 학습 나눔 검증 통과")
