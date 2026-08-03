"""서브 작업(대기·공구) 진행 관리 검증.

실행: python3 Demo/selftest/test_sub_task.py

정본: 상위 docs/superpowers/specs/2026-08-03-uiux-글라스-design.md §5·§6

⚠️ 시간을 인자로 주입하므로 **30초를 실제로 기다리지 않는다.** 실행이 1초 안에 끝난다.
"""

import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from sub_task import SubTask

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


WAIT = {"type": "wait", "sec": 30, "label": "플라즈마 클린 진행"}
TOOL = {"type": "wait_tool", "sec": 30, "label": "N2 퍼지",
        "tool": "spanner", "tools": ["spanner", "driver", "wrench"],
        "tool_names": {"spanner": "스패너", "driver": "드라이버", "wrench": "렌치"}}


def test_none_spec_advances_immediately():
    """서브 작업이 없는 단계(4단계)는 즉시 진행 가능."""
    print("\n[1] sub 없음")
    st = SubTask(None, now=0.0)
    check(st.can_advance, "spec=None → 즉시 can_advance")
    check(st.is_active is False, "is_active=False")


def test_wait_needs_time():
    """대기는 시간이 지나야 진행 가능."""
    print("\n[2] wait — 시간 경과")
    st = SubTask(WAIT, now=100.0)
    check(not st.can_advance, "시작 직후엔 불가")
    st.tick(now=115.0)
    check(not st.can_advance and st.elapsed_sec == 15.0, "15초 경과 — 아직 불가")
    check(abs(st.progress - 0.5) < 1e-9, f"진행률 {st.progress:.2f}")
    st.tick(now=130.0)
    check(st.can_advance, "30초 경과 — 가능")
    check(st.progress == 1.0, "진행률 1.0 상한")
    st.tick(now=200.0)
    check(st.progress == 1.0, "더 지나도 1.0을 넘지 않는다")


def test_wait_tool_needs_both():
    """🔴 (가)안 — 시간 경과 AND 공구 확인이라야 진행 가능."""
    print("\n[3] wait_tool — 시간 AND 공구")
    st = SubTask(TOOL, now=0.0)
    st.tick(now=30.0)
    check(not st.can_advance, "시간만 채움 → 불가")

    st2 = SubTask(TOOL, now=0.0)
    st2.set_tool("spanner")
    check(st2.tool_ok, "공구 확인됨")
    check(not st2.can_advance, "공구만 맞음(시간 미달) → 불가")

    st2.tick(now=30.0)
    check(st2.can_advance, "시간 + 공구 → 가능")


def test_wrong_tool_and_self_clear():
    """🔴 잘못된 공구는 경고, 올바른 것으로 바꾸면 스스로 풀린다(해제 버튼 없음)."""
    print("\n[4] 잘못된 공구")
    st = SubTask(TOOL, now=0.0)
    st.set_tool("driver")
    check(st.wrong_tool == "driver", f"wrong_tool = {st.wrong_tool}")
    check(not st.tool_ok, "tool_ok=False")
    check(st.wrong_tool_name == "드라이버", f"표시명 {st.wrong_tool_name}")

    st.tick(now=30.0)
    check(not st.can_advance, "시간을 다 채워도 공구가 틀리면 불가")

    st.set_tool("spanner")
    check(st.wrong_tool is None, "올바른 공구로 바꾸면 wrong_tool → None (스스로 해제)")
    check(st.can_advance, "이제 진행 가능")


def test_tool_removed():
    """공구를 다시 치우면 확인이 풀린다."""
    print("\n[5] 공구 치움")
    st = SubTask(TOOL, now=0.0)
    st.set_tool("spanner")
    st.tick(now=30.0)
    check(st.can_advance, "확인 상태")
    st.set_tool(None)
    check(not st.tool_ok and not st.can_advance, "치우면 다시 불가")
    check(st.wrong_tool is None, "없는 것은 '잘못된 공구'가 아니다")


def test_wait_type_has_no_tool_state():
    """wait 에는 공구 개념이 없다 — set_tool 을 불러도 판정이 흔들리지 않는다."""
    print("\n[6] wait 에 공구 무관")
    st = SubTask(WAIT, now=0.0)
    st.set_tool("hammer")
    st.tick(now=30.0)
    check(st.can_advance, "공구와 무관하게 시간만으로 진행")
    check(st.wrong_tool is None, "wrong_tool 없음")
    check(st.needs_tool is False, "needs_tool=False")


def test_display_fields():
    """화면이 쓰는 표시값."""
    print("\n[7] 표시값")
    st = SubTask(TOOL, now=0.0)
    st.tick(now=22.0)
    check(st.label == "N2 퍼지", f"label = {st.label}")
    check(st.total_sec == 30, f"total_sec = {st.total_sec}")
    check(st.elapsed_sec == 22.0, f"elapsed_sec = {st.elapsed_sec}")
    check(st.needs_tool is True, "needs_tool=True")
    check(st.want_tool_name == "스패너", f"want_tool_name = {st.want_tool_name}")


def test_real_clock_default():
    """now 를 안 주면 실시간을 쓴다 — 런타임 편의."""
    print("\n[8] 기본 시계")
    st = SubTask(WAIT)
    st.tick()
    check(st.elapsed_sec < 1.0, f"방금 만들었으므로 경과 {st.elapsed_sec:.3f}s")


if __name__ == "__main__":
    t0 = time.time()
    test_none_spec_advances_immediately()
    test_wait_needs_time()
    test_wait_tool_needs_both()
    test_wrong_tool_and_self_clear()
    test_tool_removed()
    test_wait_type_has_no_tool_state()
    test_display_fields()
    test_real_clock_default()

    elapsed = time.time() - t0
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    if elapsed > 1.0:
        print(f"❌ 느림 {elapsed:.1f}s — 실시간을 기다리고 있다(시간 주입이 안 됨)")
        sys.exit(1)
    print(f"✅ 서브 작업 검증 통과 ({elapsed:.3f}s)")
