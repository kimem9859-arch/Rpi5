"""가상 작업자 · 말하는 가짜 안경(학교 방문 준비 설계 §7.1).

실행: python3 Demo/selftest/test_rehearse_worker.py
"""
import json
import os
import socket
import struct
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import rehearse_worker as RW
from fsm import State

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _Hidden:
    def __init__(self):
        self.hidden = True

    def isHidden(self):
        return self.hidden


class _Win:
    """시연 창 흉내 — 부른 함수를 적는다."""

    def __init__(self):
        self.calls = []
        self.fsm = type("F", (), {"state": State.IDLE})()
        self.alert = type("A", (), {"mode": None})()
        self.result_panel = _Hidden()

    def _on_cta(self):
        self.calls.append("cta")
        self.fsm.state = State.PROCESS_RUN

    def _press_button(self, b):
        self.calls.append(f"press:{b}")

    def _sim_tool_grasped(self):
        self.calls.append("tool")

    def _reset_work(self):
        self.calls.append("reset")

    def _on_alert_release(self):
        self.calls.append("release")
        self.alert.mode = None

    def _close_result(self):
        self.calls.append("close_result")
        self.result_panel.hidden = True

    def close(self):
        self.calls.append("close")


def _cue(path, t, key, run=1):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f'{t},cue,"{json.dumps({"run": run, "key": key}).replace(chr(34), chr(34) * 2)}"\n')


def test_action_for():
    print("\n[가상 작업자] 안내 키 → 할 일")
    cases = {"cue_B2": ("press", "B2"), "cue_EMO": ("press", "EMO"), "cue_tool_wrench": ("tool",),
             "cue_reset": ("reset",), "cue_hover_B4": None, "cue_ng": None}
    for k, want in cases.items():
        check(RW.action_for(k) == want, f"{k} → {RW.action_for(k)}")


def test_new_cues_partial_line():
    print("\n[가상 작업자] guide.csv 새 줄만 · 끝이 잘린 줄은 다음에")
    d = tempfile.mkdtemp()
    p = os.path.join(d, "guide.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("t_ms,kind,data\n")
    _cue(p, 1, "cue_B1")
    with open(p, "a", encoding="utf-8") as f:
        f.write('2,say,"{""run"": 1}"\n')
    _cue(p, 3, "cue_B2")
    with open(p, "a", encoding="utf-8") as f:
        f.write('4,cue,"{""run"": 1, ""ke')
    keys, pos = RW.new_cues(p, 0)
    check(keys == ["cue_B1", "cue_B2"], f"두 키 → {keys}")
    with open(p, "a", encoding="utf-8") as f:
        f.write('y"": ""cue_B3""}"\n')
    keys, pos = RW.new_cues(p, pos)
    check(keys == ["cue_B3"], f"마저 써진 줄 → {keys}")
    check(RW.new_cues(os.path.join(d, "없음.csv"), 0) == ([], 0), "파일이 없으면 빈 목록")


def test_say_text():
    print("\n[가상 작업자] 말 띠 → 질문")
    check(RW.say_text("「가디언」 → 「지금 몇 단계야」") == "지금 몇 단계야", "꺾쇠 마지막 것")
    check(RW.say_text("「작업 끝났어?」") == "작업 끝났어?", "하나뿐")
    check(RW.say_text("그냥 글") == "그냥 글", "꺾쇠 없음")


def test_worker_flow():
    print("\n[가상 작업자] 시작 → 안내대로 누름 → 경고 해제 → 결과창 닫기 → 판 수 채우면 닫기")
    d = tempfile.mkdtemp()
    g = os.path.join(d, "guide.csv")
    with open(g, "w", encoding="utf-8") as f:
        f.write("t_ms,kind,data\n")
    shm = os.path.join(d, "shm")
    now = [0.0]
    win = _Win()
    w = RW.Worker(win, d, runs_total=1, clock=lambda: now[0], shm_dir=shm)

    def run(ms):
        end = now[0] + ms
        while now[0] < end:
            now[0] += 100
            w.tick()

    run(1400)
    check(win.calls == [], "1.4초까지 시작 안 함")
    run(200)
    check(win.calls == ["cta"], f"1.5초에 작업 시작 → {win.calls}")
    _cue(g, 1, "cue_B1")
    run(700)
    check("press:B1" not in win.calls, "0.7초 = 아직")
    run(200)
    check(win.calls[-1] == "press:B1", f"0.8초 뒤 누름 → {win.calls}")
    win.alert.mode = "block"
    run(1600)
    check(win.calls[-1] == "release", f"차단 1.5초 뒤 해제 → {win.calls}")
    _cue(g, 2, "cue_ng")
    win.fsm.state = State.IDLE
    win.result_panel.hidden = False
    run(1600)
    check(win.calls[-1] == "close_result", f"결과창 닫기 → {win.calls}")
    os.makedirs(shm, exist_ok=True)
    import measure_prompt
    measure_prompt.write("🎤 지금 말하세요", "「가디언」 → 「지금 몇 단계야」", d=shm)
    run(3000)
    say = json.load(open(os.path.join(shm, RW.SAY_FILE), encoding="utf-8"))
    check(say == {"n": 1, "text": "지금 몇 단계야"}, f"말하기 요청 {say}")
    check(win.calls.count("cta") == 1, f"띠가 떠 있는 동안 다음 판을 시작하지 않는다 → {win.calls}")
    measure_prompt.clear(d=shm)
    run(1600)
    check(win.calls.count("cta") == 2, f"NG 한 번 → 판 하나 더 → {win.calls}")
    win.fsm.state = State.IDLE
    run(4100)
    check(win.calls[-1] == "close", f"판 수를 채우고 4초 뒤 닫기 → {win.calls}")


def test_worker_seconds():
    print("\n[가상 작업자] 대본 없는 회차 — 시작 뒤 정한 초에 닫기")
    now = [0.0]
    win = _Win()
    w = RW.Worker(win, tempfile.mkdtemp(), runs_total=0, seconds=60, clock=lambda: now[0],
                  shm_dir=tempfile.mkdtemp())
    for _ in range(620):
        now[0] += 100
        w.tick()
    check(win.calls[0] == "cta" and win.calls[-1] == "close" and win.calls.count("close") == 1, f"{win.calls}")


def test_live_glass():
    print("\n[말하는 가짜 안경] 요청한 소리를 바로 흘린다")
    import rehearse_glass as RG
    g = RG.LiveGlass(mic_port=0, cmd_port=0, noise_rms=0, quiet=True).start()
    try:
        s = socket.create_connection(("127.0.0.1", g.mic_port), timeout=3)
        s.recv(4096)
        g.say([12000, -12000] * 800)                   # 🔑 말소리처럼 평균 0 — 가짜 안경이 소리 평균을 빼므로(같은 값만 이으면 0)
        t0, hit = time.monotonic(), False
        while time.monotonic() - t0 < 1.5 and not hit:
            b = s.recv(4096)
            hit = any(v > 1400 + 10000 for v in struct.unpack(f"<{len(b) // 2}h", b[:len(b) // 2 * 2]))
        check(hit, "말소리가 1.5초 안에 온다")
        s.close()
    finally:
        g.stop()


if __name__ == "__main__":
    test_action_for()
    test_new_cues_partial_line()
    test_say_text()
    test_worker_flow()
    test_worker_seconds()
    test_live_glass()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 가상 작업자 검증 통과")
