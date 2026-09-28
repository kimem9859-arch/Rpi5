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


def test_검토함_플래그로_받기():
    print("[14] 3.3.5 판 — 고칠 게 없는 사진은 「검토함」 플래그를 켜고 저장하면 받는다")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["c_auto__S__f00000.png"])
        pth = os.path.join(d, "c_auto__S__f00000.json")
        X.write_json(pth, "x.png", 768, 1024, [X.shape("B1", [10, 10, 60, 60])])
        doc = json.load(open(pth)); doc["flags"][X.REVIEW_FLAG] = True; json.dump(doc, open(pth, "w"))
        check(CB.check_returned(man, d) == [], "초벌 표시 + 검토함 = 통과")


def test_다_봤다고_하면_받기():
    print("[15] 사용자가 「묶음을 다 봤다」고 하면 저장 흔적 없는 사진도 받고, 고치지 않은 사진을 종류별로 알려 준다")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["a_check__S__f00000.png", "c_auto__S__f00001.png"])
        man["images"][0]["kind"] = "check"
        for r in man["images"]:
            X.write_json(os.path.join(d, r["file"].replace(".png", ".json")), "x.png", 768, 1024,
                         [X.shape("B1", [10, 10, 60, 60])])
        check(len(CB.check_returned(man, d)) == 2, "기본은 둘 다 미검토")
        check(CB.check_returned(man, d, viewed_all=True) == [], "다 봤다 = 통과")
        u = CB.unchanged(man, d)
        check(u == {"check": ["a_check__S__f00000.png"], "auto": ["c_auto__S__f00001.png"]}, f"{u}")
        X.write_json(os.path.join(d, "c_auto__S__f00001.json"), "x.png", 768, 1024, [X.shape("b1", [10, 10, 60, 60])])
        check(any("'b1'" in m for m in CB.check_returned(man, d, viewed_all=True)), "다 봤다고 해도 이름 점검은 한다")


def test_exclude_사진은_수정_집계에서_뺀다():
    print("[16] 🔴 exclude 사진은 수정 집계에서 뺀다 — 남긴 박스가 「그대로」, 지운 박스가 「지움」으로 세어지면 기계 정확도가 틀어진다")
    import subprocess
    with tempfile.TemporaryDirectory() as d:
        man = _man(["c_auto__S__f00000.png", "c_auto__S__f00001.png", "c_auto__S__f00002.png"])
        ret = os.path.join(d, "ret"); os.mkdir(ret)
        finals = {"f00000": [X.shape("B1", [10, 10, 60, 60])],                                # 보통 사진 — 그대로
                  "f00001": [X.shape("B1", [10, 10, 60, 60]), X.shape(X.EXCLUDE, [0, 0, 768, 1024])],  # 박스 남김
                  "f00002": [X.shape(X.EXCLUDE, [0, 0, 768, 1024])]}                            # 박스 지움
        for k, shapes in finals.items():
            pth = os.path.join(ret, f"c_auto__S__{k}.json")
            X.write_json(pth, "x.png", 768, 1024, shapes)
            doc = json.load(open(pth)); doc["version"] = "3.3.5"; json.dump(doc, open(pth, "w"))
        mp = os.path.join(d, "manifest.json"); json.dump(man, open(mp, "w"))
        out = os.path.join(d, "out")
        r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "test", "collect_batch.py"), ret,
                            "--manifest", mp, "--out", out], capture_output=True, text=True)
        check(r.returncode == 0, f"회수 성공 {r.stdout[-300:]}{r.stderr[-300:]}")
        s = json.load(open(os.path.join(out, "stats", "t.json")))
        check(s["exclude"] == 2, f"exclude 2 — {s['exclude']}")
        check(s["auto"]["그대로"] == 1 and s["auto"]["지움"] == 0, f"auto 는 보통 사진 1장만 — {s['auto']}")
        check(s["추가"] == {}, f"exclude 박스는 「추가」가 아니다 — {s['추가']}")


def test_크게_고친_박스는_지움이_아니다():
    print("[17] 🔴 IoU 0.5 에 못 미쳐도 같은 이름으로 겹치면(IoU > 0.1 또는 중심 포함) 「크게 조정」 — 「지움 + 추가」로 세지 않는다")
    drafts = [{"label": "B3", "box": [0, 0, 100, 100], "kind": "check"},
              {"label": "제안_B4", "box": [0, 300, 100, 400], "kind": "propose"},
              {"label": "B1", "box": [500, 0, 550, 50], "kind": "auto"}]
    finals = [{"label": "B3", "box": [0, 0, 100, 250]},            # IoU 0.4 — 아래로 크게 늘림
              {"label": "B4", "box": [30, 330, 160, 460]},         # 제안을 옮겨 채택 — IoU 0.22
              {"label": "EMO", "box": [700, 700, 750, 750]}]       # 다른 이름·먼 곳 — 진짜 지움 + 추가
    s = CB.edit_stats(drafts, finals)
    check(s["check"]["크게 조정"] == 1 and s["check"]["지움"] == 0, f"check {s['check']}")
    check(s["propose"]["크게 조정"] == 1 and s["propose"]["지움"] == 0, f"propose {s['propose']}")
    check(s["auto"]["지움"] == 1 and s["추가"] == {"EMO": 1}, f"auto {s['auto']} · 추가 {s['추가']}")


