# 일회용 — VAD 효율화(Task 1)가 답을 바꾸지 않았는지: 9/7 실제 글라스 녹음에서 옛/새 find_utterance 대조
# 실행: python3 vad_equiv.py <기준 커밋의 voice_lib.py> <wav...>
import importlib.util
import sys
import wave

import numpy as np

sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
import voice_lib as new  # noqa: E402

spec = importlib.util.spec_from_file_location("voice_lib_old", sys.argv[1])
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

RATE = 16000
for path in sys.argv[2:]:
    w = wave.open(path)
    a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    n = diff = found = 0
    for end in range(RATE, len(a) + 1, RATE // 4):
        buf = a[max(0, end - 6 * RATE):end]
        r_old = old.find_utterance(buf.tolist(), RATE)
        r_new = new.find_utterance(buf, RATE)
        n += 1
        found += r_new is not None
        if r_old != r_new:
            diff += 1
            print(f"  다름 @ {end / RATE:.2f}s: 옛 {r_old} / 새 {r_new}")
    print(f"{path}: 창 {n}개 · 발화 잡힘 {found} · 다른 답 {diff}")
