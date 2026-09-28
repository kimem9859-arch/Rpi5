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


def _tiny(d, n=5):
    src = Path(d) / "src"; (src / "labels").mkdir(parents=True)
    rows = []
    for i in range(1, n + 1):
        img = Path(d) / f"o{i}.png"; img.write_bytes(bytes([i]) * 10)
        rows.append(f"A__f{i:05d}\t{img}")
        (src / "labels" / f"A__f{i:05d}.txt").write_text("6 0.2 0.2 0.1 0.1\n", encoding="utf-8")
    (src / "images.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return src


def test_묶기():
    print("[8] Colab 에 올릴 묶음 — tar 안의 data.yaml 은 원격 경로 · 사진·라벨 모두 · 원본 내용 그대로")
    import tarfile
    with tempfile.TemporaryDirectory() as d:
        ds = Path(d) / "tool_r1"
        TR.build_dataset(_tiny(d), ds)
        tar = Path(d) / "tool_r1.tar"
        n = TR.pack_dataset(ds, tar, "/content")
        with tarfile.open(tar) as t:
            names = t.getnames()
            y = t.extractfile("tool_r1/data.yaml").read().decode()
            img = t.extractfile("tool_r1/images/val/A__f00005.png").read()
        check(n == 11 and "tool_r1/labels/train/A__f00001.txt" in names, f"파일 {n} · {sorted(names)[:3]}")
        check("path: /content/tool_r1" in y and "2: pliers" in y, y)
        check(img == bytes([5]) * 10, "사진 내용 그대로(하드링크도 실제 바이트로)")


def test_원격_스크립트():
    print("[9] 원격 학습 스크립트 — 문법 OK · 학습 중 성적 재기 끔 · GPU · 버전 고정 · 표지 3종")
    src = TR.remote_script("tool_r1", [("yolov8n", "/content/yolov8n.pt"), ("tool_v3", "/content/tool_v3.pt")], 50, None, "8.4.117")
    compile(src, "remote", "exec")
    for k in ("val=False", "device=0", "epochs=50", "time=None", "ultralytics==8.4.117", "/content/tool_r1/data.yaml",
              "/content/tool_r1.tar", "'yolov8n'", "'/content/tool_v3.pt'", "@@SETUP ok", "@@DONE", "@@FAIL"):
        check(k in src, k)


def test_표지_읽기():
    print("[10] 🔴 성패는 종료 코드가 아니라 표지로 — colab exec 는 예외에도 0 을 낸다(§12.41-(6))")
    log = ("[colab] noise\n@@SETUP start\n@@SETUP ok\nEpoch 1/50 ...\n"
           "@@DONE yolov8n 6.2 /content/runs/detect/yolov8n\n"
           "@@FAIL tool_v3 RuntimeError: CUDA out of memory\nTraceback (most recent call last):\n")
    m = TR.parse_markers(log)
    check(m == {"setup_ok": True, "done": {"yolov8n": {"minutes": 6.2, "dir": "/content/runs/detect/yolov8n"}},
                "fail": {"tool_v3": "RuntimeError: CUDA out of memory"}}, f"{m}")
    check(TR.parse_markers("@@SETUP start\nERROR pip\n")["setup_ok"] is False, "설치·풀기 표지가 없으면 실패")
    echo = 'print("@@SETUP ok", flush=True)\n        print(f"@@DONE {stem} 1.0 /x", flush=True)\n'
    check(TR.parse_markers(echo) == {"setup_ok": False, "done": {}, "fail": {}}, "스크립트 원문이 되비쳐도 표지로 세지 않는다(줄 첫머리만)")


def test_개인정보_제외():
    print("[11] 개인정보 관문에서 뺀 사진은 학습 묶음(학습·떼어 둔 양쪽)에 넣지 않는다")
    with tempfile.TemporaryDirectory() as d:
        info = TR.build_dataset(_tiny(d), Path(d) / "dst", exclude={"A__f00002", "A__f00005"})
        check(info["train"] + info["val"] == ["A__f00001", "A__f00003", "A__f00004"] or
              sorted(info["train"] + info["val"]) == ["A__f00001", "A__f00003", "A__f00004"], f"{info['train']} / {info['val']}")
        check(not (Path(d) / "dst" / "images" / "val" / "A__f00005.png").exists(), "뺀 사진 파일 없음")


import argparse
import subprocess
import train_tool_round as TTR


def test_시작_전_확인():
    print("[12] 🔴 --probe 는 cpu 에서만 · 이미 있는 라운드 모델·기록은 덮어쓰지 않는다 — 데이터를 만들기 전에 멈춘다")
    with tempfile.TemporaryDirectory() as d:
        models = Path(d)
        a = argparse.Namespace(probe=True, backend="colab", round=1)
        check(any("--probe" in m for m in TTR.preflight(a, models)), "colab + probe = 멈춤")
        (models / "tool_r1.pt").write_bytes(b"x")
        a = argparse.Namespace(probe=False, backend="colab", round=1)
        check(any("tool_r1.pt" in m for m in TTR.preflight(a, models)), "기존 tool_r1.pt = 멈춤")
        a = argparse.Namespace(probe=False, backend="colab", round=2)
        check(TTR.preflight(a, models) == [], "새 라운드는 통과")


def test_결말_가르기():
    print("[13] 🔴 학습이 전부 실패하면 「관문 패배」가 아니라 「학습 실패」 — 다음 판단을 그르치지 않게")
    cur = {"caught": 2, "fake": 5, "missed": 13}
    check(TR.decide({}, cur) == ("학습 실패", None), "후보 없음 = 학습 실패")
    check(TR.decide({"a": {"caught": 1, "fake": 5, "missed": 14}}, cur) == ("관문 패배", None), "지면 관문 패배")
    check(TR.decide({"a": {"caught": 9, "fake": 5, "missed": 6}}, cur) == ("채택", "a"), "이기면 채택")


def test_개인정보_관문_결속():
    print("[14] 🔴 관문을 거치지 않은 사진은 올리지 않는다 · --exclude 의 이름이 목록에 없으면(오타) 멈춘다")
    names = ["A__f00001", "A__f00002", "B__f00001"]
    check(TR.privacy_problems(names, {"A__f00002"}, {"A__f00001", "B__f00001"}) == [], "뺀 것 빼고 전부 통과 = 문제 없음")
    p = TR.privacy_problems(names, {"A__f0002.png"}, set(names))
    check(any("A__f0002.png" in m for m in p), f"오타 exclude — {p}")
    p = TR.privacy_problems(names, set(), {"A__f00001"})
    check(any("2장" in m for m in p), f"관문 안 거친 2장 — {p}")


def test_반납_보장():
    print("[15] 🔴 GPU 빌리기가 시간 초과로 끊겨도 반납을 시도한다 · 반납이 실패해도 받은 결과는 잃지 않는다")
    with tempfile.TemporaryDirectory() as d:
        ds = Path(d) / "tool_r1"; TR.build_dataset(_tiny(d), ds)
        calls = []

        def fake_timeout(*args, timeout):
            calls.append(args[0])
            if args[0] == "new":
                raise subprocess.TimeoutExpired("colab new", timeout)
            return subprocess.CompletedProcess(args, 0, "", "")
        TTR.colab, orig = fake_timeout, TTR.colab
        try:
            try:
                TTR.train_colab([str(Path(d) / "yolov8n.pt")], ds, 50, "s")
                raised = False
            except subprocess.TimeoutExpired:
                raised = True
            check(raised and "stop" in calls, f"시간 초과가 올라오고 반납 시도 — {calls}")

            def fake_ok(*args, timeout):
                calls.append(args[0])
                if args[0] == "exec":
                    return subprocess.CompletedProcess(args, 0, "@@SETUP ok\n@@DONE yolov8n 3.0 /content/runs/yolov8n\n", "")
                if args[0] == "download":
                    Path(args[4]).write_bytes(b"w")
                if args[0] == "stop":
                    raise subprocess.TimeoutExpired("colab stop", timeout)
                return subprocess.CompletedProcess(args, 0, "", "")
            TTR.colab = fake_ok
            ds2 = Path(d) / "tool_r2"; TR.build_dataset(Path(d) / "src", ds2)
            out, mk, _ = TTR.train_colab([str(Path(d) / "yolov8n.pt")], ds2, 50, "s")
            check("yolov8n" in out and out["yolov8n"][0].exists(), f"반납이 실패해도 결과 유지 — {out}")
        finally:
            TTR.colab = orig


if __name__ == "__main__":
    test_공구만_번호_바꾸기()
    test_세션별_마지막_20퍼센트()
    test_관문_셈()
    test_고르기()
    test_라벨_없으면_멈춤()
    test_학습_폴더()
    test_이름으로_번호()
    test_시연_모델_폴더_거부()
    test_묶기()
    test_원격_스크립트()
    test_표지_읽기()
    test_개인정보_제외()
    test_시작_전_확인()
    test_결말_가르기()
    test_개인정보_관문_결속()
    test_반납_보장()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 공구 초벌 반복 학습 순수 부분 검증 통과")
