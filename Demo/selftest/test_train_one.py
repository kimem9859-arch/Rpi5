"""실험 한 번(학습/train_one.py)의 데이터 준비를 고정한다 — 늘리기·원본 · .npy · 라벨 · 동시 준비 잠금 · 실험 폴더 하드링크 · 종료 이유.

실행: python3 Demo/selftest/test_train_one.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §5 · §7
⚠️ ultralytics·GPU 가 필요 없다(학습·채점은 Task 12·13 데스크톱 실제 실행에서 확인).
"""
import fcntl
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import time
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
    print("[2-b] 다른 프로세스가 잠금을 쥐고 있으면 풀릴 때까지 만들지 않는다(사진 몇 장으로는 경쟁이 안 생겨 [2] 만으로는 잠금을 못 지킨다 · 최종 리뷰 I4)")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        b = root / "data" / "place9_v1_button_늘리기640"
        b.parent.mkdir(parents=True)
        lk = open(f"{b}.lock", "w")
        fcntl.flock(lk, fcntl.LOCK_EX)
        p = mp.Process(target=_prep, args=((_job(src, [5, 3]), root),))
        p.start()
        time.sleep(1.0)
        early = (b / ".완료").exists()
        fcntl.flock(lk, fcntl.LOCK_UN)
        lk.close()
        p.join(30)
        check(not early and p.exitcode == 0 and (b / ".완료").exists(), f"잠금 동안 안 만듦 · 풀린 뒤 완료 — 일찍 만듦 {early} · 종료 {p.exitcode}")


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


def test_고정_메모리_끄기():
    print("[5] 고정 메모리 끄기 — 학습·검증 데이터로더 모두 pin_memory=False(WSL 한도 · 2026-10-03 속도 측정)")
    import types
    seen = []

    def fake(*a, **k):
        seen.append(k.get("pin_memory", "기본 True"))
        return "loader"

    b, t, v = (types.SimpleNamespace(build_dataloader=fake) for _ in range(3))
    T1.no_pin_memory([b, t, v, types.SimpleNamespace()])
    t.build_dataloader("ds", batch=16, workers=2, shuffle=True, rank=-1)                      # 학습 — 안 넘김(기본 True)
    v.build_dataloader("ds", 32, 4, shuffle=False, rank=-1, drop_last=False, pin_memory=True)  # 검증 — 학습 중엔 True
    check(seen == [False, False], f"둘 다 False — {seen}")
    T1.no_pin_memory([t])
    check(t.build_dataloader("ds") == "loader" and seen[-1] is False and len(seen) == 3, "두 번 감싸지 않음 · 반환값 그대로")


def test_덜_만든_바탕():
    print("[2-c] 완료 표지 없이 남은 바탕 폴더(만들다 죽음)는 지우고 다시 만든다 · 완료 표지에 라벨 지문(최종 리뷰 M3 · M4)")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        b = root / "data" / "place9_v1_button_늘리기640"
        (b / "images" / "train").mkdir(parents=True)
        (b / "images" / "train" / "a__f00001.png").write_bytes(b"\x89PNG broken")
        T1.prepare_base(_job(src, [5, 3]), root)
        im = cv2.imread(str(b / "images" / "train" / "a__f00001.png"))
        check(im is not None and im.shape[:2] == (3, 5), f"잘린 사진을 다시 만듦 — {None if im is None else im.shape}")
        fp = json.loads((b / ".완료").read_text(encoding="utf-8")).get("라벨지문")
        check(bool(fp) and fp == T1.label_fingerprint(b), f"완료 표지의 라벨 지문 = 바탕 라벨로 다시 잰 값 — {fp}")
    print("[2-d] 원본 라벨이 바뀐 뒤 옛 바탕을 쓰려 하면 멈춘다(다시 만들지 않는다 — 도는 실험이 그 바탕으로 채점) · 옛 표지 바탕도 지문(최종 리뷰 M4 보강)")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        b = T1.prepare_base(_job(src, [5, 3]), root)
        check(T1.prepare_base(_job(src, [5, 3]), root) == b, "원본 그대로면 그 바탕을 쓴다")
        (b / ".완료").write_text("2026-10-03 12:00:00", encoding="utf-8")      # 옛 형식 표지
        check(T1.prepare_base(_job(src, [5, 3]), root) == b and bool(T1.label_fingerprint(b)), "옛 형식 표지도 받아들이고 지문은 바탕에서 잰다")
        (src / "labels_button" / "a__f00001.txt").write_text("1 0.5 0.5 0.1 0.1\n", encoding="utf-8")
        try:
            T1.prepare_base(_job(src, [5, 3]), root)
            stopped = ""
        except RuntimeError as e:
            stopped = str(e)
        check("원본과 다르다" in stopped and (b / "labels" / "train" / "a__f00001.txt").read_text().startswith("0 "),
              f"원본 라벨이 바뀌면 멈추고 바탕은 그대로 둔다 — {stopped[:60]}")


