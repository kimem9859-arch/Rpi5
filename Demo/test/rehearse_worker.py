"""가상 작업자 — 집 리허설에서 사람 대신 진행 도우미의 안내를 따라 시연을 누른다(학교 방문 준비 설계 §7.1).

main.py 가 SOP_REHEARSE_WORKER=1 일 때만 붙인다(시연 창 안 · QTimer 0.1초).
🔴 사람 흉내의 한계 — 손을 버튼 위에 올리는 「머묾」은 못 한다(카메라 장면이 녹화본이라) → 그 안내는 넘긴다(진행 도우미가 4초 뒤 다음으로).
"""
import csv
import io
import json
import os
import re
import time

import config
import measure_prompt
from fsm import State

REACT_MS = 800        # 안내를 듣고 누르기까지(사람 흉내)
START_GAP_MS = 1500   # 판 끝 → 다음 「작업 시작」
RELEASE_MS = 1500     # 경고 · 차단 배너 → 해제 버튼
END_IDLE_MS = 4000    # 판을 다 하고 → 창 닫기(세기가 돈다)
SAY_FILE = "rehearse_say.json"
SAY_TITLE = "🎤 지금 말하세요"


def action_for(cue_key):
    """진행 도우미 안내 키 → 할 일 · 머묾 · NG 안내는 None."""
    if cue_key == "cue_ng" or cue_key.startswith("cue_hover_"):
        return None
    if cue_key == "cue_reset":
        return ("reset",)
    if cue_key.startswith("cue_tool_"):
        return ("tool",)
    if cue_key.startswith("cue_"):
        return ("press", cue_key[4:])
    return None


def new_cues(path, pos):
    """guide.csv 의 pos(바이트) 뒤 **끝난 줄**에서 cue 키 → ([키], 새 pos) · 없으면 ([], pos)."""
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            chunk = f.read()
    except OSError:
        return [], pos
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], pos
    keys = []
    for row in csv.reader(io.StringIO(chunk[:end + 1].decode("utf-8"))):
        if len(row) < 3 or row[1] != "cue":
            continue
        try:
            k = json.loads(row[2]).get("key")
        except ValueError:
            continue
        if k:
            keys.append(k)
    return keys, pos + end + 1


def say_text(line):
    """말 띠 둘째 줄 「가디언」 → 「질문」 → 질문(마지막 꺾쇠) · 꺾쇠가 없으면 그대로."""
    found = re.findall(r"「([^」]*)」", line or "")
    return found[-1] if found else (line or "")


class Worker:
    def __init__(self, win, session_dir, runs_total, seconds=0, clock=None, shm_dir=None):
        self.win, self.runs_total, self.seconds = win, runs_total, seconds
        self.guide = os.path.join(session_dir, "guide.csv")
        self.shm = shm_dir or config.CUE_SHM_DIR
        self.clock = clock or (lambda: time.monotonic() * 1000)
        self._pos = 0
        self._due = []            # [(때 ms, 할 일)]
        self._started = 0
        self._ng = 0
        self._say_n = 0
        self._say_m = None
        self._idle_since = None
        self._alert_since = None
        self._t_first = None

    def _say(self):
        p = measure_prompt.read(self.shm)
        m = measure_prompt.mtime(self.shm)
        if p and p[0].startswith(SAY_TITLE) and m != self._say_m:
            self._say_m = m
            self._say_n += 1
            os.makedirs(self.shm, exist_ok=True)
            tmp = os.path.join(self.shm, SAY_FILE + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"n": self._say_n, "text": say_text(p[1])}, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(self.shm, SAY_FILE))
        return p is not None

    def _do(self, a):
        w = self.win
        if a[0] == "press":
            w._press_button(a[1])
        elif a[0] == "tool":
            w._sim_tool_grasped()
        elif a[0] == "reset":
            w._reset_work()

    def tick(self):
        now, w = self.clock(), self.win
        keys, self._pos = new_cues(self.guide, self._pos)
        for k in keys:
            if k == "cue_ng":
                self._ng += 1                                   # 진행 도우미가 「다시」 — 판 하나를 더 한다
            a = action_for(k)
            if a:
                self._due.append((now + REACT_MS, a))
        band = self._say()
        for item in [x for x in self._due if x[0] <= now]:
            self._due.remove(item)
            self._do(item[1])
        mode = getattr(w.alert, "mode", None)
        if mode in ("block", "order"):
            self._alert_since = self._alert_since if self._alert_since is not None else now
            if now - self._alert_since >= RELEASE_MS:
                w._on_alert_release()
                self._alert_since = None
        else:
            self._alert_since = None
        if self.seconds and self._t_first is not None and now - self._t_first >= self.seconds * 1000:
            w.close()
            self.seconds = 0
            self.runs_total = -1                                # 다시 닫지 않게
            return
        if w.fsm.state != State.IDLE or self._due:
            self._idle_since = None
            return
        self._idle_since = self._idle_since if self._idle_since is not None else now
        idle = now - self._idle_since
        if not w.result_panel.isHidden():
            if idle >= START_GAP_MS:
                w._close_result()
                self._idle_since = now
            return
        want = (1 if self.seconds else self.runs_total + self._ng)
        if self._started < want and not band and idle >= START_GAP_MS:
            w._on_cta()
            self._started += 1
            self._t_first = self._t_first if self._t_first is not None else now
            self._idle_since = None
        elif self._started >= want and not self.seconds and self.runs_total >= 0 and idle >= END_IDLE_MS:
            w.close()
            self.runs_total = -1


def _runs_in_session(d):
    """세션 폴더의 대본 → 판 수(없으면 0)."""
    import measure_script as MS
    for n in sorted(os.listdir(d)):
        if n.endswith(".csv") and n not in ("frames.csv", "boxes.csv", "env.csv", "events.csv", "fsm.csv",
                                            "guide.csv", "voice_events.csv"):
            try:
                return len({r["판"] for r in MS.load_script(os.path.join(d, n))})
            except ValueError:
                return 0
    return 0


def attach(win):
    """시연 창에 붙인다 — SOP_MEASURE_DIR(세션) · SOP_REHEARSE_RUNS · SOP_REHEARSE_SECONDS."""
    from PyQt6.QtCore import QTimer
    d = os.environ.get("SOP_MEASURE_DIR") or ""
    runs = _runs_in_session(d) if d else 0
    cap = int(os.environ.get("SOP_REHEARSE_RUNS", "0") or 0)
    if cap:
        runs = min(runs, cap) if runs else cap
    wk = Worker(win, d, runs, seconds=float(os.environ.get("SOP_REHEARSE_SECONDS", "0") or 0))
    t = QTimer(win)
    t.timeout.connect(wk.tick)
    t.start(100)
    wk.timer = t
    print(f"[리허설] 가상 작업자 — 판 {runs} · 초 {wk.seconds}", flush=True)
    return wk
