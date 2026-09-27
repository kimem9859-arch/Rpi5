"""반자동 라벨링 묶음 도구(review_batch · collect_batch · audit_batch)의 순수 함수를 고정한다.

실행: python3 Demo/selftest/test_label_batch.py
정본 설계: ../../docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §3 · §4 · §6 · §8 · §9
⚠️ Hailo·모델·사진이 필요 없다.
"""
import json
import os
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import review_batch as RB

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_세션_짧은_이름():
    print("[1] 세션 폴더 이름 → 짧은 이름")
    check(RB.short_name("20260923_185802_esp32_xga-rt-s6-r1_console_v2") == "0923-185802", "0923-185802")


def test_파일이름_세션_포함():
    print("[2] 🔴 세션이 달라도 같은 프레임 번호 — 파일 이름이 겹치지 않는다")
    a = RB.batch_name("auto", False, "0923-184709", 1); b = RB.batch_name("auto", False, "0923-185802", 1)
    check(a != b and a.endswith("0923-184709__f00001.png"), f"{a} ≠ {b}")


def test_봉인():
    print("[3] 🔴 실험 1 사진과 그 주변(최소 간격 안)은 봉인")
    seal, gap = {"S": [100]}, {"S": 60}
    check(RB.is_sealed("S", 150, seal, gap), "150 은 봉인(거리 50 < 60)")
    check(not RB.is_sealed("S", 160, seal, gap), "160 은 봉인 아님(거리 60)")
    check(not RB.is_sealed("T", 100, seal, gap), "다른 세션은 봉인 아님")


def test_봉인_파일_읽기():
    print("[4] selection.json 에서 봉인 목록")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "selection.json")
        json.dump({"plan": [["184709_esp32_xga-rt-s1-r1", "s1-r1", 2, 30]],
                   "picked": [{"session": "20260923_184709_esp32_xga-rt-s1-r1_console_v2", "frame": 51}]}, open(p, "w"))
        seal, gap = RB.load_seal(p)
        s = "20260923_184709_esp32_xga-rt-s1-r1_console_v2"
        check(seal == {s: [51]} and gap == {s: 30}, f"{seal} · {gap}")


def test_세션_비율로_뽑기():
    print("[5] 세션 비율대로 · 같은 시드면 같은 결과")
    cands = [("A", i, f"a{i}") for i in range(100)] + [("B", i, f"b{i}") for i in range(300)]
    p1 = RB.pick_frames(cands, 40, 7); p2 = RB.pick_frames(cands, 40, 7)
    check(p1 == p2 and len(p1) == 40, "40장 · 재현")
    check(sum(1 for c in p1 if c[0] == "A") == 10, "A 10 · B 30")


def test_초벌_모양_만들기():
    print("[6] 기계 확정·사람·제안·공구가 라벨 파일에서 구별된다")
    rev = {"boxes": [{"name": "B1", "score": 0.9, "box": [1, 2, 30, 40], "pre": [0, 0, 32, 44], "why": []},
                     {"name": "B3", "score": 0.8, "box": [50, 2, 80, 40], "pre": [48, 0, 82, 44], "why": ["흐림"]}],
           "missing": [("B4", [100, 100, 150, 150])], "nvis": 2}
    tools = [["driver", 0.31, 200, 200, 260, 300]]
    shapes, drafts, kind = RB.compose_shapes(rev, tools)
    check([s["label"] for s in shapes] == ["B1", "B3", "제안_B4", "driver"], f"{[s['label'] for s in shapes]}")
    check([d["kind"] for d in drafts] == ["auto", "check", "propose", "tool"], f"{[d['kind'] for d in drafts]}")
    check(shapes[0]["description"] == "기계 확정" and shapes[1]["description"].startswith("확인:"), "설명")
    check(kind == "check", f"종류 {kind}")


def test_검토_순서_표시():
    print("[7] 검토 순서 — 사람 확인 → 제안 → 흐림 후보 → 기계 확정만")
    check(RB.batch_name("check", True, "s", 1).startswith("a_check__"), "확인이 있으면 흐려도 a")
    check(RB.batch_name("propose", False, "s", 1).startswith("b_propose__"), "제안 b")
    check(RB.batch_name("auto", True, "s", 1).startswith("d_blur__"), "기계 확정만 + 흐림 d")
    check(RB.batch_name("auto", False, "s", 1).startswith("c_auto__"), "기계 확정만 c")
    rev0 = {"boxes": [], "missing": [], "nvis": 0}
    check(RB.compose_shapes(rev0, [])[2] == "auto", "박스 0개 사진도 종류가 있다(auto)")


if __name__ == "__main__":
    test_세션_짧은_이름()
    test_파일이름_세션_포함()
    test_봉인()
    test_봉인_파일_읽기()
    test_세션_비율로_뽑기()
    test_초벌_모양_만들기()
    test_검토_순서_표시()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 반자동 라벨링 묶음 도구 검증 통과")
