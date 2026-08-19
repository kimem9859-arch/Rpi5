"""작업 완료 결과 안내창 — 정본: 상위 specs/2026-08-19-자동진행-결과창-design.md §3

무엇을 보이나: 판정 · 누른 순서 · 소요시간 · 순서위반 · 인터락 · 공구 · 검출.

🔴 **오탐지 건수를 보이지 않는다** — 정답 라벨 없이는 셀 수 없다(§3.4).
🔴 **검출을 비율(%)로 보이지 않는다** — 손 없는 프레임이 분모에 섞인다.
   「검출 프레임 / 전체 프레임」 두 수를 그대로 적는다.
🔴 화면 맨 아래에 **관측치이지 모델 성능이 아니라는 문장**을 반드시 적는다.
"""

import time

from PyQt6.QtWidgets import (QLabel, QVBoxLayout, QScrollArea, QWidget,
                             QHBoxLayout)

import config
import theme
from overlay import place
from overlay_menu import _Sheet

_RESULT_W = 0.52          # 화면 폭 대비 — 표가 들어가야 해 설정(0.30)보다 넓다


def _hhmmss(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}분 {s}초" if m else f"{s}초"


def _stamp(ts):
    return time.strftime("%Y.%m.%d %H:%M:%S", time.localtime(ts))


class ResultPanel(_Sheet):
    """작업 완료 결과. 내용이 길어 스크롤한다.

    🔴 `closed` 시그널을 여기서 다시 선언하지 않는다 — 기반 클래스 `_Sheet.closed`
       를 가려, 기반 클래스 타입으로 connect 한 곳이 조용히 끊긴다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        self._title = QLabel("작업 완료")
        self._title.setFont(config.font("title", 800))
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(self._make_close_button())
        lay.addLayout(head)

        self._verdict = QLabel("")
        self._verdict.setFont(config.font("body", 800))
        lay.addWidget(self._verdict)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(10)
        self._scroll.setWidget(self._body)
        lay.addWidget(self._scroll, 1)

        # 🔴 이 문장을 빼지 않는다 — 1회 관측치가 성능으로 읽히면 안 된다(§3.4).
        self._note = QLabel("이 값은 이번 1회 시연에서 관측된 수치이며 모델 성능이 아닙니다.")
        self._note.setFont(config.font("small"))
        self._note.setWordWrap(True)
        lay.addWidget(self._note)

        self.hide()

    # ------------------------------------------------------------------ 표시
    def show_result(self, d):
        for i in reversed(range(self._body_lay.count())):
            w = self._body_lay.itemAt(i).widget()
            if w:
                w.setParent(None)

        ok = d.get("ok", True)
        self._verdict.setText("✅ 완주 성공" if ok else "⚠ 위반이 있었습니다")
        self._verdict.setStyleSheet(theme.text_qss("done" if ok else "warn", 800))

        order = " → ".join(s["button"] for s in d["steps"])
        self._section("누른 순서", [order or "—"])
        self._section("소요 시간", [f"총 {_hhmmss(d['total_sec'])}"] + [
            f"{s['order']}. {s['button']} {s['name']} — {_hhmmss(s['sec'])}"
            for s in d["steps"]])

        vs = d["violations"]
        self._section(f"순서 위반 {len(vs)}건", [
            f"{i}. {_stamp(v['at'])} — 기대 {v['expected']} → 실제 {v['actual']}"
            f" ({'차단' if v['level'] == 'block' else '경고'})"
            for i, v in enumerate(vs, 1)] or ["없음"])

        ils = d["interlocks"]
        self._section(f"인터락 작동 {len(ils)}건", [
            f"{i}. {_stamp(x['at'])} 작동"
            + (f" → {_stamp(x['released_at'])} 해제" if x["released_at"] else " (해제 안 됨)")
            for i, x in enumerate(ils, 1)] or ["없음"])

        # 🔑 공구는 키(wrench)가 아니라 표시명(렌치)으로 보인다 — 나머지 UI 와 같게.
        names = d.get("tool_names") or {}

        def tname(key):
            return names.get(key, key)

        rows = []
        for t in d["tools"]:
            got = f"{t['grasp_sec']:.1f}초 만에 쥠" if t["grasp_sec"] is not None else "쥐지 않음"
            rows.append(f"{t['button']} — 요구 {tname(t['want'])} · {got}")
            if t["wrong"]:
                # 🔴 **횟수**를 보인다 — 종류 수가 아니다(설계 §3.3).
                total = sum(t["wrong"].values())
                detail = ", ".join(f"{tname(k)} {n}회"
                                   for k, n in sorted(t["wrong"].items()))
                rows.append(f"    다른 공구 {total}회: {detail}")
        self._section("공구 서브 작업", rows or ["없음"])

        det = d["detections"]
        frames = d["frames"]
        tool_keys = set(getattr(config, "TOOL_BOX_COLORS", {})) | set(names)
        rows = [f"전체 {frames} 프레임"]
        tool_rows = []
        for name in sorted(det):
            v = det[name]
            (tool_rows if name in tool_keys else rows).append(
                self._det_line(tname(name) if name in tool_keys else name, v))
        self._section("AI 검출", rows)
        if tool_rows:
            # 🔴 공구는 분모가 다르다 — 같은 표에 놓으면 「거의 안 잡혔다」로 읽힌다.
            self._section("AI 검출 — 공구", tool_rows + [
                "공구는 약 1초에 1회만 추론하므로 위 전체 프레임 수와 분모가 다릅니다"])

        self.apply_theme()
        self.show()
        self.raise_()

    @staticmethod
    def _det_line(name, v):
        """검출 한 줄. 🔴 점수 표본이 없으면 신뢰도를 **적지 않는다** —
        자리표시자를 평균 내면 근거 없는 「평균 신뢰도 1.00」이 나간다."""
        n = v.get("score_frames", 0)
        if not n:
            return f"{name} — 검출 {v['frames']} 프레임"
        return (f"{name} — 검출 {v['frames']} 프레임 · "
                f"평균 신뢰도 {v['score_sum'] / n:.2f}")

    def _section(self, title, lines):
        cap = QLabel(title)
        cap.setFont(config.font("small", 700))
        cap.setStyleSheet(theme.text_qss("label", 700))
        self._body_lay.addWidget(cap)
        for line in lines:
            lbl = QLabel(line)
            lbl.setFont(config.font("body", 600))
            lbl.setWordWrap(True)
            lbl.setStyleSheet(theme.text_qss("text", 600))
            self._body_lay.addWidget(lbl)

    def apply_theme(self):
        super().apply_theme()
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._note.setStyleSheet(theme.text_qss("todo", 600))
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._body.setStyleSheet("background: transparent;")

    def relayout(self, parent_rect):
        place(self, parent_rect, width=_RESULT_W, top=0.10, height=0.72)
