"""안경 소리 점검 도구(voice/glass_sound_check.py)의 분석 — 합성 소리로 판정이 맞는지(2026-10-09).

실행: python3 Demo/selftest/test_glass_sound_check.py
⚠️ 보드·소켓을 쓰지 않는다 — 분석 함수만 본다.
"""
import os
import sys

import numpy as np

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "voice"))

import glass_sound_check as g  # noqa: E402

R = g.RATE
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def sine(f0, ms, amp=8000.0, h2=0.0):
    t = np.arange(int(R * ms / 1000)) / R
    return amp * np.sin(2 * np.pi * f0 * t) + h2 * amp * np.sin(2 * np.pi * 2 * f0 * t)


def noise(ms, rms=20.0, seed=0):
    return np.random.default_rng(seed).normal(0, rms, int(R * ms / 1000))


def chime(lo, hi, h2_lo=0.0):
    """펌웨어 일정 그대로(30 · 120 · 40 · 180 · 60) — 앞 여백 30ms 는 무음이라 소리는 낮은 음부터."""
    return np.concatenate([np.zeros(int(R * 0.03)), sine(lo, 120, h2=h2_lo), np.zeros(int(R * 0.04)),
                           sine(hi, 180), np.zeros(int(R * 0.06))])


print("[펌웨어 높이] 소스의 CHIME_LO·HI — 단일 출처")
lo, hi = g.fw_chime_hz()
check(lo < hi, f"열림 = 낮은 음 → 높은 음 · {lo:g} → {hi:g}")
check(1175.0 not in (lo, hi), "🔴 1175Hz 를 쓰지 않는다(10/8 실측 — 스피커가 못 내고 2배음이 더 컸다)")

print("[음 하나] tone_quality — 깨끗한 사인 ↔ 2배음 섞임")
_, h, _ = g.tone_quality(sine(1568, 120), 1568)
check(h < g.CLEAN_HARM, f"깨끗한 1568Hz → 배음 {h * 100:.2f}%")
_, h, _ = g.tone_quality(sine(1175, 120, h2=1.2), 1175)
check(h > 1.0, f"2배음이 기본음보다 큰 1175Hz(10/8 의 모양) → 배음 {h * 100:.0f}%")
_, h, _ = g.tone_quality(np.zeros(100), 1568)
check(h != h, "20ms 미만 → 판정 없음(nan)")

print("[띠링] 소리 시작에서 일정대로 두 음을 자른다 — 일그러진 음도 빠뜨리지 않는다")
rec = np.concatenate([noise(500)] + [np.concatenate([chime(1175, 1568, h2_lo=1.5), noise(800, seed=i)])
                                     for i in range(3)])
ev = g.sound_events(rec)
check(len(ev) == 3, f"띠링 3번 = 소리 덩어리 3개(안의 40ms 쉼은 붙인다) · {len(ev)}")
res = [g.chime_notes(rec, s, 1175, 1568) for s, _ in ev]
check(all(a["harm"] > 1.0 and b["harm"] < g.CLEAN_HARM for a, b in res),
      f"낮은 음 일그러짐 · 높은 음 깨끗 · {[(round(a['harm'], 2), round(b['harm'], 3)) for a, b in res]}")

print("[닫힘음] 미끄러지며 내려가나 · 2배음")
n = int(R * 0.34)
x = np.arange(n) / n
f = 2093 * (1568 / 2093) ** x
ph = 2 * np.pi * np.cumsum(f) / R
glide = 8000 * (1 - x) * np.sin(ph)
gl = g.glide_report(np.concatenate([noise(300), glide, noise(300)]), 1568, 2093)
check(gl is not None and gl["end_hz"] < gl["start_hz"] * 0.9, f"내려감 · {gl and (round(gl['start_hz']), round(gl['end_hz']))}")
check(gl is not None and gl["harm"] < g.CLEAN_HARM, f"깨끗 · 2배음 {gl and round(gl['harm'] * 100, 2)}%")
check(g.glide_report(noise(1000), 1568, 2093) is None, "소리 없으면 None(옛 펌웨어는 C 를 모른다)")

print("[닫힘음 C 판] 짧고 힘 있게 — 0.2초 · 작아지지 않음(2026-10-09 사용자 「3번이 좋은 거 같아」)")
n = int(R * 0.20)
x = np.arange(n) / n
ph = 2 * np.pi * np.cumsum(2093 * (1568 / 2093) ** x) / R
fd = int(R * 0.005)
env = np.minimum(np.minimum(np.arange(n) / fd, 1.0), np.minimum((n - 1 - np.arange(n)) / fd, 1.0))
short_glide = 8000 * env * np.sin(ph)
rec = np.concatenate([noise(500)] + [np.concatenate([short_glide, noise(1000, seed=i)]) for i in range(3)])
ev = g.sound_events(rec, min_ms=g.CLOSE_MIN_MS)
check(len(ev) == 3, f"3번 다 센다(닫힘음 덩어리 기준 {g.CLOSE_MIN_MS}ms) · {len(ev)}")
gl = g.glide_report(rec[ev[0][0]:ev[0][1]], 1568, 2093) if ev else None
check(gl is not None and gl["end_hz"] < gl["start_hz"] * 0.9 and gl["harm"] < g.CLEAN_HARM, f"내려감·깨끗 · {gl and (round(gl['start_hz']), round(gl['end_hz']))}")

