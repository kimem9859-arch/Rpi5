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


def test_세션_보류():
    print("[h1] 세션 보류 — 그 세션은 버튼 학습·검증에서 빠지고 세션 채점에만 · 기존 채점은 그대로(1-3 Review Focus 1)")
    names = [f"s{s}__f{i:05d}" for s in (1, 2) for i in range(0, 300, 3)]
    test = [n for n in names if int(n.split("__f")[1]) >= 240]
    d = SP.make_split("t_v1", names, test, lambda n, g: ["0 0.5 0.5 0.1 0.1"])
    h = SP.hold_session(d, "s2", names, "t_v2b")
    tr, va, te = SP.lists_for(h, "button")
    st = SP.session_test(h, "button")
    check(not any(n.startswith("s2__") for n in tr + va), "보류 세션이 학습·검증에 없음")
    check(st == sorted(n for n in names if n.startswith("s2__")), "세션 채점 = 그 세션 전부")
    check(te == d["공통"]["test"] and h["tool"] == d["tool"], "기존 채점·공구 몫은 그대로")
    check(h["나눔"] == "t_v2b" and h["규칙"]["세션보류"] == "s2" and SP.split_hash(h) == h["해시"], "이름·규칙·해시")
    check(SP.session_test(d, "button") == [], "보류 없는 판 → 빈 목록")
    check(SP.names_of(d) == sorted(names), "바탕판의 이름 전부(몫 · 빈 구간 · 안 씀 · 뺀 배경)")
    h2 = SP.hold_session(d, "s2", SP.names_of(d) + ["s2__f99999"], "t_v2c")
    check("s2__f99999" not in SP.session_test(SP.hold_session(d, "s2", SP.names_of(d), "t_v2d"), "button")
          and "s2__f99999" in SP.session_test(h2, "button"), "세션 채점 = 넘긴 목록 기준(바탕판 이름만 넘기면 새 묶음이 안 섞임 — 사용자 A)")


def _base_split():
    """s1 = 100장(f0~f990 · 검증 f700~f760) · s2 = 10장(검증 없음 · 떼어 둔 f80·f90 = 안 씀) · 공구 = f300 앞만 있음."""
    a = [f"s1__f{i:05d}" for i in range(0, 1000, 10)]
    b = [f"s2__f{i:05d}" for i in range(0, 100, 10)]
    lab = lambda n, g: ["0 0.5 0.5 0.1 0.1"] if g == "button" or SP.frame_no(n) < 300 else []
    return SP.make_split("t_v1", a + b, [n for n in a if SP.frame_no(n) >= 800], lab), lab


def test_솎기():
    print("[t1] 솎기 — 그 무리 학습 몫만 세션·프레임 순서로 한 장 건너 · 나머지 몫·바탕판은 그대로(학습량 곡선 §3)")
    d, _ = _base_split()
    before = json.dumps(d, sort_keys=True)
    h = SP.thin(d, "tool", "t_v1half", 2)
    xs = sorted(d["tool"]["train"], key=lambda n: (SP.session_of(n), SP.frame_no(n)))
    kept = h["tool"]["train"]
    s1p = [n for n in kept if n.startswith("s1__") and SP.frame_no(n) < 300]
    check(len(kept) == 20 and s1p == [f"s1__f{i:05d}" for i in range(0, 300, 20)]
          and [n for n in kept if n.startswith("s2__")] == ["s2__f00000", "s2__f00020", "s2__f00040"],
          f"손으로 센 남김 20장 = s1 공구 f0·f20…f280 15 + s1 배경 2 + s2 f0·f20·f40 — {len(kept)}")
    check(sorted(h["tool"]["train"] + h["tool"]["thinned"]) == sorted(xs), "남김 + 솎아 낸 것 = 바탕판 학습 몫")
    check(h["공통"] == d["공통"] and h["button"] == d["button"] and h["tool"]["bg_dropped"] == d["tool"]["bg_dropped"],
          "공통 몫 · 다른 무리 · 뺀 배경은 그대로")
    check(h["규칙"]["솎기"] == 2 and h["규칙"]["바탕판"] == "t_v1" and h["규칙"]["무리"] == "tool", "규칙 = 솎기 · 바탕판 · 무리")
    check(h["나눔"] == "t_v1half" and SP.split_hash(h) == h["해시"] != d["해시"], "이름 · 해시")
    check(SP.names_of(h) == SP.names_of(d), "판의 사진 범위 = 바탕판과 같다(솎아 낸 것도 기록)")
    check(json.dumps(d, sort_keys=True) == before, "바탕판을 고치지 않는다")


