"""hoi_metrics 단위 테스트 — 판정 규칙만 검증한다(DB 불필요·합성 데이터).

실행: python3 selftest/test_hoi_metrics.py   (cwd = Demo/)
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

from hoi_metrics import WINDOW_N, capability_hit, capability_rate


def test_window_length_is_five():
    assert WINDOW_N == 5


def test_hit_on_press_frame():
    """눌림 프레임 자체에서 보이면 성공."""
    series = {100: "B2"}
    assert capability_hit(series, 100, "B2") is True


def test_hit_at_window_edge():
    """창 경계(눌림−5)에서 보여도 성공."""
    series = {95: "B2"}
    assert capability_hit(series, 100, "B2") is True


def test_miss_just_outside_window():
    """창 밖(눌림−6)은 실패."""
    series = {94: "B2"}
    assert capability_hit(series, 100, "B2") is False


def test_miss_on_wrong_button():
    """옆 버튼만 보였으면 실패."""
    series = {98: "B1", 99: "B3", 100: "B1"}
    assert capability_hit(series, 100, "B2") is False


def test_miss_when_nothing_seen():
    series = {98: None, 99: None, 100: None}
    assert capability_hit(series, 100, "B2") is False


def test_single_frame_in_window_is_enough():
    """창 안에 한 프레임만 맞아도 성공 — '한 번이라도' 규칙."""
    series = {96: None, 97: "B2", 98: None, 99: None, 100: None}
    assert capability_hit(series, 100, "B2") is True


def test_custom_window_length():
    series = {91: "B2"}
    assert capability_hit(series, 100, "B2", n=5) is False
    assert capability_hit(series, 100, "B2", n=9) is True


def test_rate_counts_presses_not_frames():
    """분모는 눌림 수다. 창 안에 여러 프레임이 맞아도 1건으로 센다."""
    series = {98: "B1", 99: "B1", 100: "B1", 200: None}
    presses = [{"frame": 100, "button": "B1"}, {"frame": 200, "button": "B2"}]
    assert capability_rate(series, presses) == (1, 2)


def test_rate_empty_presses():
    assert capability_rate({}, []) == (0, 0)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
