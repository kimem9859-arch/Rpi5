"""진행 도우미(측정 진행 도우미 설계 2026-10-11 §4.4 · D8 · D15) — 화면·키 없이 판단 부분만.

실행: python3 Demo/selftest/test_measure_guide.py
"""
import json
import os
import sys
import tempfile

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import measure_guide as G
import measure_script as MS

_fails = []
B = ["B1", "B2", "B3", "B4"]


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def E(t, k, **d):
    return (float(t), k, d)


def ST(t, new, exp):
    return E(t, "state", old="X", new=new, expected=exp)


def rows(*pairs):
    return [{"판": p, "행동": "위반", "대상": "", "메모": f"줄{i}", "누름": s, "낱말": MS.parse_tokens(s, B, row=i)}
            for i, (p, s) in enumerate(pairs)]


def test_next_cue():
    print("\n[안내 때] 조건(상태 · 기대 버튼) + 직전 행동·안내에서 1초 · 낱말마다 한 번 · 머묾은 해제 또는 4초")
    toks = MS.parse_tokens("B2@B1 B1 ~B4@B3", B)
    st = {"state": "PROCESS_RUN", "expected": "B1", "last": 0.0, "released": []}
    check(G.next_cue(toks, 0, {}, st, 500.0) is None, "1초 전에는 안 낸다")
    check(G.next_cue(toks, 0, {}, st, 1000.0) == (0, "cue_B2"), "1초 뒤 첫 낱말")
    check(G.next_cue(toks, 0, {0: 1000.0}, st, 5000.0) is None, "낸 누름이 아직 안 눌렸으면 기다린다")
    check(G.next_cue(toks, 1, {0: 1000.0}, dict(st, state="BLOCK"), 9000.0) is None, "차단 중에는 안 낸다")
    check(G.next_cue(toks, 1, {0: 1000.0}, dict(st, last=8000.0), 9000.0) == (1, "cue_B1"), "해제 뒤 1초 → 다음 낱말")
    st3 = {"state": "MONITOR", "expected": "B3", "last": 0.0, "released": []}
    check(G.next_cue(toks, 2, {0: 1.0, 1: 2.0}, st3, 3000.0) == (2, "cue_hover_B4"), "머묾 안내")
    check(G.next_cue(toks, 2, {0: 1.0, 1: 2.0}, dict(st3, expected="B2"), 3000.0) is None, "기대 버튼이 다르면 기다린다")
    check(G.cue_key(MS.parse_tokens("#플라이어", B)[0]) == "cue_tool_pliers", "공구 안내 키")


def test_guide_step_and_ng():
    print("\n[진행] 안내 요청 · 안내와 다른 누름 = 「다시」 한 번 · N/U 기록")
    sent, logged = [], []
    g = G.Guide(rows((1, "B2@B1 B1")), "EMO", cue_sink=lambda k, t: sent.append(k),
                log_sink=lambda t, k, d: logged.append((k, d)))
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    check(g.step(ev, 1100.0) == ("cue", "cue_B2") and sent == ["cue_B2"], f"첫 안내 = {sent}")
    check(g.step(ev, 3000.0) is None, "같은 낱말을 다시 내지 않는다")
    ev = ev + [E(3100, "press", button="B3", expected="B1", state="MONITOR", source="gpio")]
    check(g.step(ev, 3200.0) == ("ng", "cue_ng") and g.step(ev, 3300.0) is None, "자동 NG → 「다시」 한 번")
    g.mark(3400.0, "ng", "장비")
    g.mark(3500.0, "undo")
    check([k for k, _ in logged] == ["cue", "cue", "ng", "undo"], f"guide.csv 줄 = {logged}")


