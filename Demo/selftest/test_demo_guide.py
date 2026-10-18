"""시연 안내 프로그램 — 문장별 시작 조건 · 알림 비키기 · 다르게 했을 때(상위 specs/2026-10-18-시연안내모드-design.md §4.2 · §4.3 · §6.3~§6.5).

실행: python3 Demo/selftest/test_demo_guide.py   (가짜 시계 · 가짜 상태 · 가짜 음성비서 — 장치 없음)
World = 시연 프로그램 상태(st) · 손 파일(hand) · 음성 사건(voice) · 응답(ack)을 흉내 낸다.
  · 안내가 낸 소리는 clip_ms 뒤 끝난다(play_end 완료 + ack) — 알림이 나는 동안은 기다린다(스피커 한 줄)
  · 상태가 경고 · 차단 · 비상정지로 바뀌면 알림 사건(alert → alert_ms 뒤 alert_played) · 풀리면 alert_clear
  · 알림 시작 · 풀림은 재생 중인 안내 소리를 끊는다(play_end 중단 + ack) — 음성비서 spk.stop 과 같다
Actor = 참여자 흉내 — 문장이 끝나면 그 문장이 시킨 일을 한다(시험이 바꿀 수 있다).
"""
import os
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import demo_guide as dg

_fails = []
SENT = dg.load_sentences()


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


ALARM = ("WARNING", "BLOCK")


def _alarm(st):
    if not st or not st.get("세션"):
        return "emo" if (st or {}).get("비상정지") else None
    if st.get("비상정지"):
        return "emo"
    return st.get("상태") if st.get("상태") in ALARM else None


class World:
    def __init__(self, clip_ms=500, alert_ms=2800, ack_mode="ok"):
        self.core = dg.GuideCore(SENT)
        self.now = 1_000_000.0
        self.st = {"pid": 1, "세션": False, "안내모드": True, "비상정지": False}
        self.hand = {"roi": None, "level": 0, "공구단계": None, "손판정끔": False, "pid": 1}
        self.voice, self.ack = [], None
        self.clip_ms, self.alert_ms, self.ack_mode = clip_ms, alert_ms, ack_mode
        self.playing = None          # (sid, key, seq, end)
        self.alert_end = None
        self.said = []               # (sid, key)
        self.todo = []               # (t, fn)
        self.on_done = None          # fn(sid) — 문장 끝(마지막 소리 ack)
        self.ghost = False

    # --- 장치 흉내
    def set(self, **kv):
        old = _alarm(self.st)
        self.st.update(kv)
        new = _alarm(self.st)
        if new and new != old:
            self._cut()
            self.voice.append([self.now, "alert", {"key": new}])
            self.alert_end = self.now + self.alert_ms
        elif old and not new:
            self._cut()
            self.voice.append([self.now, "alert_clear", {}])
            self.alert_end = None

    def sub(self, **kv):
        p = dict(self.st.get("서브진행") or {"상태": "진행 중", "공구충족": False, "공구오답": None})
        p.update(kv)
        self.set(서브진행=p)

    def _cut(self):
        if self.playing:
            sid, key, seq, _ = self.playing
            self.voice.append([self.now, "play_end", {"what": "중단", "key": key}])
            self.ack = {"seq": seq, "ok": True}
            self.playing = None

    def later(self, ms, fn):
        self.todo.append((self.now + ms, fn))

    def start(self):
        if self.core.prev is None:
            self.step()                  # 🔑 작업 전 상태를 한 번 본 뒤에 시작 — 처음 본 상태가 작업 중이면 그 회차는 건너뛴다(설계)
        self.set(세션=True, 현재단계=1, 현재버튼="B1", 상태="PROCESS RUN", 서브진행=None, 결과=None)

    def step(self, ms=100):
        self.now += ms
        for t, fn in sorted([x for x in self.todo if x[0] <= self.now], key=lambda x: x[0]):
            self.todo.remove((t, fn))
            fn()
        if self.alert_end is not None and self.now >= self.alert_end:
            self.voice.append([self.now, "alert_played", {}])
            self.alert_end = None
        if self.playing and self.alert_end is None and self.now >= self.playing[3]:
            sid, key, seq, _ = self.playing
            self.voice.append([self.now, "play_end", {"what": "완료", "key": key}])
            self.ack = {"seq": seq, "ok": True}
            self.playing = None
            if self.on_done and key == SENT[sid][-1]:
                self.on_done(sid)
        st = None if self.ghost else dict(self.st)
        r = self.core.tick(self.now, st, dict(self.hand), [list(e) for e in self.voice], self.ack)
        if r is not None:
            self.said.append((r.sid, r.key))
            if self.ack_mode == "fail":
                self.ack = {"seq": r.seq, "ok": False}
                if self.on_done and r.key == SENT[r.sid][-1]:
                    self.on_done(r.sid)
            elif self.ack_mode == "ok":
                self.voice.append([self.now, "play_start", {"key": r.key}])
                self.playing = (r.sid, r.key, r.seq, self.now + self.clip_ms)
        return r

    def run(self, ms):
        end = self.now + ms
        while self.now < end:
            self.step()

    def until(self, pred, max_ms=180_000):
        end = self.now + max_ms
        while self.now < end:
            self.step()
            if pred():
                return True
        return False

    def sids(self):
        """지금까지 낸 문장 번호(한 문장의 첫 소리마다 한 번 · 다시 내면 또 센다)."""
        return [s for s, k in self.said if k == SENT[s][0]]