def _run_collect(ret, mp, out, *extra):
    import subprocess
    return subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "test", "collect_batch.py"), ret,
                           "--manifest", mp, "--out", out, *extra], capture_output=True, text=True)


def test_다시_회수해도_어긋나지_않는다():
    print("[18] 🔴 같은 묶음을 다시 회수하면 images.txt 가 겹치지 않고, exclude 로 바뀐 사진의 옛 라벨·목록 줄이 지워진다")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["c_auto__S__f00000.png", "c_auto__S__f00001.png"])
        ret = os.path.join(d, "ret"); os.mkdir(ret)

        def put(k, shapes):
            pth = os.path.join(ret, f"c_auto__S__{k}.json")
            X.write_json(pth, "x.png", 768, 1024, shapes)
            doc = json.load(open(pth)); doc["version"] = "3.3.5"; json.dump(doc, open(pth, "w"))
        put("f00000", [X.shape("B1", [10, 10, 60, 60])]); put("f00001", [X.shape("B1", [10, 10, 60, 60])])
        mp = os.path.join(d, "manifest.json"); json.dump(man, open(mp, "w"))
        out = os.path.join(d, "out")
        r1 = _run_collect(ret, mp, out); r2 = _run_collect(ret, mp, out)
        lines = open(os.path.join(out, "images.txt"), encoding="utf-8").read().split()
        check(r1.returncode == 0 and r2.returncode == 0, "두 번 다 회수")
        check(len([x for x in open(os.path.join(out, "images.txt"), encoding="utf-8") if x.strip()]) == 2, f"images.txt 2줄 — {lines}")
        put("f00001", [X.shape(X.EXCLUDE, [0, 0, 768, 1024])])
        _run_collect(ret, mp, out)
        txt = open(os.path.join(out, "images.txt"), encoding="utf-8").read()
        check("S__f00001" not in txt and "S__f00000" in txt, f"exclude 로 바뀐 사진은 목록에서 빠짐 — {txt!r}")
        check(not os.path.exists(os.path.join(out, "labels", "S__f00001.txt")), "옛 라벨 파일 지움")


def test_두_번_보낸_폴더는_거부():
    print("[19] 🔴 returned 안에 images 폴더가 있으면(폴더째 두 번 보냄) 거부 — 옛 파일을 읽고 고친 것을 조용히 놓친다")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["c_auto__S__f00000.png"])
        pth = os.path.join(d, "c_auto__S__f00000.json")
        X.write_json(pth, "x.png", 768, 1024, [X.shape("B1", [10, 10, 60, 60])])
        doc = json.load(open(pth)); doc["version"] = "3.3.5"; json.dump(doc, open(pth, "w"))
        os.mkdir(os.path.join(d, "images"))
        check(any("images 폴더" in m for m in CB.check_returned(man, d)), f"{CB.check_returned(man, d)}")


def test_쓴_사진과_닮은_후보는_뺀다():
    print("[20] 🔴 이전 묶음에 쓴 사진과 pHash 가 가까운 후보는 뺀다 — 묶음마다 중복 제거가 새로 시작되지 않게")
    import numpy as np
    a = np.zeros(64, bool); b = a.copy(); b[:3] = True          # a 와 거리 3
    c = np.ones(64, bool)                                        # a 와 거리 64
    check(RB.drop_near([a, b, c], [a], 6) == [2], f"{RB.drop_near([a, b, c], [a], 6)}")
    check(RB.drop_near([a, c], [], 6) == [0, 1], "쓴 사진이 없으면 그대로")


def test_묶음_기록의_모델은_실제_설정():
    print("[21] 🔴 묶음 기록의 버튼 모델은 실제로 불러온 설정(백엔드·경로·점수 기준·방식) — 고정 문자열이 아니다")
    import config
    m = RB.button_model_record()
    exp = config.HEF_MODEL_PATH if config.INFERENCE_BACKEND == "hailo" else config.PT_MODEL_PATH
    check(m["backend"] == config.INFERENCE_BACKEND and m["path"] == os.path.relpath(exp, _DEMO_DIR)
          and m["conf"] == config.YOLO_CONF_LOW and m["method"].startswith("tile2"), f"{m}")


def test_공구_초벌이_잡아_준_비율():
    print("[22] 공구 초벌이 잡아 준 비율 = 최종 공구 박스 중 초벌과 짝지어진 것(이름 바뀜 포함) — b001 집계로")
    stats = {"tool": {"그대로": 0, "박스 조정": 51, "크게 조정": 9, "이름 바뀜": 4, "지움": 33, "채택": 0},
             "추가": {"B4": 1, "pliers": 39, "wrench": 57, "driver": 19}}
    check(CB.tool_catch(stats) == {"caught": 64, "total": 179, "renamed": 4, "fake": 33}, f"{CB.tool_catch(stats)}")
    check(CB.tool_catch({"tool": {}, "추가": {}}) == {"caught": 0, "total": 0, "renamed": 0, "fake": 0}, "빈 집계")


