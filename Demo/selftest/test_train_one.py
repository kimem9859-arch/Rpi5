"""실험 한 번(학습/train_one.py)의 데이터 준비를 고정한다 — 늘리기·원본 · .npy · 라벨 · 동시 준비 잠금 · 실험 폴더 하드링크 · 종료 이유.

실행: python3 Demo/selftest/test_train_one.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §5 · §7
⚠️ ultralytics·GPU 가 필요 없다(학습·채점은 Task 12·13 데스크톱 실제 실행에서 확인).
"""
import multiprocessing as mp
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))
sys.path.insert(0, os.path.join(_RPI5, "Demo", "test"))

import train_one as T1

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _src(t):
    src = Path(t) / "원본"
    for sub in ("images", "labels8", "labels_button"):
        (src / sub).mkdir(parents=True)
    for n in ("a__f00001", "a__f00002", "a__f00003"):
        cv2.imwrite(str(src / "images" / f"{n}.png"), np.full((8, 6, 3), 100, np.uint8))   # 세로 8 · 가로 6
        (src / "labels8" / f"{n}.txt").write_text("5 0.5 0.5 0.1 0.1\n", encoding="utf-8")
        (src / "labels_button" / f"{n}.txt").write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    return src


def _job(src, stretch):
    return {"id": "E0-button-s0", "group": "button", "입력": "늘리기640" if stretch else "원본768x1024",
            "stretch": stretch, "names": ["B1", "B2", "B3", "B4", "EMO"], "원본": str(src),
            "나눔": {"name": "place9_v1", "train": ["a__f00001"], "val": ["a__f00002"], "test": ["a__f00003"]}}


def _prep(args):
    T1.prepare_base(*args)


def test_바탕_폴더():
    print("[1] 바탕 폴더 — 늘리기 (가로, 세로) · .npy(학습·검증만) · 라벨(채점 = 8종)")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        b = T1.prepare_base(_job(src, [5, 3]), root)
        im = cv2.imread(str(b / "images" / "train" / "a__f00001.png"))
        check(im.shape == (3, 5, 3), f"늘리기 [5, 3] = 가로 5 · 세로 3 — {im.shape}")
        check((b / "images" / "train" / "a__f00001.npy").exists() and not (b / "images" / "test" / "a__f00003.npy").exists(), ".npy = 학습·검증만")
        check(np.array_equal(np.load(b / "images" / "val" / "a__f00002.npy"), cv2.imread(str(b / "images" / "val" / "a__f00002.png"))), ".npy = 그 사진 그대로(cache=disk 와 같음)")
        check((b / "labels" / "test" / "a__f00003.txt").read_text().startswith("5 "), "채점 라벨 = 8종")
        check((b / "labels" / "train" / "a__f00001.txt").read_text().startswith("0 "), "학습 라벨 = 무리 번호")
        check((b / ".완료").exists() and T1.prepare_base(_job(src, [5, 3]), root) == b, "완료 표지 · 두 번째는 그대로")
        b2 = T1.prepare_base(_job(src, None), root)
        check(os.stat(b2 / "images" / "train" / "a__f00001.png").st_ino == os.stat(src / "images" / "a__f00001.png").st_ino, "원본 입력 = 하드링크")


def test_동시_준비():
    print("[2] 동시 학습 둘이 같은 바탕 폴더를 처음 만든다 — 잠금으로 한 번만")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        ps = [mp.Process(target=_prep, args=((_job(src, [5, 3]), root),)) for _ in range(2)]
        [p.start() for p in ps]
        [p.join(30) for p in ps]
        check(all(p.exitcode == 0 for p in ps), f"두 프로세스 모두 정상 — {[p.exitcode for p in ps]}")
        b = root / "data" / "place9_v1_button_늘리기640"
        check((b / ".완료").exists() and len(list((b / "images" / "train").iterdir())) == 2, "완료 · 사진+npy 2개")


def test_실험_폴더():
    print("[3] 실험 폴더 — 하드링크 · data.yaml")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        b = T1.prepare_base(_job(src, [5, 3]), root)
        rd = root / "runs" / "E0-button-s0"
        y = T1.job_dataset(b, rd, _job(src, [5, 3]))
        check(os.stat(rd / "data" / "images" / "train" / "a__f00001.npy").st_ino == os.stat(b / "images" / "train" / "a__f00001.npy").st_ino, ".npy 하드링크")
        txt = y.read_text(encoding="utf-8")
        check(f"path: {rd / 'data'}" in txt and "  4: EMO" in txt and "test" not in txt, "data.yaml = 학습·검증만 · 무리 이름")


def test_종료_이유():
    print("[4] 종료 이유")
    check(T1.end_reason("포화", 40, 200) == "포화", "콜백 이유 우선")
    check(T1.end_reason(None, 200, 200) == "최대에폭", "최대 에폭")
    check(T1.end_reason(None, 57, 200) == "일찍멈춤", "일찍 멈춤")


if __name__ == "__main__":
    test_바탕_폴더()
    test_동시_준비()
    test_실험_폴더()
    test_종료_이유()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 실험 한 번 데이터 준비 검증 통과")