class Actor:
    """참여자 흉내 — 문장이 끝나면 시킨 일을 한다. skip = 하지 않을 문장 · over = 바꿔 할 일."""

    def __init__(self, w, skip=(), over=None):
        self.w, self.skip, self.over = w, set(skip), over or {}
        w.on_done = self.done

    def done(self, sid):
        if sid in self.skip:
            return
        fn = self.over.get(sid) or getattr(self, "a_" + sid.replace("-", "_"), None)
        if fn:
            self.w.later(800, fn)

    # --- 대본대로
    def press_wait(self, btn, nxt_step, nxt_btn, wait_ms=5000):
        w = self.w
        w.set(현재버튼=btn)
        w.sub()
        w.later(wait_ms, lambda: w.set(현재단계=nxt_step, 현재버튼=nxt_btn, 서브진행=None))

    def a_3_1(self):
        self.press_wait("B1", 2, "B2")

    def a_5_2(self):
        w = self.w
        w.hand.update(roi="B3", level=2)
        w.later(200, lambda: w.hand.update(roi=None, level=0))

    def a_6_1(self):
        self.w.set(현재버튼="B2")
        self.w.sub()

    def a_7_2(self):
        self.w.sub(공구오답="드라이버")
        self.w.hand.update(공구단계="search", 손판정끔=True)

    def a_8_1(self):
        self.w.sub(공구오답=None)
        self.w.hand.update(손판정끔=False)

    def a_9_2(self):
        w = self.w
        w.hand.update(공구단계="checking", 손판정끔=True)
        w.later(1500, lambda: (w.hand.update(공구단계="grasped"),
                               w.set(현재단계=3, 현재버튼="B3", 서브진행=None)))

    def a_9_5(self):
        self.w.hand.update(손판정끔=False, 공구단계=None)

    def a_10_2(self):
        self.w.hand.update(roi="B2", level=2)
        self.w.set(상태="WARNING")

    def a_11_1(self):
        self.w.hand.update(roi=None, level=0)
        self.w.set(상태="MONITOR")

    def a_12_2(self):
        self.w.set(상태="WARNING")
        self.w.later(300, lambda: self.w.set(상태="BLOCK"))

    def a_13_1(self):
        self.w.set(상태="PROCESS RUN")

    def a_14_1(self):
        self.press_wait("B3", 4, "B4")

    def a_15_1(self):
        w = self.w
        w.voice.append([w.now, "wake", {}])
        w.voice.append([w.now + 900, "stt", {"text": "지금 몇 단계야"}])
        w.later(1500, lambda: w.voice.append([w.now, "answer", {"src": "즉답", "key": None}]))
        w.later(4000, lambda: w.voice.append([w.now, "play_end", {"what": "완료", "key": None}]))

    def a_16_1(self):
        self.w.set(현재단계=4, 결과={"위반": 1})


