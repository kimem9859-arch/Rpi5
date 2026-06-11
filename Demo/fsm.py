"""작업 순서 위반 감지 FSM (판정부) — 통합 설계문서 §9 정본 구현.

§8의 '인식 / 판정 / 제어 분리' 원칙에 따라, 이 모듈은 Qt·소켓·하드웨어에
의존하지 않는 순수 상태머신이다. 입력은 (1) 비전 틱 — 손이 들어와 있는 ROI,
(2) 물리 버튼 눌림, (3) EMO, (4) 해제 버튼 2종이며, 출력은 상태 전이와
부수효과(시청각 피드백 단계 / 인터록 ON·OFF)를 콜백으로 통지한다.

핵심 불변식(§6·§9): 기대단계 N에 대해 정답 ROI = f"B{N}", 그 외 공정 버튼은
오답. **오답은 단계를 절대 진전시키지 않는다.** 위반으로 BLOCK된 뒤 해제해도
기대단계는 유지되며, EMO 해제만 기대단계를 1로 리셋한다.
"""

import enum

import config


class State(enum.Enum):
    IDLE        = "IDLE"          # 전원 대기
    READY       = "READY"         # 레시피 로드 완료, 감시 대기
    PROCESS_RUN = "PROCESS RUN"   # 정상 공정 진행 중
    MONITOR     = "MONITOR"       # 손-ROI 판정 (정답/오답 분기)
    WARNING     = "WARNING"       # 시·청 경고 출력
    BLOCK       = "BLOCK"         # 인터록으로 전기 입력 차단


class Feedback(enum.Enum):
    """시청각 피드백 단계 (촉각/햅틱은 §13 확장)."""
    NONE    = 0
    WARNING = 1   # 시각 팝업 + 청각 타워램프
    BLOCK   = 2   # 차단 경고 (인터록 동반)


