"""사실 카드 검증 — 🔴 「부재를 명시하는가」가 핵심이다.

실행: python3 Demo/selftest/test_voice_card.py

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §5

🔑 비면 LLM 이 지어낸다(§10.53-(4) 유형 ①②⑤ = 「모른다」고 말하지 못하는 문제).
   그래서 없는 것은 빼지 않고 **없다고 적는지**를 본다.
"""
import json
import os
import shutil
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from voice_card import build_card, card_facts, read_state, verify_answer

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


LIVE = {
    "세션": True, "공정명": "PECVD 정비(PM) 시퀀스", "전체단계": 4,
    "현재단계": 2, "현재단계명": "펌프/퍼지", "현재버튼": "B2",
    "다음단계": 3, "다음단계명": "전극 냉각", "다음버튼": "B3",
    "상태": "PROCESS RUN",
    "서브작업": {"label": "N2 퍼지", "sec": 10, "tool": "wrench", "tool_name": "렌치"},
    "결과": None, "pid": os.getpid(), "쓴시각": time.time(),
}


def main():
    tmp = tempfile.mkdtemp(prefix="sop_card_test_")
    path = os.path.join(tmp, "state.json")
    try:
        print("── read_state")
        check(read_state(path) is None, "파일이 없으면 None")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(LIVE, f, ensure_ascii=False)
        check(read_state(path)["현재단계"] == 2, "정상 파일을 읽는다")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{망가진")
        check(read_state(path) is None, "깨진 json 이면 None")
        ghost = dict(LIVE, pid=999999)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ghost, f, ensure_ascii=False)
        check(read_state(path) is None, "🔑 죽은 pid 의 유령 상태는 None")
        init = dict(LIVE, pid=1)          # 🔑 pid 1 = 살아 있지만 신호 권한이 없다
        with open(path, "w", encoding="utf-8") as f:
            json.dump(init, f, ensure_ascii=False)
        check(read_state(path) is not None,
              "🔴 PermissionError 는 유령이 아니다 — 프로세스가 있다는 뜻이다")

        print("── build_card · 정상")
        card = build_card(LIVE, [("wrench", 0.44, 0, 0, 9, 9)], True)
        check("현재 진행 중인 단계: 2단계" in card, "🔴 라벨을 축약하지 않는다(현재 진행 중인 단계)")
        check("그 다음에 올 단계: 3단계" in card, "🔴 다음 라벨도 풀어 쓴다")
        check("2단계에 필요한 공구 = 렌치" in card, "필요 공구(정적)가 단계 번호와 함께 나온다")
        check("카메라에 지금 보이는 공구: 렌치" in card, "보이는 공구(실시간)가 따로 나온다")
        check(card.count("렌치") >= 2, "🔑 필요 공구와 보이는 공구는 다른 줄이다")

        print("── build_card · 🔴 부재 표기")
        c2 = build_card(LIVE, [], False)
        check("확인 중이 아님" in c2, "공구가 낡았으면 「확인 중이 아님」이라고 적는다")
        c3 = build_card(None, [], False)
        check("시작되지 않음" in c3, "상태가 없으면 「시작되지 않음」이라고 적는다")
        check("확인 중이 아님" in c3, "그 경우에도 공구 줄이 사라지지 않는다")
        nosub = dict(LIVE, 서브작업=None)
        c4 = build_card(nosub, [], False)
        check("서브작업: 없음" in c4, "서브작업 없는 단계도 「없음」이라고 적는다")

        print("── build_card · 완주 결과")
        done = dict(LIVE, 결과={"total_sec": 92.4, "ok": True,
                                "steps": [1, 2, 3, 4], "violations": [], "interlocks": []})
        c5 = build_card(done, [], False)
        check("작업 결과" in c5 and "위반 0회" in c5, "완주하면 결과가 카드에 실린다")
        check("이미 완료됨" in c5 and "진행 중" not in c5,
              "🔴 완주 뒤에는 「진행 중」이라고 쓰지 않는다 — 결과와 모순된다")

        print("── card_facts (검산이 쓸 재료)")
        f1 = card_facts(LIVE, [("wrench", 0.44, 0, 0, 9, 9)], True)
        check(f1 == {"공구": "wrench", "단계": 2, "버튼": "B2",
                     "상태": "정상", "세션": True}, "정상 상태의 사실 묶음")
        f2 = card_facts(None, [], False)
        check(f2["세션"] is False and f2["공구"] is None, "상태가 없으면 전부 비어 있다")
        check(card_facts(dict(LIVE, 상태="MONITOR"), [], False)["상태"] == "정상",
              "🔴 MONITOR 는 카드와 같게 「정상」으로 접힌다 — 손이 ROI 에 들어간 것뿐이다")
        check(card_facts(dict(LIVE, 상태="BLOCK"), [], False)["상태"] == "차단",
              "BLOCK 은 「차단」")

        print("── verify_answer · 🔑 문장에 나온 사실만 본다")
        # 🔑 `base`/`now` 는 card_facts 가 낸 모양이다 — 상태는 **버킷**(정상/경고/차단)
        base = {"공구": "wrench", "단계": 2, "버튼": "B2",
                "상태": "정상", "세션": True}
        ok, bad = verify_answer("2단계에 필요한 공구는 렌치입니다.", base, base)
        check(ok and bad == [], "안 바뀌었으면 통과")

        moved = dict(base, 공구="driver")
        ok, bad = verify_answer("현재 보이는 공구는 렌치입니다.", base, moved)
        check(not ok and bad == ["공구"], "🔴 공구를 말했는데 공구가 바뀌면 불일치")

        ok, bad = verify_answer("버튼 B2를 누르시면 됩니다.", base, moved)
        check(ok, "🔑 공구를 말하지 않았으면 공구가 바뀌어도 통과 — 과잉 폴백을 막는다")

        stepped = dict(base, 단계=3, 버튼="B3")
        ok, bad = verify_answer("버튼 B2를 누르시면 됩니다.", base, stepped)
        check(not ok and "버튼" in bad, "버튼을 말했는데 버튼이 바뀌면 불일치")
        ok, bad = verify_answer("2단계 「펌프/퍼지」입니다.", base, stepped)
        check(not ok and "단계" in bad, "단계를 말했는데 단계가 바뀌면 불일치")

        blocked = dict(base, 상태="차단")
        ok, bad = verify_answer("지금 차단된 상태입니다.", base, blocked)
        check(not ok and "상태" in bad, "차단을 말했는데 상태가 바뀌면 불일치")
        ok, bad = verify_answer("렌치가 보입니다.", base, blocked)
        check(ok, "차단을 말하지 않았으면 상태 변화만으로는 안 버린다")

        moved_roi = dict(base, 상태="정상")     # PROCESS RUN → MONITOR 는 같은 버킷
        ok, bad = verify_answer("정상이며 경고나 차단은 없습니다.", dict(base, 상태="정상"), moved_roi)
        check(ok, "🔴 카드가 말하지 않은 상태 차이로는 답을 버리지 않는다")

        ended = dict(base, 세션=False)
        ok, bad = verify_answer("렌치가 보입니다.", base, ended)
        check(not ok and "세션" in bad,
              "🔴 세션은 문장 언급과 무관하게 본다 — 작업이 끝났으면 무슨 답이든 어긋난다")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