def test_검증_라벨():
    print("[2-e] 검증 몫 8종 라벨 — 바탕에 labels8_val · 옛 바탕은 다시 만들지 않고 보탬(Review Focus 3)")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        b = T1.prepare_base(_job(src, [5, 3]), root)
        lv = b / "labels8_val" / "a__f00002.txt"
        check(lv.exists() and lv.read_text().startswith("5 "), "검증 몫 = 8종 라벨")
        shutil.rmtree(b / "labels8_val")
        mark = (b / ".완료").read_text(encoding="utf-8")
        T1.prepare_base(_job(src, [5, 3]), root)
        check(lv.exists() and (b / ".완료").read_text(encoding="utf-8") == mark, "옛 바탕 = 보태기만(완료 표지 그대로)")


def test_흐림_목록():
    print("[2-f] 흐림 목록 → 학습에 넘길 변환 이름 · 없으면 빈 목록(기본 변환 끔) · 설치 뒤엔 모든 실험이 명시 목록을 넘김")
    check(T1.album_names(["Blur", "MotionBlur"]) == ["Blur", "MotionBlur"] and T1.album_names(None) == [], "목록 · 빈 목록")
    check(T1.album_kwargs({}, installed=False) == {}, "albumentations 없음 → 넘기지 않음(1단계와 같음)")
    check(T1.album_kwargs({}, installed=True) == {"augmentations": []}, "설치됨 · 흐림 없음 → 빈 목록(기본 묶음의 ToGray 가 끼어들지 않게)")


def test_세션_바탕():
    print("[b-s] 바탕 — 세션 보류 몫은 images/test_session 에만(8종 라벨 · .npy 없음) · 학습·검증 몫에 없음 · 지문이 그 몫까지(1-3 Review Focus 1·2)")
    with tempfile.TemporaryDirectory() as t:
        src, root = _src(t), Path(t) / "루트"
        cv2.imwrite(str(src / "images" / "b__f00001.png"), np.full((8, 6, 3), 100, np.uint8))
        (src / "labels8" / "b__f00001.txt").write_text("4 0.5 0.5 0.1 0.1\n", encoding="utf-8")
        (src / "labels_button" / "b__f00001.txt").write_text("4 0.5 0.5 0.1 0.1\n", encoding="utf-8")
        job = _job(src, [5, 3])
        job["나눔"]["name"], job["나눔"]["test_session"] = "place9_v2b", ["b__f00001"]
        b = T1.prepare_base(job, root)
        check((b / "images" / "test_session" / "b__f00001.png").exists()
              and (b / "labels" / "test_session" / "b__f00001.txt").read_text().startswith("4 "), "세션 몫 = 사진 + 8종 라벨")
        check(not (b / "images" / "test_session" / "b__f00001.npy").exists(), "세션 몫 .npy 없음")
        check(not any(p.name.startswith("b__") for part in ("train", "val") for p in (b / "images" / part).iterdir()), "학습·검증 몫에 세션 사진 없음")
        check(T1.source_fingerprint(job) == T1.label_fingerprint(b), "라벨 지문 = 원본(세션 몫 포함)")
        check(T1.prepare_base(_job(src, [5, 3]), root) != b, "옛 판(세션 몫 없음)은 다른 바탕 폴더")


if __name__ == "__main__":
    test_바탕_폴더()
    test_동시_준비()
    test_덜_만든_바탕()
    test_검증_라벨()
    test_실험_폴더()
    test_종료_이유()
    test_고정_메모리_끄기()
    test_흐림_목록()
    test_세션_바탕()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 실험 한 번 데이터 준비 검증 통과")