def test_resume_from_guide_csv():
    print("\n[다시 켬] guide.csv 의 안내·N 을 다시 읽어 이미 낸 안내를 되풀이하지 않는다 · N 을 잃지 않는다")
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    g0 = G.Guide(rows((1, "B2@B1 B1")), "EMO", cue_sink=lambda k, t: None)
    check(g0.step(ev, 5000.0) == ("cue", "cue_B2"), "다시 읽지 않으면 첫 안내를 낸다(대조)")
    g = G.Guide(rows((1, "B2@B1 B1")), "EMO", cue_sink=lambda k, t: None)
    g.restore([E(1100, "cue", run=1, script=1, tok=0, key="cue_B2")])
    check(g.step(ev, 5000.0) is None, "낸 안내를 다시 내지 않는다")
    g2 = G.Guide(rows((1, "B2@B1 B1")), "EMO", cue_sink=lambda k, t: None)
    g2.restore([E(1200, "ng", why="사람")])
    check(g2.marks == [(1200.0, "ng", "사람")], f"N 표시 = {g2.marks}")


def test_no_script():
    print("\n[대본 없음] 안내 없음 · N 만")
    g = G.Guide([], "EMO", cue_sink=lambda k, t: None)
    check(g.step([E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")], 5000.0) is None, "안내 없음")
    g.mark(6000.0, "ng", "사람")
    check(g.marks == [(6000.0, "ng", "사람")], "N 은 된다")


def test_tail_and_req():
    print("\n[파일] 꼬리 읽기 = 완전한 줄만 · 요청 파일 · 응답 상태")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "events.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write('t_ms,kind,data\n1.0,run_start,{}\n2.0,press,"{""button"": ""B1""}"\n3.0,run_')
        t = G.Tail(p)
        check(t.poll() and [k for _, k, _ in t.rows] == ["run_start", "press"], f"{t.rows}")
        with open(p, "a", encoding="utf-8") as f:
            f.write('end,{}\n')
        check(t.poll() and t.rows[-1][1] == "run_end", "이어 쓴 줄")
        G.write_req("cue_B2", 1234.5, d=d)
        with open(os.path.join(d, "req.json"), encoding="utf-8") as f:
            req = json.load(f)
        check(req == {"seq": 1234, "key": "cue_B2", "t_req_ms": 1234.5}, f"{req}")


def test_ack_status():
    print("\n[응답] 음성비서가 답했나 — 없음 · 응답 · 응답 없음")
    with tempfile.TemporaryDirectory() as d:
        check("안내 전" in G.ack_status(None, d=d, now_ms=0.0), "안내 전")
        check("응답 없음" in G.ack_status((10, 1000.0), d=d, now_ms=5000.0), "3초 넘게 응답 없음")
        with open(os.path.join(d, "ack.json"), "w", encoding="utf-8") as f:
            json.dump({"seq": 10, "ok": True, "t_ms": 1500.0}, f)
        s = G.ack_status((10, 1000.0), d=d, now_ms=5000.0)
        check("응답" in s and "없음" not in s, s)


def _sess(base, name, on=True, ended=False, events=True):
    d = os.path.join(base, name)
    os.makedirs(d)
    with open(os.path.join(d, "session.json"), "w", encoding="utf-8") as f:
        json.dump({"입력": {"대본": ""}, "측정기록": on}, f)
    if events:
        with open(os.path.join(d, "events.csv"), "w", encoding="utf-8") as f:
            f.write("t_ms,kind,data\n1.0,run_start,{}\n" + ('2.0,measure_end,"{}"\n' if ended else ""))
    return d


def test_pick_session():
    print("\n[세션 고르기] 가장 새 기록 세션 하나만 — 기록 끔은 건너뛰고 · 끝났거나 따라간 것이면 기다린다(오래된 세션으로 돌아가지 않는다) · 더 새 세션이 생기면 그쪽(최종 리뷰 Important 2)")
    with tempfile.TemporaryDirectory() as base:
        os.makedirs(os.path.join(base, "폐기"))
        a = _sess(base, "20261011_100000_장소1_위반")
        check(G.pick_session(base) == a, "기록 중인 세션")
        _sess(base, "20261011_110000_장소1_시험", on=False, events=False)
        check(G.pick_session(base) == a, "더 새 세션이 기록 끔이면 건너뛴다")
        b = _sess(base, "20261011_120000_장소1_위반")
        check(G.pick_session(base) == b, "더 새 기록 세션이 생기면 그쪽")
        check(G.pick_session(base, done={b}) is None, "가장 새 것을 이미 따라갔으면 기다린다(옛 a 로 돌아가지 않는다)")
        _sess(base, "20261011_130000_장소1_위반", ended=True)
        check(G.pick_session(base) is None, "가장 새 것이 끝났으면 기다린다")


def test_single_instance():
    print("\n[한 대만] 새로 켠 진행 도우미가 옛 것을 끄고 잠금을 넘겨받는다 — 안내가 겹치지 않게(최종 리뷰 Important 3)")
    import subprocess
    import time
    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, "g.lock")
        code = ("import sys, time; sys.path.insert(0, %r); import measure_guide as G; "
                "f = G.take_lock(%r); print('잡음', flush=True); time.sleep(30)") % (_DEMO, lock)
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        check(p.stdout.readline().strip() == "잡음", "옛 진행 도우미가 잠금을 잡았다")
        t0 = time.time()
        f = G.take_lock(lock, wait_sec=5.0)
        check(f is not None and p.wait(timeout=5) is not None and time.time() - t0 < 5, "옛 것을 끄고 넘겨받았다")
        with open(lock, encoding="utf-8") as fh:
            check(fh.read().strip() == str(os.getpid()), "잠금 파일에 새 pid")


def test_keys():
    print("\n[키] N 뒤 1·2 · 3초 · U 는 기다리는 N 을 취소 · 한 번에 들어온 글자도 차례로(최종 리뷰 Minor 5·6)")
    pend, acts = G.handle_keys("N2", None, 1000.0)
    check(pend is None and acts == [("ng", 1000.0, "장비")], f"N2 = {acts}")
    pend, acts = G.handle_keys("n", None, 1000.0)
    check(pend == 1000.0 and acts == [], "N 만 = 이유 기다림")
    check(G.handle_keys("", pend, 4100.0) == (None, [("ng", 1000.0, "사람")]), "3초 지나면 사람")
    check(G.handle_keys("u", pend, 1500.0) == (None, []), "기다리는 N 을 U 로 취소 = 기록 없음")
    check(G.handle_keys("U", None, 2000.0) == (None, [("undo", 2000.0, None)]), "U = 마지막 N 취소")
    check(G.handle_keys("q", None, 0.0)[1] == [("quit", 0.0, None)], "Q = 끝")


def test_no_token_rows():
    print("\n[누름 칸 없음] 옛 대본이면 안내·자동 NG 없이 N 만(최종 리뷰 Important 5a)")
    R = [{"판": 1, "행동": "정상", "대상": "", "메모": "m", "누름": "", "낱말": []}]
    g = G.Guide(R, "EMO", cue_sink=lambda k, t: None)
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1"), E(20, "press", button="B3", expected="B1", state="MONITOR", source="gpio")]
    check(g.step(ev, 5000.0) is None and not g.auto, "안내·「다시」 없음")


def test_reset_cue():
    print("\n[초기화 안내] 틀린 공구 — 공구 대기(레시피)가 끝나고 1초 뒤 「작업 초기화」 한 번(설계 D17)")
    check(G.tool_waits() == {"B2": 10000.0}, f"레시피 공구 대기 = {G.tool_waits()}")
    try:
        R = rows((1, "B2 #플라이어 초기화"))
    except ValueError as e:
        check(False, f"「초기화」 를 못 읽음 — {e}")
        return
    check(G.cue_key(R[0]["낱말"][2]) == "cue_reset", "초기화 안내 키")
    sent = []
    g = G.Guide(R, "EMO", cue_sink=lambda k, t: sent.append(k), waits={"B2": 10000.0})
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B2")]
    g.step(ev, 1100.0)
    ev += [E(2000, "press", button="B2", expected="B2", state="MONITOR", source="gpio"),
           E(2000, "sub", what="start", button="B2", label="N2 퍼지")]
    g.step(ev, 3000.0)
    check(g.step(ev, 12900.0) is None, "공구 대기 끝(12.0초) + 1초 전에는 안 낸다")
    check(g.step(ev, 13000.0) == ("cue", "cue_reset"), "공구 대기 끝 + 1초 = 「작업 초기화」")
    check(g.step(ev, 20000.0) is None, "한 번만")
    check(sent == ["cue_B2", "cue_tool_pliers", "cue_reset"], f"낸 안내 = {sent}")


def test_cue_sounds_exist():
    print("\n[소리] 진행 도우미가 낼 수 있는 안내마다 소리(make_answers.CUES)가 있다 — 없으면 안경에서 조용히 안 난다")
    sys.path.insert(0, os.path.join(_DEMO, "voice"))
    import make_answers
    try:
        toks = MS.parse_tokens("B1 B2 B3 B4 EMO ~B1@B2 ~B2@B1 ~B3@B1 ~B4@B1 #렌치 #드라이버 #플라이어 초기화", B)
    except ValueError as e:
        check(False, f"낱말을 못 읽음 — {e}")
        return
    keys = {G.cue_key(t) for t in toks} | {"cue_ng"}
    check(keys <= set(make_answers.CUES), f"소리 없는 안내 = {sorted(keys - set(make_answers.CUES))}")


def V(t, k, **d):
    return (float(t), k, d)


def say_rows():
    T = lambda s: MS.parse_tokens(s, B)   # noqa: E731
    return [{"판": 1, "행동": "정상", "대상": "", "메모": "", "누름": "B1 말~ B2 말", "낱말": T("B1 말~ B2 말")},
            {"판": 1, "행동": "질문", "대상": "지금 몇 단계야?", "메모": "", "누름": "", "낱말": []},
            {"판": 1, "행동": "질문", "대상": "작업 결과 어때?", "메모": "", "누름": "", "낱말": []},
            {"판": 2, "행동": "호출", "대상": "", "메모": "", "누름": "EMO@B1 말", "낱말": T("EMO@B1 말")},
            {"판": 2, "행동": "비상질문", "대상": "지금 B1 눌러도 돼?", "메모": "", "누름": "", "낱말": []}]


def _say_guide():
    out, logged = [], []
    try:
        g = G.Guide(say_rows(), "EMO", cue_sink=lambda k, t: out.append(("cue", k)),
                    prompt_sink=lambda a, b: out.append(("p", a, b)), log_sink=lambda t, k, d: logged.append((k, d)))
    except (TypeError, ValueError) as e:
        check(False, f"말 안내를 못 만듦 — {e}")
        return None, out, logged
    return g, out, logged


def test_say_flow():
    print("\n[말] 음성 줄 화면 띠(3판 D21~D24) — 대기 중 · 다음 버튼 미룸 · 호출 → 이제 질문 → 끝 · 결과창 · 다음 판 넘어감 · 비상")
    g, out, logged = _say_guide()
    if g is None:
        return
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    g.step(ev, 1100.0)
    ev += [E(2000, "press", button="B1", expected="B1", state="MONITOR", source="gpio"),
           E(2000, "sub", what="start", button="B1")]
    check(g.step(ev, 2900.0) is None, "말~ = 앞 누름 + 1초 전에는 안 띄운다")
    check(g.step(ev, 3000.0) == ("say", "지금 몇 단계야?") and out[-1][0] == "p" and "지금 몇 단계야?" in out[-1][2],
          f"말~ 띄움 · {out[-1:]}")
    ev += [E(12000, "sub", what="finish", button="B1"), ST(12000, "PROCESS_RUN", "B2")]
    check(g.step(ev, 13500.0) is None, "말 동안 다음 버튼(B2) 소리를 미룬다")
    v = [V(14000, "stt", text="아니야."), V(14500, "stt", text="가디야."), V(14500, "wake")]
    g.step(ev, 14600.0, voice=v)
    check(out[-1][0] == "p" and "이제 질문" in (out[-1][1] or ""), f"호출 → 「이제 질문」 · {out[-1]}")
    v += [V(16000, "stt", text="지금몇단계야?")]
    check(g.step(ev, 16100.0, voice=v) == ("said", "질문") and out[-1] == ("p", None, None), "질문 받음 → 끝 · 띠 지움")
    check(logged[-1][0] == "said" and logged[-1][1].get("attempts") == 3, f"호출 시도 = 띄운 동안 받아쓰기 조각 수 · {logged[-1]}")
    check(g.step(ev, 17200.0, voice=v) is None, "질문 뒤 음성비서가 답하는 동안(확인 중 · 생각 중)은 버튼 소리를 미룬다(실물 피드백)")
    v += [V(17000, "play_start", key="checking"), V(18000, "play_end", key="checking"), V(20000, "answer", src="LLM"),
          V(20300, "play_start", key=None)]
    check(g.step(ev, 21000.0, voice=v) is None, "답 재생 중 = 미룸")
    v += [V(23000, "play_end", key=None)]
    check(g.step(ev, 23900.0, voice=v) is None, "답이 끝나고 1초 전 = 미룸")
    check(g.step(ev, 24100.0, voice=v) == ("cue", "cue_B2"), "답이 끝나고 1초 뒤 미룬 B2 소리")
    ev += [E(24200, "press", button="B2", expected="B2", state="MONITOR", source="gpio"), E(24200, "run_end", ok=True)]
    check(g.step(ev, 25100.0, voice=v) is None, "결과창 말 = 완주 + 1초 전에는 안 띄운다")
    check(g.step(ev, 25300.0, voice=v) == ("say", "작업 결과 어때?"), "판 끝 말 = 결과창(판이 닫힌 뒤)")
    ev += [E(26000, "run_start"), ST(26010, "PROCESS_RUN", "B1")]
    check(g.step(ev, 26100.0, voice=v) == ("said", "넘어감"), "다음 판이 시작되면 넘어감")
    check(g.step(ev, 27200.0, voice=v) == ("cue", "cue_EMO"), "다음 대본 판(비상) 안내")
    ev += [E(28000, "press", button="EMO", expected="B1", state="MONITOR", source="gpio"), ST(28000, "BLOCK", "B1")]
    check(g.step(ev, 29100.0, voice=v) == ("say", "지금 B1 눌러도 돼?") and "대답 없음" in (out[-1][1] or ""),
          f"비상 말 = 차단 중에도 띄움 · {out[-1]}")
    v += [V(30000, "stt", text="가디야."), V(30000, "emergency_ignored", text="가디야.", wake=True)]
    g.step(ev, 30100.0, voice=v)
    check("이제 질문" in (out[-1][1] or ""), f"비상 중 호출 → 「이제 질문」 · {out[-1]}")
    v += [V(31000, "stt", text="지금B1눌러도돼?"), V(31000, "emergency_ignored", text="지금B1눌러도돼?", wake=False)]
    check(g.step(ev, 31100.0, voice=v) == ("said", "질문"), "비상 중 질문 → 끝(대답 없음이 정상)")


def test_say_end_cases():
    print("\n[말 끝] 호출+질문 한 문장 · 30초 · 다음 버튼 = 넘어감")
    base = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1"), E(2000, "press", button="B1", expected="B1", state="MONITOR",
            source="gpio"), E(2000, "sub", what="start", button="B1")]
    g, out, _ = _say_guide()
    if g is None:
        return
    g.step(base, 3000.0)
    check(g.step(base, 4100.0, voice=[V(4000, "stt", text="가디언 지금 몇 단계야")]) == ("said", "질문"), "한 문장 = 끝")
    g, out, _ = _say_guide()
    g.step(base, 3000.0)
    v = [V(4000, "stt", text="가디관?"), V(4000, "wake")]
    check(g.step(base, 4100.0, voice=v) is None and "이제 질문" in (out[-1][1] or ""),
          "「가디관」(호출어 변형) = 호출만 — 음성비서 질문 규칙(is_question)과 같게")
    v += [V(5000, "stt", text="응.")]
    check(g.step(base, 5100.0, voice=v) is None, "호출 뒤 「응」(한 글자) = 질문 아님 — 음성비서도 무시한다")
    v += [V(6000, "stt", text="지금몇단계야")]
    check(g.step(base, 6100.0, voice=v) == ("said", "질문"), "그다음 질문 = 끝")
    g, out, _ = _say_guide()
    g.step(base, 3000.0)
    check(g.step(base, 32900.0) is None and g.step(base, 33000.0) == ("said", "시간"), "30초 = 시간")
    g, out, _ = _say_guide()
    g.step(base, 3000.0)
    ev = base + [E(12000, "sub", what="finish", button="B1"), ST(12000, "PROCESS_RUN", "B2"),
                 E(13000, "press", button="B2", expected="B2", state="MONITOR", source="gpio")]
    check(g.step(ev, 13100.0) == ("said", "넘어감") and out[-1] == ("p", None, None), "다음 버튼을 누르면 넘어감 · 띠 지움")


