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


import collect_batch as CB
import xany_io as X


def _man(files):
    return {"batch": "t", "images": [{"file": f, "original": f"/orig/{f}", "session": "S", "frame": i, "w": 768,
                                     "h": 1024, "kind": "auto", "blur": False,
                                     "drafts": [{"label": "B1", "box": [10, 10, 60, 60], "kind": "auto", "why": []}]}
                                    for i, f in enumerate(files)]}


def test_빈_사진과_미검토():
    print("[8] 🔴 박스 0개로 저장한 사진은 받고 · 초벌 표시 그대로(안 본 사진)면 미검토 · 라벨 파일이 없으면 문제")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["c_auto__S__f00000.png", "c_auto__S__f00001.png", "c_auto__S__f00002.png"])
        X.write_json(os.path.join(d, "c_auto__S__f00000.json"), "x.png", 768, 1024, [])
        doc = json.load(open(os.path.join(d, "c_auto__S__f00000.json")))
        doc["version"] = "4.0.6"; json.dump(doc, open(os.path.join(d, "c_auto__S__f00000.json"), "w"))
        X.write_json(os.path.join(d, "c_auto__S__f00001.json"), "y.png", 768, 1024, [])     # 초벌 표시 그대로
        p = CB.check_returned(man, d)
        check(not any("f00000" in m for m in p), "박스 0개 + 다시 저장 = 통과")
        check(any("f00001" in m and "미검토" in m for m in p), "초벌 표시 그대로 = 미검토")
        check(any("f00002" in m and "라벨 파일 없음" in m for m in p), "파일 없음")


def test_제안_남음과_모르는_이름():
    print("[9] 제안_ 이 남거나 모르는 이름이면 회수 거부")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["a_check__S__f00000.png"])
        pth = os.path.join(d, "a_check__S__f00000.json")
        X.write_json(pth, "x.png", 768, 1024, [X.shape("제안_B4", [1, 1, 9, 9]), X.shape("b3", [20, 20, 40, 40])])
        doc = json.load(open(pth)); doc["version"] = "4.0.6"; json.dump(doc, open(pth, "w"))
        p = CB.check_returned(man, d)
        check(any("제안" in m for m in p) and any("'b3'" in m for m in p), f"{p}")


def test_수정_집계():
    print("[10] 수정 집계 — 그대로 · 박스 조정 · 이름 바뀜 · 지움 · 채택 · 추가")
    drafts = [{"label": "B1", "box": [0, 0, 100, 100], "kind": "auto"},
              {"label": "B2", "box": [200, 0, 300, 100], "kind": "auto"},
              {"label": "EMO", "box": [400, 0, 500, 100], "kind": "check"},
              {"label": "B4", "box": [600, 0, 700, 100], "kind": "check"},
              {"label": "제안_B3", "box": [0, 300, 100, 400], "kind": "propose"}]
    finals = [{"label": "B1", "box": [0, 0, 100, 100]},
              {"label": "B2", "box": [220, 0, 300, 100]},
              {"label": "B3", "box": [400, 0, 500, 100]},
              {"label": "B3", "box": [0, 300, 100, 400]},
              {"label": "driver", "box": [300, 500, 400, 700]}]
    s = CB.edit_stats(drafts, finals)
    check(s["auto"]["그대로"] == 1 and s["auto"]["박스 조정"] == 1, f"auto {s['auto']}")
    check(s["check"]["이름 바뀜"] == 1 and s["check"]["지움"] == 1, f"check {s['check']}")
    check(s["propose"]["채택"] == 1, f"propose {s['propose']}")
    check(s["추가"] == {"driver": 1}, f"추가 {s['추가']}")


import audit_batch as AB


def test_표본은_기계_확정만():
    print("[11] 표본은 기계 확정 박스만 · 같은 시드면 같은 표본 · 개수는 있는 만큼")
    man = {"images": [{"file": "a.png", "original": "/o/a.png",
                       "drafts": [{"label": "B1", "box": [0, 0, 5, 5], "kind": "auto"},
                                  {"label": "B3", "box": [9, 9, 20, 20], "kind": "check"},
                                  {"label": "driver", "box": [9, 9, 20, 20], "kind": "tool"}]},
                      {"file": "b.png", "original": "/o/b.png",
                       "drafts": [{"label": "EMO", "box": [0, 0, 5, 5], "kind": "auto"}]}]}
    s1 = AB.sample_auto(man, 10, 3); s2 = AB.sample_auto(man, 10, 3)
    check(len(s1) == 2 and all(d["kind"] == "auto" for _, d in s1), f"{[(r['file'], d['label']) for r, d in s1]}")
    check(s1 == s2, "재현")


def test_검토_완료_표시():
    print("[12] 🔴 고칠 게 없어 저장되지 않은 사진도 X-AnyLabeling 「검토 완료(checked)」 표시가 있으면 검토한 것으로 받는다")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["c_auto__S__f00000.png"])
        pth = os.path.join(d, "c_auto__S__f00000.json")
        X.write_json(pth, "x.png", 768, 1024, [X.shape("B1", [10, 10, 60, 60])])
        doc = json.load(open(pth)); doc["checked"] = True; json.dump(doc, open(pth, "w"))   # version 은 초벌 표시 그대로
        check(CB.check_returned(man, d) == [], "초벌 표시 + checked = 통과")


def test_작은_이동도_조정():
    print("[13] 1 px 만 옮겨도 「박스 조정」 — 작은 버튼에서는 1 px 도 뜻이 있다")
    s = CB.edit_stats([{"label": "B3", "box": [737, 303, 768, 358], "kind": "check"}],
                      [{"label": "B3", "box": [736, 303, 767, 359]}])
    check(s["check"]["박스 조정"] == 1 and s["check"]["그대로"] == 0, f"{s['check']}")
    s2 = CB.edit_stats([{"label": "B3", "box": [737, 303, 768, 358], "kind": "check"}],
                       [{"label": "B3", "box": [737.2, 303, 768, 358]}])
    check(s2["check"]["그대로"] == 1, "0.5 px 미만 차이는 그대로(저장 때 반올림)")


if __name__ == "__main__":
    test_세션_짧은_이름()
    test_파일이름_세션_포함()
    test_봉인()
    test_봉인_파일_읽기()
    test_세션_비율로_뽑기()
    test_초벌_모양_만들기()
    test_검토_순서_표시()
    test_빈_사진과_미검토()
    test_제안_남음과_모르는_이름()
    test_수정_집계()
    test_표본은_기계_확정만()
    test_검토_완료_표시()
    test_작은_이동도_조정()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 반자동 라벨링 묶음 도구 검증 통과")