NORMAL = ["1-1", "1-2", "1-3", "2-1", "3-1", "4-1", "4-2", "5-1", "5-2", "5-3", "6-1", "6-2", "7-1", "7-2", "8-1",
          "9-1", "9-2", "9-3", "9-4", "9-5", "10-1", "10-2", "11-1", "12-1", "12-2", "13-1", "14-1", "14-2", "14-3",
          "15-1", "16-1", "16-2"]


def _normal(w=None, **kw):
    w = w or World()
    Actor(w, **kw)
    w.start()
    return w


# ------------------------------------------------------------------ 정상
def test_normal_run():
    print("\n[정상] 16장면 · §4.3 차례 그대로")
    w = _normal()
    ok = w.until(lambda: "16-2" in w.sids() and w.playing is None)
    check(ok and w.sids() == NORMAL, f"문장 차례({w.sids()})")
    keys = [k for s in NORMAL for k in SENT[s]]
    check([k for _, k in w.said] == keys, "소리 키 = 문장들의 키를 이은 것")
    w.run(20_000)
    check(w.sids() == NORMAL, "끝난 뒤에는 말하지 않는다")


# ------------------------------------------------------------------ 시작 조건 · 차례
def test_waits_for_sound_and_condition():
    print("\n[차례] 4-2 = 4-1 소리 끝 AND 대기 끝")
    w = World(clip_ms=3000)
    a = Actor(w, over={"3-1": lambda: None})
    w.start()
    w.until(lambda: "3-1" in w.sids())
    w.until(lambda: w.playing is None)
    w.set(현재버튼="B1")
    w.sub()
    w.until(lambda: "4-1" in w.sids())
    w.set(현재단계=2, 현재버튼="B2", 서브진행=None)          # 4-1 이 나가는 중에 대기 끝
    w.step()
    check("4-2" not in w.sids(), "4-1 소리가 끝나기 전에는 4-2 없음")
    w.until(lambda: "4-2" in w.sids(), 10_000)          # 4-1 = 소리 둘(각 3초)
    check("4-2" in w.sids(), "소리가 끝나면 4-2")
    w2 = World()
    Actor(w2, over={"3-1": lambda: (w2.set(현재버튼="B1"), w2.sub())})
    w2.start()
    w2.until(lambda: "4-1" in w2.sids() and w2.playing is None)
    w2.run(3000)
    check("4-2" not in w2.sids(), "소리가 끝나도 대기가 안 끝나면 4-2 없음")
    del a


def test_start_signals():
    print("\n[시작] 세션 거짓→참 · 결과 있음→없음 · 켬/끔")
    w = World()
    w.run(1000)
    check(w.said == [], "작업 시작 전에는 말하지 않는다")
    w.start()
    w.until(lambda: "1-1" in w.sids(), 2000)
    check(w.sids()[:1] == ["1-1"], "세션 거짓→참 = 1-1")
    w2 = World()
    w2.set(세션=True, 현재단계=4, 결과={"위반": 0}, 상태="IDLE")
    w2.run(1000)
    check(w2.said == [], "완료 화면(결과 있음)에서 켜면 말하지 않는다")
    w2.set(결과=None, 현재단계=1, 현재버튼="B1", 상태="PROCESS RUN")
    w2.until(lambda: "1-1" in w2.sids(), 2000)
    check(w2.sids()[:1] == ["1-1"], "두 번째 참여자 — 결과 있음→없음 = 1-1")
    w3 = World()
    w3.st["안내모드"] = False
    w3.start()
    w3.run(1000)
    w3.set(안내모드=True)
    w3.run(5000)
    check(w3.said == [], "작업 도중 켜면 그 회차는 말하지 않는다")
    w4 = _normal()
    w4.until(lambda: "1-2" in w4.sids())
    w4.set(안내모드=False)
    n = len(w4.said)
    w4.run(10_000)
    check(len(w4.said) == n, "끄면 바로 멈춘다")


def test_ghost_files_ignored():
    print("\n[유령] 상태 파일이 없거나 못 믿으면 말하지 않는다")
    w = World()
    w.ghost = True
    w.start()
    w.run(3000)
    check(w.said == [], "상태 없음 = 조용")


