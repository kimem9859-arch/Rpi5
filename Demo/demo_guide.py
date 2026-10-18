#!/usr/bin/env python3
"""시연 안내 프로그램 — 참여자가 안경 안내만 듣고 16장면을 직접 해 보게 한다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-18-시연안내모드-design.md(§4 대본 · §4.2 다르게 했을 때 · §4.3 문장마다
       시작 조건 · §6 구조) · 계획 = plans/2026-10-18-시연안내모드.md Task 5
실행: run_demo.sh 가 함께 띄운다(늘 · 설정 「시연 안내」 끔이면 말없이 기다림) · 따로 = python3 Demo/demo_guide.py
🔑 시연 프로그램을 건드리지 않는다 — 읽기만: state.json(GUI · 안내모드 칸) · hand.json(손 · 공구 단계) · voice.json(음성 사건 거울)
   · ack.json · 쓰는 것 = req.json(안내 소리 요청 — 측정 진행 도우미와 같은 길) · 자기 기록(logs/guide_*.log).
🔑 규칙 — 앞 소리가 끝나고(ack) 넘어갈 조건도 채워졌을 때 다음 소리 · 알림 > 음성비서 대화 > 안내(안내는 늘 비켜 준다) ·
   대본은 상태를 따라간다(앞서 가면 맞는 장면으로 · 차단으로 뒤로 가면 실제 단계의 버튼 장면으로 · 이미 한 시연 장면은 다시 안 함).
"""
import argparse
import datetime
import json
import os
import signal
import sys
import time
from collections import namedtuple

_DEMO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import config          # noqa: E402
import measure_log     # noqa: E402
import voice_card      # noqa: E402 — read_state(유령 거르기 · 손 · 음성 파일에도 같은 함수)
import measure_guide as MG   # noqa: E402 — write_req · assistant_busy · LOCK_FILE(측정 진행 도우미와 같은 규칙)

LINES_PATH = os.path.join(_DEMO, "voice", "guide_lines.json")
Say = namedtuple("Say", "sid key seq")

MAIN = ["1-1", "1-2", "1-3", "2-1", "3-1", "4-1", "4-2", "5-1", "5-2", "5-3", "6-1", "6-2", "7-1", "7-2", "8-1",
        "9-1", "9-2", "9-3", "9-4", "9-5", "10-1", "10-2", "11-1", "12-1", "12-2", "13-1", "14-1", "14-2", "14-3",
        "15-1", "16-1", "16-2"]
# 10 · 11 경고 중 분홍을 눌러 버렸을 때(§4.2) — 순서 위반을 파랑 차례에서 노랑으로
FALLBACK = ["14-2", "14-3", "12-1", "12-2b", "13-1", "15-1", "16-1", "16-2"]
GROUPS = {"G5": ("5-1", "5-2", "5-3"), "G78": ("7-1", "7-2", "8-1"), "G10": ("10-1", "10-2", "11-1"),
          "G12": ("12-1", "12-2", "12-2b", "13-1"), "G15": ("15-1",)}
GROUP_OF = {s: g for g, ss in GROUPS.items() for s in ss}
PRESS_SCENE = {1: "3-1", 2: "6-1", 3: "14-1", 4: "16-1"}    # 차단으로 서브가 취소됐을 때 돌아갈 버튼 장면
# 알림이 그 장면에서 시작되면 계획된 것(끊겨도 다시 내지 않는다) — 그 밖에서 시작되면 계획에 없던 것
EXPECT = {"5-2": ("WARNING",), "5-3": ("WARNING",), "10-2": ("WARNING",), "11-1": ("WARNING",),
          "12-1": ("BLOCK",),    # 미리 안내 중 먼저 파랑을 눌러 난 차단은 순서 위반 장면이다(리뷰 M6 — 두 번 시키지 않는다) ·
                                 # 경고(손이 먼저 감)는 계획에 없던 것 — 미리 안내를 알림 뒤 다시 낸다
          "12-2": ("WARNING", "BLOCK"), "12-2b": ("WARNING", "BLOCK"), "13-1": ("WARNING", "BLOCK")}
