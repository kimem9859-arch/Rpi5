"""음성비서 — 시연 안내 모드의 색 이름 알림 · 음성 사건 거울(상위 specs/2026-10-18-시연안내모드-design.md §4.1 · §6.2).

실행: python3 Demo/selftest/test_voice_guide.py
🔴 안내 모드가 꺼져 있으면 지금과 같아야 한다 — 알림 키 그대로 · voice.json 을 쓰지 않는다.
"""
import json
import os
import sys
import tempfile

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import measure_log
import voice_assistant as va

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class FakeSpk:
    def __init__(self):
        self.played = []

    def play(self, key, alog=None, still_valid=None):
        self.played.append(key)
        return True

    def stop(self):
        pass


class FakeLog:
    enabled = True

    def __init__(self):
        self.ev = []

    def event(self, kind, t=None, **d):
        self.ev.append((kind, d))

    def close(self, timeout=5.0):
        self.closed = True


def _touch(d, name):
    open(os.path.join(d, name), "wb").close()


def test_alert_key_off_unchanged():
    print("\n[알림 키] 끔 — _c 파일이 있어도 원래 키")
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "alert_warn_B3_c.wav")
        check(va.alert_key_for("alert_warn_B3", False, d) == "alert_warn_B3", "끔 = 원래 키")


def test_alert_key_on():
    print("\n[알림 키] 켬 — _c 가 있으면 그것 · 없으면 원래 키")
    with tempfile.TemporaryDirectory() as d:
        _touch(d, "alert_warn_B3_c.wav")
        check(va.alert_key_for("alert_warn_B3", True, d) == "alert_warn_B3_c", "켬 + 파일 있음 = _c")
        check(va.alert_key_for("alert_block_B1", True, d) == "alert_block_B1", "켬 + 파일 없음 = 원래 키(안전)")


def test_alert_watcher_uses_key_for():
    print("\n[알림] AlertWatcher 가 key_for 로 고른 키를 낸다")
    va.VLOG = FakeLog()
    spk = FakeSpk()
    st = {"세션": True, "상태": "MONITOR", "현재버튼": "B3", "pid": 1}
    w = va.AlertWatcher(spk, read_state=lambda: dict(st), key_for=lambda k: k + "_c")
    w.step()
    st["상태"] = "WARNING"
    w.step()
    check(spk.played == ["alert_warn_B3_c"], f"경고 → 색 이름판({spk.played})")
    w2 = va.AlertWatcher(FakeSpk(), read_state=lambda: dict(st, 상태="MONITOR"))
    w2.step()
    st2 = dict(st, 상태="BLOCK")
    w2._read = lambda: st2
    w2.step()
    check(w2.spk.played == ["alert_block_B3"], f"key_for 없으면 원래 키({w2.spk.played})")


def test_guide_flag_cache():
    print("\n[안내 모드] 상태 파일 안내모드 칸 · 0.3초 묶어 읽기 · 유령이면 끔")
    calls, now = [], [0.0]
    st = {"안내모드": True}

    def rd():
        calls.append(1)
        return st

    f = va.GuideFlag(read_state=rd, ttl=0.3, clock=lambda: now[0])
    check(f() is True, "안내모드 참 → 참")
    now[0] = 0.1
    f()
    check(len(calls) == 1, f"0.3초 안에는 다시 읽지 않는다(읽음 {len(calls)})")
    now[0] = 0.5
    st["안내모드"] = False
    check(f() is False and len(calls) == 2, "0.3초 뒤 다시 읽어 끔")
    g = va.GuideFlag(read_state=lambda: None, ttl=0.3, clock=lambda: 0.0)
    check(g() is False, "상태 없음(유령 · 파일 없음) = 끔")


def test_mirror_off_writes_nothing():
    print("\n[거울] 끔 — voice.json 을 쓰지 않는다")
    with tempfile.TemporaryDirectory() as d:
        m = va.GuideMirror(d=d, on=lambda: False)
        m.event("wake")
        check(not os.path.exists(os.path.join(d, "voice.json")), "파일 없음")


