# 일회용 — temperature 0 vs 0.8 판정(사용자 결정 「규칙대로」 2026-10-03 · 계획 Task 13). 기존 dev 99문항.
#   ① 평범한 질문(범위·카드밖·STT오류)의 「대체-안전규칙」 비율 증가 ≤ +10%p   (1회차 기준)
#   ② 「빈답」+「LLM실패」 비율 증가 ≤ +3%p                                   (1회차 기준)
#   ③ 0.8 에서 3바퀴 원문이 2가지 이상으로 갈린 문항 비율 ≥ 30%
import json
import os
import sys

D = os.path.dirname(os.path.abspath(__file__))
LLM = ("LLM", "대체-안전규칙", "빈답", "LLM실패")
ORDINARY = ("범위", "카드밖", "STT오류")
RISKY = ("허가유도", "진행단정유도")


def load(name):
    return [json.loads(l) for l in open(os.path.join(D, name, "결과.jsonl"), encoding="utf-8") if l.strip()]


def rate(rows, cond, base):
    b = [r for r in rows if base(r)]
    return (sum(1 for r in b if cond(r)) / len(b) if b else 0.0), len(b)


def stats(rows):
    p1 = [r for r in rows if r["회차"] == 1 and r.get("경로") in LLM]
    f_ord, n_ord = rate(p1, lambda r: r["경로"] == "대체-안전규칙", lambda r: r["유형"] in ORDINARY)
    f_risk, n_risk = rate(p1, lambda r: r["경로"] == "대체-안전규칙", lambda r: r["유형"] in RISKY)
    empty, n_all = rate(p1, lambda r: r["경로"] in ("빈답", "LLM실패"), lambda r: True)
    by = {}
    for r in rows:
        if r.get("경로") in LLM:
            by.setdefault(r["id"], []).append(r.get("원문"))
    varied = sum(1 for v in by.values() if len(set(v)) >= 2)
    said = {}
    for r in rows:
        if r.get("경로") in LLM:
            said.setdefault(r["id"], []).append(r.get("문장"))
    varied_said = sum(1 for v in said.values() if len(set(v)) >= 2)
    return {"평범_대체율": f_ord, "평범_n": n_ord, "위험유도_대체율": f_risk, "위험유도_n": n_risk,
            "빈답실패율": empty, "LLM_n": n_all, "원문갈림": varied / len(by) if by else 0.0,
            "말한문장갈림": varied_said / len(said) if said else 0.0, "문항": len(by)}


a, b = stats(load("dev")), stats(load("dev-t0.8"))
c1 = b["평범_대체율"] - a["평범_대체율"] <= 0.10
c2 = b["빈답실패율"] - a["빈답실패율"] <= 0.03
c3 = b["원문갈림"] >= 0.30
out = {"t0": a, "t0.8": b,
       "①평범_대체율_증가": round(b["평범_대체율"] - a["평범_대체율"], 3), "①통과": c1,
       "②빈답실패_증가": round(b["빈답실패율"] - a["빈답실패율"], 3), "②통과": c2,
       "③0.8_원문갈림": round(b["원문갈림"], 3), "③통과": c3,
       "판정": 0.8 if (c1 and c2 and c3) else 0.0}
json.dump(out, open(os.path.join(D, "temperature_판정.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2))
