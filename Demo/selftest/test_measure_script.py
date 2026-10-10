"""판 맞춤(측정 진행 도우미 설계 2026-10-11 §3.1 · §4.2 · §4.3) — 손으로 만든 작은 기록으로.

실행: python3 Demo/selftest/test_measure_script.py
"""
import os
import sys
import tempfile

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import measure_script as MS

_fails = []
B = ["B1", "B2", "B3", "B4"]


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def E(t, k, **d):
    return (float(t), k, d)


def P(t, b, exp, state="MONITOR"):
    return E(t, "press", button=b, expected=exp, state=state, source="gpio")


def rows(*pairs):
    """(판, 누름 칸) → load_script 꼴 줄."""
    return [{"판": p, "행동": "위반", "누름": s, "낱말": MS.parse_tokens(s, B, row=i)} for i, (p, s) in enumerate(pairs)]


def test_parse_tokens():
    print("\n[낱말] 맞는 누름 · 위반 · EMO · 머묾 · 공구 · 끝 ? · 틀린 낱말")
    t = MS.parse_tokens("B2@B1 B1 EMO@B4 EMO ~B4@B3 #렌치 B3? B4?", B)
    check([(x.kind, x.name, x.expected, x.optional) for x in t] == [
        ("press", "B2", "B1", False), ("press", "B1", "B1", False), ("press", "EMO", "B4", False),
        ("press", "EMO", None, False), ("hover", "B4", "B3", False), ("tool", "렌치", None, False),
        ("press", "B3", "B3", True), ("press", "B4", "B4", True)], f"{t}")
    for bad in ("B5", "~B4", "#망치", "B2@B9", "~EMO@B1", "B2@@B1"):
        try:
            MS.parse_tokens(bad, B)
            check(False, f"「{bad}」 를 못 잡음")
        except ValueError:
            check(True, f"「{bad}」 = ValueError")


def test_load_script():
    print("\n[대본] 누름 칸을 낱말로 · 틀리면 줄 번호 · 칸이 없으면 낱말 없음(지금처럼 센다)")
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "s.csv")
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("판,행동,대상,기대,메모,누름\n1,위반,B2,,메모,B2@B1 B1\n1,호출,,,,\n")
        r = MS.load_script(p, buttons=B)
        check(len(r) == 2 and [x.name for x in r[0]["낱말"]] == ["B2", "B1"] and r[1]["낱말"] == [], "낱말 읽음")
        check(MS.has_tokens(r), "낱말 있음")
        with open(p, "w", encoding="utf-8") as f:
            f.write("판,행동,대상,기대,메모,누름\n1,위반,B2,,,B2@B1\n2,위반,B3,,,B7\n")
        try:
            MS.load_script(p, buttons=B)
            check(False, "틀린 낱말을 못 잡음")
        except ValueError as e:
            check("3행" in str(e) and "누름" in str(e), f"{e}")
        with open(p, "w", encoding="utf-8") as f:
            f.write("판,행동,대상,기대,메모\n1,위반,B2,,\n")
        check(not MS.has_tokens(MS.load_script(p, buttons=B)), "누름 칸 없음 = 낱말 없음")


def test_run_presses_ignored():
    print("\n[무시] 차단 중 EMO 아닌 버튼 · 자기 대기 중 같은 버튼 — 시연도 무시한 누름은 세지 않는다")
    ev = [P(1, "B1", "B1"), E(2, "sub", what="start", button="B1"), P(3, "B1", "B1"),
          P(4, "B2", "B1"), E(5, "sub", what="cancel", button="B1"), P(6, "B3", "B1", state="BLOCK"),
          P(7, "EMO", "B1", state="BLOCK"), P(8, "B1", "B1")]
    got = [(b, e) for _, b, e in MS.run_presses(ev)]
    check(got == [("B1", "B1"), ("B2", "B1"), ("EMO", "B1"), ("B1", "B1")], f"{got}")


def _run(t0, presses, end="run_reset"):
    return [E(t0, "run_start")] + presses + [E(t0 + 90, end)]


