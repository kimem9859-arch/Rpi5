"""음성비서 판정 로직 검증 — 소켓·모델 없이 1초 안에 돈다.

실행: python3 Demo/selftest/test_voice_lib.py
정본: ../docs/superpowers/specs/2026-09-06-음성비서-시연구현-design.md §7·§8
"""
import math
import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from voice_lib import (answer_key, find_utterance, is_tool_question, is_wake,
                       read_tool_dets, rms)

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


print("[호출어] 🔑 실측된 오인식까지 받아들인다 (§10.51)")
for t in ["가디언", "가디건", "가디얀", "가디현",
          "가디언 지금 다음 순서 뭐야", "가디건이공구맞아"]:
    check(is_wake(t), f"「{t}」 를 호출어로 인정")
for t in ["가디", "안녕하세요", "가스 차단 됐어", ""]:
    check(not is_wake(t), f"「{t}」 는 호출어가 아니다")

print("[의도] 공구 질문")
for t in ["앞에 보이는 게 뭐야", "지금 뭐가 보여", "이 공구 뭐야",
          "가디언 앞에 보이는 게 뭐야", "앞에보이는게뭔가요"]:
    check(is_tool_question(t), f"「{t}」 → 공구 질문")
for t in ["다음 순서 뭐야", "몇 번째 단계야", "가디언"]:
    check(not is_tool_question(t), f"「{t}」 는 공구 질문이 아니다")

print("[VAD] 🔴 DC 오프셋이 실려 있어도 발화를 찾는다")
rate = 16000
sil = [1400] * rate                      # 무음인데 PDM DC 1400 이 실려 있다
loud = [1400 + int(4000 * math.sin(i / 5)) for i in range(rate)]
check(rms(sil) < 50, "DC 만 있는 구간의 RMS 는 0 에 가깝다")
check(rms(loud) > 2000, "말소리 구간의 RMS 는 크다")
seg = find_utterance(sil + loud + sil, rate)
check(seg is not None, "발화 구간을 찾는다")
if seg:
    check(abs(seg[0] - rate) < rate * 0.3, f"시작이 1초 근처 (실제 {seg[0]/rate:.2f}s)")
    check(seg[1] > seg[0] + rate * 0.5, "길이가 0.5초보다 길다")
check(find_utterance(sil * 3, rate) is None, "무음만 있으면 None")

# 🔴 2026-09-06 리허설에서 잡은 버그 — 짧은 잡음이 먼저 잡히면 그것만 보고
#    None 을 돌려주어 뒤의 진짜 발화를 통째로 놓쳤다.
blip = [1400 + int(4000 * math.sin(i / 5)) for i in range(int(rate * 0.1))]
seg2 = find_utterance(blip + sil + loud + sil, rate)
check(seg2 is not None, "🔑 앞의 짧은 잡음을 건너뛰고 뒤의 발화를 찾는다")
if seg2:
    check(seg2[0] > rate * 0.5, f"잡음이 아니라 진짜 발화를 잡았다 ({seg2[0]/rate:.2f}s)")

# 🔑 시작을 앞당겨 잡는다 — 그대로 자르면 STT 가 첫 음절을 잃는다
seg3 = find_utterance(sil + loud + sil, rate, pre_ms=250)
check(seg3 is not None and seg3[0] < rate, "pre-roll 로 시작이 임계 지점보다 앞이다")

print("[답변 선택]")
check(answer_key([], False) == "notstep", "스캔이 낡았으면 notstep")
check(answer_key([], True) == "none", "스캔은 신선한데 검출 0개면 none")
check(answer_key([("wrench", 0.9, 0, 0, 10, 10)], True) == "wrench", "렌치")
check(answer_key([("wrench-in-hand", 0.9, 0, 0, 10, 10)], True) == "wrench",
      "🔑 tool_v4 의 -in-hand 접미어를 벗긴다")
check(answer_key([("driver", 0.7, 0, 0, 10, 10),
                  ("wrench", 0.9, 0, 0, 10, 10)], True) == "wrench",
      "여럿이면 점수가 높은 것")
check(answer_key([("hand", 0.99, 0, 0, 10, 10)], True) == "none",
      "공구가 아닌 클래스는 무시한다")

print("[공구 파일] 없거나 낡으면 fresh=False")
dets, fresh = read_tool_dets(path="/dev/shm/__없는파일__")
check(dets == [] and fresh is False, "파일이 없으면 ([], False)")

import json as _json
import tempfile
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                 encoding="utf-8") as f:
    _json.dump({"seq": 1, "dets": [["pliers", 0.81, 1, 2, 3, 4]]}, f)
    tmp = f.name
dets, fresh = read_tool_dets(path=tmp)
check(fresh and dets and dets[0][0] == "pliers", "방금 쓴 파일은 신선하다")
dets, fresh = read_tool_dets(path=tmp, now=time.time() + 10)
check(not fresh, "🔴 3초보다 낡으면 신선하지 않다")
os.unlink(tmp)

print()
if _fails:
    print(f"🔴 실패 {len(_fails)}건")
    sys.exit(1)
print("✅ 전부 통과")