def test_공구_초벌_모델_기록():
    print("[23] 묶음 기록의 공구 모델 = 인자로 준 파일(경로·해시·점수 기준) — 라운드마다 무엇으로 만든 초벌인지 가르려고")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "tool_r1.pt"); open(p, "wb").write(b"weights")
        m = RB.tool_model_record(p)
        check(m["path"] == p and m["sha256_16"] == RB._sha(p) and m["conf"] == 0.25, f"{m}")


def test_exclude_사진의_남은_제안은_문제_아님():
    print("[24] exclude 사진은 통째로 빠지므로 남은 제안_ 박스로 회수를 거부하지 않는다 — exclude 없는 사진은 그대로 거부")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["a_check__S__f00000.png", "a_check__S__f00001.png"])
        for k, extra in (("f00000", [X.shape(X.EXCLUDE, [0, 0, 768, 1024])]), ("f00001", [])):
            pth = os.path.join(d, f"a_check__S__{k}.json")
            X.write_json(pth, "x.png", 768, 1024, [X.shape("B1", [10, 10, 60, 60]), X.shape("제안_B3", [100, 100, 150, 150])] + extra)
            doc = json.load(open(pth)); doc["version"] = "3.3.5"; json.dump(doc, open(pth, "w"))
        p = CB.check_returned(man, d)
        check(not any("f00000" in m for m in p), f"exclude 사진 통과 — {p}")
        check(any("f00001" in m and "제안" in m for m in p), "exclude 없는 사진은 거부")


def test_겹친_공구_초벌_거르기():
    print("[25] 같은 이름 공구 초벌이 다른 박스 안에 대부분(80%) 들어가 있으면 작은 것을 뺀다 — 떨어진 공구·다른 이름·조금 겹침은 그대로")
    whole = ["wrench", 0.8, 0, 0, 100, 300]; head = ["wrench", 0.6, 10, 10, 90, 100]
    other = ["wrench", 0.7, 200, 0, 250, 100]; drv = ["driver", 0.5, 20, 20, 60, 90]
    side = ["wrench", 0.5, 80, 250, 180, 350]                       # whole 과 조금만 겹침(작은 쪽의 20%)
    got = RB.drop_nested([head, whole, other, drv, side])
    check(got == [whole, other, drv, side], f"{[g[2:] for g in got]}")
    check(RB.drop_nested([]) == [], "빈 목록")


def test_같은_자리_두_이름():
    print("[26] 🔴 같은 자리(IoU 0.9 이상)에 이름이 둘이면 회수 거부 — b003 f00205 B3·EMO · exclude 사진은 예외 · 떨어진 박스는 통과")
    with tempfile.TemporaryDirectory() as d:
        man = _man(["a_check__S__f00000.png", "a_check__S__f00001.png", "a_check__S__f00002.png"])
        cases = {"f00000": [X.shape("B3", [10, 10, 60, 60]), X.shape("EMO", [10, 10, 60, 61])],
                 "f00001": [X.shape("B3", [10, 10, 60, 60]), X.shape("EMO", [200, 200, 250, 250])],
                 "f00002": [X.shape("B3", [10, 10, 60, 60]), X.shape("EMO", [10, 10, 60, 60]), X.shape(X.EXCLUDE, [0, 0, 768, 1024])]}
        for k, shapes in cases.items():
            pth = os.path.join(d, f"a_check__S__{k}.json")
            X.write_json(pth, "x.png", 768, 1024, shapes)
            doc = json.load(open(pth)); doc["version"] = "3.3.5"; json.dump(doc, open(pth, "w"))
        p = CB.check_returned(man, d)
        check(any("f00000" in m and "같은 자리" in m for m in p), f"같은 자리 두 이름 = 거부 — {p}")
        check(not any("f00001" in m or "f00002" in m for m in p), "떨어진 박스 · exclude 사진 = 통과")


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
    test_검토함_플래그로_받기()
    test_다_봤다고_하면_받기()
    test_exclude_사진은_수정_집계에서_뺀다()
    test_크게_고친_박스는_지움이_아니다()
    test_다시_회수해도_어긋나지_않는다()
    test_두_번_보낸_폴더는_거부()
    test_쓴_사진과_닮은_후보는_뺀다()
    test_묶음_기록의_모델은_실제_설정()
    test_공구_초벌이_잡아_준_비율()
    test_공구_초벌_모델_기록()
    test_exclude_사진의_남은_제안은_문제_아님()
    test_겹친_공구_초벌_거르기()
    test_같은_자리_두_이름()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 반자동 라벨링 묶음 도구 검증 통과")
