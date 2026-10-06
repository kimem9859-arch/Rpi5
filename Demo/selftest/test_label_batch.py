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
    print("[6] 기계 확정·사람·제안·공구가 라벨 파일에서 구별된다(제안을 켰을 때 · --propose)")
    rev = {"boxes": [{"name": "B1", "score": 0.9, "box": [1, 2, 30, 40], "pre": [0, 0, 32, 44], "why": []},
                     {"name": "B3", "score": 0.8, "box": [50, 2, 80, 40], "pre": [48, 0, 82, 44], "why": ["흐림"]}],
           "missing": [("B4", [100, 100, 150, 150])], "nvis": 2}
    tools = [["driver", 0.31, 200, 200, 260, 300]]
    shapes, drafts, kind = RB.compose_shapes(rev, tools, propose=True)
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


def test_버튼_수고():
    print("[27] 버튼 수고 = 사람 확인 + 빠진 자리 제안 + 새로 그린 버튼 · 가짜 = 사람 확인 중 지움 · 기계 확정 틀림 — b003 집계로(spec 2026-09-29 §1)")
    stats = {"auto": {"그대로": 344, "박스 조정": 5, "크게 조정": 0, "이름 바뀜": 0, "지움": 0, "채택": 0},
             "check": {"그대로": 109, "박스 조정": 72, "크게 조정": 2, "이름 바뀜": 1, "지움": 36, "채택": 0},
             "propose": {"그대로": 0, "박스 조정": 0, "크게 조정": 6, "이름 바뀜": 0, "지움": 37, "채택": 2},
             "추가": {"wrench": 13, "B1": 3, "B4": 1, "driver": 1, "pliers": 1}}
    got = CB.button_work(stats)
    check(got == {"work": 269, "check": 220, "propose": 45, "added": 4, "fake": 36, "auto_wrong": 0}, f"{got}")
    stats["auto"].update({"이름 바뀜": 1, "크게 조정": 2, "지움": 3})
    check(CB.button_work(stats)["auto_wrong"] == 6, "기계 확정 중 이름 바뀜·크게 조정·지움")
    check(CB.button_work({"추가": {}})["work"] == 0, "빈 집계")


def test_버튼_모델_기록():
    print("[28] 새 버튼 모델을 주면 묶음 기록 = 그 파일(경로·해시) · 점수 기준 config.YOLO_CONF_LOW · 방식 whole(조각 안 함) · 안 주면 지금 방식 그대로")
    import config
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "button_r1.pt"); open(p, "wb").write(b"weights")
        m = RB.button_model_record(p)
        check(m["path"] == p and m["sha256_16"] == RB._sha(p) and m["conf"] == config.YOLO_CONF_LOW
              and m["method"].startswith("whole") and m["backend"] == "pt-rfenv", f"{m}")
    check(RB.button_model_record()["method"].startswith("tile2"), "모델을 안 주면 지금 방식(console_v2 조각)")


def test_제안은_기본으로_끔():
    print("[29] 빠진 자리 제안은 기본으로 넣지 않는다(사용자 결정 2026-09-29 · b001~b004 제안 45개 중 쓸모 0~8) · 제안만 있던 사진은 auto")
    rev = {"boxes": [{"name": "B1", "score": 0.9, "box": [1, 2, 30, 40], "pre": [0, 0, 32, 44], "why": []}],
           "missing": [("B4", [100, 100, 150, 150])], "nvis": 1}
    shapes, drafts, kind = RB.compose_shapes(rev, [])
    check([s["label"] for s in shapes] == ["B1"] and [d["kind"] for d in drafts] == ["auto"], f"{[s['label'] for s in shapes]}")
    check(kind == "auto", f"종류 {kind}")
    check(RB.compose_shapes(rev, [], propose=True)[2] == "propose", "켜면 예전대로 propose")