def test_match_ok_ng_retry():
    print("\n[맞춤] 대본대로 = ok · 안내와 다른 누름 = 자동 NG → 같은 대본 판 다시(진행 도우미 ahead 0)")
    R = rows((1, "B2@B1 B1"), (2, "B3@B1 B1"))
    ev = (_run(0, [P(10, "B2", "B1"), P(20, "B1", "B1")]) + _run(100, [P(110, "B4", "B1")])
          + _run(200, [P(210, "B3", "B1"), P(220, "B1", "B1")]))
    m = MS.match(ev, R)
    check([(r["i"], r["script"], r["status"]) for r in m["runs"]] == [(1, 1, "ok"), (2, 2, "ng"), (3, 2, "ok")],
          f"{[(r['i'], r['script'], r['status']) for r in m['runs']]}")
    check(m["runs"][1]["why"].startswith("자동 — 1번째 누름 B4@B1"), m["runs"][1]["why"])
    check(m["next"] is None, "대본을 다 했다")


def test_match_ahead():
    print("\n[앞 찾기] 세기(ahead 2) — NG 뒤 다시 안 하고 넘어간 기록도 맞추고 건너뛴 판을 남긴다 · 뒤 판은 끝까지 맞을 때만")
    R = rows((1, "B2@B1 B1"), (2, "B3@B1 B1"), (3, "B4@B1 B1"))
    ev = (_run(0, [P(10, "B4", "B1")]) + _run(100, [P(110, "B3", "B1"), P(120, "B1", "B1")])
          + _run(200, [P(210, "B4", "B1"), P(220, "B1", "B1")]))
    m = MS.match(ev, R, ahead=2)
    check([(r["script"], r["status"], r["skipped"]) for r in m["runs"]] == [(1, "ng", []), (2, "ok", [1]), (3, "ok", [])],
          f"{[(r['script'], r['status'], r['skipped']) for r in m['runs']]} — 1번째(B4 만)는 대본 3 의 앞부분과 같아도 건너뛰지 않는다")
    m0 = MS.match(ev, R, ahead=0)
    check([r["status"] for r in m0["runs"]] == ["ng", "ng", "ng"], "진행 도우미(ahead 0)는 지금 판에만 맞춘다")


def test_match_partial_and_extra():
    print("\n[미완 · 대본 밖] 일찍 끝난 판 = 미완(남김) → 다음 대본 판 · 대본 뒤 판 = 대본 밖 · 끝 ? 는 없어도 ok")
    R = rows((1, "B1 B2"), (2, "B1 B2? B3?"))
    ev = _run(0, [P(10, "B1", "B1")]) + _run(100, [P(110, "B1", "B1")]) + _run(200, [P(210, "B1", "B1")])
    m = MS.match(ev, R, ahead=2)
    check([(r["script"], r["status"], r["missing"]) for r in m["runs"]] == [(1, "partial", 1), (2, "ok", 0), (None, "extra", 0)],
          f"{[(r['script'], r['status'], r['missing']) for r in m['runs']]}")


def test_match_manual():
    print("\n[수동] N = 그 시각의 판(판 사이면 막 끝난 판) NG · 같은 대본 판 다시 · U = 마지막 N 취소")
    R = rows((1, "B1"), (2, "B2@B1"))
    ev = _run(0, [P(10, "B1", "B1")]) + _run(100, [P(110, "B1", "B1")]) + _run(200, [P(210, "B2", "B1")])
    m = MS.match(ev, R, marks=[(95.0, "ng", "장비")])
    check([(r["script"], r["status"]) for r in m["runs"]] == [(1, "ng"), (1, "ok"), (2, "ok")],
          f"{[(r['script'], r['status']) for r in m['runs']]}")
    check(m["runs"][0]["why"] == "수동 — 장비", m["runs"][0]["why"])
    m2 = MS.match(ev, R, marks=[(95.0, "ng", "사람"), (96.0, "undo", None)])
    check(m2["runs"][0]["status"] == "ok", "U 가 N 을 지웠다")


