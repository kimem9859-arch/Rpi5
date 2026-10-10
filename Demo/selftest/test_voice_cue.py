"""음성비서 안내 소리 경로(측정 진행 도우미 설계 2026-10-11 D6 · D13③) — 가짜 스피커로.

실행: python3 Demo/selftest/test_voice_cue.py
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
    def __init__(self, ok=True):
        self.played, self.ok = [], ok

    def play(self, key, alog=None, still_valid=None):
        self.played.append(key)
        return self.ok


class FakeLog:
    enabled = True

    def __init__(self):
        self.ev = []

    def event(self, kind, t=None, **d):
        self.ev.append((kind, d))


def write_req(d, seq, key, age_ms=0.0):
    with open(os.path.join(d, "req.json"), "w", encoding="utf-8") as f:
        json.dump({"seq": seq, "key": key, "t_req_ms": measure_log.now_ms() - age_ms}, f)


def test_cue_watcher():
    print("\n[안내] 새 번호만 · cue_ 만 · 3초 넘은 요청은 버림 · 응답 파일 · 음성 사건")
    with tempfile.TemporaryDirectory() as d:
        va.VLOG = FakeLog()
        spk = FakeSpk()
        w = va.CueWatcher(spk, d=d)
        check(w.step() is None and spk.played == [], "요청 파일이 없으면 아무 일도 없다")
        write_req(d, 1, "cue_B2")
        check(w.step() == "cue_B2" and spk.played == ["cue_B2"], "새 요청 → 그 소리")
        check(w.step() is None and spk.played == ["cue_B2"], "같은 번호는 다시 내지 않는다")
        with open(os.path.join(d, "ack.json"), encoding="utf-8") as f:
            ack = json.load(f)
        check(ack["seq"] == 1 and ack["ok"] is True, f"응답 파일 = {ack}")
        write_req(d, 2, "alert_block_B1")
        check(w.step() is None and spk.played == ["cue_B2"], "cue_ 가 아닌 키는 버린다")
        write_req(d, 3, "cue_B3", age_ms=5000.0)
        check(w.step() is None and spk.played == ["cue_B2"], "3초 넘은 요청은 버린다(지난 세션 파일)")
        check([k for k, _ in va.VLOG.ev] == ["cue"] and va.VLOG.ev[0][1]["key"] == "cue_B2", f"{va.VLOG.ev}")
        check(not w.speaking.is_set(), "재생이 끝나면 말하는 중 표시가 풀린다")


def test_play_key():
    print("\n[재생 사건] 펌웨어 [재생] 줄 → play_start 에 소리 키(알림·안내를 세기가 가른다)")
    va.VLOG = FakeLog()
    va.vev_play_line("[재생] 1000샘플", "cue_B1")
    va.vev_play_line("[재생 완료]", "cue_B1")
    va.vev_play_line("[재생] 1000샘플")
    check(va.VLOG.ev == [("play_start", {"key": "cue_B1"}), ("play_end", {"what": "완료", "key": "cue_B1"}),
                         ("play_start", {"key": None})], f"{va.VLOG.ev}")


class _RaceSock:
    """보낸 소리마다 [적재] ok → [재생] → 0.6초 뒤 [재생 완료] 를 돌려주는 가짜 명령 채널(최종 리뷰 Important 4 재현)."""

    def __init__(self):
        import threading
        self.q, self.lock, self.to = [], threading.Lock(), 1.0

    def settimeout(self, t):
        self.to = t

    def sendall(self, b):
        import time
        if b and b[:1] == b"W":
            now = time.time()
            with self.lock:
                self.q += [(now, "[적재] ok\n".encode()), (now + 0.05, "[재생] 1000\n".encode()),
                           (now + 0.6, "[재생 완료]\n".encode())]

    def recv(self, n):
        import socket
        import time
        end = time.time() + (self.to or 0)
        while True:
            with self.lock:
                if self.q and self.q[0][0] <= time.time():
                    return self.q.pop(0)[1]
            if self.to == 0.0:
                raise BlockingIOError
            if time.time() > end:
                raise socket.timeout
            time.sleep(0.01)

    def close(self):
        pass


def test_play_key_race():
    print("\n[경쟁] 재생 중에 다른 소리를 내라고 해도 재생 사건의 소리 키가 자기 것이다(최종 리뷰 Important 4)")
    import threading
    import time

    class Spk(va.Speaker):
        def _ensure(self):
            if self.s is None:
                self.s = _RaceSock()

    va.VLOG = FakeLog()
    spk = Spk("0.0.0.0")
    a = threading.Thread(target=lambda: spk.play("alert_warn_B2"))
    a.start()
    time.sleep(0.2)
    b = threading.Thread(target=lambda: spk.play("cue_B3"))
    b.start()
    a.join()
    b.join()
    got = [(k, d.get("key")) for k, d in va.VLOG.ev if k in ("play_start", "play_end")]
    check(got == [("play_start", "alert_warn_B2"), ("play_end", "alert_warn_B2"),
                  ("play_start", "cue_B3"), ("play_end", "cue_B3")], f"{got}")


def main():
    test_cue_watcher()
    test_play_key()
    test_play_key_race()
    va.VLOG = measure_log.NullLog()
    print()
    if _fails:
        print(f"❌ {len(_fails)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
