"""판정 기록 — 표준입력 JSON {번호: {...}} 을 판정.json 에 합친다.
한 사진 = {"공구": {id: "종류 · 어디"}, "R": {"R1": 판정}, "T": {"T1": 판정}, "S": {"S1-1": 판정}, "메모": ""}
판정 = 공구 id(맞음 · 박스가 그 공구에 IoU 0.5 이상으로 보임) · "id~"(그 공구지만 박스가 크게 어긋남) · "id!종류"(그 공구인데 이름 틀림) · "F"(가짜) · "A"(애매 — 셈에서 뺌)
"""
import json, sys
from pathlib import Path
p = Path("판정.json")
d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
d.update(json.load(sys.stdin))
p.write_text(json.dumps(dict(sorted(d.items())), ensure_ascii=False, indent=1), encoding="utf-8")
print("판정", len(d), "장")
