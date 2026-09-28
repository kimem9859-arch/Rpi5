"""tool_round — 공구 초벌 반복 학습의 순수 부분(학습 데이터 · 떼어 두기 · 관문 셈 · 고르기)을 고정한다.

실행: python3 Demo/selftest/test_tool_round.py
정본 설계: ../../docs/superpowers/specs/2026-09-28-공구초벌-반복학습-design.md §4 · §6 · §7
⚠️ ultralytics·모델이 필요 없다.
"""
import os
import sys
import tempfile
from pathlib import Path

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import tool_round as TR

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_공구만_번호_바꾸기():
    print("[1] 8종 라벨에서 공구만 남기고 번호를 0~2 로 — 버튼 줄은 버린다")
    got = TR.tool_lines(["0 0.5 0.5 0.1 0.1", "5 0.2 0.2 0.1 0.1", "6 0.3 0.3 0.1 0.2", "7 0.4 0.4 0.2 0.2", "4 0.1 0.1 0.1 0.1", ""])
    check(got == ["0 0.2 0.2 0.1 0.1", "1 0.3 0.3 0.1 0.2", "2 0.4 0.4 0.2 0.2"], f"{got}")


def test_세션별_마지막_20퍼센트():
    print("[2] 🔴 세션마다 프레임 순서 마지막 20%(올림)를 떼어 둔다 — 무작위가 아니다 · 1장뿐인 세션은 통째로")
    names = [f"A__f{i:05d}" for i in (5, 1, 3, 2, 4, 9, 8, 7, 6, 10)] + ["B__f00001"] + [f"C__f{i:05d}" for i in range(1, 6)]
    tr, ho = TR.split_holdout(names, 0.2)
    check(ho == ["A__f00009", "A__f00010", "B__f00001", "C__f00005"], f"떼어 둔 {ho}")
    check(len(tr) + len(ho) == len(names) and not set(tr) & set(ho), "겹침 없이 모두")


def test_관문_셈():
    print("[3] 관문 셈 — 같은 번호 IoU 0.5 이상만 잡은 것 · 나머지 예측은 가짜 · 남은 정답은 놓침")
    truths = [(0, [0, 0, 100, 100]), (1, [200, 0, 300, 100]), (2, [400, 0, 500, 100])]
    preds = [(0, [5, 5, 100, 100]),        # 잡음
             (2, [200, 0, 300, 100]),      # 자리는 맞으나 번호 틀림 → 가짜 · wrench 놓침
             (2, [460, 60, 560, 160])]     # IoU 0.09 → 가짜 · pliers 놓침
    c = TR.match_counts(preds, truths)
    check(c == {"caught": 1, "fake": 2, "missed": 2}, f"{c}")
    check(TR.net(c) == -1, "순이익 = 잡은 수 − 가짜 수")


def test_고르기():
    print("[4] 순이익이 가장 큰 후보가 지금 모델보다 클 때만 채택 · 같으면 이름순 첫째 · 지면 None")
    cur = {"caught": 3, "fake": 2, "missed": 10}                      # 1
    check(TR.pick({"tool_v3": {"caught": 5, "fake": 1, "missed": 8}, "yolov8n": {"caught": 9, "fake": 3, "missed": 4}}, cur) == "yolov8n", "큰 쪽")
    check(TR.pick({"b": {"caught": 4, "fake": 0, "missed": 9}, "a": {"caught": 5, "fake": 1, "missed": 8}}, cur) == "a", "같으면 이름순")
    check(TR.pick({"x": {"caught": 1, "fake": 0, "missed": 12}}, cur) is None, "지면 지금 모델 유지")
    check(TR.pick({"x": {"caught": 0, "fake": 0, "missed": 0}}, {"caught": 0, "fake": 1, "missed": 0}) == "x", "공구 0개면 가짜 수로 갈린다")


def test_라벨_없으면_멈춤():
    print("[5] 🔴 images.txt 에 있는데 라벨 파일이 없으면 멈춘다 — 공구 있는 사진을 「공구 없음」으로 가르치지 않게")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"; (src / "labels").mkdir(parents=True)
        img = Path(d) / "orig.png"; img.write_bytes(b"x")
        (src / "images.txt").write_text(f"A__f00001\t{img}\nA__f00002\t{img}\n", encoding="utf-8")
        (src / "labels" / "A__f00001.txt").write_text("5 0.5 0.5 0.1 0.1\n", encoding="utf-8")
        try:
            TR.build_dataset(src, Path(d) / "dst")
            ok = False
        except FileNotFoundError:
            ok = True
        check(ok, "FileNotFoundError")


def test_학습_폴더():
    print("[5-b] 학습 폴더 — images/labels × train/val · 공구 없는 사진도 빈 라벨 · data.yaml 이름 3종 · 원본은 그대로")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"; (src / "labels").mkdir(parents=True)
        rows = []
        for i in range(1, 6):
            img = Path(d) / f"o{i}.png"; img.write_bytes(bytes([i]))
            rows.append(f"A__f{i:05d}\t{img}")
            (src / "labels" / f"A__f{i:05d}.txt").write_text("0 0.5 0.5 0.1 0.1\n6 0.2 0.2 0.1 0.1\n" if i != 2 else "3 0.5 0.5 0.1 0.1\n", encoding="utf-8")
        (src / "images.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        info = TR.build_dataset(src, Path(d) / "dst")
        dst = Path(d) / "dst"
        check(info["val"] == ["A__f00005"] and len(info["train"]) == 4, f"{info['train']} / {info['val']}")
        check(info["boxes"] == {"train": 3, "val": 1}, f"공구 박스 {info['boxes']}")
        check((dst / "labels" / "train" / "A__f00002.txt").read_text() == "", "공구 없는 사진 = 빈 라벨")
        check((dst / "images" / "val" / "A__f00005.png").read_bytes() == bytes([5]), "사진 연결")
        y = (dst / "data.yaml").read_text(encoding="utf-8")
        check("0: driver" in y and "1: wrench" in y and "2: pliers" in y and "train: images/train" in y, y)
        try:
            TR.build_dataset(src, dst); again = False
        except FileExistsError:
            again = True
        check(again, "이미 있으면 덮어쓰지 않는다")


def test_이름으로_번호():
    print("[6] 모델 클래스 이름 → 학습 번호 — `-in-hand` 를 떼고, 모르는 이름은 None")
    check([TR.tool_index(n) for n in ("driver", "wrench-in-hand", "pliers", "hammer")] == [0, 1, 2, None], "")
    check(TR.yolo_to_boxes(["1 0.5 0.5 0.2 0.4"], 100, 200) == [(1, [40.0, 60.0, 60.0, 140.0])], "YOLO → 픽셀")


def test_시연_모델_폴더_거부():
    print("[7] 🔴 결과 모델을 Demo/models 안에 두려 하면 거부")
    dm = Path(_DEMO_DIR) / "models"
    check(TR.is_demo_models(dm, dm) and TR.is_demo_models(dm / "sub", dm), "Demo/models 와 그 아래")
    check(not TR.is_demo_models(Path.home() / "data" / "label_models", dm), "~/data/label_models 는 허용")


if __name__ == "__main__":
    test_공구만_번호_바꾸기()
    test_세션별_마지막_20퍼센트()
    test_관문_셈()
    test_고르기()
    test_라벨_없으면_멈춤()
    test_학습_폴더()
    test_이름으로_번호()
    test_시연_모델_폴더_거부()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 공구 초벌 반복 학습 순수 부분 검증 통과")
