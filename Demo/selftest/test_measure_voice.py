"""음성 데몬 측정 기록(측정 도구 정합 ⑤ V1~V9) — 가짜 상태·스피커로.

실행: python3 Demo/selftest/test_measure_voice.py
"""
import csv
import json
import os
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import measure_log as ML
import state_publisher
import voice_assistant as va

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_publisher_has_mono():
    print("\n[음성 기록] 상태 공개에 단조 시각이 함께")
    d = tempfile.mkdtemp()
    p = state_publisher.StatePublisher(d)
    t0 = time.monotonic()
    p.publish({"세션": True})
    with open(os.path.join(d, "state.json"), encoding="utf-8") as f:
        rec = json.load(f)
    check("쓴시각" in rec and abs(rec["쓴시각_mono"] - t0) < 1.0, f"{rec}")


def test_voice_events():
    print("\n[음성 기록] 재생 시작·끝 · 업링크(모듈 함수)")
    d = tempfile.mkdtemp()
    va.VLOG = ML.MeasureLog(d, ["voice_events"], event_file="voice_events")
    va.vev_play_line("[재생] ok")
    va.vev_play_line("[재생 완료]")
    va.vev_play_line("[재생 중단]")
    va.vev_uplink(32000, True)
    va.VLOG.close()
    va.VLOG = ML.NullLog()
    with open(os.path.join(d, "voice_events.csv"), encoding="utf-8", newline="") as f:
        rs = list(csv.DictReader(f))
    check([r["kind"] for r in rs][:4] == ["play_start", "play_end", "play_end", "uplink"], f"{[r['kind'] for r in rs]}")
    check(json.loads(rs[2]["data"]) == {"what": "중단"}, f"중단 표시 {rs[2]}")


class _FakeSpk:
    last_play_start = None

    def stop(self):
        return True

    def play(self, key, alog, still_valid=None):
        return True


def test_alert_events_match_log():
    print("\n[음성 기록] 알림 감시 — 받음(alert)·재생 마침(alert_played)·풀림(alert_clear) = 데몬 로그 줄과 같은 자리")
    d = tempfile.mkdtemp()
    va.VLOG = ML.MeasureLog(d, ["voice_events"], event_file="voice_events")
    run = {"pid": 1, "세션": True, "상태": "PROCESS RUN", "현재버튼": "B2"}      # test_voice_loop 의 STATE 모양
    warn = dict(run, 상태="WARNING", 쓴시각=time.time(), 쓴시각_mono=time.monotonic())
    seq = [run, warn, run]
    w = va.AlertWatcher(_FakeSpk(), read_state=lambda: seq.pop(0), alog=None)
    said = []
    orig_log, va.log = va.log, said.append
    try:
        w.step()                                   # 직전 상태를 익힘(사건 없음)
        w.step()                                   # 알림(재생 스레드 없음 → 그 자리에서 _play)
        w.step()                                   # 풀림
    finally:
        va.log = orig_log
        va.VLOG.close()
        va.VLOG = ML.NullLog()
    with open(os.path.join(d, "voice_events.csv"), encoding="utf-8", newline="") as f:
        kinds = [r["kind"] for r in csv.DictReader(f)]
    n_play_log = sum("🔔 알림 →" in s for s in said)
    n_clear_log = sum("알림 상황이 풀렸다" in s for s in said)
    check(kinds.count("alert") == 1 and kinds.count("alert_played") == n_play_log == 1, f"{kinds} · 로그 {said}")
    check(kinds.count("alert_clear") == n_clear_log == 1, f"{kinds} · 로그 {said}")


def test_mic_bytes():
    print("\n[음성 기록] 업링크 누적 바이트")
    import voice_mic
    m = voice_mic.MicReceiver(lambda: "127.0.0.1", 1)
    check(hasattr(m, "bytes_total") and m.bytes_total == 0, "bytes_total 시작 0")



def test_sigterm_closes_log():
    print("\n[음성 기록] 세션 끝 SIGTERM 에도 기록을 닫는다 — measure_end 가 남는다(리뷰 I-1)")
    import subprocess
    d = tempfile.mkdtemp()
    code = (
        "import os, signal, sys, time\n"
        f"sys.path.insert(0, {_DEMO_DIR!r})\n"
        "import measure_log as ML, voice_assistant as va\n"
        "va.VLOG = ML.open_from_env(['voice_events'], event_file='voice_events')\n"
        "va.exit_on_sigterm()\n"
        "try:\n"
        "    va.VLOG.event('alert', key='k')\n"
        "    os.kill(os.getpid(), signal.SIGTERM)\n"
        "    time.sleep(3)\n"
        "finally:\n"
        "    va.VLOG.close()\n")
    r = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, SOP_MEASURE_DIR=d),
                       capture_output=True, text=True, timeout=30)
    path = os.path.join(d, "voice_events.csv")
    kinds = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as f:
            kinds = [x["kind"] for x in csv.DictReader(f)]
    check(r.returncode == 0 and kinds == ["alert", "measure_end"], f"rc={r.returncode} {kinds} {r.stderr[-200:]}")


def test_stt_event_before_answer():
    print("\n[음성 기록] 받아쓰기 사건은 판단(on_text) 전에 — 판단이 실패해도 남는다(리뷰 M-3)")
    import numpy as np
    d = tempfile.mkdtemp()
    va.VLOG = ML.MeasureLog(d, ["voice_events"], event_file="voice_events")

    class _Bot:
        def alert_gen(self):
            return 0

        def on_text(self, text, m, gen0=None):
            raise RuntimeError("판단 실패")

    class _Alog:
        def utterance(self, samples, text):
            pass
    orig_log, va.log = va.log, (lambda m: None)
    try:
        va.handle_utterance(_Bot(), lambda s: "가디언 지금 몇 단계", _Alog(), np.zeros(1600, dtype=np.int16))
    except RuntimeError:
        pass
    finally:
        va.log = orig_log
        va.VLOG.close()
        va.VLOG = ML.NullLog()
    with open(os.path.join(d, "voice_events.csv"), encoding="utf-8", newline="") as f:
        kinds = [x["kind"] for x in csv.DictReader(f)]
    check("stt" in kinds, f"{kinds}")


if __name__ == "__main__":
    test_publisher_has_mono()
    test_voice_events()
    test_alert_events_match_log()
    test_mic_bytes()
    test_sigterm_closes_log()
    test_stt_event_before_answer()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 음성 측정 기록 검증 통과")
