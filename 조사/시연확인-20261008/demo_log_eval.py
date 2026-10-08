#!/usr/bin/env python3
"""시연 GUI 로그 → 임시 평가(읽기 전용 · 측정 세션 아님).

사용: python3 demo_log_eval.py <Demo/logs/…_log.txt> [voice_….log]
"""
import re
import statistics as st
import sys

T = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d{3})\] (.*)")


def ts(m):
    h, mi, s, ms = (int(x) for x in m.groups()[:4])
    return h * 3600 + mi * 60 + s + ms / 1000


def hm(t):
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


rows = []
for line in open(sys.argv[1], encoding="utf-8"):
    m = T.match(line.rstrip("\n"))
    if m:
        rows.append((ts(m), m.group(5)))

# ── 작업 회차 ──
sess, cur = [], None
for t, msg in rows:
    if "[FSM] 작업 시작" in msg:
        cur = {"start": t, "events": []}
        sess.append(cur)
    if cur is not None:
        cur["events"].append((t, msg))

print(f"로그 {hm(rows[0][0])} ~ {hm(rows[-1][0])} · 작업 회차 {len(sess)}")
press_lead, unconf, grip_lat = [], [], []
for i, s in enumerate(sess, 1):
    ev = s["events"]
    res = next((m for t, m in ev if "[결과]" in m), None)
    steps = [m.split("→ ")[1].split(":")[0] for t, m in ev if "단계 진행" in m]
    warns = [t for t, m in ev if "→ WARNING" in m]
    blocks = [t for t, m in ev if "→ BLOCK" in m]
    presses = [m.split("] ")[1] for t, m in ev if m.startswith("[버튼]")]
    # 2단계 시작 → 렌치 쥠
    t2 = next((t for t, m in ev if "단계 진행 → 2단계" in m), None)
    tg = next((t for t, m in ev if "찾기 → 쥠" in m), None)
    if t2 and tg:
        grip_lat.append(tg - t2)
    for t, m in ev:
        mm = re.search(r"카메라 확인\(누르기 ([\d.]+)초 전 관측\)", m)
        if mm:
            press_lead.append(float(mm.group(1)))
        if "카메라 미확인" in m:
            unconf.append((i, hm(t), m))
    print(f"  {i}회차 {hm(s['start'])} · 누름 {len(presses)}({' '.join(p.split()[0] for p in presses)})"
          f" · 경고 {len(warns)} · 차단 {len(blocks)} · 렌치 쥠까지 {('%.1f초' % (tg - t2)) if t2 and tg else '—'}"
          f" · {res.split('] ')[1] if res else '끝나지 않음'}")

print(f"누름 카메라 확인 {len(press_lead)} · 미확인 {len(unconf)}")
if press_lead:
    print(f"  관측 시점(누르기 몇 초 전) 중앙값 {st.median(press_lead):.1f} · 범위 {min(press_lead):.1f}~{max(press_lead):.1f}")
for u in unconf:
    print(f"  미확인: {u[0]}회차 {u[1]} — {u[2]}")
if grip_lat:
    print(f"2단계 시작 → 렌치 쥠 인식: {len(grip_lat)}회 · " + " · ".join(f"{x:.1f}초" for x in grip_lat))

# ── 경고 → 인터락 응답 ──
for t, m in rows:
    if "→ WARNING" in m or "→ BLOCK" in m:
        ack = next(((t2, m2) for t2, m2 in rows if t2 >= t and "[인터락] →" in m2), None)
        rel = next((t2 for t2, m2 in rows if t2 > t and ("WARNING → " in m2 or "BLOCK → " in m2)), None)
        print(f"{hm(t)} {m.split('] ')[1]} · 인터락 응답 {((ack[0] - t) * 1000):.0f}ms ({ack[1].split('] ')[1]})"
              f" · 풀림까지 {(rel - t):.1f}초" if ack and rel else f"{hm(t)} {m}")

# ── 처리 속도 ──
fps = [float(m.split()[1]) for t, m in rows if m.startswith("[FPS]")]
if fps:
    q = sorted(fps)
    print(f"FPS 기록 {len(fps)}개(약 10초 간격 · 애니메이션 on · PNG 저장 없음) · 중앙값 {st.median(fps):.1f}"
          f" · 최저 {q[0]:.1f} · 최고 {q[-1]:.1f} · 15 미만 {sum(f < 15 for f in fps)}개")

# ── 카메라 연결 ──
cam = [m for t, m in rows if m.startswith("[카메라]")]
print("카메라: " + " | ".join(cam))

# ── 음성비서 ──
if len(sys.argv) > 2:
    heard, alerts = [], []
    for line in open(sys.argv[2], encoding="utf-8"):
        if "들림:" in line:
            heard.append(line.split("들림:")[1].strip())
        if "🔔 알림" in line:
            alerts.append(line.split("] ", 1)[1].strip())
    print(f"음성: 받아쓴 발화 {len(heard)}개 {heard} · 호출어 인식 {sum('가디' in h for h in heard)}")
    for a in alerts:
        print("  " + a)