def test_alert_then_guide():
    print("\n[알림] 경고 알림이 끝나기 전에는 11-1 을 내지 않는다")
    w = _normal()
    w.until(lambda: any(e[1] == "alert" for e in w.voice) and "10-2" in w.sids())
    t_alert = w.now
    w.until(lambda: "11-1" in w.sids())
    played = [e[0] for e in w.voice if e[1] == "alert_played"]
    check(played and w.now >= played[-1] and w.now - t_alert >= w.alert_ms, "11-1 은 알림 소리가 끝난 뒤")


def test_assistant_busy_defers():
    print("\n[대화] 음성비서가 듣거나 답하는 동안 안내를 미룬다")
    w = World(clip_ms=1500)
    Actor(w)
    w.start()
    w.until(lambda: "5-3" in w.sids())                  # 5-3 이 나가는 동안 참여자가 스스로 부름
    w.voice.append([w.now, "wake", {}])
    w.voice.append([w.now + 500, "stt", {"text": "지금 몇 단계야"}])
    w.until(lambda: w.playing is None)
    w.run(1500)
    check("6-1" not in w.sids(), "호출 · 질문 뒤 답이 끝나기 전에는 6-1 없음")
    w.voice.append([w.now, "answer", {"key": None}])
    w.voice.append([w.now + 1000, "play_end", {"what": "완료", "key": None}])
    w.until(lambda: "6-1" in w.sids(), 5000)
    check("6-1" in w.sids(), "답 재생이 끝나면 6-1")


def test_no_ack_moves_on():
    print("\n[응답] ack 가 안 오면 상한 뒤 다음 · 기록")
    w = World(ack_mode="none")
    w.start()
    w.until(lambda: "1-2" in w.sids(), 60_000)
    check("1-2" in w.sids(), "1-1 응답이 없어도 상한 뒤 1-2")
    check(any("응답 없음" in m for m in w.core.log), "기록에 「응답 없음」")


def test_missing_wav_moves_on():
    print("\n[소리 없음] ack ok 거짓이면 끝난 것으로 치고 다음 · 기록")
    w = World(ack_mode="fail")
    w.start()
    w.until(lambda: "2-1" in w.sids(), 10_000)
    check("2-1" in w.sids(), "1-1~1-3 을 못 내도 2-1 까지 간다")
    check(any("못 냄" in m for m in w.core.log), "기록에 「못 냄」")


# ------------------------------------------------------------------ 끊김
def test_cut_by_alert_replays_once():
    print("\n[끊김] 계획에 없던 경고가 12-1 을 끊으면 알림 · 풀림 뒤 12-1 을 한 번 다시")
    w = World(clip_ms=1500)
    a = Actor(w)
    a.over["11-1"] = lambda: (a.a_11_1(), w.later(1000, lambda: w.set(상태="WARNING")),
                              w.later(4500, lambda: w.set(상태="MONITOR")))
    w.start()
    w.until(lambda: w.sids().count("12-1") >= 2 and "12-2" in w.sids())
    s = w.sids()
    check(s.count("12-1") == 2 and s.index("12-2") > len(s) - 1 - s[::-1].index("12-1"), f"12-1 두 번 뒤 12-2({s[-6:]})")


def test_cut_scene_done_no_replay():
    print("\n[끊김] 10-2 도중 먼저 손을 올려 경고 → 10-2 를 되풀이하지 않고 11-1")
    w = World(clip_ms=2000)
    a = Actor(w, skip={"10-2"})
    a.over["10-1"] = lambda: w.later(1200, a.a_10_2)          # 10-2 가 나가는 도중
    w.start()
    w.until(lambda: "11-1" in w.sids())
    check(w.sids().count("10-2") == 1, f"10-2 한 번만({w.sids()[-4:]})")


def test_cut_by_clear_no_replay():
    print("\n[끊김] 11-1 도중 경고가 풀려 끊기면 다시 내지 않고 12-1")
    w = World(clip_ms=3000)
    a = Actor(w, skip={"11-1"})
    a.over["10-2"] = lambda: (a.a_10_2(), w.later(w.alert_ms + 600, a.a_11_1))
    w.start()
    w.until(lambda: "12-1" in w.sids())
    check(w.sids().count("11-1") == 1, f"11-1 한 번만({w.sids()[-4:]})")


