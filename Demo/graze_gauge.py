"""스침 판정 카드의 값 — 판정기(fsm.SafetyFSM)가 이미 계산한 값을 매 장 읽어 「지금 어느 틀린 버튼을 판정 중인가 ·
얼마나 머물렀나 · 버튼 안에서 손끝이 가장 느렸던 속도 · 결과」를 만든다(2026-10-22 사용자 시안 B2).

🔴 판정은 하지 않는다 — 경고 여부 · 이유는 판정기의 상태(WARNING)와 `last_warn_reason` 을 그대로 옮긴다.
   그래서 화면과 실제 판정이 어긋날 수 없다. 기준값도 판정기 설정(dwell_threshold · slow_px_s)에서 읽는다.
🔑 Qt 없이 돈다 — 그리기는 overlay_graze.GrazeCard.
"""
import config
from fsm import State
from roi_zones import INSIDE as ZONE_INSIDE

_JUDGING = (State.PROCESS_RUN, State.MONITOR)


class GrazeTracker:
    """`observe(t, fsm)` 를 판정기 update_vision 바로 뒤에 매 장 부른다 · `view(now)` 가 카드에 그릴 값."""

    def __init__(self, hold_sec=None):
        self.hold_sec = config.GRAZE_RESULT_HOLD_SEC if hold_sec is None else hold_sec
        self._visit = None           # {"btn", "exp", "t0", "t_last", "min", "cur"}
        self._result = None          # {"btn", "exp", "kind": "pass"|"dwell"|"slow", "elapsed", "min", "t_end"}
        self._prev = None

    def _speed_into(self, v, fsm):
        """이 장에 버튼 상자 안에서 실제로 본 손끝 속도면 그 방문에 넣는다(가장 느린 값 = 경고를 가르는 값)."""
        sp = getattr(fsm, "last_speed", None)
        if (sp is not None and getattr(fsm, "last_speed_observed", False)
                and getattr(fsm, "_last_roi", None) == v["btn"] and getattr(fsm, "_last_level", None) == ZONE_INSIDE):
            v["cur"] = sp
            v["min"] = sp if v["min"] is None else min(v["min"], sp)

    def _end(self, v, kind, t_end):
        self._result = {"btn": v["btn"], "exp": v["exp"], "kind": kind, "elapsed": max(0.0, t_end - v["t0"]),
                        "min": v["min"], "t_end": t_end}
        self._visit = None

    def observe(self, t, fsm):
        st, roi = fsm.state, getattr(fsm, "_dwell_roi", None)
        warned = st == State.WARNING and self._prev not in (None, State.WARNING)
        v = self._visit
        if v is None and warned and getattr(fsm, "_warn_roi", None):
            # 들어간 첫 장에 바로 경고(느린 진입) — 판정기가 같은 장에 체류를 세웠다 지워 방문이 시작되지 않았다
            v = {"btn": fsm._warn_roi, "exp": fsm.correct_roi, "t0": t, "t_last": t, "min": None, "cur": None}
        if v is not None:
            self._speed_into(v, fsm)
            if warned:
                self._end(v, "slow" if fsm.last_warn_reason == "slow" else "dwell", t)
            elif st not in _JUDGING:
                self._visit = None           # 차단 · 초기화 등 — 그 방문은 결과 없이 접는다(차단은 알림 상자가 말한다)
            elif roi != v["btn"]:
                self._end(v, "pass", v["t_last"])     # 손이 그 버튼 구역을 떠났다(링 밖 · 다른 버튼 · 정답 버튼)
            elif getattr(fsm, "last_speed_observed", False) and getattr(fsm, "_last_roi", None) == v["btn"]:
                v["t_last"] = t      # 🔑 이 장에 실제로 본 때만 — 판정기는 손이 떠나도 갭메우기(0.3초)로 붙들어 결과 시간이 부풀었다
        if self._visit is None and roi is not None and st in _JUDGING:
            self._visit = {"btn": roi, "exp": fsm.correct_roi, "t0": getattr(fsm, "_dwell_start", None) or t,
                           "t_last": t, "min": None, "cur": None}
            self._result = None
            self._speed_into(self._visit, fsm)
        self._prev = st

    def view(self, now):
        """카드 값 — mode = "judging" | "result" | "idle"."""
        v = self._visit
        if v is not None:
            return {"mode": "judging", "btn": v["btn"], "exp": v["exp"], "elapsed": max(0.0, v["t_last"] - v["t0"]),
                    "min": v["min"], "cur": v["cur"]}
        r = self._result
        if r is not None and now - r["t_end"] <= self.hold_sec:
            return dict(r, mode="result")
        return {"mode": "idle"}

    def pop_new_result(self):
        """새로 난 결과(한 번만) 또는 None — 콘솔이 시연 기록에 한 줄로 남긴다(끝나고 셀 수 있게 · 10/22)."""
        r = self._result
        if r is None or r.get("logged"):
            return None
        r["logged"] = True
        return r

    def reset(self):
        self._visit = self._result = None
