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
v1 = [i for i in items if i["판"] == 1]
v2 = [i for i in items if i["판"] == 2]


def norm(q):
    return "".join(c for c in q if not c.isspace() and c not in ",.?!·")


check(len(qs.QUESTIONS) == 60 and len({q for _, q in qs.QUESTIONS}) == 60, "판 1 질문 60개 · 중복 없음")
check(len(qs.QUESTIONS2) == 31 and len({norm(q) for _, q in qs.QUESTIONS2}) == 31, "판 2 질문 31개 · 띄어쓰기를 빼도 중복 없음")
check(not ({norm(q) for _, q in qs.QUESTIONS} & {norm(q) for _, q in qs.QUESTIONS2}),
      "🔒 판 2 질문은 판 1 과 겹치지 않는다(띄어쓰기·문장부호 무시)")
check(len(qs.STATES) == 9 and len(qs.STATES2_EXTRA) == 7, "상태 = 옛 9 + 새 7")
check(len(v1) == 60 * 16 and len(v2) == 31 * 16, f"판 1 {len(v1)} · 판 2 {len(v2)}")
check(len({i["id"] for i in items}) == len(items), "id 중복 없음")
check([i["id"] for i in v1][:2] == ["S1-작업전-q01", "S1-작업전-q02"], "🔒 판 1 의 id 는 그대로")
old = [i for i in v1 if i["상태키"] in {k for k, _, _ in qs.STATES}]
check(all(i["옛분할"] == ("dev" if zlib.crc32(i["id"].encode()) % 3 == 0 else "holdout") for i in old),
      "🔒 옛 분할 = crc32 % 3 규칙 그대로(기록용)")
check(all(i["분할"] == ("dev" if i["옛분할"] == "holdout" else "쉼") for i in old),
      "🔒 옛 holdout(이미 봄) → dev · 옛 dev → 쉼")
new1 = [i for i in v1 if i not in old]
check(all(i["분할"] == ("dev" if zlib.crc32(i["id"].encode()) % 3 == 0 else "쉼") for i in new1),
      "판 1 × 새 상태 = crc32 몫만 dev")
check(all(i["분할"] == "holdout" and i["id"].startswith("H2-") for i in v2), "🔒 판 2 는 전부 holdout · id 앞 H2-")
check({i["유형"] for i in v2} == {"할일", "공구", "범위", "진행단정유도", "허가유도", "카드밖", "STT오류"},
      f"판 2 유형 7종 — {sorted({i['유형'] for i in v2})}")
check(len({i["상태키"] for i in v2}) == 16, "판 2 는 상태 16 전부")
for key, state, tools in qs.STATES + qs.STATES2_EXTRA:
    card = voice_card.build_card(state, *tools)
    check(card.startswith("[사실]"), f"{key} 카드가 만들어진다")

print()
if _fails:
    print(f"❌ 실패 {len(_fails)}건")
    sys.exit(1)
print("✅ 질문 세트 검증 통과")
