"""점검(1차·2차·수동) 검증 — Qt 없이 돈다.

실행: python3 Demo/selftest/test_precheck.py
정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §4.2
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import precheck
from precheck import run_stage1, run_stage2, summary, STAGE1_ITEMS, STAGE2_ITEMS

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class FakeHand:
    def __init__(self, available=True, raises=False):
        self.available = available
        self.reason = "" if available else "모델/소스 없음"
        self._raises = raises
        self.calls = 0

    def detect(self, frame, draw_on=None):
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        return None                     # 손 없음 — 정상적인 답이다


def ctx(**kw):
    base = dict(camera_thread=None, detector_available=False, hand_tracker=None,
                interlock=None, gpio_input=None, last_frame_time=0.0,
                seen_buttons=(), last_frame=None)
    base.update(kw)
    return base


def test_stage_items():
    print("\n[1] 항목 구성")
    r1 = run_stage1(ctx())
    r2 = run_stage2(ctx())
    check(tuple(r.key for r in r1) == STAGE1_ITEMS, f"1차 {[r.key for r in r1]}")
    check(tuple(r.key for r in r2) == STAGE2_ITEMS, f"2차 {[r.key for r in r2]}")


def test_no_stage_words_in_names():
    """🔴 화면 문구에 '1차'·'2차'가 없어야 한다 — 차수는 내부 구분이다."""
    print("\n[2] 차수 표기 없음")
    names = [r.name for r in run_stage1(ctx()) + run_stage2(ctx())]
    bad = [n for n in names if "1차" in n or "2차" in n]
    check(not bad, f"항목 이름에 차수 없음 (검출: {bad or '없음'})")


def test_buttons_exclude_emo():
    """🔴 버튼 검출은 B1~B4 4개만 센다 — EMO 는 실콘솔에서 화각 밖이다."""
    print("\n[3] EMO 제외")
    r = next(x for x in run_stage2(ctx(seen_buttons={"B1", "B2", "B3", "B4"})) if x.key == "buttons")
    check(r.ok, f"B1~B4 만으로 통과: {r.detail}")

    r2 = next(x for x in run_stage2(ctx(seen_buttons={"B1", "B2", "B3", "EMO"})) if x.key == "buttons")
    check(not r2.ok, f"EMO 가 있어도 B4 가 없으면 실패: {r2.detail}")

    r3 = next(x for x in run_stage2(ctx(seen_buttons={"B1", "B2", "B3", "B4", "EMO"})) if x.key == "buttons")
    check(r3.ok and "4/4" in r3.detail, f"EMO 는 세지 않는다: {r3.detail}")


def test_hand_loose_pass():
    """손 검출은 '추론이 돌기만 하면 통과'(느슨). 손이 없어도 OK."""
    print("\n[4] 손 검출 느슨 판정")
    h = FakeHand()
    r = next(x for x in run_stage2(ctx(hand_tracker=h, last_frame=object())) if x.key == "hand_infer")
    check(r.ok, f"손 없음(None)인데 통과: {r.detail}")
    check(h.calls == 1, "프레임 하나로 실제 추론을 돌린다")


def test_hand_fails_on_exception():
    """추론이 터지면 실패로 잡는다 — 이게 이 점검의 존재 이유다."""
    print("\n[5] 손 검출 예외 감지")
    h = FakeHand(raises=True)
    r = next(x for x in run_stage2(ctx(hand_tracker=h, last_frame=object())) if x.key == "hand_infer")
    check(not r.ok and "실패" in r.detail, f"예외를 잡는다: {r.detail}")

    h2 = FakeHand(available=False)
    r2 = next(x for x in run_stage2(ctx(hand_tracker=h2, last_frame=object())) if x.key == "hand_infer")
    check(not r2.ok, f"모델 비활성도 잡는다: {r2.detail}")


def test_stream_freshness():
    """영상 수신은 '연결됐나'가 아니라 '최근 프레임이 왔나'를 본다."""
    print("\n[6] 영상 신선도")
    import time
    now = time.time()
    fresh = next(x for x in run_stage2(ctx(last_frame_time=now - 0.5), now=now) if x.key == "stream")
    stale = next(x for x in run_stage2(ctx(last_frame_time=now - 30), now=now) if x.key == "stream")
    check(fresh.ok, f"0.5초 전 → 통과 ({fresh.detail})")
    check(not stale.ok, f"30초 전 → 실패 ({stale.detail})")


def test_retryable_flags():
    """수동 점검에서 「재연결」을 붙일 항목이 표시되는가."""
    print("\n[7] 재시도 가능 표시")
    r1 = {r.key: r.retryable for r in run_stage1(ctx())}
    check(r1["camera"] and r1["interlock"], "카메라·인터락은 재연결 가능")
    check(not r1["hand"], "손 모델은 재연결 대상이 아니다(파일 문제)")


def test_summary():
    print("\n[8] 요약")
    ok, text = summary(run_stage1(ctx()))
    check(not ok and text == "0/5", f"전부 실패 → {text}")
    ok2, text2 = summary(run_stage1(ctx(
        camera_thread=type("C", (), {"sock": object(), "gave_up": False})(),
        detector_available=True, hand_tracker=FakeHand(),
        interlock=type("I", (), {"connected": True})(),
        gpio_input=type("G", (), {"available": True})())))
    check(ok2 and text2 == "5/5", f"전부 통과 → {text2}")


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 점검 검증 통과")