def test_busy_unprompted():
    print("\n[대화 중] 띠 없이 스스로 「가디언」을 불러도 답이 끝날 때까지 버튼 소리를 미룬다 · 답이 없으면 21초 뒤 다시")
    out = []
    g = G.Guide(rows((1, "B1 B2")), "EMO", cue_sink=lambda k, t: out.append(k))
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    v = [V(500, "stt", text="가디야."), V(500, "wake")]
    check(g.step(ev, 1100.0, voice=v) is None, "호출 뒤 = 미룸")
    v2 = v + [V(5000, "answer", src="LLM"), V(5200, "play_start", key=None), V(7000, "play_end", key=None)]
    check(g.step(ev, 8100.0, voice=v2) == ("cue", "cue_B1"), "답이 끝나고 1초 뒤 = 안내")
    g = G.Guide(rows((1, "B1 B2")), "EMO", cue_sink=lambda k, t: None)
    check(g.step(ev, 22400.0, voice=v) is None and g.step(ev, 22600.0, voice=v) == ("cue", "cue_B1"),
          "답이 없으면(호출만) 호출 + 21초(대화창) + 1초 뒤 다시 안내")


def test_busy_slow_answer():
    print("\n[대화 중 · 늦은 답] 질문을 받았으면 LLM 한도까지 기다린다 · 답 재생 끝은 그 답의 소리만 센다(최종 리뷰 I1)")
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    v = [V(500, "stt", text="가디야."), V(500, "wake"), V(8500, "stt", text="지금몇단계야?")]
    check(G.assistant_busy(v, 25000.0)[0], "호출 + 8초 질문 → 호출 + 24.5초에도 아직 대화 중(답을 기다린다)")
    check(G.assistant_busy(v + [V(33500, "answer", src="LLM")], 33600.0)[0], "질문 + 25초 답 → 답 재생 중")
    v2 = v + [V(33500, "answer", src="LLM"), V(33600, "play_start", key="cue_B1"), V(33900, "play_end", key="cue_B1")]
    check(G.assistant_busy(v2, 34000.0)[0], "안내 소리 재생 끝은 답 끝으로 세지 않는다")
    v3 = v2 + [V(34000, "play_start", key=None), V(36000, "play_end", key=None)]
    check(G.assistant_busy(v3, 36100.0) == (False, 36000.0), "그 답(LLM · 키 없음)의 재생 끝 = 대화 끝")
    v4 = [V(500, "stt", text="가디야."), V(500, "wake")]
    check(not G.assistant_busy(v4, 22000.0)[0], "질문 없이 호출만 = 대화창(20초) + 1초 뒤 풀림(종전과 같음)")
    g = G.Guide(rows((1, "B1 B2")), "EMO", cue_sink=lambda k, t: None)
    check(g.step(ev, 25000.0, voice=v) is None, "늦은 답을 기다리는 동안 버튼 안내를 내지 않는다")


