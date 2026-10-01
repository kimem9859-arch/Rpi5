"""장소1 추정 + 장소2·3 계획의 클래스별 예상 장수(일회용 · 2026-10-01).
입력 = 사람검토비율(label_rates.py 와 같은 집계) · 묶음 b001~b014 원본 무리 구성 · 1분 160장(보수)."""
import collections, json
from pathlib import Path
LB = Path.home() / "data/label_batches"
G = {"s1": "s1 정지", "s2": "s2 이동", "s6": "s6 SOP작업", "tool-free": "공구 자유"}
CL = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]
rate = collections.defaultdict(collections.Counter)
for b in ["b001", "b002", "b003", "b004"]:
    m = json.load(open(LB / b / "manifest.json"))
    for it in m["images"]:
        g = next(v for k, v in G.items() if f"-{k}" in it["session"] or f"_{k}" in it["session"])
        labs = {s["label"] for s in json.load(open(LB / b / "returned" / (Path(it["file"]).stem + ".json")))["shapes"]}
        rate[g]["n"] += 1
        if "exclude" not in labs:
            for c in CL: rate[g][c] += c in labs
R = {g: {c: rate[g][c] / rate[g]["n"] for c in CL} for g in rate}
mix = collections.Counter()
for i in range(1, 15):
    for it in json.load(open(LB / f"b{i:03d}/manifest.json"))["images"]:
        mix[next(v for k, v in G.items() if f"-{k}" in it["session"] or f"_{k}" in it["session"])] += 1
print("장소1 묶음 구성", dict(mix), "합", sum(mix.values()))
p1 = {c: sum(mix[g] * R[g][c] for g in mix) for c in CL}
PER_MIN = 160
def plan(minutes):   # 장면 무리별 분 → 클래스별 장수(장소1 무리 비율을 대응시킨다)
    return {c: PER_MIN * (minutes["console"] * R["s2 이동"][c] + minutes["button"] * R["s6 SOP작업"][c]
                          + minutes["tool"] * R["공구 자유"][c]) for c in CL}
P2a = plan({"console": 5, "button": 7, "tool": 8})      # 처음 안 22분
P2 = plan({"console": 5, "button": 7, "tool": 15})      # 승인 29분
P3 = plan({"console": 2, "button": 3, "tool": 7})       # 장소3 13분
print(f"{'클래스':<8}{'장소1':>8}{'장소2(22분)':>12}{'합':>8}{'장소2(29분)':>12}{'합':>8}{'여유':>8}{'장소3':>8}")
for c in CL:
    t = p1[c] + P2[c]
    print(f"{c:<8}{p1[c]:>8.0f}{P2a[c]:>12.0f}{p1[c]+P2a[c]:>8.0f}{P2[c]:>12.0f}{t:>8.0f}{(t/1500-1)*100:>7.0f}%{P3[c]:>8.0f}")