print("[sweep] 높이를 차례로 낸 녹음 — 일정으로 자리를 잡아 판정")
weak = g.sweep_pcm(g.SWEEP_HZ).astype(np.float64)
weak[: int(R * 0.2) + int(R * 0.2)] *= 0.001                 # 🔑 첫 음(800Hz)이 거의 안 나도 자리가 안 어긋난다
rows = g.analyze_sweep(np.concatenate([noise(300), weak + noise(len(weak) * 1000 / R, seed=7), noise(300)]))
check([r["verdict"] for r in rows][1:] == ["깨끗"] * (len(rows) - 1) and rows[0]["verdict"].startswith("약함"),
      f"첫 음 약함 · 나머지 제자리 · {[r.get('verdict') for r in rows]}")
pcm = g.sweep_pcm(g.SWEEP_HZ).astype(np.float64)
rows = g.analyze_sweep(np.concatenate([noise(300), pcm + noise(len(pcm) * 1000 / R, seed=5), noise(300)]))
check(all(r["found"] and r["verdict"] == "깨끗" for r in rows), f"깨끗한 합성 → 전부 「깨끗」 · {[r.get('verdict') for r in rows]}")
bad = pcm.copy()
i = g.SWEEP_HZ.index(1175)
s0 = int(R * 0.2) + i * int(R * 0.32)
t = np.arange(int(R * 0.2)) / R
bad[s0:s0 + len(t)] += 1.5 * 12000 * np.sin(2 * np.pi * 2350 * t)
rows = g.analyze_sweep(np.concatenate([noise(300), bad + noise(len(bad) * 1000 / R, seed=6), noise(300)]))
v = {r["hz"]: r["verdict"] for r in rows}
check(v[1175] == "일그러짐" and v[1568] == "깨끗", f"1175Hz 만 일그러짐 · {v[1175]} · 1568 {v[1568]}")

print("[score] 계측 줄 → 관문 수(판정을 다시 하지 않는다)")
M = [dict(t="1", 발화초=0.6, STT텍스트="가디언", 호출어=True, 증폭=4.0),
     dict(t="2", 발화초=0.6, STT텍스트="아", 호출어=False, 증폭=4.0),                        # 띠링 메아리(한 글자)
     dict(t="3", 발화초=1.3, STT텍스트="지금 몇 단계야", 호출어=False, 답변출처="LLM", 증폭=4.0),
     dict(t="4", 발화초=0.6, STT텍스트="가디야", 호출어=True, 증폭=4.0),
     dict(t="5", 발화초=1.0, STT텍스트="오늘 점심 뭐 먹지", 호출어=False, 답변출처="LLM", 증폭=4.0),   # 대본 밖
     dict(t="6", 발화초=0.6, STT텍스트="가디언", 호출어=True, 증폭=4.0),
     dict(t="7", 발화초=0.5, STT텍스트="아아", 호출어=False, 답변출처="LLM", 증폭=4.0),          # 🔴 두 글자 메아리 → 질문으로 감
     dict(t="8", 발화초=0.83, STT텍스트="가디언", 호출어=True, 증폭=4.0),
     dict(t="9", 발화초=0.83, STT텍스트="지금 상태 어때", 호출어=False, 답변출처="LLM", 증폭=4.0)]  # 짧지만 대본 질문
r = g.score_utterances(M, ["… 대화창 닫힘(질문 없음) → 닫힘음", "… 대화창 닫힘(답 끝) → 닫힘음"])
check(r["wakes"] == 4 and r["answered"] == 4, f"호출 4 · 답 4 · {r['wakes']} · {r['answered']}")
check(r["echo"] == 2, f"호출 뒤 「아」·「아아」 = 메아리 의심 2(두 글자도 잡는다 · 0.83초 진짜 질문은 아님) · {r['echo']}")
check(r["junk"] == ["오늘 점심 뭐 먹지", "아아"], f"대본 밖 질문 · {r['junk']}")
check(r["gains"] == [4.0], f"계측의 증폭 배율 · {r['gains']}")
check(r["close"] == {"질문 없음": 1, "답 끝": 1}, f"닫힘음 로그 · {r['close']}")
check(r["cers"][0][2] == 0.0, f"대본 그대로면 글자 오류 0 · {r['cers'][0]}")

print("[녹음 길이] 짧게 잘린 녹음은 판정하지 않는다(2026-10-09 실물 — 첫 녹음 앞 약 2초가 빠져 띠링 1/3)")
short, got, need = g.recording_short(int(16000 * 2.53), 3 * 1.2 + 0.8)
check(short and abs(got - 2.53) < 0.01, f"2.53초 녹음 · 기대 {need:g}초 → 짧다")
short, got, need = g.recording_short(int(16000 * 4.42), 3 * 1.2 + 0.8)
check(not short, f"4.42초 녹음 → 됐다 · 기대 {need:g}초")
check(g.recording_short(0, 1.0)[0], "0초 녹음(켠 직후 「녹음 0.0초」) → 짧다")

print()
if _fails:
    print(f"🔴 실패 {len(_fails)}건")
    sys.exit(1)
print("✅ 전부 통과")
