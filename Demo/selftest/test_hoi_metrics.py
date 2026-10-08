"""hoi_metrics 단위 테스트 — 판정 규칙만 검증한다(DB 불필요·합성 데이터).

실행: python3 selftest/test_hoi_metrics.py   (cwd = Demo/)
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

from hoi_metrics import WINDOW_N, analyze_presses, capability_hit, capability_rate, segments


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


# ── analyze_presses · segments (2026-10-09 dwell_probe 에서 옮김 — 세기가 쓴다) ──
def test_press_ok_lead_from_run_start():
    """누른 순간 그 버튼 구역 → 선행시간 = 눌림 − 이어진 구간의 시작."""
    frames, times = [10, 11, 12, 13], [1.0, 1.1, 1.2, 1.3]
    series = [None, "B2", "B2", "B2"]
    (row,) = analyze_presses([(1.25, "B2", 12)], series, frames, times, 0.3)
    btn, fr, lead, seen, status, win = row
    assert (btn, fr, seen, status, win) == ("B2", 12, "B2", "OK", True)
    assert abs(lead - 0.15) < 1e-9


def test_press_roi_mismatch():
    frames, times = [10, 11, 12], [1.0, 1.1, 1.2]
    (row,) = analyze_presses([(1.25, "B2", 12)], [None, "B2", "B1"], frames, times, 0.3)
    assert row[2:5] == (None, "B1", "ROI 불일치")


def test_press_not_detected():
    frames, times = [10, 11, 12], [1.0, 1.1, 1.2]
    (row,) = analyze_presses([(1.25, "B2", 12)], ["B2", None, None], frames, times, 0.3)
    assert row[2:5] == (None, None, "미검출")
    assert row[5] is True          # 창(능력 상한)은 10 프레임의 B2 를 본다


def test_press_before_first_frame():
    (row,) = analyze_presses([(0.5, "B2", 9)], ["B2"], [10], [1.0], 0.3)
    assert row[2:5] == (None, None, "프레임 없음")


def test_press_window_uses_raw_series():
    """창은 갭메우기 전(raw_series)으로 잰다 — 메운 구간만 맞으면 창은 실패."""
    frames, times = [10, 11, 12], [1.0, 1.1, 1.2]
    filled, raw = ["B2", "B2", "B2"], [None, None, None]
    (row,) = analyze_presses([(1.25, "B2", 12)], filled, frames, times, 0.3, raw_series=raw)
    assert row[4] == "OK" and row[5] is False


def test_segments_split_by_roi():
    series = [None, "B1", "B1", None, "B2", "B3"]
    frames = [1, 2, 3, 4, 5, 6]
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    segs = segments(series, frames, times)
    assert [(r, a, b) for r, a, b, _ in segs] == [("B1", 2, 3), ("B2", 5, 5), ("B3", 6, 6)]
    assert abs(segs[0][3] - 0.1) < 1e-9 and segs[1][3] == 0.0   # 첫 관측 → 마지막 관측


def test_segments_empty():
    assert segments([None, None], [1, 2], [0.0, 0.1]) == []


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
