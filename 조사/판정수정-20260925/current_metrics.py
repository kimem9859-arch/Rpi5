"""§12.31 정의로 판정기 지표를 잰다 — after_current_metrics.txt 와 preview_variants.txt 덧붙임
(P2만·P3만)을 다시 만든다.

실행: cd Rpi5/Demo && python3 ../조사/판정수정-20260925/current_metrics.py
조건 = fsm_sim 시뮬레이션 정책 4종 · hoi.db 22세션(2026-07 모조 콘솔 VGA · 매 프레임 PNG 저장 중 9.1fps 촬영).
2026-09-25 판정 수정 ① 때 한 번 돌리고 저장하지 않은 명령을 그대로 옮겼다(① 최종 리뷰 9 —
재현 명령이 저장소에 없었다 · 원문 = 세션 56d1f2c1 기록).
🔴 「수정 후」 줄은 **지금 코드**의 fsm.py 를 잰다 — ① 뒤 판정기가 바뀌면 값이 달라진다.
   「수정 전」·「P2만」·「P3만」은 preview_variants.py 의 재구현(make_cls)이다.
"""
import sys

sys.path[:0] = ['test', '.']
import fsm_sim
import hoi_metrics

PV = "../조사/판정수정-20260925/preview_variants.py"
con = hoi_metrics.connect()


def summary(label):
    rows = fsm_sim.run_all(con)
    norm = [r for r in rows if r['violations'] == 0]
    fa = sum(r['false_alarms'] for r in norm)
    mins = sum(r['duration_sec'] for r in norm) / 60
    tb = sum(r['blocked'] for r in rows)
    tv = sum(r['violations'] for r in rows)
    ex = fsm_sim.run_all(con, exclude_cliff=True)
    eb = sum(r['blocked'] for r in ex)
    ev = sum(r['violations'] for r in ex)
    print(f"{label}: E2E 오경보(정상 세션 {len(norm)}개) {fa}건/{mins:.1f}분 = {fa/mins:.2f}회/분"
          f" · 사전 차단 {tb}/{tv} = {tb/tv*100:.1f}% · 절벽 제외 {eb}/{ev} = {eb/ev*100:.1f}%")


summary("수정 후(실제 코드)")
# preview_variants.py 의 규칙 재구현(make_cls)만 빌린다 — 실행 루프 앞까지
src = open(PV, encoding="utf-8").read().split("\nfor name, flags")[0]
ns = {}
exec(compile(src, "preview_variants", "exec"), ns)
fsm_sim.SafetyFSM = ns["make_cls"](0, 0, 0, 0)
summary("수정 전(재구성)")
for name, flags in [("P2만", (0, 0, 1, 0)), ("P3만", (0, 0, 0, 1))]:
    fsm_sim.SafetyFSM = ns["make_cls"](*flags)
    rows = fsm_sim.run_all(con)
    fa = sum(r['false_alarms'] for r in rows)
    tb = sum(r['blocked'] for r in rows)
    tv = sum(r['violations'] for r in rows)
    print(f"{name:<10} 오경보 {fa:>4}건 · 사전 차단 {tb}/{tv}")     # preview_variants.txt 덧붙임과 같은 모양