def test_묶음_안내문():
    print("[30] 묶음 안내문 — 안내서 주소 · 공유 드라이브 · 사진마다 검토함 · .json 만 올림 · 컴파일 경고 없음(Windows 경로 역슬래시)")
    import warnings
    g = RB.GUIDE.format(batch="b005", n=200, created="2026-09-29 12:00")
    for k in (RB.GUIDE_URL, "공유 드라이브", "검토함", ".json", "returned", "b005"):
        check(k in g, k)
    src = open(RB.__file__, encoding="utf-8").read()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            compile(src, RB.__file__, "exec"); ok = True
        except SyntaxError as e:
            ok = False; print("   ", e)
    check(ok, "review_batch.py 컴파일 경고 없음")


def test_같은_이름_개수_상한_초벌():
    print("[31] 🔴 초벌의 같은 이름 박스는 버튼 5종·driver·pliers 1개 · wrench 2개까지 — 확신도 높은 것을 남기고 순서는 그대로"
          " (b004~b014 초벌에 같은 버튼 박스가 똑같이 두 번 · 사용자 2026-10-03)")
    A = [10, 10, 60, 60]
    rev = {"boxes": [{"name": "B1", "score": 0.9, "box": A, "pre": A, "why": ["배치 불확실"]},
                     {"name": "B1", "score": 0.7, "box": A, "pre": A, "why": ["배치 불확실"]},
                     {"name": "B2", "score": 0.6, "box": [100, 10, 150, 60], "pre": [100, 10, 150, 60], "why": []},
                     {"name": "B2", "score": 0.8, "box": [200, 10, 250, 60], "pre": [200, 10, 250, 60], "why": []}],
           "missing": [], "nvis": 4}
    tools = [["wrench", 0.5, 0, 300, 50, 400], ["wrench", 0.6, 100, 300, 150, 400], ["wrench", 0.4, 200, 300, 250, 400],
             ["driver", 0.3, 300, 300, 350, 400], ["driver", 0.35, 400, 300, 450, 400]]
    shapes, drafts, _ = RB.compose_shapes(rev, tools)
    got = [(s["label"], s["score"]) for s in shapes]
    check(got == [("B1", 0.9), ("B2", 0.8), ("wrench", 0.5), ("wrench", 0.6), ("driver", 0.35)], f"{got}")
    check([d["label"] for d in drafts] == [s["label"] for s in shapes], "초벌 기록도 같은 박스만")
    rev2 = {"boxes": [{"name": "B1", "score": 0.95, "box": [300, 10, 350, 60], "pre": [300, 10, 350, 60], "why": ["배치≠초벌"], "layout": "B4"},
                      {"name": "B1", "score": 0.6, "box": A, "pre": A, "why": [], "layout": "B1"}], "missing": [], "nvis": 2}
    got2 = [(s["label"], s["score"]) for s in RB.compose_shapes(rev2, [])[0]]
    check(got2 == [("B1", 0.6)], f"버튼은 콘솔 자리가 이름과 맞는 박스를 확신도보다 먼저 남긴다 — {got2}")