def test_mirror_on_keeps_kinds():
    print("\n[거울] 켬 — 정한 사건만 · 시각 ms · 최근 keep 개")
    with tempfile.TemporaryDirectory() as d:
        m = va.GuideMirror(d=d, on=lambda: True, keep=3)
        t0 = measure_log.now_ms()
        m.event("wake")
        m.event("voice_config", quick=True)
        m.event("play_end", what="중단", key="cue_g3_1")
        with open(os.path.join(d, "voice.json"), encoding="utf-8") as f:
            v = json.load(f)
        kinds = [e[1] for e in v["events"]]
        check(kinds == ["wake", "play_end"], f"목록 밖 사건은 빼고 차례대로({kinds})")
        check(v["events"][1][2] == {"what": "중단", "key": "cue_g3_1"}, "사건 내용 그대로")
        check(v["events"][0][0] >= t0 and v.get("pid") == os.getpid(), "시각 = 단조 ms · pid")
        for k in ("alert", "alert_played", "alert_clear"):
            m.event(k, key="alert_warn_B3")
        with open(os.path.join(d, "voice.json"), encoding="utf-8") as f:
            v = json.load(f)
        check([e[1] for e in v["events"]] == ["alert", "alert_played", "alert_clear"], "keep 넘으면 오래된 것부터 빠진다")


def test_mirror_threads():
    print("\n[거울] 여러 스레드가 동시에 써도 사건이 사라지지 않고 파일이 깨지지 않는다(리뷰 M1)")
    import threading
    with tempfile.TemporaryDirectory() as d:
        m = va.GuideMirror(d=d, on=lambda: True, keep=10_000)
        errs = []
        orig = va.log
        va.log = lambda msg: errs.append(msg)
        try:
            ths = [threading.Thread(target=lambda n=n: [m.event("cue", key=f"t{n}-{i}") for i in range(150)]) for n in range(4)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
        finally:
            va.log = orig
        with open(os.path.join(d, "voice.json"), encoding="utf-8") as f:
            v = json.load(f)
        check(len(v["events"]) == 600, f"사건 600개 그대로({len(v['events'])})")
        check(not errs, f"쓰기 오류 없음({errs[:1]})")


def test_tee_passthrough():
    print("\n[겹] TeeLog — 둘 다에 · 나머지 속성은 원래 기록으로")
    base = FakeLog()
    got = []

    class M:
        def event(self, kind, t=None, **d):
            got.append(kind)

    t = va.TeeLog(base, M())
    t.event("wake")
    check(base.ev == [("wake", {})] and got == ["wake"], "사건이 둘 다에 간다")
    check(t.enabled is True, "enabled 는 원래 기록의 값")
    t.close()
    check(getattr(base, "closed", False), "close 는 원래 기록으로")
    n = va.TeeLog(measure_log.NullLog(), M())
    check(n.enabled == measure_log.NullLog().enabled, "NullLog 도 그대로")

    class Bad:
        def event(self, kind, t=None, **d):
            raise OSError("쓰기 실패")

    b = FakeLog()
    va.TeeLog(b, Bad()).event("wake")
    check(b.ev == [("wake", {})], "거울이 터져도 원래 기록은 남고 예외가 올라오지 않는다")


if __name__ == "__main__":
    for fn in (test_alert_key_off_unchanged, test_alert_key_on, test_alert_watcher_uses_key_for, test_guide_flag_cache,
               test_mirror_off_writes_nothing, test_mirror_on_keeps_kinds, test_mirror_threads, test_tee_passthrough):
        try:
            fn()
        except Exception as e:                       # noqa: BLE001
            check(False, f"{fn.__name__} 예외: {type(e).__name__}: {e}")
    if _fails:
        print(f"\n❌ {len(_fails)}건 실패")
        sys.exit(1)
    print("\n✅ 음성비서 시연 안내 시험 통과")