def test_11_skipped_if_released():
    print("\n[11] 알림이 끝났을 때 이미 경고가 풀렸으면 11-1 없이 12-1")
    w = World()
    a = Actor(w)
    a.over["10-2"] = lambda: (a.a_10_2(), w.later(1500, a.a_11_1))
    w.start()
    w.until(lambda: "12-1" in w.sids())
    check("11-1" not in w.sids(), f"11-1 없음({w.sids()[-4:]})")


# ------------------------------------------------------------------ 다르게 했을 때(§4.2)
def test_graze_from_5_2_start():
    print("\n[스침] 5-2 가 나가는 도중 스쳐도 인정")
    w = World(clip_ms=2000)
    a = Actor(w)
    a.over["5-1"] = lambda: w.later(1000, a.a_5_2)
    w.start()
    w.until(lambda: "5-3" in w.sids(), 60_000)
    check("5-3" in w.sids() and "5-R" not in w.sids(), "5-3")


def test_graze_ring_only_not_counted():
    print("\n[스침] 링(접근)만 지나간 것은 스침 아님")
    w = World()
    Actor(w, over={"5-2": lambda: (w.hand.update(roi="B3", level=1), w.later(200, lambda: w.hand.update(roi=None, level=0)))})
    w.start()
    w.until(lambda: "5-2" in w.sids())
    w.run(5000)
    check("5-3" not in w.sids(), "5-3 없음")


def test_graze_warning_retry_twice():
    print("\n[스침] 경고 세 번 → 5-R 5-2 5-R 5-2 뒤 6-1")
    w = World()

    def slow():
        w.hand.update(roi="B3", level=2)
        w.set(상태="WARNING")
        w.later(w.alert_ms + 300, lambda: (w.hand.update(roi=None, level=0), w.set(상태="MONITOR")))
    Actor(w, over={"5-2": slow})
    w.start()
    w.until(lambda: "6-1" in w.sids())
    s = w.sids()
    i = s.index("5-2")
    check(s[i:s.index("6-1") + 1] == ["5-2", "5-R", "5-2", "5-R", "5-2", "6-1"], f"차례({s[i:s.index('6-1') + 1]})")


def test_graze_count_resets_per_run():
    print("\n[스침] 실패 횟수는 참여자(회차)마다 새로 센다")
    w = World()

    def slow():
        w.hand.update(roi="B3", level=2)
        w.set(상태="WARNING")
        w.later(w.alert_ms + 300, lambda: (w.hand.update(roi=None, level=0), w.set(상태="MONITOR")))
    a = Actor(w, over={"5-2": slow})
    w.start()
    w.until(lambda: w.sids().count("5-R") == 2)            # 앞 참여자 — 경고 두 번
    w.set(세션=False, 상태="IDLE")                          # 작업 초기화
    w.run(1000)
    a.over["5-2"] = slow
    w.start()                                              # 다음 참여자
    w.until(lambda: w.sids().count("1-1") == 2)
    w.until(lambda: w.sids().count("5-R") == 3 or "6-1" in w.sids()[w.sids().index("1-1", 1):])
    s2 = w.sids()[w.sids().index("1-1", 1):]
    check("5-R" in s2, f"다음 참여자의 첫 경고는 다시 해 보기(5-R) — 앞 참여자 횟수가 넘어오지 않는다({s2[-4:]})")


def test_graze_timeout_skips():
    print("\n[스침] 손이 안 잡히면 15초 뒤 5-2 다시 · 또 15초 뒤 6-1")
    w = World()
    Actor(w, skip={"5-2"})
    w.start()
    w.until(lambda: "6-1" in w.sids())
    s = w.sids()
    check(s[s.index("5-2"):s.index("6-1") + 1] == ["5-2", "5-2", "6-1"], f"차례({s[s.index('5-2'):s.index('6-1') + 1]})")


def test_white_before_graze():
    print("\n[스침] 5-1 중에 흰색을 먼저 누름 → 5 건너뛰고 6-2")
    w = World(clip_ms=1500)
    a = Actor(w)
    a.over["4-2"] = lambda: w.later(500, a.a_6_1)
    w.start()
    w.until(lambda: "6-2" in w.sids())
    s = w.sids()
    check("5-3" not in s and "6-1" not in s and s.index("6-2") > s.index("4-2"), f"차례({s[s.index('4-2'):]})")