# 기다리는 장면 → (다시 낼 문장, 종류, 넘어갈 곳) — must = 15초마다 · 최대 GUIDE_REPROMPT_MAX · demo = 한 번 더 뒤 넘어감
WAIT = {"4-1": ("3-1", "must", None), "6-2": ("6-1", "must", None), "9-3": ("9-2", "must", None),
        "9-4": ("9-2", "must", None), "10-1": ("9-5", "must", None), "12-1": ("11-1", "must", None),
        "14-1": ("13-1", "must", None), "14-2": ("14-1", "must", None), "16-2": ("16-1", "must", None),
        "5-3": ("5-2", "demo", "6-1"), "8-1": ("7-2", "demo", "9-1"), "9-1": ("8-1", "demo", "9-1!"),
        "11-1": ("10-2", "demo", "12-1"), "13-1": ("12-2", "demo", "14-1")}


def load_sentences(path=LINES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["sentences"]


def _alarm(st):
    if st.get("비상정지"):
        return "emo"
    s = st.get("상태")
    return s if s in ("WARNING", "BLOCK") else None


def _sub_running(st):
    return ((st.get("서브진행") or {}).get("상태")) in ("진행 중", "멈춤")


def _pressed(st, b):
    return st.get("현재버튼") == b and _sub_running(st)


def _step(st):
    return int(st.get("현재단계") or 0)


class GuideCore:
    """한 번에 소리 하나 — tick 이 다음에 낼 소리(Say)를 돌려준다(없으면 None). 장치 · 파일 없음(시험이 직접 부른다)."""

    def __init__(self, sentences, cfg=config):
        self.S, self.cfg = sentences, cfg
        self.log = []
        self.prev = None
        self._seq = 0
        self._reset(False)

    # ------------------------------------------------------------------ 상태
    def _reset(self, active):
        self.active, self.emo_wait = active, False
        self.seq, self.p = list(MAIN), 0
        self.play = None                 # {sid, keys, i, key, seq, t_req, main}
        self.pending = []                # 먼저 낼 문장(예외 · 다시 내기)
        self.t_start, self.t_end = {}, {}
        self.done_groups = set()
        self.alarm, self.alarm_planned, self.alarm_hist = None, True, []   # (종류, 시작 ms)
        self.unplanned = self.after_block = False
        self.wait_since = None
        self.reprompts = 0
        self.g_in = self.g_out = False
        self.graze_fails = 0             # 이번 틱까지 새로 본 스침 경고(_decide 가 _gf 로 옮긴다)
        self._gf = 0                     # 이번 회차 스침 경고 누적 — 참여자마다 0 부터
        self.voice_t0, self.voice_fails = None, 0
        self.ub_count = 0                # 계획에 없던 차단에 낸 13-1 수(리뷰 M5 — 15초마다 · 상한 GUIDE_REPROMPT_MAX)

    def _note(self, msg):
        self.log.append(f"{self.now:.0f} {msg}")

    def cur(self):
        return self.seq[self.p] if self.p < len(self.seq) else None

    # ------------------------------------------------------------------ 한 틱
    def tick(self, now_ms, st, hand, voice, ack):
        self.now = now_ms
        hand = hand or {}
        voice = voice or []
        on = bool(st and st.get("안내모드"))
        start = self._start_signal(self.prev, st)
        self.prev = st
        if not on:
            if self.active or self.emo_wait:
                self._note("안내 끔(또는 상태 없음) — 멈춤")
                self._reset(False)
            return None
        if start:
            self._reset(True)
            self._note("작업 시작 — 1-1 부터")
        if st.get("비상정지"):
            if self.active:
                self._note("비상정지 — 조용히 기다림")
                self.active, self.play, self.emo_wait = False, None, True
            return None
        if self.emo_wait:
            if not st.get("세션"):
                self.emo_wait = False
                self.active = True
                self.seq, self.p = [], 0                  # X-EMO 하나만 내고 끝
                return self._start("X-EMO", main=False)
            return None
        if not self.active:
            return None
        if not st.get("세션"):
            if self.play is None or self.play["sid"] != "X-EMO":
                self._note("작업 초기화 — 조용히 기다림")
                self._reset(False)
                return None
        self._track(st, hand)
        if self.play:
            r = self._advance_play(st, voice, ack)
            if r is not None or self.play:
                return r
        if self._alert_busy(voice):
            self.wait_since = self.now
            return None
        busy, _ = MG.assistant_busy([tuple(e) for e in voice], now_ms)
        if busy:
            self.wait_since = self.now
            return None
        return self._decide(st, hand, voice)

    @staticmethod
    def _start_signal(prev, cur):
        if not cur or not cur.get("세션") or not prev:
            return False
        return (not prev.get("세션")) or (bool(prev.get("결과")) and not cur.get("결과"))

    def _track(self, st, hand):
        a = _alarm(st)
        if a != self.alarm:
            if a:
                planned = a in EXPECT.get(self.cur() or "", ())
                self.alarm_hist.append((a, self.now))
                self._note(f"알림 상황 {a} — {'계획된 것' if planned else '계획에 없던 것'}({self.cur()})")
                if not planned:
                    self.unplanned = True
                    self.after_block = self.after_block or a == "BLOCK"
                else:
                    self.unplanned = self.after_block = False   # 계획된 상황이 앞의 계획에 없던 경고를 넘겨받는다
                if self.cur() in ("5-2", "5-3") and a == "WARNING":
                    self.graze_fails += 1
            self.alarm = a
        if self.play and self.play["sid"] == "5-2" or self.cur() == "5-3":
            if hand.get("roi") == "B3" and hand.get("level") == 2:
                self.g_in = True
            elif self.g_in and hand.get("roi") != "B3":
                self.g_out = True

    def _since(self, kind, t0):
        return any(k == kind and t >= t0 for k, t in self.alarm_hist)

    def _alert_busy(self, voice):
        """알림 소리가 나는 중인가 — 알림 상황이 시작된 뒤 alert_played · alert_clear 가 올 때까지(상한 GUIDE_ALERT_WAIT_SEC)."""
        if not self.alarm_hist:
            return False
        _, t0 = self.alarm_hist[-1]
        if self.now - t0 >= self.cfg.GUIDE_ALERT_WAIT_SEC * 1000:
            return False
        # 🔑 그 알림(시작 뒤 마지막 alert 사건)의 키로 끝을 찾는다 — 경고가 차단에 끊기면 끊긴 경고의 alert_played 가
        #    차단 alert 뒤에 기록된다(voice_assistant AlertWatcher._play) · 그것을 차단 알림의 끝으로 보지 않는다(리뷰 I3)
        al = [e for e in voice if e[1] == "alert" and e[0] >= t0 - 300]
        if not al:
            return self.alarm is not None            # 알림이 나기 전에 상황이 풀렸으면 기다릴 것이 없다
        ta, key = al[-1][0], (al[-1][2] or {}).get("key")
        return not any((e[1] == "alert_played" and (e[2] or {}).get("key") == key or e[1] == "alert_clear")
                       and e[0] >= ta for e in voice)

    # ------------------------------------------------------------------ 소리
    def _start(self, sid, main=True):
        keys = list(self.S[sid])
        self.play = {"sid": sid, "keys": keys, "i": 0, "main": main}
        if main:
            self.t_start[sid] = self.now
            if sid == "5-2":
                self.g_in = self.g_out = False
        self._note(f"▶ {sid}{'' if main else ' (다시 · 예외)'}")
        return self._request(keys[0])

    def _request(self, key):
        self._seq = max(self._seq + 1, int(self.now))
        self.play.update(key=key, seq=self._seq, t_req=self.now)
        return Say(self.play["sid"], key, self._seq)

    def _advance_play(self, st, voice, ack):
        p = self.play
        done = bool(ack) and ack.get("seq") == p["seq"]
        if done and not ack.get("ok"):
            self._note(f"소리 못 냄 — {p['key']}(파일 · 스피커 확인) · 끝난 것으로 치고 다음")
        if not done and self.now - p["t_req"] >= self.cfg.GUIDE_ACK_WAIT_SEC * 1000:
            self._note(f"응답 없음 — {p['key']} · 끝난 것으로 치고 다음")
            done = True
        if not done:
            return None
        stop = [e for e in voice if e[1] == "play_end" and (e[2] or {}).get("key") == p["key"]
                and (e[2] or {}).get("what") == "중단" and e[0] >= p["t_req"]]
        if stop:
            cuts = [e for e in voice if e[1] in ("alert", "alert_clear") and p["t_req"] - 200 <= e[0] <= stop[-1][0]]
            why = cuts[-1][1] if cuts else None
            self.play = None
            if why == "alert" and not self.alarm_planned_now():
                self._note(f"끊김(계획에 없던 알림) — {p['sid']} 를 알림 뒤 다시")
                if not p["main"]:                 # 대본 문장은 지점에 그대로 남아 다시 나온다 · 예외 문장만 한 번 다시
                    self.pending = [p["sid"]] + [s for s in self.pending if s != p["sid"]]
                return None
            self._note(f"끊김({'계획된 알림' if why == 'alert' else '알림 풀림' if why else '멈춤'}) — {p['sid']} 다시 안 냄")
            self._finished(p, cut=True)
            return None
        p["i"] += 1
        if p["i"] < len(p["keys"]):
            return self._request(p["keys"][p["i"]])
        self.play = None
        self._finished(p)
        return None

    def alarm_planned_now(self):
        if not self.alarm_hist:
            return False
        a, _ = self.alarm_hist[-1]
        return not self.unplanned and a in EXPECT.get(self.cur() or "", ("",))

    def _finished(self, p, cut=False):
        sid = p["sid"]
        self.wait_since = self.now
        if sid in ("15-1", "15-R1", "15-R2") and not cut:
            self.voice_t0 = self.now
        if not p["main"]:
            return
        self.t_end[sid] = self.now
        if self.cur() == sid:
            self._move(self.p + 1)

    def _move(self, i):
        """대본 지점 옮기기 — 지나간 묶음은 끝난 것 · 끝난 묶음의 문장은 건너뛴다."""
        for s in self.seq[self.p:i]:
            g = GROUP_OF.get(s)
            if g and s == GROUPS[g][-1]:
                self.done_groups.add(g)
        self.p = i
        while self.cur() and GROUP_OF.get(self.cur()) in self.done_groups:
            self.p += 1
        self.reprompts, self.wait_since = 0, self.now

    def _jump(self, sid, done=()):
        for g in done:
            self.done_groups.add(g)
        if sid in self.seq[self.p:]:
            self._move(self.seq.index(sid, self.p))
        elif sid in self.seq:
            self.p = self.seq.index(sid)
            self._move(self.p)
        self._note(f"→ {sid} 로 옮김")

    # ------------------------------------------------------------------ 다음에 낼 것
    def _decide(self, st, hand, voice):
        if self.unplanned:
            if self.alarm == "BLOCK" and self.after_block:
                # 13-1 「…차단 해제 버튼을 눌러 주세요」 — 처음 한 번 · 안 풀리면 15초마다(버튼 장면과 같은 상한 · 리뷰 M5)
                due = self.ub_count == 0 or (self.now - (self.wait_since or self.now) >= self.cfg.GUIDE_REPROMPT_SEC * 1000
                                             and self.ub_count <= self.cfg.GUIDE_REPROMPT_MAX)
                if due:
                    self.ub_count += 1
                    return self._start("13-1", main=False)
                return None
            if self.alarm:
                self.wait_since = self.now
                return None
            self.unplanned, self.ub_count = False, 0
            if self.after_block:
                self.after_block = False
                self._resync_back(st)
            else:
                # 🔑 지금 기다리는 장면의 행동 문장만 다시(리뷰 C1 — 지난 장면 버튼을 시키면 안내가 순서 위반을 부른다) ·
                #    WAIT 에 없는 장면(대기 · 음성비서 · 자동으로 넘어가는 곳)은 다시 안내하지 않는다
                w = WAIT.get(self.cur() or "")
                if w and not self.pending and self._cond(self.cur(), st, hand, voice) is False:
                    self.pending.append("12-2b" if w[0] == "12-2" and "12-2b" in self.seq else w[0])
        if self.graze_fails and self.cur() in ("5-2", "5-3") and not self.alarm:
            n, self.graze_fails = self.graze_fails, 0
            self._gf += n
            if self._gf >= 3:
                self._gf = 0
                self._jump("6-1", done=("G5",))
            else:
                self._jump("5-2")
                return self._start("5-R", main=False)
        if self.pending:
            sid = self.pending.pop(0)
            return self._start(sid, main=False)
        self._resync_ahead(st, hand)
        sid = self.cur()
        if sid is None:
            return None
        if sid == "16-1" and "15-1" in self.t_end and self.voice_t0 is not None:
            r = self._voice_scene(voice)
            if r is not None:
                return r
        ok = self._cond(sid, st, hand, voice)
        if ok == "skip":
            self._note(f"{sid} 건너뜀 — 이미 지나감")
            self._move(self.p + 1)
            return None
        if ok:
            return self._start(sid)
        return self._reprompt(sid)

    def _cond(self, sid, st, hand, voice):
        if sid is None:
            return False
        step = _step(st)
        # 누름 문장 — 이미 눌렸거나 단계가 지났으면 건너뛴다(리뷰 I5 — 이미 한 일을 시키지 않는다)
        if sid == "3-1":
            return "skip" if _pressed(st, "B1") or step >= 2 else True
        if sid == "6-1":
            return "skip" if _pressed(st, "B2") or step >= 3 else True
        if sid == "4-1":
            return _pressed(st, "B1") or step >= 2
        if sid == "4-2":
            return step >= 2
        if sid == "5-3":
            # 🔑 손이 B3 안쪽에 들어간 마지막 시각(GUI hand.json 「마지막안쪽」)으로 본다 — 빠른 스침은 0.1초 읽기 사이에
            #    들어갔다 나와 틱으로는 안 보인다(리뷰 I4) · 틱에서 직접 본 들고남도 함께 받는다
            t5 = self.t_start.get("5-2", self.now)
            last = (hand.get("마지막안쪽") or {}).get("B3")
            went = (self.g_in and self.g_out) or (last is not None and last >= t5 and hand.get("roi") != "B3")
            return went and not self._since("WARNING", t5)
        if sid == "6-2":
            return _pressed(st, "B2") or step >= 3
        if sid == "8-1":
            return bool((st.get("서브진행") or {}).get("공구오답"))
        if sid == "9-1":
            return not (st.get("서브진행") or {}).get("공구오답")
        if sid == "9-3":
            return "skip" if step >= 3 else hand.get("공구단계") in ("checking", "grasped")
        if sid == "9-4":
            return step >= 3
        if sid == "10-1":
            return not hand.get("손판정끔")
        if sid == "11-1":
            if not self._since("WARNING", self.t_start.get("10-2", self.now)):
                return False
            return True if self.alarm == "WARNING" else "skip"
        if sid == "12-1":
            return self.alarm != "WARNING"
        if sid == "13-1":
            t0 = max(self.t_start.get("12-2", 0), self.t_start.get("12-2b", 0)) or self.now
            if not self._since("BLOCK", t0):
                return False
            return True if self.alarm == "BLOCK" else "skip"
        if sid == "14-1":
            if _pressed(st, "B3") or step >= 4:
                return "skip"
            return self.alarm != "BLOCK"
        if sid == "14-2":
            return _pressed(st, "B3") or step >= 4
        if sid == "14-3":
            return step >= 4
        if sid == "15-1":
            return self.alarm is None
        if sid == "16-1":
            return self._voice_ok(voice) or self.voice_fails >= 2
        if sid == "16-2":
            return bool(st.get("결과"))
        return True

    def _voice_ok(self, voice):
        t0 = self.t_end.get("15-1")
        if t0 is None:
            return False
        # 🔑 성공 = 15-1 뒤 호출(wake) 다음의 답(answer)이 끝까지 재생됨(play_end 완료 · 같은 키) — 호출만 · 질문 못 알아들음 ·
        #    답 중단은 실패다(설계 §4.2 · §6.5 · 리뷰 I1 — assistant_busy 는 시간이 지나도 「끝」을 돌려준다)
        ev = [e for e in voice if e[0] >= t0]
        for i, (tw, k, _) in enumerate(ev):
            if k != "wake":
                continue
            ans = next((e for e in ev[i + 1:] if e[1] == "answer"), None)
            if ans is None:
                continue
            key = (ans[2] or {}).get("key")
            if any(e[1] == "play_end" and e[0] >= ans[0] and (e[2] or {}).get("key") == key
                   and (e[2] or {}).get("what") == "완료" for e in ev):
                return True
        return False

    def _voice_scene(self, voice):
        if self._voice_ok(voice) or self.voice_fails >= 2:
            return None
        if self.now - self.voice_t0 < self.cfg.GUIDE_VOICE_WAIT_SEC * 1000:
            return None
        self.voice_fails += 1
        self._note(f"음성비서 {self.voice_fails}번째 실패 — 답이 끝나지 않음")
        return self._start("15-R1" if self.voice_fails == 1 else "15-R2", main=False)

    def _resync_ahead(self, st, hand):
        sid, step = self.cur(), _step(st)
        if sid is None:
            return
        if st.get("결과") and sid != "16-2" and "16-2" in self.seq:
            # 작업이 이미 끝났다(15번에서 바로 파랑 등) — 남은 안내 없이 완료 안내로(리뷰 I5)
            self._jump("16-2", done=tuple(GROUPS))
        elif sid in GROUPS["G5"] and (_pressed(st, "B2") or step >= 3):
            self._jump("6-2", done=("G5",))
        elif sid in GROUPS["G78"] and hand.get("공구단계") in ("checking", "grasped") \
                and not (st.get("서브진행") or {}).get("공구오답"):
            self._jump("9-2", done=("G78",))
        elif sid in ("10-1", "10-2", "11-1", "12-1", "12-2", "13-1") and "12-2b" not in self.seq \
                and (_pressed(st, "B3") or step >= 4):
            # 경고 알림 「…분홍 버튼을 누르세요」대로 분홍을 눌렀다 — 차단 장면을 빠뜨리지 않게 파랑 차례에서 노랑으로(§4.2 · 리뷰 I5)
            self.seq = self.seq[:self.p] + FALLBACK
            self._note("경고 중 분홍을 누름 — 순서 위반을 파랑 차례에서 노랑으로(대체)")
            self._move(self.p)
        elif sid in ("12-1", "12-2", "12-2b") and self.alarm == "BLOCK" and not self.unplanned:
            # 미리 안내 중 먼저 파랑을 눌러 차단 — 순서 위반 장면은 이미 일어났다 · 13-1 로(리뷰 M6)
            t_blk = max(t for k, t in self.alarm_hist if k == "BLOCK")
            self.t_start[sid if sid != "12-1" else "12-2"] = min(self.t_start.get("12-2", t_blk), t_blk)
            self._jump("13-1")

    def _resync_back(self, st):
        step = _step(st)
        if _sub_running(st) or step not in PRESS_SCENE:
            return
        target = PRESS_SCENE[step]
        # 🔑 되돌아가는 것은 지점이 그 단계의 버튼 장면을 이미 지났을 때뿐(= 서브가 취소됐다) — 아직 앞이면 그대로 둔다
        #    (예: 5-1 중 차단 → 6-1 로 건너뛰면 스침 장면이 통째로 빠진다)
        if target in self.seq and self.seq.index(target) < self.p:
            self.p = self.seq.index(target)
            self._move(self.p)
            self._note(f"차단이 풀림 · 서브 취소 — {target} 부터(이미 한 시연 장면은 건너뜀)")

    def _reprompt(self, sid):
        w = WAIT.get(sid)
        if not w or self.wait_since is None:
            return None
        if self.now - self.wait_since < self.cfg.GUIDE_REPROMPT_SEC * 1000:
            return None
        line, kind, nxt = w
        if kind == "demo" and self.reprompts >= 1 and nxt.endswith("!"):
            # 조건 없이 그 문장을 낸다 — 9-1 「렌치를 잡아 주세요」는 드라이버를 안 내려놓아도 해야 할 안내(리뷰 I2)
            self._note(f"{sid} 기다림 끝 — 조건 없이 {sid}")
            return self._start(sid)
        if kind == "demo" and self.reprompts >= 1:
            self._note(f"{sid} 기다림 끝 — 넘어감")
            g = GROUP_OF.get(sid) or GROUP_OF.get(line)
            target = nxt.rstrip("!")
            if g:
                self.done_groups.add(g)
            if target in self.seq[self.p:] and target != sid:
                self._move(self.seq.index(target, self.p))
            else:
                self._move(self.p + 1)
            return None
        if kind == "must" and self.reprompts >= self.cfg.GUIDE_REPROMPT_MAX:
            return None
        if line == "12-2" and "12-2b" in self.seq:
            line = "12-2b"
        self.reprompts += 1
        self._note(f"{sid} 조건 안 채워짐 {self.cfg.GUIDE_REPROMPT_SEC:.0f}초 — {line} 다시({self.reprompts})")
        return self._start(line, main=False)


# ---------------------------------------------------------------------- 실행
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _measure_guide_running():
    """측정 진행 도우미가 잠금을 쥐고 있나 — 🔑 잠금 파일이 없으면 돌고 있지 않다(만들지 않는다 · 리뷰 M3)."""
    import fcntl
    if not os.path.exists(MG.LOCK_FILE):
        return False
    try:
        with open(MG.LOCK_FILE, "r") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="시연 안내 프로그램(설정 「시연 안내」 켬일 때만 말한다)")
    ap.add_argument("--tick", type=float, default=0.1)
    a = ap.parse_args(argv)
    import socket
    guard = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        guard.bind("\0sop_demo_guide")          # 🔑 하나만(리뷰 M7) — 추상 주소라 파일이 없고 프로세스가 끝나면 풀린다
    except OSError:
        print("시연 안내 프로그램이 이미 돈다 — 끝낸다", flush=True)
        return 0
    logp = os.path.join(_DEMO, "logs", f"guide_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
    box = {"out": None, "early": []}

    def say(m):
        """화면엔 늘 · 기록 파일은 안내가 처음 켜질 때 연다(끔이면 파일을 만들지 않는다 — 설계 §6.1 · 리뷰 M3)."""
        line = f"[{datetime.datetime.now():%H:%M:%S}] {m}"
        print(line, flush=True)
        if box["out"] is None:
            box["early"] = (box["early"] + [line])[-20:]
            return
        box["out"].write(line + "\n")
        box["out"].flush()

    def open_log():
        if box["out"] is None:
            os.makedirs(os.path.dirname(logp), exist_ok=True)
            box["out"] = open(logp, "a", encoding="utf-8")
            box["out"].write("\n".join(box["early"]) + "\n")
            box["out"].flush()

    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    try:
        sys.path.insert(0, os.path.join(_DEMO, "voice"))
        import make_guide
        probs = make_guide.check()
        say(f"안내 소리 검사 — 문제 {len(probs)}개" + ("" if not probs else ": " + " · ".join(probs[:8])))
    except Exception as e:                       # noqa: BLE001 — 검사가 못 돌아도 안내는 돈다
        say(f"안내 소리 검사를 못 했다 — {type(e).__name__}: {e}")
    core = GuideCore(load_sentences())
    hand_p = os.path.join(config.STATE_SHM_DIR, config.HAND_STATE_FILE)
    voice_p = os.path.join(config.CUE_SHM_DIR, config.GUIDE_VOICE_FILE)
    ack_p = os.path.join(config.CUE_SHM_DIR, "ack.json")
    say(f"시연 안내 프로그램 시작 — 설정 「시연 안내」 켬일 때만 말한다 · 기록(켠 뒤) {logp}")
    seen, lock_t, locked = 0, 0.0, False
    while not stop:
        try:
            now = measure_log.now_ms()
            if now - lock_t > 3000:
                lock_t, was = now, locked
                locked = _measure_guide_running()
                if locked != was:
                    say("측정 진행 도우미가 돌고 있다 — 안내를 쉰다" if locked else "측정 진행 도우미가 끝났다 — 안내를 다시 받는다")
            ack = _read_json(ack_p)              # 🔑 응답을 음성 사건보다 먼저 — 음성비서는 play_end → ack 차례로 쓴다(리뷰 M2)
            st = voice_card.read_state()
            hand = voice_card.read_state(hand_p)
            vv = voice_card.read_state(voice_p)
            r = core.tick(now, None if locked else st, hand, (vv or {}).get("events") or [], ack)
            if core.active or core.emo_wait:
                open_log()
            for m in core.log[seen:]:
                say(m)
            seen = len(core.log)
            if r is not None:
                try:
                    MG.write_req(r.key, float(r.seq))
                except OSError as e:
                    say(f"🔴 안내 요청을 못 썼다 — {e}")
        except Exception as e:                   # noqa: BLE001 — 안내가 죽으면 시연 내내 안내가 없다(리뷰 M4)
            say(f"🔴 안내 오류 — 계속한다: {type(e).__name__}: {e}")
        time.sleep(a.tick)
    say("시연 안내 프로그램 끝")
    if box["out"] is not None:
        box["out"].close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
