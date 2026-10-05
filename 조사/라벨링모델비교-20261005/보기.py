"""판정 보조 — 번호 범위의 예측(R·T0)과 시드 1·2 짝을 글로 보인다. 사용: python3 보기.py 1 5"""
import json, sys
d = json.load(open("예측.json", encoding="utf-8"))["사진"]; p = json.load(open("짝.json", encoding="utf-8"))
a, b = int(sys.argv[1]), int(sys.argv[2])
for n, v in sorted(d.items()):
    k = p[n]["번호"]
    if a <= k <= b:
        f = lambda bs, t: " ".join(f"{t}{i}:{x[0][:2]}{x[1]:.2f}[{int(x[2])},{int(x[3])},{int(x[4])},{int(x[5])}]" for i, x in enumerate(bs, 1)) or "-"
        print(f"#{k:03d} R {f(v['R'],'R')} | T {f(v['T0'],'T')}")
        print(f"      s1 {p[n]['T1']} {[round(x[1],2) for x in v['T1']]} · s2 {p[n]['T2']} {[round(x[1],2) for x in v['T2']]}")
