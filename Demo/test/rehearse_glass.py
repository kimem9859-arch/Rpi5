"""리허설용 가짜 안경 소리 — 말을 필요할 때 흘린다 · 질문 소리 만들기(학교 방문 준비 설계 §7.1).

LiveGlass = fake_glass.FakeGlass 와 같은 8889 · 8890 규약 · 마이크는 연결을 열어 둔 채 잡음을 흘리다가 say() 로 받은 소리를 끼운다.
질문 소리 = ~/env/tts/.venv/bin/python rehearse_glass.py --synth <폴더> <글>… (16kHz 16비트 wav · index.json)
🔴 답하는 것 = 흐름(호출 → 질문 → 답 · 띠 진행) · 답하지 않는 것 = 실물 마이크 · 소음 속 인식률(학교 값)
"""
import json
import os
import queue
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_glass import CHUNK, FakeGlass, load_16k   # noqa: E402

TTS_PY = os.path.expanduser("~/env/tts/.venv/bin/python")


class LiveGlass(FakeGlass):
    def __init__(self, **kw):
        super().__init__([], **kw)
        self._q = queue.Queue()

    def say(self, samples):
        self._q.put(self._clip(list(samples)))

    def _mic_loop(self):
        n = 0
        while not self._stop.is_set():
            c = self._accept(self._mic_srv)
            if c is None:
                return
            n += 1
            self._event("mic_conn", n)
            c.settimeout(self.write_block_sec)
            while not self._stop.is_set():
                try:
                    s = self._q.get_nowait()
                    self._event("say", len(s))
                except queue.Empty:
                    s = self._noise(CHUNK)
                if not self._push(c, s):
                    break
            try:
                c.close()
            except OSError:
                pass


def make_clips(texts, out_dir):
    """질문 글마다 「가디언, 질문」 소리를 만든다(tts 가상환경) → {글: wav 경로} · 실패하면 빈 사전."""
    os.makedirs(out_dir, exist_ok=True)
    idx = os.path.join(out_dir, "index.json")
    r = subprocess.run([TTS_PY, os.path.abspath(__file__), "--synth", out_dir, *texts], capture_output=True,
                       text=True, timeout=600, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if r.returncode != 0 or not os.path.exists(idx):
        print(f"⚠️ 질문 소리 만들기 실패: {r.stderr[-300:]}", flush=True)
        return {}
    with open(idx, encoding="utf-8") as f:
        return json.load(f)


def watch_say(glass, clips, stop_event, shm_dir=None):
    """가상 작업자의 말하기 요청(rehearse_say.json)을 보고 그 소리를 흘린다 — 배경 스레드로 돌린다."""
    import config
    path = os.path.join(shm_dir or config.CUE_SHM_DIR, "rehearse_say.json")
    last = 0
    while not stop_event.is_set():
        try:
            with open(path, encoding="utf-8") as f:
                req = json.load(f)
        except (OSError, ValueError):
            req = None
        if req and req.get("n", 0) > last:
            last = req["n"]
            wav = clips.get(req.get("text") or "")
            if wav:
                glass.say(load_16k(wav))
        time.sleep(0.1)


def _synth(out_dir, texts):
    """tts 가상환경에서만 — 22050 → 16000 선형 보간."""
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import voice_tts
    tts, out = voice_tts.Tts(), {}
    for i, text in enumerate(texts):
        r = tts.synth(f"가디언, {text}")
        if r is None:
            print(f"합성 실패: {text} — {tts.last_error}", file=sys.stderr)
            continue
        pcm, rate, _ = r
        x = np.frombuffer(pcm, np.int16).astype(np.float32)
        n = int(len(x) * 16000 / rate)
        y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)
        p = os.path.join(out_dir, f"q{i:02d}.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(y.tobytes())
        out[text] = p
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--synth":
        _synth(sys.argv[2], sys.argv[3:])
