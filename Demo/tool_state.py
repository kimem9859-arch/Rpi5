"""공구 지참 판정 — 서브 작업(wait_tool)의 두 마디 상태기계.

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §4.3·§4.4

무엇을 판정하나:
    ① 찾기  — 요구 공구를 아직 쥐지 않았다
    ② 쥠    — 손끝이 요구 공구 박스 안에 들어왔다 (🔒 여기서 완료·유지)

🔑 **판정 대상은 「보이는 공구」가 아니라 「쥔 공구」다.**
   시연 시나리오는 3종(드라이버·렌치·플라이어)을 종류별 1개씩 책상에 두므로
   **3종이 동시에 보이는 것이 정상**이다. 그중 점수가 높은 것을 고르는 것은
   아무것도 판정하지 않는 것과 같다.

🔑 **부재를 근거로 쓰지 않는다.**
   존재는 검출로 확인되지만, 부재는 "정말 없다"와 "못 봤다"가 구별되지 않는다.
   그래서 **「공구가 안 보인다」로는 어떤 판정도 하지 않는다.** 손이 보일 때
   검출된 박스만 근거가 된다.

🔴 **2026-08-16 개정 — 「넣음」 마디를 없앴다.** 경위 = 통합문서 §10.44.
   종전 3마디는 「손은 보이는데 요구 공구가 안 보임」이 N회 연속이면 **지정
   공간에 넣은 것**으로 봤다. 실HW 검증에서 **쥔 공구를 모델이 놓치기만 해도
   완료가 나는 오완료**가 실제로 발생했다(§10.44-(3)). 부재를 증거로 쓰는 한
   미검출과 「넣음」은 구별할 수 없다 — 그래서 그 근거 자체를 버렸다.
   덤으로 「지정 공간에 넣었다」의 판정 기준을 정할 필요도 사라졌다.

⚠️ 완료는 **유지된다**(되돌아가지 않는다). 렌치를 쥐고 다음 동작으로
   누르러 가는 동안 손끝은 공구 박스를 벗어나는데, 매 프레임 재판정하면
   완료가 풀려 버튼을 누를 수 없다. 대신 **잘못 확정되면 서브 작업을 리셋해야만
   복구된다.**

⚠️ Qt·카메라·config 에 의존하지 않는다 — 검출 결과와 손끝 좌표를 **인자로
   받는다**(sub_task.py 와 같은 철학). GUI 없이 시험할 수 있어야 한다.

🔴 남는 위험: 공구를 쥐지 않고 손이 그 위를 지나가기만 해도 확정된다. 손끝이
   박스 안이라는 것과 쥐었다는 것은 다르다 — 시연 절차로 완화한다(설계 §9).
"""


class ToolState:
    """한 서브 작업의 공구 판정 상태.

    `update()` 가 돌려주는 값을 그대로 `SubTask.set_tool()` 에 넣으면 된다.
    """

    def __init__(self, want_tool):
        self._want = want_tool
        self._phase = "search"

    # ------------------------------------------------------------------ 상태
    @property
    def phase(self):
        """"search" | "grasped"."""
        return self._phase

    @property
    def want_tool(self):
        return self._want

    # ------------------------------------------------------------------ 판정
    def update(self, dets, fingertip):
        """한 번의 스캔 결과를 먹인다.

        dets      = [(클래스명, 점수, x1, y1, x2, y2), ...] — **이미 임계로 걸러진 것**
        fingertip = (x, y) 또는 None(손이 안 보임)

        반환 = `SubTask.set_tool()` 에 넣을 값
            · 오답 공구를 쥐면 그 키   → wrong_tool 경고가 뜬다
            · 요구 공구를 쥐면 want_tool → tool_ok, 시간까지 찼으면 게이트 열림
            · 그 밖에는 None
        """
        if self._phase == "grasped":
            return self._want                    # 한 번 확정되면 유지한다

        if fingertip is None:
            return None                          # 🔑 손이 안 보이면 판정하지 않는다

        held = self._held_tool(dets, fingertip)
        if held is None:
            return None
        if held == self._want:
            self._phase = "grasped"
            return self._want
        return held                              # 오답 → 경고

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
