"""작업 완료 결과 안내창 — 정본: 상위 specs/2026-08-19-자동진행-결과창-design.md §3

무엇을 보이나: 판정 · 누른 순서 · 소요시간 · 순서위반 · 차단 · 카메라 미확인 · 공구 · 검출.

🔑 모양(2026-10-14 사용자 요청 「결과를 선명하게 · 오른쪽 스크롤 막대」) — 메뉴 · 설정과 같은 각진 판 ·
   RESULT 머리 → 판정 띠(초록 완주 / 빨강 · 주황 위반) → 숫자 칸 4개 → 칸으로 나눈 자세한 내용(스크롤).
   위반이 있으면 「순서 위반」 · 「차단」 칸이 맨 위로 온다.

🔴 **오탐지 건수를 보이지 않는다** — 정답 라벨 없이는 셀 수 없다(§3.4).
🔴 **검출을 비율(%)로 보이지 않는다** — 손 없는 프레임이 분모에 섞인다.
   「검출 프레임 / 전체 프레임」 두 수를 그대로 적는다.
🔴 화면 맨 아래에 **관측치이지 모델 성능이 아니라는 문장**을 반드시 적는다.
"""

import re
import time

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import (QLabel, QVBoxLayout, QScrollArea, QWidget,
                             QHBoxLayout, QFrame, QScroller)

import config
import theme
from overlay import place, cut_corner_path, _qcolor
from overlay_menu import _Sheet

_RESULT_W = 0.52          # 화면 폭 대비 — 표가 들어가야 해 설정(0.30)보다 넓다
_SCROLL_W = 30            # 오른쪽 스크롤 막대 폭(px) — 손가락으로 잡을 수 있게(사용자 10/14)


def _hhmmss(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}분 {s}초" if m else f"{s}초"


def _stamp(ts):
    return time.strftime("%Y.%m.%d %H:%M:%S", time.localtime(ts))


