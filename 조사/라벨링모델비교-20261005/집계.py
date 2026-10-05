"""판정.json(Claude 육안 판정 · 사진 50장)으로 모델별 공구 라벨링 지표를 낸다.

판정 값(기록.py 머리말): 공구 id = 맞음 · "id~" = 그 공구지만 박스 크게 어긋남 · "id!이름" = 이름 틀림 · "F" = 가짜 · "A" = 애매(셈에서 뺌).
시드 1·2 박스는 짝.json 으로 R·T0 박스 판정을 이어받거나(같은 이름 · IoU 0.5 이상) S 판정을 쓴다.
한 공구에 맞음 박스가 둘 이상이면 하나만 잡음 · 나머지는 「중복」(사람이 지울 박스).
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
pred = json.load(open(HERE / "예측.json", encoding="utf-8"))["사진"]
pair = json.load(open(HERE / "짝.json", encoding="utf-8"))
judge = json.load(open(HERE / "판정.json", encoding="utf-8"))
by_no = {f"{v['번호']:03d}": n for n, v in pair.items()}


def boxes(no, model):
    """(판정, 점수, 이름) 목록."""
    n, j = by_no[no], judge[no]
    v = pred[n]
    if model in ("R", "T0"):
        tag, key = ("R", "R") if model == "R" else ("T", "T")
        return [(j[key].get(f"{tag}{i}", "?"), b[1], b[0]) for i, b in enumerate(v[model], 1)]
    out = []
    for ref, b in zip(pair[n][model], v[model]):
        if ref.startswith("S"):
            out.append((j.get("S", {}).get(ref, "?"), b[1], b[0]))
        else:
            src = "R" if ref.startswith("R") else "T"
            out.append((j[src].get(ref, "?"), b[1], b[0]))
    return out


def score(model, thr):
    c = Counter()
    kinds = Counter()
    for no, j in judge.items():
        objs = set(j["공구"])
        c["공구"] += len(objs)
        hit = Counter()
        for jv, s, name in boxes(no, model):
            if s < thr:
                continue
            if jv == "?":
                raise SystemExit(f"{no} {model} 판정 빠짐")
            if jv == "A":
                c["애매"] += 1
            elif jv in objs:
                hit[jv] += 1
            elif jv == "F":
                c["가짜"] += 1
            elif jv.endswith("~"):
                c["어긋남"] += 1
            elif "!" in jv:
                c["이름틀림"] += 1
        c["잡음"] += len(hit)
        c["중복"] += sum(v - 1 for v in hit.values())
        for o in objs - set(hit):
            c["놓침"] += 1
            kinds[j["공구"][o].split(" ·")[0]] += 1
    c["지울박스"] = c["가짜"] + c["어긋남"] + c["이름틀림"] + c["중복"]
    c["순이익"] = c["잡음"] - c["지울박스"]
    return c, kinds


def main():
    rows = []
    print(f"사진 {len(judge)}장 · 공구 {sum(len(j['공구']) for j in judge.values())}개 · "
          f"종류 {dict(Counter(v.split(' ·')[0] for j in judge.values() for v in j['공구'].values()))}")
    for thr in (0.25, 0.65):
        for m in ("R", "T0", "T1", "T2"):
            c, kinds = score(m, thr)
            rows.append({"문턱": thr, "모델": m, **c, "놓친종류": dict(kinds)})
            print(f"문턱 {thr} {m:3} 잡음 {c['잡음']}/{c['공구']} · 놓침 {c['놓침']} {dict(kinds)} · 지울 박스 {c['지울박스']}"
                  f"(가짜 {c['가짜']} · 어긋남 {c['어긋남']} · 이름 {c['이름틀림']} · 중복 {c['중복']}) · 순이익 {c['순이익']} · 애매 {c['애매']}")
    (HERE / "집계.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
