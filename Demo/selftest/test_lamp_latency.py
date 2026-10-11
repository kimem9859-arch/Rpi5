"""램프 지연 도구 — 램프 자리 찾기 · 첫 바뀐 장 · 요약 · 가짜 장치로 끝까지(학교 방문 준비 설계 §6).

실행: python3 Demo/selftest/test_lamp_latency.py
"""
import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import cv2
import numpy as np

import lamp_latency as LL
from fake_camera import FakeCamera
from fake_interlock import FakeInterlock

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_find_spot():
    print("\n[자리] 켬 평균 − 끔 평균이 가장 큰 덩어리 · 차이가 없으면 None(→ --screen)")
    off = [np.full((120, 160), 60, np.uint8) for _ in range(3)]
    on = [o.copy() for o in off]
    for o in on:
        o[50:90, 50:90] = 255
    sp = LL.find_spot(on, off)
    check(sp is not None and 50 <= sp[0] < 90 and 50 <= sp[1] < 90, f"자리 {sp}")
    check(LL.find_spot(off, off) is None, "차이 없음 → None")


def test_first_cross():
    print("\n[첫 장] 명령 뒤 가운데 수준을 처음 넘는 장의 받은 시각")
    fr = [(0, 10), (50, 10), (100, 10), (150, 200), (200, 200)]
    check(LL.first_cross(fr, 60, 105, True) == 150, "켜짐 → 150")
    check(LL.first_cross(fr, 160, 105, False) is None, "꺼짐이 없으면 None")
    check(LL.first_cross(fr, 60, 105, True, until=140) is None, "다음 명령 전까지만")


def test_summarize():
    print("\n[요약] 중앙값 · 90% · 최소 · 최대")
    s = LL.summarize([80, 90, 100, 110, 300])
    check(s["n"] == 5 and s["med"] == 100 and s["max"] == 300 and s["min"] == 80, f"{s}")
    check(LL.summarize([])["n"] == 0, "빈 목록")


def _rig(react=True):
    img = cv2.imencode(".jpg", np.full((240, 320, 3), 60, np.uint8))[1].tobytes()
    cam = FakeCamera([img], port=0, fps=40, mimic=True).start()
    fi = FakeInterlock(on_cmd=(lambda c, t: cam.lamp(c == "WARN", 0.08)) if react else None).start()
    return cam, fi


def test_end_to_end():
    print("\n[끝까지] 가짜 카메라(램프 흉내 지연 0.08초) + 가짜 인터락 → 지연 중앙값 80~135ms")
    cam, fi = _rig()
    try:
        r = LL.run("127.0.0.1", cam.port, fi.port, n_find=4, n_meas=6, interval=0.5, settle_s=0.0)
    finally:
        cam.stop()
        fi.stop()
    check("error" not in r, f"오류 없음 {r.get('error')}")
    check(r.get("n") == 6 and r.get("med") is not None and 80 <= r["med"] <= 135, f"n {r.get('n')} · 중앙값 {r.get('med')}")
    check(r.get("ack_med") is not None and r["ack_med"] < 50, f"ACK {r.get('ack_med')}ms")
    check("상한" in r.get("note", ""), "결과에 「상한 값」 표시")


def test_spot_missing():
    print("\n[실패] 램프가 영상에 안 보이면 오류 + --screen 안내(V11)")
    cam, fi = _rig(react=False)
    try:
        r = LL.run("127.0.0.1", cam.port, fi.port, n_find=4, n_meas=2, interval=0.4, settle_s=0.0)
    finally:
        cam.stop()
        fi.stop()
    check("--screen" in r.get("error", "") and "V11" in r.get("error", ""), f"{r.get('error')}")


def test_scene_moves_no_lamp():
    print("\n[헛자리] 램프가 안 보이고 장면만 바뀌면 값을 내지 않고 오류(V11) — 리허설이 찾은 허점(엉터리 23ms)")
    import glob
    src = os.path.expanduser("~/lab/화면검사/20261011_②B_전")
    if not glob.glob(os.path.join(src, "f*.jpg")):
        print("  ⏭ 원본 없음 — 건너뜀")
        return
    from fake_camera import load_frames
    cam = FakeCamera(load_frames(src, 200), port=0, fps=19.5).start()
    fi = FakeInterlock().start()
    try:
        r = LL.run("127.0.0.1", cam.port, fi.port, n_find=6, n_meas=2, interval=0.6, settle_s=0.0)
    finally:
        cam.stop()
        fi.stop()
    check("error" in r and "V11" in r["error"], f"{r.get('error') or {k: r.get(k) for k in ('med', 'n')}}")


if __name__ == "__main__":
    test_find_spot()
    test_first_cross()
    test_summarize()
    test_end_to_end()
    test_spot_missing()
    test_scene_moves_no_lamp()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 램프 지연 도구 검증 통과")
