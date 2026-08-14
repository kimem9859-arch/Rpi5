"""공구 지참 판정 — 서브 작업(wait_tool)의 세 마디 상태기계.

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §4.3·§4.4

무엇을 판정하나:
    ① 찾기  — 요구 공구가 화면에 보임
    ② 쥠    — 손끝이 요구 공구 박스 안에 들어옴 (🔒 여기서 확정)
    ③ 완료  — 손은 보이는데 요구 공구가 화면에서 사라짐, 연속 N회

🔑 **판정 대상은 「보이는 공구」가 아니라 「쥔 공구」다.**
   시연 시나리오는 3종(드라이버·렌치·플라이어)을 종류별 1개씩 책상에 두므로
   **3종이 동시에 보이는 것이 정상**이다. 그중 점수가 높은 것을 고르는 것은
   아무것도 판정하지 않는 것과 같다.

🔑 **부재를 증거로 쓰지 않는다 — 손이 「증인」이다.**
   존재는 검출로 확인되지만, 부재는 "정말 없다"와 "못 봤다"가 구별되지 않는다.
   손이 잡힌다 = 카메라가 그 자리를 제대로 보고 있다 = 그때만 "공구가 없다"를
   믿는다. 손이 안 보이면 **아무 판정도 하지 않는다**(카운터를 초기화하는 것도
   아니고 세는 것도 아니다). 그래서 고개를 돌리거나 화면이 흔들려도 오완료가
   나지 않는다.

   🔴 이 「일시정지」를 「초기화」로 구현하면 안 된다 — 손이 잠깐씩 끊기는 것이
      흔해서, 초기화로 만들면 완료가 영영 안 난다.

왜 연속 N회인가:
    관통 구멍이라 넣으면 화면에서 완전히 사라진다. 그런데 1프레임 미검출로
    완료하면 가림·거리 때문에 못 본 것을 넣은 것으로 오판한다. N회를 요구해
    그 확률을 낮춘다(N = config.TOOL_PLACED_COUNT).

⚠️ Qt·카메라·config 에 의존하지 않는다 — 검출 결과와 손끝 좌표를 **인자로
   받는다**(sub_task.py 와 같은 철학). GUI 없이 시험할 수 있어야 한다.

🔴 남는 위험: 손에 쥔 채 공구가 N회 내내 손에 가려 안 잡히면 오완료가 난다.
   완전히 막을 방법이 없어 시연 절차로 완화한다(설계 §9).
"""


class ToolState:
    """한 서브 작업의 공구 판정 상태.

    `update()` 가 돌려주는 값을 그대로 `SubTask.set_tool()` 에 넣으면 된다.
    """

    def __init__(self, want_tool, placed_count=3):
        self._want = want_tool
        self._need = max(1, int(placed_count))
        self._phase = "search"
        self._miss = 0

    # ------------------------------------------------------------------ 상태
    @property
    def phase(self):
        """"search" | "grasped" | "placed"."""
        return self._phase

    @property
    def want_tool(self):
        return self._want

    @property
    def miss_count(self):
        """현재 연속 미검출 횟수 — 로그·테스트용."""
        return self._miss

    # ------------------------------------------------------------------ 판정
    def update(self, dets, fingertip):
        """한 번의 스캔 결과를 먹인다.

        dets      = [(클래스명, 점수, x1, y1, x2, y2), ...] — **이미 임계로 걸러진 것**
        fingertip = (x, y) 또는 None(손이 안 보임)

        반환 = `SubTask.set_tool()` 에 넣을 값
            · 오답 공구를 쥐면 그 키   → wrong_tool 경고가 뜬다
            · 정답 공구를 쥐면 None    → 경고 없음, 게이트는 아직 닫힘
            · 넣음이 확정되면 want_tool → tool_ok, 시간까지 찼으면 게이트 열림
        """
        hand_seen = fingertip is not None

        if self._phase == "placed":
            return self._want                    # 한 번 완료되면 유지한다

        if self._phase == "search":
            if not hand_seen:
                return None
            held = self._held_tool(dets, fingertip)
            if held is None:
                return None
            if held == self._want:
                self._phase = "grasped"
                self._miss = 0
                return None                      # 쥐기만 했으니 아직 None
            return held                          # 오답 → 경고

        # ---- grasped: 「손은 보이는데 요구 공구가 없다」를 센다
        if not hand_seen:
            return None                          # 🔑 보류 — 세지도, 초기화하지도 않는다

        if any(d[0] == self._want for d in dets):
            self._miss = 0                       # 다시 보이면 처음부터
            return None

        self._miss += 1
        if self._miss >= self._need:
            self._phase = "placed"
            return self._want
        return None

    # ------------------------------------------------------------------ 보조
    @staticmethod
    def _held_tool(dets, fingertip):
        """손끝이 들어 있는 박스의 클래스명. 없으면 None.

        버튼의 `roi_zones.zone_at_point` 와 같은 원리이되 링/안쪽 2단계 구분 없이
        **박스 안이면 쥔 것**으로 단순화한다.

        여러 박스가 겹치면 **면적이 작은 쪽**을 택한다 — 큰 박스가 작은 박스를
        덮는 경우, 안쪽의 작은 것이 실제로 짚은 대상일 가능성이 높다.
        """
        fx, fy = fingertip
        best = None
        best_area = None
        for name, _score, x1, y1, x2, y2 in dets:
            if not (x1 <= fx <= x2 and y1 <= fy <= y2):
                continue
            area = max(0, x2 - x1) * max(0, y2 - y1)
            if best_area is None or area < best_area:
                best, best_area = name, area
        return best
