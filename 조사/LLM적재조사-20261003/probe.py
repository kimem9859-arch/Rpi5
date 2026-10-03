# 일회용 — 데운 상태에서도 매 요청 적재 시간이 나오는 원인 조사(설계 2026-10-03 §4.2 · R3 I2). 실제 함수만 쓴다.
import json
import os
import sys
import urllib.request

sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo/voice")
import config  # noqa: E402
import llm_gate  # noqa: E402
import voice_card  # noqa: E402
import voice_llm  # noqa: E402

BASE = config.LLM_URL.rsplit("/api/", 1)[0]


def ps():
    return json.load(urllib.request.urlopen(BASE + "/api/ps", timeout=5))


rows = [{"구분": "ps 시작", "ps": ps()}]
ok, m = voice_llm.warm()
rows.append({"구분": "예열", "성공": ok, **m, "ps": ps()})
card = voice_card.build_card(llm_gate.STATE, llm_gate.DETS, True)
card3 = voice_card.build_card(dict(llm_gate.STATE, 현재단계=3, 현재단계명="전극 냉각", 현재버튼="B3",
                                   다음단계=4, 다음단계명="챔버 벤트", 다음버튼="B4"), [], False)
plan = ([("같은질문", card, "지금 몇 단계야?")] * 3
        + [("다른질문", card, q) for q in ("이번 단계에 무슨 공구 필요해?", "다음 순서 뭐야?", "앞에 보이는 게 뭐야?")]
        + [("다른카드", card3, "지금 몇 단계야?")] * 2)
for label, c, q in plan:
    t, m = voice_llm.ask(c, q)
    rows.append({"구분": label, "질문": q, "답": t, **m})
    print(rows[-1], flush=True)
rows.append({"구분": "ps 끝", "ps": ps()})
json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.json"), "w"),
          ensure_ascii=False, indent=1)
