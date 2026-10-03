# 일회용 — LLM 답변 합성 흉내: 실제 voice_tts.Tts(스레드 2)로 28~41자 문장을 10초마다 합성(LLM 이 답할 때마다 일어나는 일)
import sys, time; sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
from voice_tts import Tts
t = Tts(); S = ["지금은 2단계 펌프 퍼지입니다. 렌치를 쥐고 진행하세요.",
               "다음 단계는 3단계 전극 냉각이고 B3 버튼을 누릅니다.",
               "현재 차단 중입니다. 순서를 확인한 뒤 차단 해제를 누르세요."]
i = 0
while True:
    a = time.monotonic(); t.synth(S[i % 3]); print(f"[tts] 합성 {time.monotonic()-a:.2f}초", flush=True); i += 1
    time.sleep(max(0, 10 - (time.monotonic() - a)))
