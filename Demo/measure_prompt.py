"""측정 화면 띠 파일 — 진행 도우미가 쓰고 시연 화면이 읽는다(측정 진행 도우미 설계 2026-10-11 §10 · D19·D20).

음성 줄(호출·질문·비상질문)을 「언제 무엇을 말할지」 콘솔 화면 맨 아래 띠에 글로 보인다 — 소리로는 내지 않는다
(사용자 「음성 안내가 음성비서에 들어 갈 것 같아서」). 🔴 순수 모듈(Qt 없음) — 형식의 단일 출처.
파일 = config.CUE_SHM_DIR/prompt.json {"title", "line"} · 없거나 비면 띠를 숨긴다.
"""
import json
import os

import config

NAME = "prompt.json"


def _path(d=None):
    return os.path.join(d or config.CUE_SHM_DIR, NAME)


def write(title, line, d=None):
    """띠에 보일 두 줄 — 원자적으로 바꾼다(시연 화면이 반쯤 쓴 파일을 읽지 않게)."""
    d = d or config.CUE_SHM_DIR
    os.makedirs(d, exist_ok=True)
    tmp = _path(d) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"title": title, "line": line}, f, ensure_ascii=False)
    os.replace(tmp, _path(d))


def clear(d=None):
    """띠를 숨긴다 — 파일을 지운다(없어도 괜찮다)."""
    try:
        os.remove(_path(d))
    except OSError:
        pass


def read(d=None):
    """→ (title, line) 또는 None(없음 · 깨짐 · 빈 글)."""
    try:
        with open(_path(d), encoding="utf-8") as f:
            x = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(x, dict) or not (x.get("title") or x.get("line")):
        return None
    return str(x.get("title") or ""), str(x.get("line") or "")


def mtime(d=None):
    """파일 바뀜 확인용(ns) — 없으면 None."""
    try:
        return os.stat(_path(d)).st_mtime_ns
    except OSError:
        return None