def test_같은_이름_개수_회수():
    print("[32] 🔴 회수 — 똑같은 박스(이름·위치)는 하나로 합쳐 받고 · 위치가 다른 같은 이름이 상한을 넘으면 거부(wrench 는 2개까지) · exclude 사진은 예외")
    B = [10, 10, 60, 60]
    with tempfile.TemporaryDirectory() as d:
        files = [f"a_check__S__f0000{i}.png" for i in range(5)]
        man = _man(files)
        man["images"][0]["drafts"] = [{"label": "B1", "box": B, "kind": "check", "why": []},
                                      {"label": "B1", "box": B, "kind": "check", "why": []}]
        cases = {0: [X.shape("B1", B), X.shape("B1", B)],
                 1: [X.shape("B2", [10, 10, 60, 60]), X.shape("B2", [200, 200, 250, 250])],
                 2: [X.shape("wrench", [0, 300, 50, 400]), X.shape("wrench", [100, 300, 150, 400])],
                 3: [X.shape("wrench", [0, 300, 50, 400]), X.shape("wrench", [100, 300, 150, 400]), X.shape("wrench", [200, 300, 250, 400])],
                 4: [X.shape("B2", [10, 10, 60, 60]), X.shape("B2", [200, 200, 250, 250]), X.shape(X.EXCLUDE, [0, 0, 768, 1024])]}
        for i, shapes in cases.items():
            pth = os.path.join(d, f"a_check__S__f0000{i}.json")
            X.write_json(pth, "x.png", 768, 1024, shapes)
            doc = json.load(open(pth)); doc["version"] = "3.3.5"; json.dump(doc, open(pth, "w"))
        p = CB.check_returned(man, d)
        check(not any("f00000" in m for m in p), f"똑같은 박스 둘 = 통과 — {p}")
        check(any("f00001" in m and "B2" in m for m in p), "위치가 다른 B2 둘 = 거부")
        check(not any("f00002" in m for m in p), "wrench 둘 = 통과")
        check(any("f00003" in m and "wrench" in m for m in p), "wrench 셋 = 거부")
        check(not any("f00004" in m for m in p), "exclude 사진 = 통과")
        near = [{"label": "B1", "box": B}, {"label": "B1", "box": [10, 11, 60, 61]}]   # 1px 어긋난 숨은 사본(b011 f07159 · b012 f09310 초벌)
        apart = [{"label": "B2", "box": [10, 10, 60, 60]}, {"label": "B2", "box": [200, 200, 250, 250]}]
        check(any("겹쳐 숨은" in m for m in CB.too_many(near)), f"거의 같은 자리 둘이면 숨은 사본이라고 알린다 — {CB.too_many(near)}")
        check(CB.too_many(apart) and not any("겹쳐 숨은" in m for m in CB.too_many(apart)), "떨어진 둘은 거부하되 그 말을 붙이지 않는다")
        ret = os.path.join(d, "ret"); os.mkdir(ret)
        os.rename(os.path.join(d, "a_check__S__f00000.json"), os.path.join(ret, "a_check__S__f00000.json"))
        man["images"] = man["images"][:1]
        mp = os.path.join(d, "manifest.json"); json.dump(man, open(mp, "w"))
        out = os.path.join(d, "out")
        r = _run_collect(ret, mp, out)
        lab = open(os.path.join(out, "labels", "S__f00000.txt")).read().splitlines()
        check(r.returncode == 0 and len(lab) == 1, f"라벨 한 줄 — {lab} {r.stdout[-300:]}")
        check("똑같은 박스 합침 1" in r.stdout, "합친 수를 알린다")
        st = json.load(open(os.path.join(out, "stats", "t.json"), encoding="utf-8"))
        check(st["check"]["그대로"] == 1 and st["check"]["지움"] == 0, f"초벌 중복도 합쳐 집계(지움으로 안 셈) — {st['check']}")


def test_늘린_사진_박스_되돌리기():
    print("[33] 🔴 늘린 사진(640×640)에 그린 공구 박스를 원본(768×1024) 좌표로 — 축마다 비율만 곱하고 반올림(사각형은 사각형 그대로)")
    import prelabel_tools as PT
    check(PT.stretch_back([64, 64, 320, 320], 768, 1024, (640, 640)) == [77, 102, 384, 512],
          f"{PT.stretch_back([64, 64, 320, 320], 768, 1024, (640, 640))}")
    check(PT.stretch_back([0, 0, 640, 640], 768, 1024, (640, 640)) == [0, 0, 768, 1024], "사진 전체 = 원본 전체")
    check(PT.parse_size("640x640") == (640, 640) and PT.parse_size(None) is None, "옵션 글자 → (가로, 세로)")


