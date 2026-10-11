"""근거 분석 도구 — 손끝 속도 · 들어감(다가옴 · 안 속도 · 머묾 · 감속 · 보임) · 장면 요약(학교 방문 준비 설계 §5.3).

실행: python3 Demo/selftest/test_measure_basis.py
"""
import json
import os
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))

import measure_basis as MB

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def F(t, x=None, y=0, roi=""):
    return {"t": float(t), "tip": None if x is None else (float(x), float(y)), "roi": roi}


def approach_then_stay():
    """손끝이 0.1초마다 100화소씩 오다가(1000화소/초) B2 에 들어가 0.5초 머문다."""
    fr = [F(t, x=t) for t in range(0, 600, 100)]                  # x = 0 … 500
    fr += [F(t, x=600, roi="B2") for t in range(600, 1200, 100)]   # 들어감 t=600 · 머묾
    fr += [F(1200, x=900)]
    return fr


def test_speeds():
    print("\n[속도] 앞 손끝이 0.25초 안 · 최대 3장 앞 — 10/11 분석과 같은 정의")
    sp = MB.speeds(approach_then_stay())
    check(sp[0] is None and abs(sp[1] - 1000) < 1e-6, f"첫 장 없음 · 둘째 1000 → {sp[:2]}")
    check(sp[7] == 0.0, f"머무는 장 0 → {sp[7]}")
    gap = [F(0, x=0), F(100), F(200), F(300), F(400, x=100)]
    check(MB.speeds(gap)[4] is None, "손끝이 빠진 뒤 0.25초 넘게 → None")
    near = [F(0, x=0), F(100), F(200, x=50)]
    check(abs(MB.speeds(near)[2] - 250) < 1e-6, f"두 장 앞(0.2초) 손끝 → 250 {MB.speeds(near)[2]}")


def test_entries():
    print("\n[들어감] 다가옴 · 안 속도 · 머문 시간 · 감속 비 · 보임")
    e = MB.entries(approach_then_stay())
    check(len(e) == 1 and e[0]["roi"] == "B2", f"들어감 하나 {e}")
    x = e[0]
    check(abs(x["approach"] - 1000) < 1e-6, f"다가옴 1000 → {x['approach']}")
    check(x["inside"] == 0.0 and abs(x["dwell"] - 0.5) < 1e-6, f"안 속도 0 · 머묾 0.5초 → {x['inside']} · {x['dwell']}")
    check(x["decel"] is not None and x["decel"] < 0.1, f"감속 비 < 0.1 → {x['decel']}")
    check(abs(x["seen"] - 1.0) < 1e-6, f"보임 1.0 → {x['seen']}")
    two = [F(0, 0), F(100, 100, roi="B1"), F(200, 200, roi="B3"), F(300, 300)]
    check([y["roi"] for y in MB.entries(two)] == ["B1", "B3"], "구역이 바뀌면 들어감 둘")


def _session(d, runs):
    """합성 세션 — 대본(안내 칸) · events · frames."""
    with open(os.path.join(d, "장소1_⑥근거.csv"), "w", encoding="utf-8-sig") as f:
        f.write("판,행동,대상,기대,메모,누름,안내\n")
        for i, scene in enumerate(runs, 1):
            f.write(f"{i},정상,,,,B1 B2 B3 B4,{scene} · 시험\n")
    ev, fr, t = [], [], 1000.0
    for i, _ in enumerate(runs):
        ev.append((t, "run_start", {}))
        ev.append((t + 1, "state", {"old": "IDLE", "new": "PROCESS_RUN", "expected": "B1"}))
        base = approach_then_stay()
        for k, b in enumerate(("B1", "B2", "B3", "B4")):
            t0 = t + 10 + k * 1300
            fr += [dict(x, t=x["t"] + t0, roi=(b if x["roi"] else "")) for x in base]
            ev.append((t0 + 700, "press", {"button": b, "expected": b, "state": "PROCESS_RUN", "source": "gpio"}))
        t += 6000
        ev.append((t - 100, "run_end", {}))
    with open(os.path.join(d, "events.csv"), "w", encoding="utf-8") as f:
        f.write("t_ms,kind,data\n")
        for tt, k, dd in ev:
            f.write(f'{tt},{k},"{json.dumps(dd).replace(chr(34), chr(34) * 2)}"\n')
    with open(os.path.join(d, "frames.csv"), "w", encoding="utf-8") as f:
        f.write("frame,t_recv_ms,tip_x,tip_y,roi\n")
        for n, x in enumerate(sorted(fr, key=lambda z: z["t"])):
            tx, ty = ("", "") if x["tip"] is None else x["tip"]
            f.write(f"{n + 1},{x['t']},{tx},{ty},{x['roi']}\n")


def test_summarize():
    print("\n[요약] 장면마다 들어감 · 쓸 만한 수 · 다시 할 판(쓸 만한 들어감 < 5)")
    d = tempfile.mkdtemp()
    _session(d, ["G1", "G1", "G2"])
    s = MB.summarize(d)
    check(s["장면"]["G1"]["runs"] == 2 and s["장면"]["G1"]["usable"] == 8, f"G1 {s['장면'].get('G1')}")
    check(s["장면"]["G2"]["usable"] == 4 and s["redo"] == {"G2": [3]}, f"G2 · 다시 할 판 {s['redo']}")
    check(abs(s["장면"]["G1"]["approach_med"] - 1000) < 1e-6, f"다가옴 중앙 {s['장면']['G1']['approach_med']}")
    out = MB.main([d])
    check(out == 1 and os.path.exists(os.path.join(d, "basis.json")), "다시 할 판이 있으면 종료 코드 1 · basis.json")


if __name__ == "__main__":
    test_speeds()
    test_entries()
    test_summarize()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 근거 분석 도구 검증 통과")
