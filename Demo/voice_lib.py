"""음성비서 판정 로직 — 소켓·모델에 의존하지 않는 순수 함수만 둔다.

정본: ../docs/superpowers/specs/2026-09-06-음성비서-시연구현-design.md

🔑 왜 갈라 두나 — 소켓·모델이 붙은 코드는 HW 없이 못 돌린다. 판정만 빼 두면
   1초 안에 도는 selftest 가 되고, 촬영 현장에서 임계나 호출어 목록을 고쳐야
   할 때 근거가 된다(tool_state.py 와 같은 철학).
"""
import json
import math
import os
import time

try:
    import numpy as _np           # 🔑 있으면 쓴다 — 없으면 순수 파이썬으로 돈다
except ImportError:               # pragma: no cover
    _np = None

# 🔑 실측된 오인식을 그대로 받아들인다 — §10.51 에서 「가디언」이 이렇게 튀었다
#    (가디건·가디얀·가디현, 0/4 적중). 이 목록 덕에 사실상 4/4 가 된다.
WAKE_WORDS = ("가디언", "가디건", "가디얀", "가디현")

# 공구 질문 — 「보이다」 계열 또는 「공구」 + 「무엇」 계열이 함께 있으면 그것으로 본다.
_TOOL_HINTS = ("보이", "보여", "공구")
_WHAT_HINTS = ("뭐", "무엇", "뭔")

# 🔴 런타임 모델(tool_v3)의 클래스명. tool_v4 는 `-in-hand` 접미어가 붙는다.
_TOOL_KEYS = ("driver", "wrench", "pliers")

TOOL_SHM = "/dev/shm/sop_tool/resp.json"
FRESH_SEC = 3.0          # 🔴 공구 추론은 wait_tool 동안에만 돈다 — 낡으면 「단계 아님」


def _norm(text):
    """공백·문장부호를 지운다 — STT 는 띄어쓰기를 자주 다르게 낸다."""
    return "".join(c for c in (text or "") if not c.isspace() and c not in ",.?!·")


def is_wake(text):
    """호출어가 들어 있는가."""
    n = _norm(text)
    return any(w in n for w in WAKE_WORDS)


def is_tool_question(text):
    """「지금 보이는 공구가 무엇인가」를 묻는가."""
    n = _norm(text)
    return any(h in n for h in _TOOL_HINTS) and any(h in n for h in _WHAT_HINTS)


def rms(samples):
    """DC 오프셋을 뺀 실효값.

    🔴 PDM 마이크는 1000~1600 의 오프셋을 함께 낸다 — 빼지 않으면 무음도 커
       보여 VAD 가 늘 켜진다(2026-08-26 에 실제로 물린 함정).
    """
    n = len(samples)
    if n == 0:
        return 0.0
    dc = sum(samples) / n
    return math.sqrt(sum((s - dc) ** 2 for s in samples) / n)


def _frame_rms(samples, fr):
    """20ms 프레임마다의 RMS 를 한 번에 낸다.

    🔴 순수 파이썬으로 매 청크마다 전체 버퍼를 훑으면 **실시간을 못 따라간다**
       (2026-09-06 오프라인 리허설에서 4.5초 오디오 처리에 5초가 걸렸다).
       그래서 numpy 가 있으면 벡터로 계산한다.
    """
    n = (len(samples) // fr) * fr
    if n == 0:
        return []
    if _np is not None:
        a = _np.asarray(samples[:n], dtype=_np.float64).reshape(-1, fr)
        a = a - a.mean(axis=1, keepdims=True)      # 프레임마다 DC 제거
        return _np.sqrt((a * a).mean(axis=1)).tolist()
    return [rms(samples[i:i + fr]) for i in range(0, n, fr)]


def find_utterance(samples, rate, start_th=600, end_th=300,
                   min_ms=300, tail_ms=700, pre_ms=250):
    """말이 시작된 지점과 끝난 지점 `(start, end)`. 없으면 None.

    20ms 프레임의 RMS 를 보고 `start_th` 를 넘으면 시작, `end_th` 아래가
    `tail_ms` 만큼 이어지면 끝으로 본다.

    🔑 `pre_ms` — 시작을 그만큼 **앞당겨** 잡는다. 임계를 넘는 순간은 이미
       첫 음절의 한복판이라, 그대로 자르면 STT 가 앞을 잃는다. 실제로
       「가디언」이 「바디원」으로 들렸다(2026-09-06 리허설).

    🔴 **길이 미달 구간에서 멈추지 않는다.** 짧은 잡음이 먼저 잡히면 그것만
       보고 None 을 돌려주던 버그가 있었다 — 뒤에 있는 진짜 발화를 통째로
       놓쳤다(2026-09-06 리허설에서 RMS 11166 인 구간을 못 봤다).

    ⚠️ `tail_ms` 기본값이 700ms 인 이유 — 500ms 면 **문장 중간 쉼에서 잘린다.**
       "가디언, 지금 다음 순서 뭐야?" 가 2.43초에서 끊겼다(원본 4.5초).
    """
    fr = max(1, int(rate * 0.02))
    vals = _frame_rms(samples, fr)
    tail_frames = max(1, int(tail_ms / 20))
    pre = int(rate * pre_ms / 1000)
    min_len = rate * min_ms / 1000
    start = None
    quiet = 0
    for k, v in enumerate(vals):
        i = k * fr
        if start is None:
            if v >= start_th:
                start, quiet = max(0, i - pre), 0
        else:
            quiet = quiet + 1 if v < end_th else 0
            if quiet >= tail_frames:
                end = i - quiet * fr
                if end - start >= min_len:
                    return start, end
                start, quiet = None, 0      # 🔴 너무 짧다 — 버리고 계속 찾는다
    if start is not None and len(samples) - start >= min_len:
        return start, len(samples)
    return None


def read_tool_dets(path=TOOL_SHM, fresh_sec=FRESH_SEC, now=None):
    """`(dets, fresh)` — 공구 검출과 그것이 신선한지.

    🔴 공구 추론은 `wait_tool` 서브 작업 동안에만 돈다(camera_thread.py:242).
       파일이 낡았으면 「지금 확인하는 단계가 아니다」로 답한다 —
       **부재를 근거로 지어내지 않는다**(tool_state.py 와 같은 원칙).
    """
    try:
        st = os.stat(path)
    except OSError:
        return [], False
    if (now or time.time()) - st.st_mtime > fresh_sec:
        return [], False
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f).get("dets") or []
    except (OSError, ValueError):
        return [], False
    # dets = [(클래스명, 점수, x1, y1, x2, y2), ...] — tool_gate.py:145 와 같은 모양
    return [tuple(d) for d in raw], True


def answer_key(dets, fresh):
    """재생할 wav 키. make_answers.ANSWERS 의 키와 정확히 같아야 한다."""
    if not fresh:
        return "notstep"
    best, best_score = None, -1.0
    for d in dets or []:
        # 🔑 tool_v4 부터 `wrench-in-hand` 처럼 접미어가 붙는다 — 벗긴다.
        name = str(d[0]).split("-in-hand")[0].strip()
        if name not in _TOOL_KEYS:
            continue
        score = float(d[1])
        if score > best_score:
            best, best_score = name, score
    return best or "none"
