"""공구 판정 상태기계(A-2) 검증.

실행: python3 Demo/selftest/test_tool_state.py

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §4.3·§4.4

⚠️ 검출 결과·손끝 좌표를 **인자로 주입**하므로 카메라·Qt·모델이 필요 없다.
   실행이 1초 안에 끝난다.
"""

import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from tool_state import ToolState

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


# 검출 1건 = (클래스명, 점수, x1, y1, x2, y2). 임계는 이미 걸러진 것으로 본다.
BOX_W = ("wrench", 0.80, 100, 100, 200, 200)   # 요구 공구
BOX_D = ("driver", 0.75, 300, 100, 400, 200)   # 다른 공구
BOX_P = ("pliers", 0.90, 500, 100, 600, 200)   # 점수가 가장 높은 제3의 공구
IN_W = (150, 150)    # 렌치 박스 안
IN_D = (350, 150)    # 드라이버 박스 안
OUT = (900, 900)     # 아무 박스도 아님
ALL3 = [BOX_W, BOX_D, BOX_P]


# ------------------------------------------------------- ① 전제 — 쥐기 전
def test_안쥐면_완료_안됨():
    """🔴 이 전제가 없으면 작업 시작 직후 바로 완료된다.

    아직 공구를 찾지도 않았을 때도 「손 보임 + 공구 안 보임」이기 때문이다.
    """
    print("[1] 쥐기 전에는 완료되지 않는다")
    st = ToolState("wrench", placed_count=3)
    out = None
    for _ in range(10):
        out = st.update([], IN_W)          # 손 보임 + 공구 없음
    check(st.phase == "search", "10회 반복해도 search 유지")
    check(out is None, "완료 값이 나오지 않는다")
    check(st.miss_count == 0, "search 에서는 세지 않는다")


# ------------------------------------------------------- ② 정상 경로
def test_정답쥐고_넣으면_완료():
    print("[2] 정답을 쥐고 넣으면 완료")
    st = ToolState("wrench", placed_count=3)
    check(st.update([BOX_W], IN_W) is None, "정답을 쥐면 경고 없음(None)")
    check(st.phase == "grasped", "쥠 확정")
    check(st.update([], IN_W) is None, "1회차 — 아직")
    check(st.update([], IN_W) is None, "2회차 — 아직")
    check(st.update([], IN_W) == "wrench", "3회차 — 완료, want_tool 반환")
    check(st.phase == "placed", "phase=placed")


def test_완료후_유지():
    print("[3] 완료된 뒤에는 값이 유지된다")
    st = ToolState("wrench", placed_count=1)
    st.update([BOX_W], IN_W)
    check(st.update([], IN_W) == "wrench", "완료")
    check(st.update([BOX_W], IN_W) == "wrench", "공구가 다시 보여도 완료는 유지")
    check(st.update([], None) == "wrench", "손이 사라져도 완료는 유지")


# ------------------------------------------------------- ③ 손 = 증인
def test_손_안보이면_일시정지():
    """🔑 초기화가 아니라 멈춤이다 — 손이 안 보이면 아무 판정도 하지 않는다."""
    print("[4] 손이 안 보이면 일시정지(초기화 아님)")
    st = ToolState("wrench", placed_count=3)
    st.update([BOX_W], IN_W)
    st.update([], IN_W)                             # 1
    check(st.miss_count == 1, "1회 셌다")
    check(st.update([], None) is None, "손 안 보임 — 판정 보류")
    check(st.miss_count == 1, "카운터가 1로 유지(초기화 아님)")
    check(st.update([], None) is None, "계속 안 보여도 보류")
    check(st.miss_count == 1, "여전히 1")
    st.update([], IN_W)                             # 2
    check(st.update([], IN_W) == "wrench", "손이 돌아오면 이어서 세어 완료")


def test_손_안보이면_공구없어도_안센다():
    """손도 공구도 안 보이는 상황(고개 돌림) — 오완료가 나면 안 된다."""
    print("[5] 손·공구가 함께 사라지면 완료되지 않는다")
    st = ToolState("wrench", placed_count=3)
    st.update([BOX_W], IN_W)
    for _ in range(10):
        out = st.update([], None)
    check(out is None, "10회 반복해도 완료되지 않는다")
    check(st.phase == "grasped", "grasped 에 머문다")
    check(st.miss_count == 0, "한 번도 세지 않았다")


