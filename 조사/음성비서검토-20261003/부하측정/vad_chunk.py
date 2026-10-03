# 일회용 — 가설 시험: 음성비서 루프의 「조각마다 버퍼 전체 VAD」 CPU 시간을 조각 크기별로 잰다(STT 제외 · 코드 무변경 · 같은 함수 import)
import array, sys, time, wave
sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
import voice_assistant as va            # WINDOW_SEC·LAG_LIMIT·QUIET_TAIL 을 그대로 읽는다
from voice_lib import find_utterance
RATE = 16000
w = wave.open("/home/pi/lab/voice-capture/음성비서_촬영본/20260907_194844/오디오/마이크_전체.wav"); a = array.array("h"); a.frombytes(w.readframes(w.getnframes()))
dur = len(a) / RATE
for chunk in (512, 8192):
    buf = array.array("h"); calls = 0; t0 = time.process_time()
    for i in range(0, len(a), chunk):
        buf.extend(a[i:i + chunk])
        limit = int(RATE * (va.WINDOW_SEC + va.LAG_LIMIT))
        if len(buf) > limit: del buf[:len(buf) - int(RATE * va.WINDOW_SEC)]
        if len(buf) < RATE * 0.8: continue
        seg = find_utterance(buf.tolist(), RATE); calls += 1
        if seg is None:
            if len(buf) > RATE * va.WINDOW_SEC: del buf[:len(buf) - int(RATE * 1.0)]
            continue
        s, e = seg
        if len(buf) - e < int(RATE * va.QUIET_TAIL): continue
        del buf[:e]                      # (STT 자리 — 이 시험에서는 재지 않는다)
    cpu = time.process_time() - t0
    print(f"조각 {chunk:5d}샘플({1000*chunk/RATE:.0f}ms): VAD 호출 {calls}회 · CPU {cpu:.2f}초 / 오디오 {dur:.1f}초 = 코어 1개의 {100*cpu/dur:.1f}% · 1회 평균 {1000*cpu/max(calls,1):.1f}ms")
