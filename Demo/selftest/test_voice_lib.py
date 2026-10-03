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

import random

import numpy as np

import voice_lib
from voice_lib import (answer_key, find_utterance, is_question, is_tool_question,
                       is_wake, read_tool_dets, rms)

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


print("[호출어] 🔑 접두 매칭 — 뒤 음절은 매번 다르게 들린다")
for t in ["가디언", "가디건", "가디얀", "가디현",
          "가디연", "가디안", "카디언", "가디야", "가디아", "가디원",
          "가디오", "가디",                       # 2026-09-07 실HW 에서 나온 것
          "가디언 지금 다음 순서 뭐야", "가디건이공구맞아"]:
    check(is_wake(t), f"「{t}」 를 호출어로 인정")
for t in ["안녕하세요", "가스 차단 됐어", "", "앞에 보이는 게 뭐야"]:
    check(not is_wake(t), f"「{t}」 는 호출어가 아니다")

print("[의도] 공구 질문")
for t in ["앞에 보이는 게 뭐야", "지금 뭐가 보여", "이 공구 뭐야",
          "가디언 앞에 보이는 게 뭐야", "앞에보이는게뭔가요",
          "아보이는게뭐야", "이게 뭐야",
          "앞에보이는게", "앞에모이는게뭐야", "아배보이는게뭐야"]:  # 2026-09-07 실HW
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

print("[적응형 임계] 🔴 고정 임계는 시끄러운 방에서 무너진다")
import random
from voice_lib import noise_floor

# 🔑 실측에 맞춘 신호 — 2026-09-01 폰 녹음 8개에서 말소리 RMS 5,068~6,465,
#    조용한 실내 무음 147~184 였다(§10.59). 진폭 8000 사인 = RMS 약 5,657.
speech = [int(8000 * math.sin(i / 5)) for i in range(rate * 4)]
room = [0] * rate + speech + [0] * (rate * 3)      # 8초 — max_ms(6초) 를 넘길 수 있게
random.seed(1)
check(noise_floor(room, rate) < 200, "조용한 방의 노이즈 플로어는 낮다")

for lvl, label in ((350, "약한 소음"), (700, "보통 소음")):
    noisy = [v + int(random.gauss(0, lvl)) for v in room]
    fl = noise_floor(noisy, rate)
    fixed = find_utterance(noisy, rate, start_th=600, end_th=300)   # 종전 고정 임계
    adapt = find_utterance(noisy, rate)                              # 적응형
    check(fl > lvl * 0.7, f"{label}: 바닥을 {fl:.0f} 로 잡는다")
    check(adapt is not None, f"{label}: 적응형은 발화를 찾는다")
    if lvl >= 700:
        # 소음이 종료 임계(300)를 계속 넘어 발화가 안 끝난다 → max_ms 로 잘린다
        check(fixed is not None and (fixed[1] - fixed[0]) >= rate * 5.9,
              f"{label}: 🔴 고정 임계는 발화가 안 끝나 max_ms 로 잘린다")
        check(adapt is not None and (adapt[1] - adapt[0]) < rate * 5.9,
              f"{label}: 적응형은 제때 끝난다")

print("[max_ms] 소음이 종료 임계를 계속 넘어도 STT 는 돌아야 한다")
cont = [int(3500 * math.sin(i / 7.0)) for i in range(rate * 20)]
seg_c = find_utterance(cont, rate, start_th=600, end_th=300)
check(seg_c is not None and abs((seg_c[1] - seg_c[0]) - rate * 6) < rate * 0.2,
      "🔴 끊김 없는 20초도 max_ms 6초에서 강제로 끊긴다")
check(find_utterance(cont, rate) is None,
      "🔑 적응형에서는 균일한 연속음을 「말이 아니다」로 무시한다")

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

# ---- V3 가드(전후 통과) — 호출어는 발화 어디에 있어도 잡는다(설명을 이 동작에 맞췄다)
check(is_wake("아 저기 가디언 지금 몇 단계야"), "V3 — 군말 뒤의 호출어도 잡는다")
check(not is_wake("지금 몇 단계야"), "V3 — 호출어가 없으면 아니다")

# ---- 설계 2026-10-03 §4.1 — VAD 효율화(Q7 · R2 ⑤)
print("[VAD] 배열을 넘겨도 리스트와 같은 구간을 낸다")
_rng = random.Random(7)


def _noisy(sec, amp=150):
    return [1400 + int(_rng.gauss(0, amp)) for _ in range(int(rate * sec))]


def _speech(sec, amp=4000):
    return [1400 + int(amp * math.sin(i / 5)) for i in range(int(rate * sec))]


_cases = [_noisy(1) + _speech(1) + _noisy(1),
          _noisy(0.5) + _speech(0.1) + _noisy(0.5) + _speech(0.8) + _noisy(1),
          _noisy(3),
          _noisy(0.3) + _speech(6.5)]
for _i, _c in enumerate(_cases):
    _a = find_utterance(_c, rate)
    _b = find_utterance(np.array(_c, dtype=np.int16), rate)
    check(_a == _b, f"사례 {_i}: 리스트 {_a} == 배열 {_b}")

print("[VAD] 프레임 RMS 는 한 번만 계산한다(같은 버퍼를 두 번 훑지 않는다)")
_calls = []
_orig = voice_lib._frame_rms
voice_lib._frame_rms = lambda s, fr: (_calls.append(1), _orig(s, fr))[1]
try:
    voice_lib.find_utterance(np.array(_cases[0], dtype=np.int16), rate)
finally:
    voice_lib._frame_rms = _orig
check(len(_calls) == 1, f"프레임 RMS 계산 {len(_calls)}회 — 1회여야 한다")

print("[VAD] 성능 — 6초 버퍼 1회 중앙값 ≤ 3ms(설계 §4.8)")
_buf6 = np.array(_noisy(6), dtype=np.int16)
_ts = []
for _ in range(21):
    _t0 = time.perf_counter()
    find_utterance(_buf6, rate)
    _ts.append(time.perf_counter() - _t0)
_med = sorted(_ts)[len(_ts) // 2] * 1000
check(_med <= 3.0, f"6초 버퍼 중앙값 {_med:.2f}ms")

print("[질문 판정] is_question — 깨어난 창 안의 2글자 이상 발화(Review Focus 1)")
check(not is_question("지금 몇 단계야", False), "깨어 있지 않으면 질문이 아니다")
check(not is_question("가디언", True), "호출어만 있으면 질문이 아니다(띠링으로 답한다)")
check(is_question("가디언 지금 몇 단계야", True), "호출어 + 말 = 질문")
check(not is_question("아", True), "🔑 1글자(띠링 반향 「아」)는 질문이 아니다")
check(is_question("몇 단계", True), "깨어 있으면 호출어 없이도 질문")

print()
if _fails:
    print(f"🔴 실패 {len(_fails)}건")
    sys.exit(1)
print("✅ 전부 통과")