def test_wrench_direct():
    print("\n[공구] 드라이버 대신 바로 렌치 → 7-2 · 8-1 건너뛰고 9-2")
    w = World()
    a = Actor(w)
    a.over["7-1"] = lambda: a.a_9_2()
    w.start()
    w.until(lambda: "9-4" in w.sids())
    s = w.sids()
    check("8-1" not in s and "9-1" not in s and "9-2" in s, f"차례({s[s.index('7-1'):]})")


def test_9_3_skipped_when_judged():
    print("\n[렌치] 9-2 끝에 이미 판정이 끝났으면 9-3 없이 9-4")
    w = World(clip_ms=2500)
    a = Actor(w)
    a.over["9-1"] = lambda: w.later(300, lambda: (w.hand.update(공구단계="grasped", 손판정끔=True),
                                                  w.set(현재단계=3, 현재버튼="B3", 서브진행=None)))
    w.start()
    w.until(lambda: "9-4" in w.sids())
    check("9-3" not in w.sids(), f"9-3 없음({w.sids()[-4:]})")


def test_10_waits_tool_down():
    print("\n[렌치] 9-5 뒤 공구를 든 채면 10-1 없음 · 내려놓으면 10-1")
    w = World()
    a = Actor(w, skip={"9-5"})
    w.start()
    w.until(lambda: "9-5" in w.sids() and w.playing is None)
    w.run(3000)
    check("10-1" not in w.sids(), "손 판정 끔 동안 10-1 없음")
    a.a_9_5()
    w.until(lambda: "10-1" in w.sids(), 5000)
    check("10-1" in w.sids(), "내려놓으면 10-1")


def test_pink_during_warning_fallback():
    print("\n[대체] 10~11 경고 중 분홍을 누름 → 14-2 14-3 12-1 12-2b 13-1 15-1 16-1 16-2")
    w = World()
    a = Actor(w)

    def pink():
        w.set(상태="MONITOR", 현재버튼="B3")
        w.sub()
        w.later(5000, lambda: w.set(현재단계=4, 현재버튼="B4", 서브진행=None))
    a.over["10-2"] = lambda: (a.a_10_2(), w.later(1000, pink))
    a.over["12-2b"] = a.a_12_2
    w.start()
    w.until(lambda: "16-2" in w.sids())
    s = w.sids()
    tail = s[s.index("10-2") + 1:]
    check(tail == ["14-2", "14-3", "12-1", "12-2b", "13-1", "15-1", "16-1", "16-2"], f"차례({tail})")


def test_unplanned_block_resume():
    print("\n[차단] 9(공구 서브)에서 차단 → 13-1 → 풀림(서브 취소) → 6-1 → 6-2 → 9-1(7 · 8 다시 안 함)")
    w = World()
    a = Actor(w, skip={"9-2", "13-1"})                  # 차단 중에는 렌치 판정이 진행되지 않는다(서브 취소 — 실제와 같게)

    def block():
        w.set(상태="BLOCK")
        w.later(w.alert_ms + 2000, lambda: w.set(상태="PROCESS RUN", 서브진행=None, 현재단계=2, 현재버튼="B2"))
    a.over["9-1"] = block
    w.start()
    w.until(lambda: w.sids().count("9-1") >= 2)
    s = w.sids()
    tail = s[s.index("9-1") + 1:]
    check(tail == ["9-2", "13-1", "6-1", "6-2", "9-1"], f"차례({tail})")


def test_unplanned_block_without_sub_keeps_scene():
    print("\n[차단] 서브가 없을 때(5-1 미리 안내 중) 차단 → 풀린 뒤 6-1 로 건너뛰지 않고 5-1 부터")
    w = World(clip_ms=2000)
    a = Actor(w, skip={"13-1"})
    a.over["4-2"] = lambda: w.later(400, lambda: (w.set(상태="BLOCK"),
                                                  w.later(w.alert_ms + 2500, lambda: w.set(상태="PROCESS RUN"))))
    w.start()
    w.until(lambda: "13-1" in w.sids() and w.sids().count("5-1") >= 2, 60_000)
    s = w.sids()
    tail = s[s.index("13-1"):]
    check(tail[:2] == ["13-1", "5-1"] and "6-1" not in tail[:3], f"차례({tail[:4]})")