# ------------------------------------------------------- ④ 되돌림
def test_공구_다시보이면_초기화():
    print("[6] 공구가 다시 보이면 카운터 초기화")
    st = ToolState("wrench", placed_count=3)
    st.update([BOX_W], IN_W)
    st.update([], IN_W)
    st.update([], IN_W)
    check(st.miss_count == 2, "2회까지 셌다")
    check(st.update([BOX_W], IN_W) is None, "공구가 다시 보이면 완료 안 됨")
    check(st.miss_count == 0, "카운터 0으로 초기화")
    check(st.phase == "grasped", "쥠 상태는 유지")


def test_손끝이_박스밖이어도_보이면_센다():
    """🔑 「넣음」 판정은 손끝 위치가 아니라 **공구가 화면에 없음**이 기준이다.

    구멍에 넣은 뒤 손을 빼면 손끝은 어디에 있어도 무관하다.
    """
    print("[7] 넣음 판정은 손끝 위치를 따지지 않는다")
    st = ToolState("wrench", placed_count=3)
    st.update([BOX_W], IN_W)
    check(st.update([], OUT) is None, "1회차")
    check(st.update([], OUT) is None, "2회차")
    check(st.update([], OUT) == "wrench", "3회차 — 완료")


# ------------------------------------------------------- ⑤ 오답 공구
def test_오답공구_경고와_해제():
    print("[8] 오답 공구를 쥐면 경고, 바꿔 쥐면 풀림")
    st = ToolState("wrench", placed_count=3)
    check(st.update(ALL3, IN_D) == "driver", "오답을 쥐면 그 키 반환")
    check(st.phase == "search", "쥠으로 올라가지 않는다")
    check(st.update(ALL3, IN_W) is None, "정답으로 바꿔 쥐면 풀린다")
    check(st.phase == "grasped", "쥠 확정")


def test_아무것도_안쥠():
    print("[9] 아무 박스도 안 짚으면 아무 일 없음")
    st = ToolState("wrench", placed_count=3)
    check(st.update(ALL3, OUT) is None, "박스 밖이면 None")
    check(st.phase == "search", "search 유지")
    check(st.update(ALL3, None) is None, "손이 안 보이면 None")
    check(st.phase == "search", "search 유지")


# ------------------------------------------------------- ⑥ 3종 동시 검출
def test_3종이_다_보이는것은_정상():
    """🔑 시나리오상 3종이 동시에 보인다. 「최고 점수」를 고르지 않는다."""
    print("[10] 3종 동시 검출이 정상 — 최고 점수를 고르지 않는다")
    st = ToolState("wrench", placed_count=3)
    check(st.update(ALL3, IN_W) is None,
          "점수가 더 높은 pliers 가 있어도 쥔 것이 정답이면 통과")
    check(st.phase == "grasped", "쥠 확정")


def test_겹친박스는_작은쪽():
    """큰 박스가 작은 박스를 덮으면 작은 쪽을 쥔 것으로 본다."""
    print("[11] 박스가 겹치면 작은 쪽")
    big = ("driver", 0.70, 0, 0, 400, 400)      # 렌치 박스를 통째로 덮는다
    st = ToolState("wrench", placed_count=3)
    check(st.update([big, BOX_W], IN_W) is None, "작은 쪽(wrench)을 쥔 것으로 본다")
    check(st.phase == "grasped", "쥠 확정")


# ------------------------------------------------------- ⑦ 요구 공구가 다를 때
def test_요구공구가_드라이버일때():
    """요구 공구는 설정에서 바뀐다 — wrench 하드코딩이 없어야 한다."""
    print("[12] 요구 공구가 드라이버여도 같이 동작")
    st = ToolState("driver", placed_count=2)
    check(st.update(ALL3, IN_W) == "wrench", "렌치를 쥐면 그것이 오답")
    check(st.update(ALL3, IN_D) is None, "드라이버를 쥐면 정답")
    check(st.update([BOX_W, BOX_P], IN_D) is None, "1회차")
    check(st.update([BOX_W, BOX_P], IN_D) == "driver", "2회차 — 완료")


if __name__ == "__main__":
    t0 = time.time()
    test_안쥐면_완료_안됨()
    test_정답쥐고_넣으면_완료()
    test_완료후_유지()
    test_손_안보이면_일시정지()
    test_손_안보이면_공구없어도_안센다()
    test_공구_다시보이면_초기화()
    test_손끝이_박스밖이어도_보이면_센다()
    test_오답공구_경고와_해제()
    test_아무것도_안쥠()
    test_3종이_다_보이는것은_정상()
    test_겹친박스는_작은쪽()
    test_요구공구가_드라이버일때()

    elapsed = time.time() - t0
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    if elapsed > 1.0:
        print(f"❌ 느림 {elapsed:.1f}s — 실시간을 기다리고 있다(주입이 안 됨)")
        sys.exit(1)
    print(f"✅ 공구 판정 검증 통과 ({elapsed:.3f}s)")