def _csv_rows(rows):
    def q(x):
        return '"' + json.dumps(x, ensure_ascii=False).replace('"', '""') + '"'
    return "t_ms,kind,data\n" + "".join(f"{t},{k},{q(d)}\n" for t, k, d in rows)


def test_replay_result_say():
    print("\n[재생] 결과창 말 · 판 사이 「said」 에서도 재생 도구가 죽지 않는다(최종 리뷰 I2)")
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "session.json"), "w", encoding="utf-8") as f:
            json.dump({"입력": {"대본": "s.csv"}, "측정기록": True}, f)
        with open(os.path.join(d, "s.csv"), "w", encoding="utf-8") as f:
            f.write("판,행동,대상,기대,메모,누름\n1,정상,,,,B1 말\n1,질문,작업 결과 어때?,,,\n")
        ev = [(0, "run_start", {}), (10, "state", {"old": "X", "new": "PROCESS_RUN", "expected": "B1"}),
              (2000, "press", {"button": "B1", "expected": "B1", "state": "MONITOR", "source": "gpio"}),
              (2000, "run_end", {"ok": True}), (9000, "run_start", {})]
        with open(os.path.join(d, "events.csv"), "w", encoding="utf-8") as f:
            f.write(_csv_rows(ev))
        try:
            out = G.replay(d, dump=False)
        except Exception as e:                       # noqa: BLE001
            check(False, f"재생이 죽음 — {type(e).__name__}: {e}")
            return
        says = [o for o in out if o[3] in ("작업 결과 어때?", "넘어감")]
        check(len(says) == 2 and all(o[1] == 1 for o in says), f"결과창 말 · 넘어감 = 1번째 판으로 남는다 · {out}")


