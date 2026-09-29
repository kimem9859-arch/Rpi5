"""gate_button — 버튼 관문의 셈(초벌 + 기계 검토 → 회수 집계 잣대)을 합성 사진으로 고정한다.

실행: python3 Demo/selftest/test_gate_button.py
정본 설계: ../../docs/superpowers/specs/2026-09-29-버튼초벌-반복학습-design.md §7
⚠️ Hailo·모델이 필요 없다 — 초벌은 미리 그린 JSON 흉내(label_review.lookup_run)로 넣는다. 합성 판은 test_label_review 것을 쓴다.
"""
import json
import os
import sys
import tempfile

import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test")); sys.path.insert(0, _DEMO_DIR); sys.path.insert(0, _HERE)

import gate_button as G
import label_review as R
from test_label_review import POS, RAD, loose, panel

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _rows(pos=None):
    """초벌 = 조금 느슨한 박스(test_label_review 와 같다)."""
    pos = pos or {}
    return [[n, 0.9, *loose(n, pos.get(n))] for n in POS]


def _fin(pos=None):
    """사용자 최종 = 버튼에 딱 맞는 박스 — 맞춘 박스(기계 확정)와도, 느슨한 박스(맞추기 실패 시)와도 IoU 0.5 를 넉넉히 넘는다."""
    pos = pos or {}
    out = []
    for n in POS:
        cx, cy = pos.get(n) or POS[n]; r = RAD[n]
        out.append({"label": n, "box": [cx - r, cy - r, cx + r, cy + r]})
    return out


def test_셈():
    print("[1] 깨끗한 사진 = 기계 확정 5 · 장갑 사진 = 6개 모두 사람에게 · 장갑 박스는 가짜(지움) → 사람 몫 6 · 가짜 1 · 기계 확정 틀림 0")
    tpl = [panel() for _ in range(3)]
    glove = (640, 950); jit = {"B1": (3, -2), "B3": (-2, 3), "EMO": (2, 2)}   # test_label_review [7] 과 같은 장면
    moved = {n: (POS[n][0] + jit.get(n, (0, 0))[0], POS[n][1] + jit.get(n, (0, 0))[1]) for n in POS}
    clean, gl = panel(), panel(extra=(glove, 28, (235, 235, 235)), jitter=jit)
    run = R.lookup_run([(tpl[0], _rows()), (clean, _rows()), (gl, _rows(moved) + [["B2", 0.7, *loose("B2", glove)]])])
    c = G.evaluate(run, False, tpl, [(clean, _fin()), (gl, _fin(moved))])
    check(c == {"work": 6, "check": 6, "propose": 0, "added": 0, "fake": 1, "auto_wrong": 0}, f"{c}")


def test_기계_확정_틀림():
    print("[2] 🔴 사용자 최종 이름과 다른 기계 확정 박스 = 기계 확정 틀림(관문 거부 사유) · 최종에만 있는 버튼 = 새로 그림(사람 몫)")
    tpl = [panel() for _ in range(3)]
    clean = panel()
    run = R.lookup_run([(tpl[0], _rows()), (clean, _rows())])
    fin = [{"label": ("EMO" if f["label"] == "B3" else f["label"]), "box": f["box"]} for f in _fin()] + [{"label": "B4", "box": [10, 10, 60, 60]}]
    c = G.evaluate(run, False, tpl, [(clean, fin)])
    check(c["auto_wrong"] == 1 and c["added"] == 1 and c["work"] == 1, f"{c}")


def test_JSON_초벌():
    print("[3] 🔴 JSON 초벌은 경로 열쇠로 — 파일에서 다시 읽은 사진을 찾는다 · JSON 에 없는 경로가 있으면 KeyError(조용히 빈 초벌 금지)")
    with tempfile.TemporaryDirectory() as d:
        pa, pb = os.path.join(d, "f00001.png"), os.path.join(d, "f00002.png")
        cv2.imwrite(pa, panel()); cv2.imwrite(pb, panel(names=("B1",)))
        j = os.path.join(d, "dets.json")
        json.dump({pa: _rows(), pb: _rows()[:1]}, open(j, "w"))
        run = G.json_run(j, [pa, pb])
        check(len(run(cv2.imread(pa))) == 5 and len(run(cv2.imread(pb))) == 1, "다시 읽은 사진 = 그 초벌")
        try:
            G.json_run(j, [pa, os.path.join(d, "f00003.png")]); raised = False
        except KeyError:
            raised = True
        check(raised, "JSON 에 없는 경로 = KeyError")


if __name__ == "__main__":
    test_셈()
    test_기계_확정_틀림()
    test_JSON_초벌()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 버튼 관문 셈 검증 통과")