def test_reprompt_press():
    print("\n[다시] 3-1 뒤 15초 무반응 → 3-1 다시")
    w = World()
    Actor(w, skip={"3-1"})
    w.start()
    w.until(lambda: w.sids().count("3-1") >= 2, 40_000)
    check(w.sids().count("3-1") == 2, f"3-1 두 번({w.sids()})")


def test_reprompt_cap():
    print("\n[다시] 버튼 장면 다시 안내는 4번까지 · 그 뒤 조용 · 상태가 바뀌면 진행")
    w = World()
    a = Actor(w, skip={"3-1"})
    w.start()
    w.run(150_000)
    check(w.sids().count("3-1") == 5, f"처음 + 다시 4번({w.sids().count('3-1')})")
    a.a_3_1()
    w.until(lambda: "4-1" in w.sids(), 5000)
    check("4-1" in w.sids(), "누르면 이어 간다")


def test_demo_scene_skip():
    print("\n[시연 장면] 무반응 → 한 번 더 → 넘어감(7-2 → 9-1 · 10-2 → 12-1 · 12-2 → 14-1)")
    w = World()
    Actor(w, skip={"7-2", "10-2", "12-2"})
    w.start()
    w.until(lambda: "14-1" in w.sids())
    s = w.sids()
    check(s.count("7-2") == 2 and "8-1" not in s and "9-1" in s, f"7-2 두 번 → 9-1({s[s.index('7-1'):s.index('9-1') + 1]})")
    check(s.count("10-2") == 2 and "11-1" not in s and "12-1" in s, "10-2 두 번 → 12-1")
    check(s.count("12-2") == 2 and "13-1" not in s and "14-1" in s, "12-2 두 번 → 14-1")


def test_voice_success():
    print("\n[음성비서] 15-1 뒤 호출 → 답 → 재생 끝 → 16-1")
    w = _normal()
    w.until(lambda: "16-1" in w.sids())
    s = w.sids()
    check(s[s.index("15-1") + 1] == "16-1", "15-R1 없이 16-1")


def test_voice_fail_twice():
    print("\n[음성비서] 20초씩 답 없음 → 15-R1 15-R2 16-1")
    w = World()
    Actor(w, skip={"15-1", "15-R1"})
    w.start()
    w.until(lambda: "16-1" in w.sids())
    s = w.sids()
    check(s[s.index("15-1"):s.index("16-1") + 1] == ["15-1", "15-R1", "15-R2", "16-1"], f"차례({s[s.index('15-1'):]})")


def test_emo_restart():
    print("\n[비상정지] 조용 → 풀려 작업 전 → X-EMO → 다음 시작 → 1-1")
    w = _normal()
    w.until(lambda: "6-1" in w.sids())
    w.set(비상정지=True, 상태="BLOCK")
    n = len(w.said)
    w.run(5000)
    check(len(w.said) == n, "비상정지 동안 조용")
    w.set(비상정지=False, 세션=False, 상태="IDLE")
    w.until(lambda: "X-EMO" in w.sids(), 10_000)
    check(w.sids()[-1] == "X-EMO", "풀리면 X-EMO")
    w.run(3000)
    w.start()
    w.until(lambda: w.sids().count("1-1") == 2, 5000)
    check(w.sids().count("1-1") == 2, "다음 시작에서 1-1")


def test_reset_midway():
    print("\n[초기화] 작업 중 세션 거짓(비상정지 아님) → 조용 → 다음 시작 → 1-1")
    w = _normal()
    w.until(lambda: "5-1" in w.sids())
    w.set(세션=False, 상태="IDLE")
    w.run(1000)
    n = len(w.said)
    w.run(20_000)
    check(len(w.said) == n, "조용")
    w.start()
    w.until(lambda: w.sids().count("1-1") == 2, 5000)
    check(w.sids().count("1-1") == 2, "다음 시작에서 1-1")


if __name__ == "__main__":
    for name, fn in [(n, f) for n, f in globals().items() if n.startswith("test_")]:
        try:
            fn()
        except Exception as e:                       # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{name} 예외: {type(e).__name__}: {e}")
    if _fails:
        print(f"\n❌ {len(_fails)}건 실패")
        sys.exit(1)
    print("\n✅ 시연 안내 프로그램 시험 통과")
