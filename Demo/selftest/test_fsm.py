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


# ============================================================================
# 관측 기록 vs 상태 게이트 분리 (2026-07-27, Task 5b)
# WARNING/BLOCK 중에도 last_roi 는 계속 갱신되고, 상태 전이만 막힌다.
# ============================================================================
def test_last_roi_updates_during_warning():
    """WARNING 중에도 last_roi 가 최신 관측을 반영한다(종전엔 낡은 값으로 멈췄다)."""
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)        # 오답 체류 시작
    fsm.update_vision("B2", now=1.0)        # 체류 1.0 ≥ 임계 → WARNING
    assert fsm.state == State.WARNING
    assert fsm.last_roi == "B2"
    fsm.update_vision("B3", now=1.1)        # WARNING 중에도 새 관측
    assert fsm.last_roi == "B3"              # 갱신됨 (종전엔 "B2"로 고정)
    print("  PASS  WARNING 중에도 last_roi 가 갱신된다")


def test_last_roi_expires_during_warning():
    """WARNING 중 손이 갭메우기(0.3초)보다 오래 사라지면 last_roi 가 None 으로 만료된다.

    (관측 무효화가 상태 게이트 '아래'에 남아 있으면 이게 실패한다 — WARNING/BLOCK
    동안 last_roi 가 영원히 만료되지 않는 버그. 실측: gap_fill=0.3일 때 마지막 관측
    (now=1.0)로부터 0.2초 공백은 유지, 0.6초 공백은 만료된다.)
    """
    fsm, _ = make_fsm(threshold=1.0, gap_fill=0.3)
    run(fsm)
    fsm.update_vision("B2", now=0.0)        # 오답 체류 시작
    fsm.update_vision("B2", now=1.0)        # 체류 1.0 ≥ 임계 → WARNING
    assert fsm.state == State.WARNING
    assert fsm.last_roi == "B2"
    fsm.update_vision(None, now=1.2)        # 공백 0.2초 < 갭메우기 0.3 → 아직 유지
    assert fsm.last_roi == "B2"
    assert fsm.state == State.WARNING        # 상태 전이는 여전히 막힘
    fsm.update_vision(None, now=1.6)        # 공백 0.6초(1.0 기준) > 갭메우기 → 만료
    assert fsm.last_roi is None              # 낡은 값으로 영원히 남지 않는다
    assert fsm.state == State.WARNING        # 상태는 그대로 (해제 버튼만이 주체)
    print("  PASS  WARNING 중 손이 오래 사라지면 last_roi 가 None 으로 만료된다")


def test_warning_state_transition_still_blocked():
    """WARNING 중 update_vision 을 여러 번 불러도 상태 전이는 막힌다(관측만 된다)."""
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)
    fsm.update_vision("B2", now=1.0)
    assert fsm.state == State.WARNING
    fsm.update_vision("B1", now=1.1)        # 정답 ROI 를 봐도
    assert fsm.state == State.WARNING        # 상태는 그대로
    fsm.update_vision(None, now=1.2)        # 손이 사라져도
    assert fsm.state == State.WARNING        # 상태는 그대로 (해제 버튼만이 주체)
    print("  PASS  WARNING 중 상태 전이는 관측과 무관하게 막힌다")


# ------------------------------------------------- 작업 초기화 (reset)
def test_reset_from_mid_process():
    """진행 중이던 작업을 「작업 시작」 직전 상태로 되돌린다."""
    fsm, _ = make_fsm()
    run(fsm)
    fsm.press_button("B1")                   # 2단계까지 진행
    assert fsm.expected_step == 2
    fsm.reset()
    assert fsm.state == State.IDLE
    assert fsm.expected_step == 1


def test_reset_from_block_releases_interlock():
    """차단 중 초기화 — 릴레이(인터락)도 함께 풀려야 한다."""
    fsm, log = make_fsm()
    run(fsm)
    fsm.press_button("B2")                   # 오답 눌림 → 즉시 BLOCK
    assert fsm.state == State.BLOCK
    assert log["interlock"][-1] is True
    fsm.reset()
    assert fsm.state == State.IDLE
    assert log["interlock"][-1] is False, "차단에서 나오면 인터락이 풀린다"


def test_reset_clears_emo_flag():
    """EMO 로 걸린 차단도 초기화가 정리한다(GUI 가 EMO 물리 상태를 따로 막는다)."""
    fsm, _ = make_fsm()
    run(fsm)
    fsm.press_button("EMO")
    assert fsm.state == State.BLOCK
    fsm.reset()
    assert fsm.state == State.IDLE
    assert fsm._emo_active is False


def test_reset_when_already_idle():
    """이미 IDLE 이면 아무 일도 일어나지 않는다(중복 호출 안전)."""
    fsm, log = make_fsm()
    before = len(log["states"])
    fsm.reset()
    assert fsm.state == State.IDLE
    assert fsm.expected_step == 1
    assert len(log["states"]) == before, "상태 변화가 없으면 콜백도 부르지 않는다"


def test_reset_clears_dwell():
    """체류 누적이 남아 초기화 직후 오판정하면 안 된다."""
    fsm, _ = make_fsm(threshold=1.0)
    run(fsm)
    fsm.update_vision("B2", now=0.0)         # 오답 ROI 체류 시작
    fsm.reset()
    assert fsm._dwell_roi is None
    assert fsm._dwell_start is None


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