def test_공구_초벌_문턱과_입력_기록():
    print("[34] 🔴 공구 초벌의 문턱·입력 방식은 묶음 기록에 남는다 — 기본값은 옛 묶음과 같다(0.25 · 원본 그대로)")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "best.pt"); open(p, "wb").write(b"weights")
        old = RB.tool_model_record(p)
        new = RB.tool_model_record(p, conf=0.65, stretch=(640, 640))
        check(old["conf"] == 0.25 and old["input"].startswith("원본"), f"{old}")
        check(new["conf"] == 0.65 and new["input"] == "늘리기 640x640", f"{new}")


def test_공구_초벌_옵션():
    print("[35] 🔴 review_batch 에 --tool-conf · --tool-stretch 가 있고 기본값은 옛 묶음과 같다(0.25 · 늘리지 않음)")
    a = RB.build_parser().parse_args(["--sessions", "s", "--template", "t", "--used", "u", "--out", "o"])
    check(a.tool_conf == 0.25 and a.tool_stretch is None, f"기본 {a.tool_conf} · {a.tool_stretch}")
    a = RB.build_parser().parse_args(["--sessions", "s", "--template", "t", "--used", "u", "--out", "o",
                                      "--tool-conf", "0.65", "--tool-stretch", "640x640"])
    check(a.tool_conf == 0.65 and a.tool_stretch == "640x640", f"지정 {a.tool_conf} · {a.tool_stretch}")


import pick_score_set as PS


def test_채점_사진_공구_종류별_고르기():
    print("[36] 🔴 채점 묶음 고르기 — 사람 라벨의 공구만 세고 · 드문 공구부터 종류별 사진 수를 채우고 · 공구 없는 사진을 더하고 · 모자라면 적는다")
    check(PS.tool_boxes(["5 0.1 0.1 0.1 0.1", "6 0.2 0.2 0.1 0.1", "6 0.5 0.5 0.1 0.1", "0 0.3 0.3 0.1 0.1", ""])
          == {"driver": 1, "wrench": 2}, "버튼(0)은 세지 않고 공구 박스 수만")
    items = {}
    for i in range(10):
        items[f"w{i:02d}"] = {"wrench": 1}
    for i in range(5):
        items[f"dw{i:02d}"] = {"driver": 1, "wrench": 1}
    for i in range(50):
        items[f"d{i:02d}"] = {"driver": 1}
        items[f"p{i:02d}"] = {"pliers": 2}
    for i in range(30):
        items[f"e{i:02d}"] = {}
    got, rep = PS.pick(items, 8, 5, 1)
    ph = rep["공구별 사진"]
    check(ph["driver"] == 8 and ph["pliers"] == 8 and ph["wrench"] >= 8, f"종류별 사진 {ph}")
    check(rep["공구 없는 사진"] == 5 and not rep["모자람"], f"공구 없음 {rep['공구 없는 사진']} · 모자람 {rep['모자람']}")
    check(rep["공구별 박스"]["pliers"] == 16, f"박스 수는 라벨대로 {rep['공구별 박스']}")
    check(got == PS.pick(items, 8, 5, 1)[0] and got == sorted(got), "같은 seed → 같은 목록(정렬)")
    _, rep2 = PS.pick(items, 20, 40, 1)
    check(rep2["모자람"] == {"wrench": 5, "공구 없음": 10}, f"모자람 {rep2['모자람']}")