def test_새사진_더하기():
    print("[t2] 새 사진 더하기 — 세션의 학습 구간(검증·떼어 둔 20% 첫 프레임보다 36 넘게 앞)만 · 더한 배경만 10% 로(학습량 곡선 §3)")
    d, lab = _base_split()
    before = json.dumps(d, sort_keys=True)
    new = [f"s1__f{i:05d}" for i in range(5, 1000, 10)] + [f"s2__f{i:05d}" for i in range(5, 100, 10)]
    h = SP.add_new(d, new, lab, "tool", "t_v1add")
    added = sorted(set(h["tool"]["train"]) - set(d["tool"]["train"]))
    hold = d["공통"]["val"] + d["공통"]["test"] + d["공통"]["unused"]
    near = [n for n in added for x in hold if SP.session_of(x) == SP.session_of(n) and 0 < SP.frame_no(x) - SP.frame_no(n) <= SP.GAP]
    check(near == [], f"더한 사진이 검증·채점·떼어 둔 사진 36 프레임 안에 없음(누출 0) — {near[:3]}")
    check(len(h["tool"]["added_unused"]) == 40, f"학습 구간 밖 = s1 f665~ 34 + s2 f45~ 6 = 40 — {len(h['tool']['added_unused'])}")
    check("s2__f00035" in added and "s2__f00045" in h["tool"]["added_unused"], "검증 없는 세션 = 떼어 둔 20% 첫 프레임(f80) − 36 앞까지")
    check(set(d["tool"]["train"]) <= set(h["tool"]["train"]), "바탕판 학습 몫은 그대로 남는다")
    zone_bg = [n for n in set(new) - set(h["tool"]["added_unused"]) if not lab(n, "tool")]
    kept_bg = [n for n in added if not lab(n, "tool")]
    check(len(zone_bg) == 36 and len(kept_bg) == 4, f"더한 것 = 공구 34 · 배경 36 중 4 만(10%) — 배경 {len(kept_bg)}")
    check(h["tool"]["bg_dropped"] == sorted(set(d["tool"]["bg_dropped"]) | (set(zone_bg) - set(kept_bg))), "뺀 배경 = 바탕판 것 + 더한 것에서 뺀 것")
    check(h["공통"] == d["공통"] and h["button"] == d["button"], "공통 몫 · 다른 무리는 그대로")
    check(h["규칙"]["더함"] == len(added) == 38 and h["규칙"]["바탕판"] == "t_v1" and h["규칙"]["무리"] == "tool", f"규칙 더함 38 — {h['규칙'].get('더함')}")
    check(SP.split_hash(h) == h["해시"] and set(new) <= set(SP.names_of(h)), "해시 · 새 사진 전부가 판의 사진 범위에")
    check(json.dumps(d, sort_keys=True) == before, "바탕판을 고치지 않는다")
    h2 = SP.add_new(d, new + ["s9__f00005"], lab, "tool", "x")
    check("s9__f00005" in h2["tool"]["added_unused"] and h2["tool"]["train"] == h["tool"]["train"],
          "바탕판에 없는 세션 = 학습 구간을 셀 수 없어 안 씀(added_unused)")
    try:
        SP.add_new(d, ["s1__f00000"], lab, "tool", "x")
        check(False, "바탕판에 이미 있는 사진 → ValueError")
    except ValueError:
        check(True, "바탕판에 이미 있는 사진 → ValueError")


def test_검증채점_같음():
    print("[t3] 검증·채점 몫 같음 — 학습 몫만 바꾼 판끼리만 견준다(판정 --나눔허용)")
    d, _ = _base_split()
    check(SP.same_eval(d, SP.thin(d, "tool", "x", 2)), "솎은 판 = 같음")
    other = json.loads(json.dumps(d))
    other["공통"]["test"] = other["공통"]["test"][1:]
    check(not SP.same_eval(d, other), "채점 몫 하나 다름 → 다름")
    other = json.loads(json.dumps(d))
    other["공통"]["val"].append("s1__f00650")
    check(not SP.same_eval(d, other), "검증 몫 하나 다름 → 다름")
    other = json.loads(json.dumps(d))
    other["button"]["test_session"] = ["s2__f00000"]
    check(not SP.same_eval(d, other), "세션 채점 몫 다름 → 다름(--채점 세션 과 함께 쓸 때)")


if __name__ == "__main__":
    test_세_몫과_빈_구간()
    test_세션_보류()
    test_솎기()
    test_새사진_더하기()
    test_검증채점_같음()
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
