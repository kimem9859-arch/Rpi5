"""SafetyFSM 단위 테스트 — 통합 설계문서 §9.3 전이 시나리오 + §6 표 검증.

하드웨어·Qt 없이 순수 로직만 검증한다. 시간(now)은 직접 주입한다.
실행: python Demo/selftest/test_fsm.py
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from fsm import SafetyFSM, State, Feedback


def make_fsm(threshold=1.0, step_count=4, gap_fill=0.3):
    # window_n=0 — 이 테스트들은 갭메우기(시간 기준)를 검증하는 것이므로 창(관측횟수
    # 기준, config 기본값 5)이 끼어들지 않게 종전 동작으로 고정한다.
    log = {"states": [], "interlock": [], "feedback": []}
    fsm = SafetyFSM(
        step_count=step_count,
        dwell_threshold=threshold,
        gap_fill=gap_fill,
        window_n=0,
        on_state_change=lambda o, n: log["states"].append((o, n)),
        on_interlock=lambda e: log["interlock"].append(e),
        on_feedback=lambda f: log["feedback"].append(f),
    )
    return fsm, log


def run(fsm):
    """IDLE → PROCESS_RUN 까지 기동."""
    fsm.load_recipe()
    assert fsm.state == State.PROCESS_RUN
    assert fsm.expected_step == 1


# --------------------------------------------------------------------- 기동
def test_boot_sequence():
    fsm, _ = make_fsm()
    assert fsm.state == State.IDLE
    fsm.load_recipe()
    assert fsm.state == State.PROCESS_RUN
    assert fsm.correct_roi == "B1"


# ----------------------------------------------- §9.3-3,4: 정답 정상 루프
def test_correct_step_advances():
    fsm, _ = make_fsm()
    run(fsm)
    fsm.update_vision("B1", now=0.0)      # 손 진입 → MONITOR
    assert fsm.state == State.MONITOR
    fsm.press_button("B1")               # 정답 눌림 → Step Complete
    assert fsm.expected_step == 2
    assert fsm.state == State.PROCESS_RUN
    assert fsm.correct_roi == "B2"


def test_full_sequence_completes_to_idle():
    fsm, _ = make_fsm()
    run(fsm)
    for step in (1, 2, 3, 4):
        fsm.update_vision(f"B{step}", now=0.0)
        fsm.press_button(f"B{step}")
    assert fsm.state == State.IDLE          # B4 정답 → 공정 완료
    assert fsm.expected_step == 1


# ------------------------------------- §9.3-5: 오답 스침(임계 내 이탈)
def test_wrong_roi_graze_returns_to_process_run():
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B3", now=0.0)        # 기대=1인데 B3 = 오답 ROI
    assert fsm.state == State.MONITOR
    fsm.update_vision("B3", now=0.5)        # 0.5초 < 1.0 임계
    assert fsm.state == State.MONITOR        # 아직 경고 아님
    # 🔴 갭메우기(0.3초)보다 뒤에서 이탈해야 '진짜 이탈'이다. 0.6이면 직전 관측(0.5)과
    #    간격이 0.1초라 §9.4 갭메우기가 유지한다 — 그게 의도된 동작이다(2026-07-22).
    fsm.update_vision(None, now=0.6)        # 공백 0.1초 < 갭메우기 → 아직 유지
    assert fsm.state == State.MONITOR
    fsm.update_vision(None, now=1.0)        # 공백 0.5초 > 갭메우기 → 손 이탈 = 스침
    assert fsm.state == State.PROCESS_RUN    # 정상 복귀, 진전 없음
    assert fsm.expected_step == 1


# ------------------------------------- §9.3-5: 오답 체류 → WARNING
def test_wrong_roi_dwell_triggers_warning():
    fsm, log = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)        # 기대=1, B2 오답
    fsm.update_vision("B2", now=1.0)        # 체류 1.0 ≥ 임계 → WARNING
    assert fsm.state == State.WARNING
    assert Feedback.WARNING in log["feedback"]
    assert fsm.expected_step == 1            # 진전 없음


# --------------------------- §9.3-5 단서: 타이머 중 오답 버튼 → 즉시 BLOCK
def test_wrong_button_press_during_timer_blocks():
    fsm, log = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)        # 오답 체류 시작 (아직 경고 전)
    fsm.update_vision("B2", now=0.5)
    assert fsm.state == State.MONITOR
    fsm.press_button("B2")                  # 오답 버튼 실제 눌림 → 즉시 BLOCK
    assert fsm.state == State.BLOCK
    assert log["interlock"][-1] is True      # 인터록 ON


# ---------------------------- §9.3-6: WARNING 두 갈래
def test_warning_release_returns_to_monitor():
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)
    fsm.update_vision("B2", now=1.0)
    assert fsm.state == State.WARNING
    fsm.release_warning()                   # WARNING 해제 → MONITOR
    assert fsm.state == State.MONITOR
    assert fsm.expected_step == 1


def test_warning_wrong_button_blocks():
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)
    fsm.update_vision("B2", now=1.0)
    assert fsm.state == State.WARNING
    fsm.press_button("B2")                  # 경고 중 오답 버튼 → BLOCK
    assert fsm.state == State.BLOCK


# ---------------------------- §9.3-7 / §6: 위반 BLOCK 해제는 기대단계 유지
def test_block_release_keeps_expected_step():
    fsm, log = make_fsm(threshold=1.0)
    run(fsm)
    fsm.press_button("B1")                  # 기대=1 정답 → 기대=2
    assert fsm.expected_step == 2
    fsm.update_vision("B1", now=0.0)        # 기대=2인데 B1 역순=오답
    fsm.press_button("B1")                  # 오답 버튼 → BLOCK
    assert fsm.state == State.BLOCK
    fsm.release_block()                     # BLOCK 해제 → READY
    assert fsm.state == State.PROCESS_RUN
    assert fsm.expected_step == 2            # 유지 (불변식)
    assert log["interlock"][-1] is False     # 인터록 OFF


# ---------------------------- §6 공통행 / §9.2: EMO 즉시 BLOCK + 해제 시 리셋
def test_emo_blocks_immediately_and_resets_on_release():
    fsm, log = make_fsm()
    run(fsm)
    fsm.press_button("B1")                  # 기대=2로 진전
    fsm.update_vision("B2", now=0.0)
    assert fsm.expected_step == 2
    fsm.press_button("EMO")                 # 비상정지 → 즉시 BLOCK
    assert fsm.state == State.BLOCK
    fsm.release_block()                     # EMO 해제 → READY + 기대=1 리셋
    assert fsm.state == State.PROCESS_RUN
    assert fsm.expected_step == 1            # 시퀀스 전체 재시작


def test_emo_from_any_state():
    for setup in ("process", "monitor", "warning"):
        fsm, _ = make_fsm(threshold=1.0)
        run(fsm)
        if setup in ("monitor", "warning"):
            fsm.update_vision("B2", now=0.0)
        if setup == "warning":
            fsm.update_vision("B2", now=1.0)
            assert fsm.state == State.WARNING
        fsm.press_button("EMO")
        assert fsm.state == State.BLOCK, f"EMO from {setup} failed"



# ============================================================================
# 도넛 2단계 ROI (2026-07-22 신설) — 설계 = 2026-07-22-도넛-2단계-ROI-design.md
# 링(1단계)=접근은 체류를 예열만 하고, 차단은 박스 안(2단계)에서만 발화한다(C1).
# ============================================================================
from roi_zones import INSIDE, RING


def test_ring_alone_does_not_warn():
    """링에만 머물면 임계를 한참 넘겨도 경고하지 않는다 — 접근은 위반이 아니다."""
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B3", now=0.0, level=RING)     # 기대=1, B3 오답이지만 '접근'
    fsm.update_vision("B3", now=5.0, level=RING)     # 임계의 5배를 머물러도
    assert fsm.state == State.MONITOR                # WARNING 아님
    print("  PASS  링에만 있으면 임계를 넘겨도 경고하지 않는다")


def test_ring_preheats_then_inside_fires():
    """링에서 쌓인 체류가 박스 안 진입 즉시 발화로 이어진다(예열)."""
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B3", now=0.0, level=RING)     # 접근 시작 — 여기서부터 누적
    fsm.update_vision("B3", now=1.2, level=RING)     # 임계 넘겼으나 링이라 발화 안 함
    assert fsm.state == State.MONITOR
    fsm.update_vision("B3", now=1.3, level=INSIDE)   # 박스 안 진입 → 예열분이 인정돼 즉시
    assert fsm.state == State.WARNING
    print("  PASS  링에서 예열된 체류가 박스 안 진입 즉시 발화한다")


def test_gap_fill_holds_then_resets():
    """갭메우기 — 짧은 공백은 유지, 임계를 넘는 공백은 리셋."""
    fsm, _ = make_fsm(threshold=1.0, gap_fill=0.3)
    run(fsm)
    fsm.update_vision("B3", now=0.0)                 # 오답 체류 시작
    fsm.update_vision(None, now=0.2)                 # 공백 0.2초 < 0.3 → 유지
    assert fsm.state == State.MONITOR
    fsm.update_vision("B3", now=1.1)                 # 체류가 안 끊겨 임계 초과 → 발화
    assert fsm.state == State.WARNING

    fsm2, _ = make_fsm(threshold=1.0, gap_fill=0.3)
    run(fsm2)
    fsm2.update_vision("B3", now=0.0)
    fsm2.update_vision(None, now=0.5)                # 공백 0.5초 > 0.3 → 진짜 이탈
    assert fsm2.state == State.PROCESS_RUN
    fsm2.update_vision("B3", now=1.1)                # 타이머가 리셋됐으므로 다시 시작
    assert fsm2.state == State.MONITOR               # 아직 경고 아님
    print("  PASS  갭메우기 — 0.2초 공백은 유지, 0.5초 공백은 리셋")

def make_win_fsm(threshold=1.0, window_n=5, window_m=3):
    """창 기반 누적 FSM. 갭메우기는 끄고 창만 본다."""
    log = {"states": []}
    fsm = SafetyFSM(
        step_count=4, dwell_threshold=threshold, gap_fill=0.0,
        window_n=window_n, window_m=window_m,
        on_state_change=lambda o, n: log["states"].append((o, n)),
    )
    fsm.load_recipe()
    return fsm, log


def test_window_holds_through_sparse_dropouts():
    """N=5·M=3 — 3연속 관측 뒤 2연속 결측까지는 창이 유지한다.

    (참고: 이탈("진짜 이탈") 시 `self._win.clear()`로 창을 통째로 비운다.
    그래서 '한 프레임 걸러' 결측을 무한 반복하는 패턴은 매 결측마다 창에
    쌓인 게 1개뿐인 상태(count=1<3)로 즉시 이탈·초기화가 반복돼 창이 아예
    쌓이지 못한다 — 유지를 얻으려면 먼저 window_m(3)회를 **연속으로** 관측해
    창을 채워야 한다. 이 테스트는 그 전제를 갖춘 뒤의 경계를 쓴다.)
    """
    fsm, _ = make_win_fsm(threshold=1.0, window_n=5, window_m=3)
    for t in (0.0, 0.1, 0.2):
        fsm.update_vision("B2", now=t)          # 3연속 관측 → 창 [B2,B2,B2]
    fsm.update_vision(None, now=0.3)             # 결측 1 — 창 count(B2)=3 → 유지
    assert fsm.state == State.MONITOR
    fsm.update_vision(None, now=0.4)             # 결측 2 — 창 count(B2)=3(길이5) → 유지
    assert fsm.state == State.MONITOR
    fsm.update_vision("B2", now=1.0)             # 체류가 안 끊겼으므로 총 1.0초 → 경고
    assert fsm.state == State.WARNING
    print("  PASS  창 — 짧은 연속 결측에서도 체류가 이어진다")


def test_window_releases_after_sustained_absence():
    """유지 자격(window_m 연속 관측)을 갖춘 뒤, 결측이 이어지면 정확히 몇 번째에서
    풀리는지를 확인한다 — `test_window_holds_through_sparse_dropouts`(유지된다)의
    반대쪽 경계(결국 풀린다)를 맡는다.

    N=5·M=3. 3연속 관측으로 창을 [B2,B2,B2]로 채운 뒤 결측을 이어가면:
      결측 1 → 창 [B2,B2,B2,None]        count(B2)=3 ≥3 → 유지
      결측 2 → 창 [B2,B2,B2,None,None]   count(B2)=3 ≥3 → 유지 (아직 안 밀림, len=5)
      결측 3 → 가장 오래된 B2가 밀려나 count(B2)=2 <3 → 이탈
    (실측 확인: 이 파일 작성 시 `python3 -c`로 위 수열을 직접 먹여 검증했다 —
    §Task5 리뷰 보고서 참조.)
    """
    fsm, _ = make_win_fsm(threshold=1.0, window_n=5, window_m=3)
    for t in (0.0, 0.1, 0.2):
        fsm.update_vision("B2", now=t)            # 3연속 관측 → 유지 자격 획득
    assert fsm.state == State.MONITOR

    fsm.update_vision(None, now=0.3)               # 결측 1
    assert fsm.state == State.MONITOR              # 아직 유지
    fsm.update_vision(None, now=0.4)               # 결측 2
    assert fsm.state == State.MONITOR              # 아직 유지

    fsm.update_vision(None, now=0.5)               # 결측 3 — 여기서 정확히 풀린다
    assert fsm.state == State.PROCESS_RUN

    fsm.update_vision(None, now=0.6)               # 풀린 뒤에도 계속 결측 → 그대로 유지
    assert fsm.state == State.PROCESS_RUN
    print("  PASS  창 — 유지 자격을 갖춘 뒤에도 결측 3번째에서 정확히 풀린다")


def test_window_disabled_falls_back_to_gap_fill():
    """window_n=0 이면 롤백 스위치 — 종전 갭메우기 동작과 동일."""
    fsm, _ = make_win_fsm(threshold=1.0, window_n=0, window_m=3)
    fsm.gap_fill = 0.3
    fsm.update_vision("B2", now=0.0)
    fsm.update_vision(None, now=0.2)              # 0.2 <= 0.3 → 유지
    assert fsm.state == State.MONITOR
    fsm.update_vision(None, now=0.8)              # 0.6 공백 > 0.3 → 이탈
    assert fsm.state == State.PROCESS_RUN
    print("  PASS  창 — window_n=0 이면 종전 갭메우기 동작")


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
