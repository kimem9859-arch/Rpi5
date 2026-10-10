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


def main():
    test_next_cue()
    test_guide_step_and_ng()
    test_resume_from_guide_csv()
    test_no_script()
    test_tail_and_req()
    test_ack_status()
    print()
    if _fails:
        print(f"❌ {len(_fails)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
