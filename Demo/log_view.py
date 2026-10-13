"""로그 창 — 줄 분류 · 거르기 · 색 HTML(시연 UI 개선 설계 2026-10-13 §4.5).

🔑 화면 표시 전용이다 — 로그 파일 · 측정 기록 형식은 바꾸지 않는다. 색은 theme 토큰.
"""
import html
import re

import theme

KEEP_LINES = 2000          # 거르기를 바꿀 때 다시 그릴 최근 줄 수(메모리 상한)
FILTERS = (("all", "전체"), ("alert", "경고·차단"), ("step", "단계"))
_TIME = re.compile(r"^(\[\d\d:\d\d:\d\d(?:\.\d+)?\])\s*(.*)$")
_ALERT = ("WARNING", "BLOCK", "경고", "차단", "EMO", "비상정지", "폴트")
_STEP = ("[버튼]", "[서브]", "[공구]", "단계", "작업 시작", "작업 초기화")


def kind(line):
    """줄 분류 — "alert"(경고 · 차단) / "step"(버튼 · 서브 작업 · 단계) / "other"."""
    if any(k in line for k in _ALERT):
        return "alert"
    if any(k in line for k in _STEP):
        return "step"
    return "other"


def keep(line, filt):
    return filt == "all" or kind(line) == filt


def to_html(line):
    """시각은 회색 · 본문은 분류 색 — 글은 이스케이프한다(로그에 < & 가 섞인다)."""
    m = _TIME.match(line)
    stamp, body = (m.group(1), m.group(2)) if m else ("", line)
    tok = {"alert": "warn_text", "step": "info", "other": "text"}[kind(line)]
    return (f'<span style="color:{theme.C("todo")}">{html.escape(stamp)}</span> '
            f'<span style="color:{theme.C(tok)}">{html.escape(body)}</span>')