def test_match_open_live():
    print("\n[열린 판] 진행 중 판 = open · 안내와 다른 누름이면 live_ng · 쓴 누름 낱말 수")
    R = rows((1, "B2@B1 B1"))
    m = MS.match([E(0, "run_start"), P(10, "B2", "B1")], R)
    check(m["runs"][0]["status"] == "open" and m["runs"][0]["consumed"] == 1 and not m["runs"][0]["live_ng"], f"{m['runs'][0]}")
    m = MS.match([E(0, "run_start"), P(10, "B3", "B1")], R)
    check(m["runs"][0]["live_ng"] and m["runs"][0]["status"] == "open", f"{m['runs'][0]}")


def test_manual_only():
    print("\n[수동만] 누름 칸 없는 대본·대본 없는 세션 — 자동 NG 없이 N 만 빼고 다음 판은 같은 대본 판(최종 리뷰 Important 5)")
    R = [{"판": 1, "행동": "정상", "누름": "", "낱말": []}, {"판": 2, "행동": "정상", "누름": "", "낱말": []}]
    ev = _run(0, [P(10, "B1", "B1")]) + _run(100, [P(110, "B3", "B1")]) + _run(200, [P(210, "B1", "B1")]) + _run(300, [])
    m = MS.match(ev, R, marks=[(150.0, "ng", "사람")], auto=False)
    check([(r["script"], r["status"]) for r in m["runs"]] == [(1, "ok"), (2, "ng"), (2, "ok"), (None, "extra")],
          f"{[(r['script'], r['status']) for r in m['runs']]}")
    m = MS.match(ev, None, marks=[(150.0, "ng", "장비")], auto=False)
    check([(r["script"], r["status"]) for r in m["runs"]] == [(None, "ok"), (None, "ng"), (None, "ok"), (None, "ok")],
          f"대본 없음 = {[(r['script'], r['status']) for r in m['runs']]}")


def test_final_open_run():
    print("\n[세기 끝] 세션이 판 도중에 끝나면 세기(final)는 그 판도 닫힌 판처럼 판정한다(최종 리뷰 Minor 3)")
    R = rows((1, "B2@B1 B1"))
    ev = [E(0, "run_start"), P(10, "B3", "B1")]
    check(MS.match(ev, R)["runs"][0]["status"] == "open", "진행 도우미 = open")
    check(MS.match(ev, R, ahead=2, final=True)["runs"][0]["status"] == "ng", "세기 = 자동 NG")


def test_auto_then_manual():
    print("\n[겹침] 자동 NG 판에 N 을 더 눌러도 자동으로 센다(최종 리뷰 Minor 2)")
    R = rows((1, "B2@B1"))
    m = MS.match(_run(0, [P(10, "B4", "B1")]), R, marks=[(50.0, "ng", "사람")])
    check(m["runs"][0]["status"] == "ng" and m["runs"][0]["why"].startswith("자동"), m["runs"][0]["why"])


def test_emo_repress():
    print("\n[EMO 재입력] EMO 차단 중 EMO 를 또 눌러도(시연은 아무 일 없음) 세지 않는다 · 해제 뒤 EMO 는 센다(최종 리뷰 Minor 7)")
    ev = [P(1, "EMO", "B4"), P(2, "EMO", "B4", state="BLOCK"), E(3, "release", what="block", ok=True),
          P(4, "B2", "B4", state="BLOCK"), P(5, "EMO", "B4", state="BLOCK")]
    got = [(b, e) for _, b, e in MS.run_presses(ev)]
    check(got == [("EMO", "B4"), ("EMO", "B4")], f"{got}")


def main():
    test_parse_tokens()
    test_load_script()
    test_run_presses_ignored()
    test_match_ok_ng_retry()
    test_match_ahead()
    test_match_partial_and_extra()
    test_match_manual()
    test_match_open_live()
    test_manual_only()
    test_final_open_run()
    test_auto_then_manual()
    test_emo_repress()
    print()
    if _fails:
        print(f"❌ {len(_fails)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
