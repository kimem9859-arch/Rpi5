"""리허설 판정 규칙 — ❌ 이상 · ⚠️ 애매 · 🟡 임시 · ✅ 확정 · 세션 지표 · 결과표(학교 방문 준비 설계 §7.3 · §7.4).

실행: python3 Demo/selftest/test_rehearse_judge.py
"""
import os
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import rehearse_judge as RJ

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def item(**kw):
    base = {"id": "R?", "kind": "확정", "finished": True, "errors": [], "warnings": [], "values": {},
            "expect": {}, "samples": {}, "script": None, "same": None, "phys": [], "split": None}
    base.update(kw)
    return base


def test_marks():
    print("\n[판정] 종류 · 조건별 표시")
    check(RJ.judge(item())[0] == "✅", "다 좋고 확정 → ✅")
    check(RJ.judge(item(kind="임시"))[0] == "🟡", "임시 → 🟡")
    check(RJ.judge(item(kind="흐름"))[0] == "✅", "흐름 → ✅")
    m, why = RJ.judge(item(values={"fps": [10.0, 11.5]}))
    check(m == "⚠️" and any("15%" in w for w in why), f"두 번 차이 15% → ⚠️ {why}")
    m, why = RJ.judge(item(values={"fps": [13.9, 13.9]}, expect={"fps": (14.5, 17.0)}))
    check(m == "⚠️" and any("범위" in w for w in why), f"기대 범위 밖 → ⚠️ {why}")
    m, why = RJ.judge(item(samples={"처리 장": (25, 30)}))
    check(m == "⚠️" and any("표본" in w for w in why), f"표본 부족 → ⚠️ {why}")
    check(RJ.judge(item(warnings=["경고 줄"]))[0] == "⚠️", "경고 출력 → ⚠️")
    check(RJ.judge(item(finished=False))[0] == "❌", "끝까지 못 돎 → ❌")
    check(RJ.judge(item(errors=["Traceback"]))[0] == "❌", "오류 → ❌")
    m, why = RJ.judge(item(phys=[("처리 ≤ 받은", False)]))
    check(m == "❌" and any("처리 ≤ 받은" in w for w in why), f"물리적으로 안 되는 값 → ❌ {why}")
    check(RJ.judge(item(script=(15, 14)))[0] == "❌", "대본 15판 · 실제 14 → ❌")
    check(RJ.judge(item(script=(15, 15)))[0] == "✅", "대본 판 수 맞음 → ✅")
    check(RJ.judge(item(same=False))[0] == "❌", "확정 비교 다름 → ❌")
    check(RJ.judge(item(values={"fps": [0.0, 12.0]}))[0] == "❌", "값 0 → ❌")
    check(RJ.judge(item(values={"fps": [None, 12.0]}))[0] == "❌", "값 없음 → ❌")
    m, why = RJ.judge(item(kind="임시", values={"2a": [15.0, 16.0], "2a+2b": [15.5, 16.2]}, split=("2a", "2a+2b")))
    check(m == "⚠️" and any("안 갈림" in w for w in why), f"효과가 흩어짐보다 작음 → ⚠️ {why}")
    m, why = RJ.judge(item(kind="임시", values={"2a": [15.0, 15.2], "2a+2b": [18.0, 18.3]}, split=("2a", "2a+2b")))
    check(m == "🟡", f"효과가 갈림 → 🟡 {why}")
    m, why = RJ.judge(item(finished=False, values={"fps": [10.0, 12.0]}))
    check(m == "❌" and len(why) >= 2, f"❌ 와 ⚠️ 가 같이 → ❌ · 이유 둘 다 {why}")


def test_session_stats():
    print("\n[세션 지표] 처리 fps = (장 수 − 1) ÷ 시간 · 받은 fps = 받은 누적 수 차이 ÷ 시간 · 판 수")
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "frames.csv"), "w", encoding="utf-8") as f:
        f.write("frame,t_recv_ms,recv_seq,t_start_ms\n")
        for i in range(11):
            f.write(f"{i + 1},{1000.0 + i * 100},{1 + 2 * i},0\n")
    with open(os.path.join(d, "events.csv"), "w", encoding="utf-8") as f:
        f.write("t_ms,kind,data\n1,run_start,{}\n2,run_end,{}\n3,run_start,{}\n")
    st = RJ.session_stats(d)
    check(st["frames"] == 11 and abs(st["proc_fps"] - 10.0) < 1e-6 and abs(st["recv_fps"] - 20.0) < 1e-6,
          f"{st}")
    check(st["runs"] == 2, f"판 수 {st['runs']}")
    empty = RJ.session_stats(tempfile.mkdtemp())
    check(empty["frames"] == 0 and empty["proc_fps"] is None, f"기록 없음 → {empty}")


def test_write_table():
    print("\n[결과표] 학교 필수 = ❌ · ⚠️ · 🟡 만 · 짝 명령 칸")
    d = tempfile.mkdtemp()
    items = [dict(item(id="R2", kind="흐름"), title="판 1 재확인"),
             dict(item(id="R3-1", kind="임시", values={"처리 fps": [15.0, 15.4]}), title="1단계"),
             dict(item(id="R6", finished=False), title="램프")]
    p = os.path.join(d, "결과.md")
    RJ.write_table(items, p, {"R3-1": "bash run_measure.sh · 처리 설정 1"})
    s = open(p, encoding="utf-8").read()
    must = s[s.index("학교 필수"):s.index("## 항목")]
    check("R3-1" in must and "R6" in must and "R2" not in must, f"학교 필수 목록 {must!r}")
    check("bash run_measure.sh · 처리 설정 1" in s and "15.0 · 15.4" in s, "짝 명령 · 두 번 값")


if __name__ == "__main__":
    test_marks()
    test_session_stats()
    test_write_table()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 리허설 판정 검증 통과")
