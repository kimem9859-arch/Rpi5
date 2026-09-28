"""xany_io — X-AnyLabeling 라벨 파일과 YOLO 변환의 경계를 고정한다.

실행: python3 Demo/selftest/test_xany_io.py
정본 설계: ../../docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §8
"""
import json
import os
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import xany_io as X

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_쓰고_읽기():
    print("[1] 쓰고 다시 읽으면 박스·이름·설명이 그대로 · 초벌 표시 version")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.json")
        X.write_json(p, "a.png", 768, 1024, [X.shape("B3", [10, 20, 60, 80], 0.91, "기계 확정")])
        doc = json.load(open(p, encoding="utf-8"))
        check(len(doc["shapes"][0]["points"]) == 4, "사각형 점 4개")
        r = X.read_json(p)
        check(r["version"] == X.DRAFT_VERSION, "version = 초벌 표시")
        s = r["shapes"][0]
        check(s["label"] == "B3" and s["box"] == [10, 20, 60, 80] and s["description"] == "기계 확정", f"{s}")


def test_점_두_개도_읽기():
    print("[2] 점 2개 사각형(LabelMe 식)도 최소·최대로 읽는다")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.json")
        json.dump({"version": "4.0.6", "shapes": [{"label": "B1", "points": [[50, 60], [10, 20]],
                                                    "shape_type": "rectangle"}],
                   "imageWidth": 768, "imageHeight": 1024, "imagePath": "b.png"}, open(p, "w"))
        check(X.read_json(p)["shapes"][0]["box"] == [10, 20, 50, 60], "[10,20,50,60]")


def test_이름_문제():
    print("[3] 🔴 이름이 8종·exclude 밖이면 문제 · 제안이 남으면 문제")
    sh = [{"label": n, "box": [0, 0, 5, 5], "shape_type": "rectangle"}
          for n in ("B3", "exclude", "b3", "EMO ", "B 3", "제안_B4", "pliers")]
    p = X.problems(sh)
    check(any("'b3'" in m for m in p) and any("'EMO '" in m for m in p) and any("'B 3'" in m for m in p),
          "b3 · 'EMO ' · 'B 3' 는 모르는 이름")
    check(any("제안" in m for m in p), "제안_B4 가 남음")
    check(not any("'B3'" in m or "'pliers'" in m or "'exclude'" in m for m in p), "B3 · pliers · exclude 는 문제 아님")
    check(X.problems([{"label": "B1", "box": [0, 0, 1, 1], "shape_type": "polygon"}]) != [], "사각형이 아니면 문제")


def test_사진_밖_박스():
    print("[4] 사진 밖으로 나간 박스는 잘라내고, 넓이 0 은 버린다")
    lines = X.to_yolo_lines([{"label": "B1", "box": [-10, -5, 50, 40]},
                             {"label": "B2", "box": [800, 10, 900, 60]}], 768, 1024)
    check(len(lines) == 1, f"남는 줄 1개 — {lines}")
    c, cx, cy, w, h = lines[0].split()
    check(c == "0" and abs(float(cx) - 25 / 768) < 1e-5 and abs(float(w) - 50 / 768) < 1e-5, f"{lines[0]}")


def test_크기가_다른_사진():
    print("[5] 같은 픽셀 박스라도 사진 크기(VGA·XGA)마다 따로 나눈다")
    sh = [{"label": "EMO", "box": [100, 100, 148, 148]}]
    a = X.to_yolo_lines(sh, 480, 640)[0].split(); b = X.to_yolo_lines(sh, 768, 1024)[0].split()
    check(a[0] == b[0] == "4", "EMO = 4")
    check(abs(float(a[3]) - 48 / 480) < 1e-5 and abs(float(b[3]) - 48 / 768) < 1e-5, f"폭 {a[3]} · {b[3]}")


def test_exclude_사진():
    print("[6] exclude 박스가 있으면 사진 전체를 뺀다(None)")
    check(X.to_yolo_lines([{"label": "exclude", "box": [0, 0, 5, 5]},
                           {"label": "B1", "box": [10, 10, 30, 30]}], 768, 1024) is None, "None")


def test_클래스_순서():
    print("[7] 클래스 번호 순서 고정")
    check(X.CLASSES == ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"], f"{X.CLASSES}")


def test_검토함_플래그():
    print("[8] 초벌 파일에는 사진 단위 플래그 「검토함」 이 꺼진 채로 들어가고, 켜지면 검토한 사진으로 읽는다")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "c.json")
        X.write_json(p, "c.png", 768, 1024, [])
        doc = json.load(open(p, encoding="utf-8"))
        check(doc["flags"] == {X.REVIEW_FLAG: False}, f"flags {doc['flags']}")
        check(X.read_json(p)["reviewed"] is False, "꺼져 있으면 검토 안 함")
        doc["flags"][X.REVIEW_FLAG] = True; json.dump(doc, open(p, "w"))
        check(X.read_json(p)["reviewed"] is True, "켜지면 검토함")
        doc["flags"] = {}; doc["checked"] = True; json.dump(doc, open(p, "w"))
        check(X.read_json(p)["reviewed"] is True, "새 판의 checked 도 검토함")


if __name__ == "__main__":
    test_쓰고_읽기()
    test_점_두_개도_읽기()
    test_이름_문제()
    test_사진_밖_박스()
    test_크기가_다른_사진()
    test_exclude_사진()
    test_클래스_순서()
    test_검토함_플래그()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ X-AnyLabeling 파일 경계 검증 통과")
