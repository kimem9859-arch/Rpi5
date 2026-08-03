"""서브 작업(대기·공구) 진행 관리 — 메인 버튼 사이에 끼는 작업.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §5·§6

무엇인가:
    "B1 누름(메인) + B1 후 대기(서브) = **하나의 B1 작업**" 이라는 정의에서 나온다.
    작업이 끝나기 전에 다른 버튼을 누르면 순서 위반이다.

    🔑 그래서 **FSM 을 고치지 않는다.** GUI 가 물리 버튼 눌림을 받아도 FSM 에 바로
    알리지 않고 여기서 서브 작업을 굴리다가, 「다음 단계 진행」을 누를 때
    비로소 `fsm.press_button()` 을 부른다. 그 지연 덕분에 대기 중에 다른 버튼을
    누르면 FSM 이 (기대단계가 아직 안 올라갔으므로) **자동으로 오답 판정**한다.

⚠️ Qt 에 의존하지 않는다 — GUI 없이 시험할 수 있어야 한다.
⚠️ 시간을 **인자로 받는다**(`now`). 내부에서 time.time() 을 부르면 테스트가
   30초를 실제로 기다려야 한다. 인자를 생략하면 실시간을 쓴다(런타임 편의).
"""

import time


class SubTask:
    """한 단계의 서브 작업 진행 상태.

    spec 이 None 이면 서브 작업이 없는 단계다(예: 4단계 챔버 벤트) — 즉시 진행 가능.
    """

    def __init__(self, spec, now=None):
        self._spec = spec or None
        self._start = time.time() if now is None else now
        self._now = self._start
        self._tool = None          # 지금 놓여 있는 공구(없으면 None)

    # ------------------------------------------------------------------ 상태
    @property
    def is_active(self):
        """진행 중인 서브 작업이 있는가."""
        return self._spec is not None

    @property
    def needs_tool(self):
        return bool(self._spec) and self._spec.get("type") == "wait_tool"

    @property
    def label(self):
        return self._spec.get("label", "") if self._spec else ""

    @property
    def total_sec(self):
        return self._spec.get("sec", 0) if self._spec else 0

    @property
    def elapsed_sec(self):
        if not self._spec:
            return 0.0
        return max(0.0, self._now - self._start)

    @property
    def progress(self):
        """0.0~1.0. 1.0을 넘지 않는다(게이지가 넘치면 안 된다)."""
        if not self._spec or self.total_sec <= 0:
            return 1.0
        return min(1.0, self.elapsed_sec / self.total_sec)

    @property
    def time_done(self):
        return self.progress >= 1.0

    # ------------------------------------------------------------------ 공구
    @property
    def want_tool(self):
        """이 단계가 요구하는 공구 키. 공구가 필요 없으면 None."""
        return self._spec.get("tool") if self.needs_tool else None

    @property
    def want_tool_name(self):
        return self._tool_name(self.want_tool)

    @property
    def tool_ok(self):
        return self.needs_tool and self._tool == self.want_tool

    @property
    def wrong_tool(self):
        """잘못 놓인 공구 키. 없거나 올바르면 None.

        🔴 '치워서 없는 것'은 잘못된 공구가 아니다 — 경고를 띄우지 않는다.
        """
        if not self.needs_tool or self._tool is None:
            return None
        return None if self._tool == self.want_tool else self._tool

    @property
    def wrong_tool_name(self):
        return self._tool_name(self.wrong_tool)

    def _tool_name(self, key):
        """표시용 한글 이름. 매핑이 없으면 키를 그대로 쓴다."""
        if key is None or not self._spec:
            return ""
        return self._spec.get("tool_names", {}).get(key, key)

    # ------------------------------------------------------------------ 진행
    @property
    def can_advance(self):
        """「다음 단계 진행」 버튼을 켤 수 있는가.

        design §6 (가)안 — wait 는 시간만, wait_tool 은 **시간 AND 공구**.
        """
        if not self._spec:
            return True
        if not self.time_done:
            return False
        return self.tool_ok if self.needs_tool else True

    # ------------------------------------------------------------------ 입력
    def tick(self, now=None):
        """현재 시각을 갱신한다. GUI 타이머가 주기적으로 부른다."""
        self._now = time.time() if now is None else now

    def set_tool(self, name):
        """지금 놓여 있는 공구를 갱신한다(없으면 None).

        공구 감지 모델이 붙기 전에는 사람이 눈으로 확인하고
        「다음 단계 진행」을 누르는 것으로 대신한다 — design §5.
        """
        self._tool = name or None
