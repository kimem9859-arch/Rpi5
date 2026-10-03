# 일회용 — dev 원문(LLM 답)에 바뀐 finalize(안전 규칙)를 다시 걸어 차이를 본다(규칙 ⓑ 뒤 dev 재확인 · LLM 안 부름).
import json, os, sys, time
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo"); sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo/voice")
import question_set, voice_card
items = {i["id"]: i for i in question_set.build_items()}
changed = []
n = 0
for name in ("dev-t0.8", "dev-추가"):
    for l in open(os.path.join(D, name, "결과.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        if not r.get("원문"):
            continue
        it = items[r["id"]]
        st = dict(it["상태"], 쓴시각=time.time()) if it["상태"] else None
        facts = voice_card.card_facts(st, *it["공구"])
        said, src, bad = voice_card.finalize(r["원문"], facts)
        n += 1
        if (src, bad) != (r.get("경로"), r.get("안전규칙") or []):
            changed.append((name, r["회차"], r["id"], r["질문"], r.get("경로"), src, bad, r["원문"][:70], said))
print(f"다시 건 답 {n}개 · 판정이 바뀐 답 {len(changed)}개")
for c in changed:
    print(" ", c[0], f"{c[1]}회", c[2], f"「{c[3]}」", f"{c[4]} → {c[5]} {c[6]}", "|", c[7], "→", c[8])
