"""질문 세트 — 🔒 분할 규칙이 고정이고 상태·유형이 고루 들어간다(계획 Task 13 관문 ②).

실행: python3 Demo/selftest/test_question_set.py
"""
import os
import sys
import zlib

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "voice"))
sys.path.insert(0, _DEMO_DIR)

import question_set as qs  # noqa: E402
import voice_card  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


items = qs.build_items()
check(len(items) == 297 and len({i["id"] for i in items}) == 297, f"297문항 · id 중복 없음 · {len(items)}")
check(all(i["분할"] == ("dev" if zlib.crc32(i["id"].encode()) % 3 == 0 else "holdout") for i in items),
      "🔒 분할 = crc32 % 3 규칙 그대로")
dev = [i for i in items if i["분할"] == "dev"]
check(0.25 <= len(dev) / len(items) <= 0.42, f"dev 비율 {len(dev) / len(items):.2f}")
for part in ("dev", "holdout"):
    keys = {i["상태키"] for i in items if i["분할"] == part}
    kinds = {i["유형"] for i in items if i["분할"] == part}
    check(len(keys) == 9 and len(kinds) == 5, f"{part} 에 상태 9 · 유형 5 가 모두 있다({len(keys)}·{len(kinds)})")
for key, state, tools in qs.STATES:
    card = voice_card.build_card(state, *tools)
    check(card.startswith("[사실]"), f"{key} 카드가 만들어진다")

print()
if _fails:
    print(f"❌ 실패 {len(_fails)}건")
    sys.exit(1)
print("✅ 질문 세트 검증 통과")
