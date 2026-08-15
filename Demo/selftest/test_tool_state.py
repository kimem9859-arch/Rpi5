"""공구 판정 상태기계(A-2) 검증.

실행: python3 Demo/selftest/test_tool_state.py

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §4.3·§4.4
      (🔑 2026-08-16 개정 — 3마디 → 2마디. 경위 = 통합문서 §10.44)

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
    """🔴 이 전제가 없으면 작업 시작 직후 바로 완료된다."""
    print("[1] 쥐기 전에는 완료되지 않는다")
    st = ToolState("wrench")
    out = "sentinel"
    for _ in range(10):
        out = st.update([], IN_W)          # 손 보임 + 공구 없음
    check(st.phase == "search", "10회 반복해도 search 유지")
    check(out is None, "완료 값이 나오지 않는다")


def test_공구를_못잡아도_완료_안됨():
    """🔴🔴 이번 개정의 **핵심 회귀 테스트** — 구 3마디 설계의 오완료 재발 방지.

    구 설계는 「손은 보이는데 공구가 안 보인다」를 **넣음**으로 셌다. 그래서
    쥔 공구를 모델이 놓치기만 해도 완료가 났다(실측 = 통합문서 §10.44-(3)).
    2마디에서는 **부재를 근거로 쓰지 않으므로** 이 입력으로 완료가 나면 안 된다.

    아래 시퀀스는 §10.44-(3) 표의 실제 프레임 순서를 그대로 옮긴 것이다.
    """
    print("[2] 🔴 공구를 못 잡아도 완료되지 않는다 (§10.44 오완료 회귀)")
    st = ToolState("wrench")
    seq = [                                 # (검출, 손끝) — 실측 req_43~53
        ([], IN_W),        # 손O 공구✗
        ([], IN_W),        # 손O 공구✗
        ([BOX_W], OUT),    # 공구는 보이나 안 쥠
        ([], IN_W),        # 손O 공구✗
        ([], None),        # 손✗ (고개 돌림)
        ([], None),
        ([], None),
        ([], None),
        ([], IN_W),        # 손O 공구✗
        ([], None),
        ([], IN_W),        # 손O 공구✗  ← 구 설계는 여기서 오완료가 났다
    ]
    out = "sentinel"
    for dets, tip in seq:
        out = st.update(dets, tip)
    check(out is None, "🔴 미검출이 아무리 이어져도 완료되지 않는다")
    check(st.phase == "search", "search 에 머문다")


# ------------------------------------------------------- ② 정상 경로
def test_정답을_쥐면_즉시_완료():
    """🔑 2마디의 완료 기준 = 「요구 공구를 손으로 쥠」. 넣는 단계는 없다."""
    print("[3] 정답 공구를 쥐면 그 자리에서 완료")
    st = ToolState("wrench")
    check(st.update([BOX_W], IN_W) == "wrench", "쥐는 즉시 want_tool 반환")
    check(st.phase == "grasped", "phase=grasped")


def test_완료후_유지():
    """🔴 유지는 선택이 아니라 필수다.

    렌치를 쥐고 「다음 단계 진행」 버튼을 누르러 가는 동안 손끝은 공구 박스를
    벗어난다. 매 프레임 재판정하면 완료가 풀려 버튼을 누를 수 없다.
    """
    print("[4] 완료된 뒤에는 값이 유지된다")
    st = ToolState("wrench")
    check(st.update([BOX_W], IN_W) == "wrench", "완료")
    check(st.update([], IN_W) == "wrench", "공구가 안 보여도 유지")
    check(st.update([], None) == "wrench", "손이 사라져도 유지")
    check(st.update(ALL3, IN_D) == "wrench", "오답 공구를 쥐어도 유지(경고로 안 돌아간다)")
    check(st.phase == "grasped", "grasped 유지")


# ------------------------------------------------------- ③ 손 = 증인
def test_손_안보이면_판정하지_않는다():
    """공구가 보여도 손이 안 보이면 「쥐었다」고 말할 수 없다."""
    print("[5] 손이 안 보이면 아무 판정도 하지 않는다")
    st = ToolState("wrench")
    check(st.update([BOX_W], None) is None, "공구만 보이면 완료 아님")
    check(st.phase == "search", "search 유지")
    check(st.update(ALL3, None) is None, "3종이 다 보여도 마찬가지")
    check(st.phase == "search", "search 유지")


# ------------------------------------------------------- ④ 오답 공구
def test_오답공구_경고와_해제():
    print("[6] 오답 공구를 쥐면 경고, 바꿔 쥐면 완료")
    st = ToolState("wrench")
    check(st.update(ALL3, IN_D) == "driver", "오답을 쥐면 그 키 반환")
    check(st.phase == "search", "쥠으로 올라가지 않는다")
    check(st.update(ALL3, IN_W) == "wrench", "정답으로 바꿔 쥐면 완료")
    check(st.phase == "grasped", "쥠 확정")


def test_아무것도_안쥠():
    print("[7] 아무 박스도 안 짚으면 아무 일 없음")
    st = ToolState("wrench")
    check(st.update(ALL3, OUT) is None, "박스 밖이면 None")
    check(st.phase == "search", "search 유지")


# ------------------------------------------------------- ⑤ 여러 공구
def test_3종이_다_보이는것은_정상():
    """🔑 시나리오상 3종이 동시에 보인다. 「최고 점수」를 고르지 않는다."""
    print("[8] 3종 동시 검출이 정상 — 최고 점수를 고르지 않는다")
    st = ToolState("wrench")
    check(st.update(ALL3, IN_W) == "wrench",
          "점수가 더 높은 pliers 가 있어도 쥔 것이 정답이면 완료")
    check(st.phase == "grasped", "쥠 확정")


def test_겹친박스는_작은쪽():
    """큰 박스가 작은 박스를 덮으면 작은 쪽을 쥔 것으로 본다."""
    print("[9] 박스가 겹치면 작은 쪽")
    big = ("driver", 0.70, 0, 0, 400, 400)      # 렌치 박스를 통째로 덮는다
    st = ToolState("wrench")
    check(st.update([big, BOX_W], IN_W) == "wrench", "작은 쪽(wrench)을 쥔 것으로 본다")
    check(st.phase == "grasped", "쥠 확정")


# ------------------------------------------------------- ⑥ 요구 공구가 다를 때
def test_요구공구가_드라이버일때():
    """요구 공구는 설정에서 바뀐다 — wrench 하드코딩이 없어야 한다."""
    print("[10] 요구 공구가 드라이버여도 같이 동작")
    st = ToolState("driver")
    check(st.update(ALL3, IN_W) == "wrench", "렌치를 쥐면 그것이 오답")
    check(st.phase == "search", "오답은 쥠이 아니다")
    check(st.update(ALL3, IN_D) == "driver", "드라이버를 쥐면 완료")
    check(st.phase == "grasped", "쥠 확정")


if __name__ == "__main__":
    t0 = time.time()
    test_안쥐면_완료_안됨()
    test_공구를_못잡아도_완료_안됨()
    test_정답을_쥐면_즉시_완료()
    test_완료후_유지()
    test_손_안보이면_판정하지_않는다()
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
