"""데이터셋 촬영 도구(capture_dataset)의 장소2·3 촬영 준비 수정을 고정한다.

실행: python3 Demo/selftest/test_capture_dataset.py
근거: 2026-10-01 시운전 — 화면 글씨가 한글을 못 그려 장면을 못 고름 · 저장 간격 0.2초가 실제 0.27초 ·
      session.json 의 크기·단계 수가 장소1 기록(bench_detector manifest)과 뜻이 달랐다.
⚠️ 카메라·Hailo 가 필요 없다(합성 사진).
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))
sys.path.insert(0, _DEMO_DIR)

import capture_dataset as CD

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_한글_안내띠():
    print("[1] 🔴 안내 띠가 한글을 그린다 — cv2.putText 는 「가」「나」를 똑같이 ??? 로 찍는다")
    base = np.full((1024, 768, 3), 90, np.uint8)
    a, b = base.copy(), base.copy()
    CD.draw_banner(a, "가", "space 녹화")
    CD.draw_banner(b, "나", "space 녹화")
    check(not np.array_equal(a, b), "「가」와 「나」의 그림이 다르다")
    check(np.array_equal(a[CD.BANNER_H:], base[CD.BANNER_H:]), "띠 아래 화면은 건드리지 않는다")


def test_저장_간격():
    print("[2] 🔴 저장 간격이 설정값 그대로 — 22fps 로 10초 받으면 0.2초 간격은 50장")
    with tempfile.TemporaryDirectory() as d:
        s = CD.Session(Path(d), "장소2", "7 쥔공구", 0.2, {})
        s.save = lambda _img: None            # 디스크 쓰기는 이 시험의 대상이 아니다
        t0 = 1_000_000.0
        n = sum(s.maybe_save(None, t0 + i / 22) for i in range(220))
        check(49 <= n <= 51, f"저장 {n}장(기대 50±1)")


def test_장소3_따로():
    print("[3] 🔴 장소3(시험 전용)은 다른 폴더 — 학습 묶음에 섞이지 않게")
    root = Path("/x/capture")
    check(CD.out_root(str(root), "장소3") == Path("/x/capture_장소3"), "장소3 → /x/capture_장소3")
    check(CD.out_root(str(root), "장소2") == root, "장소2 → /x/capture 그대로")
    try:
        r = CD.out_root(".", "장소3")
        check(r.name.endswith("_장소3") and r.is_absolute(), f"--out . 도 형제 폴더({r})")
    except ValueError as e:
        check(False, f"--out . 에서 오류: {e}")


def test_촬영_조건_기록():
    print("[4] 🔴 조건 기록이 장소1(bench_detector manifest)과 같은 이름·같은 뜻 — 크기는 센서 원본")
    m = CD.orient_meta(1024, 768, "/a/camera_calibration_1024x768.npz")
    check(m.get("frame_size") == "1024x768", f"frame_size = 회전 전 1024x768 ({m.get('frame_size')})")
    check(m.get("undistort") is True and m.get("calibration_file") == "camera_calibration_1024x768.npz",
          "보정 파일 이름")
    check(m.get("flip_mode") in ("v", "none") and isinstance(m.get("rotate_ccw90"), bool), "뒤집기·회전")
    n = CD.orient_meta(1024, 768, None)
    check(n["undistort"] is False and n["calibration_file"] is None, "보정 없으면 False·None")


def test_세션별_단계수():
    print("[5] session.json 의 단계 수는 그 녹화 동안만 센다(도구를 켠 뒤 누적이 아니다)")
    with tempfile.TemporaryDirectory() as d:
        live = {"recv": 100, "saved": 0}
        s = CD.Session(Path(d), "장소2", "2 버튼누르기", 0.2, {}, stages0=live)
        live["recv"] = 160; live["saved"] = 12          # 도구는 같은 dict 를 계속 늘린다 — 복사해 둬야 한다
        s.close(live)
        meta = json.loads((s.dir / "session.json").read_text(encoding="utf-8"))
        check(meta["stages"] == {"recv": 60, "saved": 12}, f"stages = {meta['stages']}")


def test_장면_목록():
    print("[6] 장면 — 0 정지(묶음 기준 사진) 추가 · 5 빛반사 제외(조명 없음, 사용자 2026-10-01)")
    nums = [s.split()[0] for s in CD.SCENES]
    check(nums == ["0", "1", "2", "3", "4", "6", "7", "8"], f"장면 번호 {nums}")


def test_장소_필수():
    print("[7] 🔴 --place 없이 촬영을 시작하지 않는다 — 켜면 장소1 로 시작하던 함정")
    def _never(_a):                                       # 회귀가 나도 실제 카메라에 붙지 않게
        raise AssertionError("--place 없이 촬영·세기로 들어갔다")
    saved = CD.run, CD.run_count
    CD.run, CD.run_count = _never, _never
    try:
        with contextlib.redirect_stderr(io.StringIO()):   # argparse 안내문이 결과를 어지럽히지 않게
            CD.main([])
        check(False, "멈추지 않았다")
    except SystemExit as e:
        check(e.code == 2, f"인자 오류로 멈춘다(code {e.code})")
    except AssertionError as e:
        check(False, str(e))
    finally:
        CD.run, CD.run_count = saved


def _noise(seed):
    """회색 잡음 — 씨앗이 다르면 pHash 거리 약 30(중복 아님), 회색이라 깨짐(색조 이음매) 0.
    ⚠️ 가로·세로 그러데이션은 pHash 거리가 4 라 중복으로 묶인다(2026-10-01 시험 재료 실수)."""
    g = np.random.default_rng(seed).integers(30, 180, (1024, 768), dtype=np.uint8)
    return cv2.merge([g, g, g])


def _seam():
    """왼쪽 빨강·오른쪽 초록 — 색조 이음매가 커서 깨진 프레임으로 걸러져야 한다."""
    img = np.zeros((1024, 768, 3), np.uint8)
    img[:, :384] = (0, 0, 200); img[:, 384:] = (0, 200, 0)
    return img


def test_장수_세기():
    print("[8] 🔴 현장 장수 세기 — 묶음 도구와 같은 거름(깨짐·검은 화면·중복) · 장소 전체 합쳐 · 목표 대비")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        s6 = root / "20261005_095000_장소3_6"; s7 = root / "20261005_100000_장소3_7"
        s8 = root / "20261005_101000_장소3_8"; other = root / "20261005_102000_장소2_7"
        for p in (s6, s7, s8, other):
            p.mkdir()
        cv2.imwrite(str(s6 / "f00001.png"), _noise(2)); cv2.imwrite(str(s6 / "f00002.png"), _noise(4))
        for i, img in enumerate([_noise(1), _noise(1), _noise(1), _noise(2), _seam()], 1):
            cv2.imwrite(str(s7 / f"f{i:05d}.png"), img)
        cv2.imwrite(str(s8 / "f00001.png"), np.zeros((1024, 768, 3), np.uint8))
        ok, buf = cv2.imencode(".png", _noise(5))
        (s8 / "f00002.png").write_bytes(buf.tobytes()[:200])    # 쓰다 만 파일(전원 차단 등)
        cv2.imwrite(str(other / "f00001.png"), _noise(3))
        r = CD.count_place(root, "장소3", workers=1)
        check(r["sessions"] == 3, f"장소3 세션 3개({r.get('sessions')})")
        check(r["scenes"]["6"] == {"saved": 2, "unique": 2}, f"장면 6 {r['scenes']['6']}")
        check(r["scenes"]["7"] == {"saved": 5, "unique": 1},
              f"장면 7 — 같은 장면 중복·장면 6 과 겹친 사진·깨진 사진을 뺀다 {r['scenes']['7']}")
        check(r["scenes"]["8"] == {"saved": 2, "unique": 0}, f"장면 8 — 검은 화면·쓰다 만 파일 {r['scenes']['8']}")
        check(sum(v["saved"] for v in r["scenes"].values()) == 9, "다른 장소 세션은 세지 않는다")
        c67 = next(c for c in r["checks"] if c["scenes"] == "6+7")
        check(c67["have"] == 3 and c67["need"] == CD.MIN_KEEP["장소3"]["6+7"] and not c67["ok"], f"공구 합산 {c67}")


def test_저장_실패():
    print("[9] 🔴 저장이 실패하면 장수만 오르지 않고 멈춘다 — 디스크가 차도 cv2.imwrite 는 False 만 돌려준다")
    with tempfile.TemporaryDirectory() as d:
        s = CD.Session(Path(d), "장소2", "7 쥔공구", 0.2, {})
        s.dir.rmdir()                                   # 쓸 수 없는 자리 = 저장 실패
        try:
            s.save(_noise(1))
            check(False, "예외 없이 지나갔다")
        except OSError:
            check(s.n == 0, f"실패한 장은 세지 않는다(n={s.n})")


def test_같은_초_두_녹화():
    print("[10] 같은 초에 정지→다시 시작해도 앞 녹화를 덮어쓰지 않는다 · 장면 번호는 폴더 끝 그대로")
    with tempfile.TemporaryDirectory() as d:
        a = CD.Session(Path(d), "장소2", "7 쥔공구", 0.2, {})
        b = CD.Session(Path(d), "장소2", "7 쥔공구", 0.2, {})
        check(a.dir != b.dir, f"{a.dir.name} ≠ {b.dir.name}")
        check(b.dir.name.rsplit("_", 1)[1] == "7" and b.dir.name.split("_")[2] == "장소2", f"이름 {b.dir.name}")


def test_세션_없음():
    print("[11] 세션이 하나도 없으면 「모자람」이 아니라 「경로 확인」으로 끝낸다")
    import argparse
    with tempfile.TemporaryDirectory() as d:
        r = CD.count_place(Path(d), "장소2", workers=1)
        check(r["sessions"] == 0, "세션 0개")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = CD.run_count(argparse.Namespace(out=d, place="장소2"))
        check(code == 2 and "세션 없음" in out.getvalue(), f"종료 코드 {code}")


if __name__ == "__main__":
    test_한글_안내띠()
    test_저장_간격()
    test_장소3_따로()
    test_촬영_조건_기록()
    test_세션별_단계수()
    test_장면_목록()
    test_장소_필수()
    test_장수_세기()
    test_저장_실패()
    test_같은_초_두_녹화()
    test_세션_없음()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 데이터셋 촬영 도구 검증 통과")