def _clock(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _font(role, weight, pt=None):
    f = config.font(role, weight)
    if pt:
        f.setPointSize(pt)
    return f


class _Plate(QWidget):
    """각진 판 하나 — 판정 띠 · 숫자 칸 · 내용 칸이 같이 쓴다.

    tone 이 있으면 그 색으로 옅게 채우고 테두리 · 왼쪽 굵은 띠를 칠한다(판정 띠).
    accent 가 있으면 위쪽에 그 색 선을 긋는다(숫자 칸).
    """

    def __init__(self, cut=12, tone=None, accent=None, parent=None):
        super().__init__(parent)
        self.cut, self.tone, self.accent = cut, tone, accent

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRect(0, 0, self.width() - 1, self.height() - 1)
        path = cut_corner_path(r, self.cut)
        if self.tone:
            p.fillPath(path, _qcolor(theme.rgba(self.tone, 0.14)))
            p.setClipPath(path)
            p.fillRect(QRect(0, 0, 10, self.height()), _qcolor(theme.C(self.tone)))
            p.setClipping(False)
            p.setPen(QPen(_qcolor(theme.C(self.tone)), 2))
        else:
            p.fillPath(path, _qcolor(theme.rgba("text", 0.05)))
            p.setPen(QPen(_qcolor(theme.rgba("text", 0.12)), 1))
        p.drawPath(path)
        if self.accent:
            p.setClipPath(path)
            p.fillRect(QRect(0, 0, self.width(), 4), _qcolor(theme.C(self.accent)))
        p.end()


class ResultPanel(_Sheet):
    """작업 완료 결과. 내용이 길어 스크롤한다.

    🔴 `closed` 시그널을 여기서 다시 선언하지 않는다 — 기반 클래스 `_Sheet.closed`
       를 가려, 기반 클래스 타입으로 connect 한 곳이 조용히 끊긴다.
    """

    CUT = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self._painted = []                # (라벨, 색 토큰, 굵기, 덧붙인 QSS) — 테마를 바꾸면 다시 칠한다
        self._plates = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(34, 30, 34, 24)
        lay.setSpacing(16)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(4)
        self._tag = QLabel("RESULT")
        self._tag.setFont(_font("item_sub", 700))
        self._title = QLabel("작업 결과")
        self._title.setFont(_font("sheet_title", 800))
        self._sub = QLabel("")
        self._sub.setFont(_font("item_sub", 500))
        for w in (self._tag, self._title, self._sub):
            col.addWidget(w)
        head.addLayout(col)
        head.addStretch()
        head.addWidget(self._make_close_button(), 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        # 판정 띠 — 다시 채울 때마다 안을 바꾼다(톤이 바뀌므로)
        self._band = _Plate(cut=18)
        bl = QHBoxLayout(self._band)
        bl.setContentsMargins(36, 20, 30, 20)
        bl.setSpacing(22)
        self._mark = QLabel("")
        self._mark.setFixedSize(64, 64)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mark.setFont(_font("sheet_title", 900, 28))
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self._verdict = QLabel("")
        self._verdict.setFont(_font("sheet_title", 900, 38))
        self._verdict_sub = QLabel("")
        self._verdict_sub.setFont(_font("sub", 600, 16))
        tcol.addWidget(self._verdict)
        tcol.addWidget(self._verdict_sub)
        bl.addWidget(self._mark)
        bl.addLayout(tcol, 1)
        lay.addWidget(self._band)

        # 숫자 칸 4개
        self._tiles_row = QHBoxLayout()
        self._tiles_row.setSpacing(12)
        lay.addLayout(self._tiles_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 🔑 막대를 늘 보인다 — 터치로 끌어 올리기가 잘 안 먹어 막대를 잡고 내리게 한다(사용자 10/14)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        # 손가락으로 내용 자체를 끌어도 움직이게 — 마우스 끌기는 그대로(글자 선택 · 막대 잡기와 겹치지 않게 터치만)
        QScroller.grabGesture(self._scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 18, 0)
        self._body_lay.setSpacing(12)
        self._scroll.setWidget(self._body)
        lay.addWidget(self._scroll, 1)

        # 🔴 이 문장을 빼지 않는다 — 1회 관측치가 성능으로 읽히면 안 된다(§3.4).
        self._note = QLabel("이 값은 이번 1회 시연에서 관측된 수치이며 모델 성능이 아닙니다.")
        self._note.setFont(_font("small", 600))
        self._note.setWordWrap(True)
        lay.addWidget(self._note)

        self._tone = "done"
        self.hide()

    # ------------------------------------------------------------------ 표시
    def show_result(self, d):
        self._painted = []
        self._plates = [self._band]
        for lay in (self._body_lay, self._tiles_row):
            for i in reversed(range(lay.count())):
                item = lay.takeAt(i)
                if item.widget():
                    item.widget().setParent(None)

        ok = d.get("ok", True)
        vs = d["violations"]
        ils = d["interlocks"]
        ucs = d.get("unconfirmed") or []      # 옛 데이터엔 키가 없다
        steps = d["steps"]

        # 머리 — 언제 · 무엇을
        when = d.get("finished_at") or time.time()
        name = d.get("recipe") or ""
        bits = [time.strftime("%Y.%m.%d %H:%M", time.localtime(when))]
        if name:
            bits.append(name)
        if steps:
            bits.append(f"{len(steps)}단계")
        self._sub.setText(" · ".join(bits))

        # 판정 띠 — 차단이 있으면 빨강 · 경고만이면 주황
        self._tone = "done" if ok else ("danger" if ils else "warn")
        self._band.tone = self._tone
        self._verdict.setText("완주 성공" if ok else "위반 있음")
        self._mark.setText("✓" if ok else "!")
        if ok:
            self._verdict_sub.setText(f"순서 위반 없이 {len(steps)}단계를 모두 마쳤습니다" if steps
                                      else "순서 위반 없이 마쳤습니다")
        else:
            self._verdict_sub.setText(f"순서 위반 {len(vs)}건 · 차단 {len(ils)}건이 있었습니다")

        # 숫자 칸 — 0 = 초록 · 1 이상 = 빨강(카메라 미확인은 주황)
        def count_tone(n, bad):
            return bad if n else "done"
        for label, value, tone in (
                ("총 소요 시간", _hhmmss(d["total_sec"]), "text"),
                ("순서 위반", f"{len(vs)}건", count_tone(len(vs), "danger")),
                ("차단", f"{len(ils)}건", count_tone(len(ils), "danger")),
                ("카메라 미확인", f"{len(ucs)}건", count_tone(len(ucs), "warn"))):
            self._tiles_row.addWidget(self._tile(label, value, tone), 1)

        # 자세한 내용 — 위반이 있으면 위반 · 차단이 먼저
        sec_viol = (f"순서 위반 {len(vs)}건", [
            (f"{i}. {_clock(v['at'])} — 기대 {v['expected']} → 실제 {v['actual']}",
             "차단" if v["level"] == "block" else "경고",
             "danger" if v["level"] == "block" else "warn")
            for i, v in enumerate(vs, 1)])
        sec_lock = (f"차단 {len(ils)}건", [
            f"{i}. {_clock(x['at'])} 차단"
            + (f" → {_clock(x['released_at'])} 해제" if x["released_at"] else " (해제 안 됨)")
            for i, x in enumerate(ils, 1)])
        sec_order = ("누른 순서", [" → ".join(s["button"] for s in steps) or "—"])
        sec_time = ("단계별 소요 시간", [
            (f"{s['order']}. {s['button']} {s['name']}", _hhmmss(s["sec"]), "text")
            for s in steps])
        sec_unc = (f"카메라 미확인 {len(ucs)}건", [
            f"{i}. {_stamp(u['at'])} — {u['order']}단계 {u['button']}"
            for i, u in enumerate(ucs, 1)])

        # 🔑 공구는 키(wrench)가 아니라 표시명(렌치)으로 보인다 — 나머지 UI 와 같게.
        names = d.get("tool_names") or {}

        def tname(key):
            return names.get(key, key)

        tool_rows = []
        for t in d["tools"]:
            if t["grasp_sec"] is not None:
                tool_rows.append((f"{t['button']} — 요구 {tname(t['want'])}",
                                  f"{t['grasp_sec']:.1f}초 만에 쥠", "done"))
            else:
                tool_rows.append((f"{t['button']} — 요구 {tname(t['want'])}", "쥐지 않음", "warn"))
            if t["wrong"]:
                # 🔴 **횟수**를 보인다 — 종류 수가 아니다(설계 §3.3).
                total = sum(t["wrong"].values())
                detail = ", ".join(f"{tname(k)} {n}회"
                                   for k, n in sorted(t["wrong"].items()))
                tool_rows.append(f"다른 공구 {total}회: {detail}")
        sec_tool = ("공구 서브 작업", tool_rows)

        det = d["detections"]
        frames = d["frames"]
        tool_keys = set(getattr(config, "TOOL_BOX_COLORS", {})) | set(names)
        det_rows = [f"전체 {frames} 프레임"]
        det_tool = []
        for nm in sorted(det):
            v = det[nm]
            (det_tool if nm in tool_keys else det_rows).append(
                self._det_line(tname(nm) if nm in tool_keys else nm, v))

        order = [sec_viol, sec_lock, sec_order, sec_time] if not ok else [sec_order, sec_time, sec_viol, sec_lock]
        for title, rows in order + [sec_unc, sec_tool, ("AI 검출", det_rows)]:
            self._section(title, rows)
        if det_tool:
            # 🔴 공구는 분모가 다르다 — 같은 표에 놓으면 「거의 안 잡혔다」로 읽힌다.
            self._section("AI 검출 — 공구", det_tool + [
                "공구는 약 1초에 1회만 추론하므로 위 전체 프레임 수와 분모가 다릅니다"])
        self._body_lay.addStretch()

        self.apply_theme()
        self._scroll.verticalScrollBar().setValue(0)
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

    # ------------------------------------------------------------------ 부품
    def _label(self, text, font, tone="text", weight=600, extra="", wrap=True):
        lbl = QLabel(text)
        lbl.setFont(font)
        lbl.setWordWrap(wrap)
        self._painted.append((lbl, tone, weight, extra))
        return lbl

    def _tile(self, label, value, tone):
        """숫자 칸 — 이름 작게 · 값 크게(숫자는 크게 · 단위는 작게)."""
        plate = _Plate(cut=12, accent=tone if tone != "text" else None)
        self._plates.append(plate)
        cl = QVBoxLayout(plate)
        cl.setContentsMargins(20, 18, 16, 14)
        cl.setSpacing(2)
        cl.addWidget(self._label(label, _font("item_sub", 600, 14), "label", 600))
        # 숫자만 크게 — 「1분 5초」처럼 숫자와 단위가 번갈아 와도 그대로 나눈다
        big = re.sub(r"(\D+)", r'<span style="font-size:20pt; font-weight:700;">\1</span>', value)
        v = self._label(big, _font("sheet_title", 900, 34), tone, 900, wrap=False)
        v.setTextFormat(Qt.TextFormat.RichText)
        cl.addWidget(v)
        return plate

    def _section(self, title, rows):
        """내용 칸 — 노란 제목 + 줄들. 줄이 (왼쪽, 오른쪽, 색) 이면 값을 오른쪽 끝에 붙인다."""
        plate = _Plate(cut=12)
        self._plates.append(plate)
        cl = QVBoxLayout(plate)
        cl.setContentsMargins(22, 16, 22, 16)
        cl.setSpacing(8)
        head = self._label(title, _font("sub", 800, 16), "current_text", 800)
        if not rows:
            # 빈 칸은 한 줄로 — 숫자 칸이 이미 0건을 보여 주므로 자리를 덜 쓴다
            cl.setContentsMargins(22, 12, 22, 12)
            h = QHBoxLayout()
            h.addWidget(head, 1)
            h.addWidget(self._label("없음", _font("body", 600, 17), "label", 600, wrap=False))
            cl.addLayout(h)
            self._body_lay.addWidget(plate)
            return
        cl.addWidget(head)
        for i, row in enumerate(rows):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFixedHeight(1)
                self._painted.append((line, "line", 0, ""))
                cl.addWidget(line)
            if isinstance(row, tuple):
                left, right, tone = row
                h = QHBoxLayout()
                h.setSpacing(16)
                h.addWidget(self._label(left, _font("body", 600, 17)), 1)
                h.addWidget(self._label(right, _font("body", 800, 17), tone, 800, wrap=False))
                cl.addLayout(h)
            else:
                cl.addWidget(self._label(row, _font("body", 600, 17)))
        self._body_lay.addWidget(plate)

    # ------------------------------------------------------------------ 테마 · 배치
    def apply_theme(self):
        super().apply_theme()
        self._tag.setStyleSheet(theme.text_qss("current_text", 700) + "letter-spacing: 6px;")
        self._title.setStyleSheet(theme.text_qss("text", 800))
        self._sub.setStyleSheet(theme.text_qss("label", 500))
        self._verdict.setStyleSheet(theme.text_qss(self._tone, 900))
        self._verdict_sub.setStyleSheet(theme.text_qss("text", 600))
        ink = "warn_ink" if self._tone == "warn" else "sheet_bg" if self._tone == "done" else "danger_ink"
        self._mark.setStyleSheet(f"background: {theme.C(self._tone)}; color: {theme.C(ink)};"
                                 " border-radius: 32px; font-weight: 900;")
        self._note.setStyleSheet(theme.text_qss("todo", 600))
        for w, tone, weight, extra in self._painted:
            if tone == "line":
                w.setStyleSheet(f"background-color: {theme.rgba('text', 0.08)}; border: none;")
            else:
                w.setStyleSheet(theme.text_qss(tone, weight) + extra + "background: transparent;")
        for pl in self._plates:
            pl.update()
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget > QWidget { background: transparent; }"
            f" QScrollBar:vertical {{ background: {theme.rgba('text', 0.08)}; width: {_SCROLL_W}px;"
            " margin: 0; border: none; }"
            f" QScrollBar::handle:vertical {{ background: {theme.C('current_text')}; min-height: 80px;"
            " border: none; border-radius: 0; }"
            " QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            " QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }")
        self._body.setStyleSheet("background: transparent;")

    def relayout(self, parent_rect):
        place(self, parent_rect, width=_RESULT_W, top=0.07, height=0.86)