def _guide_for(rows_):
    out = []
    g = G.Guide(rows_, "EMO", cue_sink=lambda k, t: out.append(("cue", k)), prompt_sink=lambda a, b: out.append(("p", a, b)))
    return g, out


def test_say_minor_fixes():
    print("\n[말 사소] 비상 말 제목 · 결과창 말 = 대화 끝 + 1초 · 대화창 20초 뒤 받아쓰기 = 질문 아님(최종 리뷰 M2 M3 M4)")
    T = lambda s_: MS.parse_tokens(s_, B)   # noqa: E731
    emo_rows = [{"판": 1, "행동": "호출", "대상": "", "메모": "", "누름": "EMO@B1 말", "낱말": T("EMO@B1 말")},
                {"판": 1, "행동": "비상질문", "대상": "지금 B1 눌러도 돼?", "메모": "", "누름": "", "낱말": []}]
    g, out = _guide_for(emo_rows)
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    g.step(ev, 1100.0)
    ev += [E(2000, "press", button="EMO", expected="B1", state="MONITOR", source="gpio"), ST(2000, "BLOCK", "B1")]
    g.step(ev, 3100.0)
    g.step(ev, 4100.0, voice=[V(4000, "stt", text="가디야."), V(4000, "emergency_ignored", text="가디야.", wake=True)])
    title = out[-1][1] or ""
    check("호출" in title and "띠링" not in title.split("—")[0], f"비상 말 = 띠링이 없으니 「호출 ✓」 · {title}")
    res_rows = [{"판": 1, "행동": "정상", "대상": "", "메모": "", "누름": "B1 말", "낱말": T("B1 말")},
                {"판": 1, "행동": "질문", "대상": "작업 결과 어때?", "메모": "", "누름": "", "낱말": []}]
    g, out = _guide_for(res_rows)
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1"),
          E(2000, "press", button="B1", expected="B1", state="MONITOR", source="gpio"), E(2000, "run_end", ok=True)]
    v = [V(1500, "stt", text="가디야."), V(1500, "wake"), V(2500, "answer", src="LLM"),
         V(2600, "play_start", key=None), V(2800, "play_end", key=None)]
    check(g.step(ev, 3500.0, voice=v) is None, "결과창 말 = 대화 끝 + 1초 전에는 안 띄운다(닫힘음·마이크 버림과 겹치지 않게)")
    check(g.step(ev, 3900.0, voice=v) == ("say", "작업 결과 어때?"), "대화 끝 + 1초 뒤 결과창 말")
    win_rows = [{"판": 1, "행동": "정상", "대상": "", "메모": "", "누름": "B1 말~ B2", "낱말": T("B1 말~ B2")},
                {"판": 1, "행동": "질문", "대상": "지금 몇 단계야?", "메모": "", "누름": "", "낱말": []}]
    g, out = _guide_for(win_rows)
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1"),
          E(2000, "press", button="B1", expected="B1", state="MONITOR", source="gpio"), E(2000, "sub", what="start", button="B1")]
    g.step(ev, 1100.0)
    g.step(ev, 3000.0)
    v = [V(4000, "stt", text="가디야."), V(4000, "wake"), V(25000, "stt", text="지금몇단계야?")]
    check(g.step(ev, 25100.0, voice=v) is None, "호출 + 21초 받아쓰기 = 대화창이 닫혀 음성비서도 무시 → 말은 끝나지 않는다")
    check("지금 말하세요" in (out[-1][1] or ""), f"대화창이 닫히면 띠는 다시 「지금 말하세요」 · {out[-1]}")


