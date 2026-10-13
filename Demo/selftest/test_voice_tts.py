"""런타임 합성 검증 — 프레임이 wav_payload 와 같은 모양인지 본다.

실행: ~/env/tts/.venv/bin/python Demo/selftest/test_voice_tts.py

🔴 시스템 python3 에는 sherpa_onnx 가 없다 — 반드시 tts venv 로 돌린다.
정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §7
"""
import os
import struct
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from voice_assistant import wav_payload
from voice_tts import Tts, frame

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    import re
    import numpy as np
    t = Tts()
    got = t.synth("앞에 렌치가 보입니다.")
    check(got is not None, "합성이 된다")
    pcm, rate0, sec = got
    body = frame(pcm, rate0)
    check(body.startswith(b"W "), "W 프레임으로 시작한다")
    check(body.endswith(b"P\n"), "P 로 끝난다")
    check(0.5 < sec < 5.0, f"말하는 시간이 그럴듯하다 ({sec:.2f}초)")

    head, rest = body.split(b"\n", 1)
    n, rate = int(head.split()[1]), int(head.split()[2])
    check(len(rest) == n * 2 + 4 + 2, "본문 길이 = 샘플*2 + 체크섬4 + P\\n2")
    import array
    a = array.array("h")
    a.frombytes(rest[:n * 2])
    chk = struct.unpack("<I", rest[n * 2:n * 2 + 4])[0]
    check(chk == (sum(v & 0xFFFF for v in a) & 0xFFFFFFFF),
          "🔴 체크섬 계산이 펌웨어·wav_payload 와 같다")

    # 🔴 두 프레임 생성기가 같은 PCM 에 대해 **바이트 단위로 같은 것**을 내야 한다.
    #    어긋나면 펌웨어 checksum() 이 재생을 통째로 버린다.
    ref_path = os.path.join(_DEMO_DIR, "voice", "wav", "wrench.wav")
    ref, _ = wav_payload(ref_path)
    import wave as _wave
    with _wave.open(ref_path) as w:
        ref_pcm, ref_rate = w.readframes(w.getnframes()), w.getframerate()
    check(frame(ref_pcm, ref_rate) == ref,
          "🔴 voice_tts.frame() 이 wav_payload() 와 바이트 단위로 일치한다")

    check(t.synth("") is None, "빈 문자열이면 None")

    # ── 엔진 갈래 · 한글 읽기 · 레이트(측정 진행 도우미 설계 2026-10-11 D11) ──
    import numpy as np
    import config
    import voice_tts as V
    check(V.read_out("B1 다음 B4 · EMO 해제") == "비원 다음 비포 비상정지 해제", "버튼 이름 → 한글 읽기 · 가운뎃점은 띄어쓰기(Supertonic 이 안 받는다)")
    sr = 44100
    tt = np.arange(sr) / sr
    lo = V.downsample(np.sin(2 * np.pi * 1000 * tt) * 0.5, 44100, 22050)
    hi = V.downsample(np.sin(2 * np.pi * 15000 * tt) * 0.5, 44100, 22050)
    check(len(lo) == 22050, f"44100 → 22050 길이 절반 ({len(lo)})")
    check(abs(np.abs(lo[1000:-1000]).max() - 0.5) < 0.03, "1kHz 진폭이 그대로다")
    check(np.abs(hi[1000:-1000]).max() < 0.5 * 10 ** (-30 / 20), "15kHz(새 나이퀴스트 위)는 30dB 넘게 깎인다")
    x = np.r_[np.zeros(1000), np.full(10, 0.5), np.zeros(1000)].astype(np.float32)
    check(len(V.trim(x, 22050)) == 10 + 2 * int(22050 * V.TRIM_PAD_SEC), "앞뒤 무음을 자르고 여유만 남긴다")
    check(t.engine == config.TTS_ENGINE == "supertonic2", f"기본 엔진 = supertonic2 ({t.engine})")
    check(rate0 == config.TTS_OUT_RATE == 22050, f"출력 레이트 = 22050 ({rate0})")
    check(Tts(engine="kss").synth("앞에 렌치가 보입니다.") is not None, "되돌리기 갈래(kss)도 합성된다")

    # ── 센 소리 줄이기(2026-10-11 · 사용자 「센 발음(고음)만 깍아 낼 순 없나」 · 「조금 줄인 쪽」) ──
    r = 22050
    seg = lambda f, s: (np.sin(2 * np.pi * f * np.arange(int(r * s)) / r) * 0.5).astype(np.float32)   # noqa: E731
    x = np.r_[seg(500, 0.3), seg(7000, 0.2), seg(500, 0.3)]
    try:
        y = V.deess(x, r)
    except AttributeError:
        check(False, "deess 가 없다")
        y = None
    if y is not None:
        a, b = int(r * 0.25), int(r * 0.55)          # 바뀐 곳에서 50ms 떨어진 모음(500Hz) 자리
        check(np.abs(y[:a] - x[:a]).max() < 1e-4 and np.abs(y[b:] - x[b:]).max() < 1e-4,
              "센 소리가 아닌 곳(500Hz)은 손대지 않는다 — 소리 전체를 깎지 않는다")
        mid = slice(int(r * 0.35), int(r * 0.45))
        got = np.abs(y[mid]).max()
        check(abs(got - 0.5 * config.TTS_DEESS_GAIN) < 0.03, f"센 소리(7kHz) 순간만 {config.TTS_DEESS_GAIN} 배로 ({got:.3f})")
        check(np.abs(V.deess(x, r, gain=1.0) - x).max() < 1e-4, "gain 1.0 = 끔")
        called = []
        orig = V.deess
        V.deess = lambda x, rate, **k: (called.append(rate), orig(x, rate, **k))[1]
        try:
            t.synth("다시")
        finally:
            V.deess = orig
        check(called == [config.TTS_OUT_RATE], "supertonic2 합성이 센 소리 줄이기를 지난다")
    # ── 지원하지 않는 글자(2026-10-11 실물 — 「클린·가스차단」·「펌프/퍼지」 답이 합성 실패 → 「답변할 수 없습니다」) ──
    for q in ("다음 단계는 2단계 「펌프/퍼지」이고, 버튼 B2를 누르셔야 합니다.", "지금은 1단계 「클린·가스차단」입니다.",
              "『주의』 ‘렌치’ “확인” … 끝"):
        check(t.synth(q) is not None, f"괄호·가운뎃점이 있어도 합성된다 — {q}")
    check(V.read_out("1단계 「클린·가스차단」") == "1단계 클린 가스차단", f"합성 전 글자 정리 · {V.read_out('1단계 「클린·가스차단」')!r}")
    check(t.synth("지금 온도는 25℃ 입니다") is not None, "정리 뒤에도 남는 글자(℃)는 빼고 다시 합성한다(재시도 경로 · 리뷰 M6)")
    # ── 숨 고르기(2026-10-13 사용자 귀 확인 — 「네」 뒤에 쉬지 않고 한 호흡에 말함 · 안쪽 쉼 최장 0.13초) ──
    C, E = config.TTS_PAUSE_COMMA_SEC, config.TTS_PAUSE_END_SEC
    check(V.breath_parts("네, 렌치는 이미 확인됐습니다.") == [("네,", C), ("렌치는 이미 확인됐습니다.", 0.0)],
          "쉼표 뒤에서 나누고 쉼표 쉼을 둔다")
    check(V.breath_parts("버튼은 B3입니다. 위험하면 누르세요?") == [("버튼은 B3입니다.", E), ("위험하면 누르세요?", 0.0)],
          "문장 끝에서 나누고 문장 쉼을 둔다")
    check(V.breath_parts("다음 버튼은 B3 가스 퍼지입니다.") == [("다음 버튼은 B3 가스 퍼지입니다.", 0.0)],
          "쉼표·문장 사이가 없으면 한 덩어리(지금과 같다)")
    check(V.breath_parts("약 2.5초 남았습니다") == [("약 2.5초 남았습니다", 0.0)], "소수점은 나누지 않는다(뒤에 띄어쓰기가 없다)")
    check(V.breath_parts("1. 렌치 2. 드라이버") == [("1. 렌치 2. 드라이버", 0.0)], "번호 목록은 나누지 않는다(「1.」 홀로 뭉개짐 · 리뷰)")

    def longest_gap(pcm, rate, rel=0.04):
        x = np.abs(np.frombuffer(pcm, np.int16).astype(float))
        hop = int(rate * 0.01)
        env = np.array([x[i:i + hop].mean() for i in range(0, len(x) - hop, hop)])
        q, best, run = env < rel * env.max(), 0, 0
        for v in q[5:-5]:                                    # 앞뒤 끝 무음은 뺀다
            run = run + 1 if v else 0
            best = max(best, run)
        return best * 0.01
    g = longest_gap(*t.synth("네, 렌치는 이미 확인됐습니다.")[:2])
    check(g >= C, f"쉼표 자리에 쉼이 실제로 생긴다 ({g:.2f}초 ≥ {C})")
    # ── 합성 깨짐 막기(2026-10-13 실물 — 「확인할 수 없습니다」가 0.83초 · 「…없습니다」만 들림 · 정상 1.20초) ──
    real = t._st.synthesize
    seq = []

    def fake(text, **kw):                                # 첫 번째는 글자당 0.08초(깨짐) · 다음은 정상
        n = len(re.findall(r"[가-힣]", text))
        sec = (0.08 if not seq else 0.15) * n
        seq.append(sec)
        return np.full((1, int(t._st.sample_rate * sec)), 0.3, np.float32), None
    t._st.synthesize = fake
    try:
        got = t.synth("확인할 수 없습니다.")
    finally:
        t._st.synthesize = real
    check(len(seq) == 2 and got and got[2] >= 0.15 * 8 * 0.9, f"글자당 너무 짧으면 다시 만든다 · {len(seq)}번 · {got and round(got[2], 2)}초")
    seq.clear()

    def short(text, **kw):
        seq.append(1)
        return np.full((1, int(t._st.sample_rate * 0.3)), 0.3, np.float32), None
    t._st.synthesize = short
    try:
        t.synth("네,")
    finally:
        t._st.synthesize = real
    check(len(seq) == 1, f"짧은 조각(6글자 미만)은 다시 만들지 않는다 · {len(seq)}번")
    import re
    import voice_assistant as va
    with open(va.HOTWORDS, encoding="utf-8") as f:
        bad = [w for w in f.read().splitlines() if w.strip() and not re.fullmatch(r"\S+( :\d+(\.\d+)?)?", w.strip())]
    check(not bad, f"핫워드 줄 형식 = 「낱말」 또는 「낱말 :세기」 — 틀리면 sherpa 가 경고만 남기고 건너뛴다(리뷰 M6) · {bad}")
    check(va.build_stt() is not None, f"받아쓰기가 저장소 핫워드 목록(「가디언 :8.0」 꼴)을 읽는다 — {os.path.basename(va.HOTWORDS)}")
    try:
        Tts(engine="없음")
        check(False, "모르는 엔진을 못 잡음")
    except ValueError:
        check(True, "모르는 엔진 = ValueError")

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
