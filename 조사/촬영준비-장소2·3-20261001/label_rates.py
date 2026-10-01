"""b001~b004 사람 검토 결과에서 원본 세션 무리별 제외율·클래스 비율(일회용 분석)."""
import collections, json
from pathlib import Path
LB = Path.home() / "data/label_batches"
G = {"s1": "s1 정지", "s2": "s2 이동", "s6": "s6 SOP작업", "tool-free": "공구 자유"}
BTN = ["B1", "B2", "B3", "B4", "EMO"]; TOOL = ["driver", "wrench", "pliers"]
st = collections.defaultdict(collections.Counter)
for b in ["b001", "b002", "b003", "b004"]:
    m = json.load(open(LB / b / "manifest.json"))
    for it in m["images"]:
        sess = it["session"]; g = next(v for k, v in G.items() if f"-{k}" in sess or f"_{k}" in sess)
        j = LB / b / "returned" / (Path(it["file"]).stem + ".json")
        labs = {s["label"] for s in json.load(open(j))["shapes"]}
        c = st[g]; c["n"] += 1
        if "exclude" in labs: c["exclude"] += 1; continue
        if not labs: c["empty"] += 1
        if labs & set(BTN): c["any_button"] += 1
        if labs & set(TOOL): c["any_tool"] += 1
        for k in BTN + TOOL: c[k] += k in labs
        for k in labs - set(BTN) - set(TOOL): c["기타:" + k] += 1
tot = collections.Counter()
for g, c in st.items():
    tot.update(c)
    n = c["n"]; print(g, dict(c)); print("   비율", {k: round(v / n, 3) for k, v in c.items() if k != "n"})
print("전체", dict(tot)); print("   비율", {k: round(v / tot["n"], 3) for k, v in tot.items() if k != "n"})