def main():
    test_scene_prompt()
    test_say_minor_fixes()
    test_replay_result_say()
    test_busy_slow_answer()
    test_busy_unprompted()
    test_say_flow()
    test_say_end_cases()
    test_next_cue()
    test_reset_cue()
    test_cue_sounds_exist()
    test_guide_step_and_ng()
    test_resume_from_guide_csv()
    test_no_script()
    test_tail_and_req()
    test_ack_status()
    test_pick_session()
    test_single_instance()
    test_keys()
    test_no_token_rows()
    print()
    if _fails:
        print(f"❌ {len(_fails)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


def test_scene_prompt():
    print("\n[장면 안내] 대본 「안내」 칸 → 판이 열리면 띠 한 번 · 닫히면 지움 · 안내 없는 판 · 대본은 띠를 건드리지 않음(학교 방문 준비 설계 §5.2)")
    rs = rows((1, "B1"), (2, "B1"))
    rs[0]["안내"], rs[1]["안내"] = "", "G2 · B1 — B2 위를 지나서 누르기"
    out = []
    g = G.Guide(rs, "EMO", cue_sink=lambda k, t: None, prompt_sink=lambda a, b: out.append((a, b)))
    ev = [E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")]
    g.step(ev, 100.0)
    check(out == [], f"안내 없는 판 1 → 띠 없음 {out}")
    ev += [E(500, "press", button="B1", expected="B1", state="PROCESS_RUN", source="gpio"), E(600, "run_end"),
           E(1000, "run_start"), ST(1010, "PROCESS_RUN", "B1")]
    g.step(ev, 1100.0)
    g.step(ev, 1200.0)
    check(out == [("📋 판 2 — 이렇게 하세요", "G2 · B1 — B2 위를 지나서 누르기")], f"판 2 열림 → 한 번 {out}")
    ev += [E(1500, "press", button="B1", expected="B1", state="PROCESS_RUN", source="gpio"), E(2000, "run_end")]
    g.step(ev, 2100.0)
    check(out[-1] == (None, None), f"판이 닫히면 지움 {out}")
    plain = []
    g2 = G.Guide(rows((1, "B1")), "EMO", cue_sink=lambda k, t: None, prompt_sink=lambda a, b: plain.append((a, b)))
    g2.step([E(0, "run_start"), ST(10, "PROCESS_RUN", "B1")], 100.0)
    check(plain == [], f"안내 칸 없는 대본(지금 대본) → 띠 없음 {plain}")
    g.say = {"run": 3}
    n = len(out)
    g._scene_prompt({"i": 3, "script": 2})
    check(len(out) == n, "말 띠가 떠 있으면 장면 띠를 띄우지 않는다")


if __name__ == "__main__":
    sys.exit(main())