class SafetyFSM:
    """순서 위반 감지 상태머신.

    시간은 외부에서 주입한다(테스트 결정성). 비전 루프가 매 프레임
    `update_vision(roi, now)`를, 버튼 입력 핸들러가 `press_button(btn, now)`를
    호출한다. 상태 전이·인터록·피드백은 콜백으로 통지된다.
    """

    def __init__(self, step_count=None, dwell_threshold=None,
                 sequence=None, emo_button=None,
                 on_state_change=None, on_interlock=None, on_feedback=None):
        # sequence: 레시피 steps 리스트 [{order, button, name}, ...] (recipe.json).
        # 주면 정답 순서·단계 이름을 거기서 읽고, 없으면 B1..B{step_count}로 대체.
        self._sequence = sequence
        if sequence:
            self.step_count = len(sequence)
        else:
            self.step_count = step_count if step_count is not None else config.FSM_STEP_COUNT
        self.dwell_threshold = dwell_threshold if dwell_threshold is not None else config.FSM_DWELL_THRESHOLD_SEC
        self._emo            = emo_button if emo_button is not None else config.FSM_EMO_BUTTON

        # 콜백 (없으면 무시)
        self._cb_state    = on_state_change or (lambda old, new: None)
        self._cb_interlock = on_interlock or (lambda engaged: None)
        self._cb_feedback = on_feedback or (lambda level: None)

        self.state         = State.IDLE
        self.expected_step = 1     # 1..step_count, 정답 ROI = f"B{expected_step}"

        # 오답 ROI 체류 타이머 (MONITOR 오답 분기)
        self._dwell_roi    = None  # 현재 체류 중인 오답 ROI id
        self._dwell_start  = None  # 체류 시작 시각

    # ------------------------------------------------------------------ 헬퍼
    @property
    def correct_roi(self):
        """현재 기대단계의 정답 버튼 ROI id (예: 'B2'). 레시피가 있으면 거기서."""
        if self._sequence:
            return self._sequence[self.expected_step - 1]["button"]
        return f"B{self.expected_step}"

    @property
    def current_step_name(self):
        """현재 기대단계의 사람용 이름 (디스플레이/로그용). 레시피 없으면 버튼 id."""
        if self._sequence:
            return self._sequence[self.expected_step - 1].get("name", self.correct_roi)
        return self.correct_roi

    def _goto(self, new_state):
        if new_state == self.state:
            return
        old, self.state = self.state, new_state
        # 인터록·피드백 부수효과
        if new_state == State.BLOCK:
            self._cb_interlock(True)
            self._cb_feedback(Feedback.BLOCK)
        elif new_state == State.WARNING:
            self._cb_feedback(Feedback.WARNING)
        elif old in (State.BLOCK, State.WARNING):
            # 경고/차단에서 빠져나오면 인터록 해제 + 피드백 끔
            if old == State.BLOCK:
                self._cb_interlock(False)
            self._cb_feedback(Feedback.NONE)
        self._cb_state(old, new_state)

    def _reset_dwell(self):
        self._dwell_roi   = None
        self._dwell_start = None

    # ------------------------------------------------------ 정비 시퀀스 (§9.3 1~2)
    def load_recipe(self):
        """IDLE → READY → PROCESS RUN. 레시피(공정 매뉴얼) 로드 완료."""
        if self.state == State.IDLE:
            self._goto(State.READY)
            self._goto(State.PROCESS_RUN)

    # ------------------------------------------------------ 비전 틱 (§9.3 3·5)
    def update_vision(self, roi, now):
        """매 프레임 호출. `roi`는 손이 들어와 있는 버튼 ROI id 또는 None.

        - 손이 정답 ROI에 있어도 '눌림' 전까지는 진전시키지 않는다(press_button이 확정).
        - 오답 ROI 체류는 타이머로 스침(<임계) vs 위반(≥임계)을 가른다.
        """
        if self.state in (State.IDLE, State.WARNING, State.BLOCK):
            # 경고/차단 중에는 비전 틱으로 자동 전이하지 않음 (해제 버튼이 주체)
            return

        if roi is None:
            # 손이 ROI 밖 → 오답 체류 취소(스침으로 간주), MONITOR면 정상 복귀
            if self.state == State.MONITOR:
                self._goto(State.PROCESS_RUN)
            self._reset_dwell()
            return

        # 손이 어떤 ROI 안에 있음 → 감시 시작
        if self.state == State.PROCESS_RUN:
            self._goto(State.MONITOR)

        if roi == self.correct_roi:
            # 정답 ROI 진입: 눌림 대기 (진전은 press_button에서). 오답 타이머 해제.
            self._reset_dwell()
            return

        # 오답 ROI: 체류 타이머
        if self._dwell_roi != roi:
            self._dwell_roi   = roi
            self._dwell_start = now
        elif now - self._dwell_start >= self.dwell_threshold:
            # 체류 임계 초과 → 위반 경고
            self._goto(State.WARNING)
            self._reset_dwell()

    # ------------------------------------------------------ 버튼 눌림 (§9.3 4·5·6)
    def press_button(self, button, now=None):
        """물리 버튼이 실제로 눌렸을 때 호출."""
        if button == self._emo:
            self._emo_stop()
            return

        if self.state == State.BLOCK:
            return  # 차단 중 입력 무시 (해제 버튼만 유효)

        if button == self.correct_roi:
            # 정답 버튼 눌림 → Step Complete
            if self.state in (State.MONITOR, State.PROCESS_RUN):
                self._step_complete()
            return

        # 오답 버튼이 실제로 눌림 → 경고 생략하고 즉시 BLOCK (§9.3 5 단서·6)
        if self.state in (State.MONITOR, State.WARNING, State.PROCESS_RUN):
            self._reset_dwell()
            self._goto(State.BLOCK)

    def _step_complete(self):
        """정답 처리: 다음 단계로. 마지막 단계면 공정 완료 → IDLE."""
        self._reset_dwell()
        if self.expected_step >= self.step_count:
            self.expected_step = 1
            self._goto(State.IDLE)        # 공정 완료 (§6 4단계: B4 정답→IDLE)
        else:
            self.expected_step += 1
            self._goto(State.READY)       # 다음 단계 입력 대기
            self._goto(State.PROCESS_RUN)

    # ------------------------------------------------------ EMO (§6 공통행·§9.2)
    def _emo_stop(self):
        """비상정지: 어느 상태에서든 즉시 BLOCK."""
        self._reset_dwell()
        self._emo_active = True
        self._goto(State.BLOCK)

    _emo_active = False

    # ------------------------------------------------------ 해제 버튼 2종 (§9.3 6·7)
    def release_warning(self):
        """WARNING 해제 버튼 → MONITOR 복귀. (기대단계 유지)"""
        if self.state == State.WARNING:
            self._goto(State.MONITOR)

    def release_block(self):
        """BLOCK 해제 버튼 → READY 복귀.

        위반 BLOCK은 기대단계 유지, EMO BLOCK은 기대단계=1 리셋(§6·§9.2).
        """
        if self.state != State.BLOCK:
            return
        if self._emo_active:
            self.expected_step = 1
            self._emo_active   = False
        self._goto(State.READY)
        self._goto(State.PROCESS_RUN)