def test_채점_묶음_왕복():
    print("[37] 🔴 채점 묶음 — 앞 검토 라벨을 박스로 넣고, 다음 검토자가 고치지 않고 「검토함」만 켜 회수하면 같은 라벨이 돌아온다(used 에 안 적음)")
    import subprocess
    import cv2
    import numpy as np
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "raw", "20261006_185503_장소2_6"); os.makedirs(src)
        img = os.path.join(src, "f00012.png"); cv2.imwrite(img, np.zeros((1024, 768, 3), np.uint8))
        ds = os.path.join(d, "ds"); os.makedirs(os.path.join(ds, "labels"))
        name = "1006-185503__f00012"
        lines = ["0 0.244141 0.811035 0.079427 0.059570", "5 0.500000 0.400000 0.200000 0.100000",
                 "6 0.300000 0.700000 0.150000 0.050000"]
        open(os.path.join(ds, "labels", f"{name}.txt"), "w").write("\n".join(lines) + "\n")
        open(os.path.join(ds, "images.txt"), "w").write(f"{name}\t{img}\n")
        lst = os.path.join(d, "c001_목록.txt"); open(lst, "w").write(name + "\n")
        out = os.path.join(d, "c001")
        r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "test", "score_batch.py"), "--names", lst,
                            "--dataset", ds, "--out", out], capture_output=True, text=True)
        check(r.returncode == 0, f"묶음 만들기 {r.stdout.strip()} {r.stderr.strip()[-200:]}")
        man = json.load(open(os.path.join(out, "manifest.json")))
        check(man["kind"] == "score" and man["images"][0]["file"] == f"s_score__{name}.png"
              and [x["kind"] for x in man["images"][0]["drafts"]] == ["check", "tool", "tool"], f"{man['images'][0]['file']}")
        doc = json.load(open(os.path.join(out, "images", f"s_score__{name}.json")))
        check(doc["flags"] == {X.REVIEW_FLAG: False}, "「검토함」 꺼진 채로 넘긴다")
        ret = os.path.join(d, "returned"); os.makedirs(ret)
        doc["flags"][X.REVIEW_FLAG] = True
        json.dump(doc, open(os.path.join(ret, f"s_score__{name}.json"), "w"), ensure_ascii=False)
        dst = os.path.join(d, "final")
        r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "test", "collect_batch.py"), ret,
                            "--manifest", os.path.join(out, "manifest.json"), "--out", dst], capture_output=True, text=True)
        check(r.returncode == 0, f"회수 {r.stdout.strip()[:120]} {r.stderr.strip()[-200:]}")
        back = open(os.path.join(dst, "labels", f"{name}.txt")).read().split("\n")
        check([l for l in back if l] == lines, f"같은 라벨 {back}")


def test_공구_초벌_입력_크기():
    print("[38] 🔴 원본 비율로 학습한 공구 모델(T-full-in1024 · 예측 [1024,768])은 입력 크기를 그대로 준다 — 기본 640 으로 넣으면 학습과 다른 그림")
    import prelabel_tools as PT
    check(PT.parse_imgsz("1024,768") == [1024, 768] and PT.parse_imgsz("640") == 640 and PT.parse_imgsz(None) is None, "옵션 글자 → imgsz")
    a = RB.build_parser().parse_args(["--sessions", "s", "--template", "t", "--used", "u", "--out", "o", "--tool-imgsz", "1024,768"])
    check(a.tool_imgsz == "1024,768", f"{a.tool_imgsz}")
    check(RB.build_parser().parse_args(["--sessions", "s", "--template", "t", "--used", "u", "--out", "o"]).tool_imgsz is None, "기본 없음")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "best.pt"); open(p, "wb").write(b"weights")
        m = RB.tool_model_record(p, conf=0.65, imgsz=[1024, 768])
        check(m["input"] == "원본 그대로 · imgsz [1024, 768]", f"{m}")


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
    test_버튼_수고()
    test_버튼_모델_기록()
    test_제안은_기본으로_끔()
    test_묶음_안내문()
    test_같은_이름_개수_상한_초벌()
    test_같은_이름_개수_회수()
    test_늘린_사진_박스_되돌리기()
    test_공구_초벌_문턱과_입력_기록()
    test_공구_초벌_옵션()
    test_채점_사진_공구_종류별_고르기()
    test_채점_묶음_왕복()
    test_공구_초벌_입력_크기()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 반자동 라벨링 묶음 도구 검증 통과")
