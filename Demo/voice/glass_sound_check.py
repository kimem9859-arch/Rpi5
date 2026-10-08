#!/usr/bin/env python3
"""안경 소리 점검 — 스피커가 낸 소리를 같은 보드 마이크로 받아 재고, 착용 호출 시험을 채점한다(2026-10-09).

절차·판정 기준(재기 전에 고정) = voice/실물확인_증폭_띠링.md

실행 — 🔴 음성비서가 돌고 있으면 멈춘다(명령 채널은 손님 하나 · 새 손님이 옛 손님을 끊는다):
  cd Rpi5/Demo && ~/env/tts/.venv/bin/python voice/glass_sound_check.py sweep            # 높이별 스피커 응답(굽기 전에도 된다)
  cd Rpi5/Demo && ~/env/tts/.venv/bin/python voice/glass_sound_check.py chimes           # 띠링(B)·닫힘음(C) 3번씩
  cd Rpi5/Demo && ~/env/tts/.venv/bin/python voice/glass_sound_check.py chimes --freqs 1175,1568   # 옛 펌웨어 기준선
  cd Rpi5/Demo && python3 voice/glass_sound_check.py score <SOP_VOICE_AUDIO 폴더> [음성 로그]       # 착용 시험 채점

🔑 재구현하지 않는다 — 스피커·마이크 프로토콜은 음성비서의 Speaker·MicReceiver·wav_payload 를 그대로 쓰고, 띠링 높이는
   펌웨어 소스(glass_voice.ino 의 CHIME_LO/HI)에서 읽고, 채점은 음성비서가 남긴 계측(metrics.jsonl)·로그만 센다.
🔴 마이크로 받은 소리 = 스피커 + 프레임 울림 + 마이크 경로가 섞인 값이다 — 스피커만의 일그러짐이 아니다. 같은 자리·
   같은 음량에서 높이끼리 비교하는 데 쓴다.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import wave

import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from question_set import QUESTIONS   # noqa: E402 — 질문 대본의 단일 출처(zlib 만 쓴다)

RATE = 16000
FW = os.path.join(_DEMO, "..", "arduino", "glass_voice", "glass_voice.ino")
SWEEP_HZ = [800, 1000, 1175, 1319, 1397, 1480, 1568, 1760, 1976, 2093, 2349, 2637, 2960, 3136]
CLEAN_HARM = 0.10      # 배음(2·3·4배) 에너지 ÷ 기본음 — 이보다 작으면 깨끗
WEAK_DB = -6.0         # 가장 크게 난 높이보다 이만큼 넘게 작으면 「약함」
SCRIPT_Q = [q for k, q in QUESTIONS if k == "범위"][:10]   # 착용 시험 대본 질문 = 질문 세트 「범위」 앞 10개
SCRIPT_CALLS = 12                                      # 질문 있는 호출 10 + 질문 없는 호출 2(닫힘음 확인)


def fw_chime_hz():
    """펌웨어가 지금 내는 띠링 두 높이 — 소스의 CHIME_LO·CHIME_HI(단일 출처)."""
    src = open(FW, encoding="utf-8").read()
    m = [re.search(rf"{k}\s*=\s*([\d.]+)f", src) for k in ("CHIME_LO", "CHIME_HI")]
    if not all(m):
        sys.exit(f"🔴 {FW} 에서 CHIME_LO·CHIME_HI 를 못 찾았다 — 펌웨어 띠링 상수 이름이 바뀌었나")
    return float(m[0].group(1)), float(m[1].group(1))


# ── 분석(순수 함수) ─────────────────────────────────────────────────────
def spectrum(seg):
    seg = np.asarray(seg, dtype=np.float64)
    seg = seg - seg.mean()
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    return X, np.fft.rfftfreq(len(seg), 1 / RATE)


def tone_quality(seg, f0, bw=40):
    """(기본음 에너지, 배음 비율, 그 밖 비율) — 배음 = 2·3·4배(8kHz 아래)."""
    if len(seg) < 320:                                           # 20ms 미만은 높이를 못 가른다
        return 1e-9, float("nan"), float("nan")
    X, f = spectrum(seg)
    near = lambda c: np.abs(f - c) < bw                          # noqa: E731
    fund = X[near(f0)].sum() + 1e-9
    harm = sum(X[near(k * f0)].sum() for k in (2, 3, 4) if k * f0 < RATE / 2 - bw)
    other = X[(f > 150) & (f < RATE / 2 - bw)].sum() - fund - harm
    return fund, harm / fund, other / fund


def note_report(a, s, e, f0):
    """한 음 — 가운데(앞뒤 25% 뺌)의 기본음 에너지·배음·그밖.

    ⚠️ 「딸깍」(켜짐 순간)은 숫자로 재지 않는다 — 10ms 창은 높이를 못 갈라 비율이 무의미하게 커졌다(10/8 녹음으로 확인).
       사람 귀로 본다.
    """
    q = (e - s) // 4
    fund, harm, other = tone_quality(a[s + q:e - q], f0)
    return dict(hz=f0, fund=fund, harm=harm, other=other, sec=(e - s) / RATE)


def glide_report(a, lo, hi, n=320):
    """닫힘음 — 소리가 큰 창마다 가장 센 높이와 그 2배음 비율 · 높이가 내려가나.
    🔑 「큰 창」 = 가장 큰 창의 −20dB 안 — 닫힘음 덩어리만 잘라 넘겨도 된다(중앙값을 기준으로 두면 덩어리만 넘겼을 때
       기준이 소리 자체가 되어 아무 창도 안 남았다). 소리가 아예 없으면(잡음만) 높이 비율 조건에서 걸러진다."""
    k = len(a) // n
    F = a[:k * n].reshape(k, n)
    F = F - F.mean(axis=1, keepdims=True)
    S = np.abs(np.fft.rfft(F * np.hanning(n), axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / RATE)
    tot = S[:, f > 100].sum(axis=1)
    rms = np.sqrt(tot / n)
    win = (f > lo * 0.9) & (f < hi * 1.1)
    if k == 0:
        return None
    frames = [i for i in range(k) if rms[i] > 0.1 * rms.max() and rms[i] > 50
              and S[i, win].sum() / (tot[i] + 1e-9) > 0.4]
    if not frames:
        return None
    peaks, ratios = [], []
    for i in frames:
        pk = f[win][np.argmax(S[i, win])]
        h2 = S[i, np.abs(f - 2 * pk) < 60].sum() if 2 * pk < RATE / 2 - 60 else 0.0
        peaks.append(pk)
        ratios.append(h2 / (S[i, np.abs(f - pk) < 60].sum() + 1e-9))
    return dict(frames=len(frames), start_hz=float(np.median(peaks[:2])), end_hz=float(np.median(peaks[-2:])),
                harm=float(np.median(ratios)))


# ── 보드와 주고받기(음성비서 코드 그대로) ───────────────────────────────────
class Board:
    def __init__(self):
        import voice_assistant as va
        from voice_mic import MicReceiver
        self.va = va
        self.lock = va.take_lock()
        if self.lock is None:
            sys.exit(f"🔴 음성비서가 돌고 있다({va.LOCK_FILE}) — 시연·음성비서를 끄고 다시(명령 채널은 손님 하나)")
        ip = va.esp_ip()
        self.spk = va.Speaker(lambda: ip, va.CMD_PORT)
        self.mic = MicReceiver(lambda: ip, va.MIC_PORT, rate=RATE, log=lambda m: None).start()
        end = time.time() + 10
        while not self.mic.connected and time.time() < end:
            time.sleep(0.1)
        if not self.mic.connected:
            sys.exit(f"🔴 마이크 업링크({ip}:{va.MIC_PORT})에 못 붙었다 — 보드 전원·주소(.camera_ip) 확인")
        if self.spk.send(b"") is not True:     # 명령 채널을 붙이고 음량(음성비서와 같은 VOLUME)을 맞춘다
            sys.exit(f"🔴 명령 채널({ip}:{va.CMD_PORT})에 못 붙었다 — 소리를 못 낸다")
        print(f"보드 {ip} · 음량 {va.VOLUME}단계 · 마이크 연결됨")

    def record(self, fn, tail=0.8):
        """fn() 을 하는 동안과 그 뒤 tail 초의 마이크 소리 — 따로 도는 스레드가 늘 비운다(pull 은 2초 넘은 소리를 버린다)."""
        chunks, stop = [], threading.Event()

        def pump():
            while not stop.is_set():
                a = self.mic.pull()
                if len(a):
                    chunks.append(a)
                time.sleep(0.02)
        self.mic.clear()
        th = threading.Thread(target=pump, daemon=True)
        th.start()
        out = fn()
        time.sleep(tail)
        stop.set()
        th.join(2)
        a = self.mic.pull()
        if len(a):
            chunks.append(a)
        return (np.concatenate(chunks) if chunks else np.zeros(0, np.int16)), out

    def close(self):
        self.mic.stop()


def save_wav(path, a):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.asarray(a, dtype=np.int16).tobytes())


def out_dir(arg, tag):
    d = arg or os.path.expanduser(f"~/lab/voice-capture/띠링점검_{time.strftime('%Y%m%d_%H%M%S')}_{tag}")
    os.makedirs(d, exist_ok=True)
    return d


# ── sweep ───────────────────────────────────────────────────────────────
def sweep_pcm(freqs, tone_ms=200, gap_ms=120, fade_ms=5, amp=12000):
    """높이를 차례로 — 펌웨어가 재생 때 최댓값을 음량 목표로 맞추므로 띠링과 같은 진폭으로 난다."""
    parts = [np.zeros(int(RATE * 0.2))]
    n, fd = int(RATE * tone_ms / 1000), int(RATE * fade_ms / 1000)
    env = np.ones(n)
    env[:fd] = 0.5 - 0.5 * np.cos(np.pi * np.arange(fd) / fd)
    env[-fd:] = env[:fd][::-1]
    t = np.arange(n) / RATE
    for f0 in freqs:
        parts.append(amp * env * np.sin(2 * np.pi * f0 * t))
        parts.append(np.zeros(int(RATE * gap_ms / 1000)))
    return np.concatenate(parts).astype(np.int16)


def load_wav(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def analyze_sweep(rec, freqs=SWEEP_HZ, tone_ms=200, gap_ms=120):
    """높이마다 (크기 dB · 배음 · 판정). 🔑 음 자리는 일정(tone_ms + gap_ms 간격)으로 잡는다 — 높이로 찾으면 일그러진
    음을 못 찾는다(chimes 와 같은 이유). 시작 시각은 아래 투표로 고른다."""
    a_ = np.asarray(rec, dtype=np.float64)
    ev = sound_events(a_, min_ms=100, merge_frames=0)
    rows = []
    if not ev:
        return [dict(hz=f0, found=False, verdict="못 찾음") for f0 in freqs]
    step, n = int(RATE * (tone_ms + gap_ms) / 1000), int(RATE * tone_ms / 1000)
    # 🔑 첫 음이 약해 안 잡혀도 어긋나지 않게 — 소리 덩어리마다 「i 번째 음이라면 시작은 여기」를 내고 가장 많이 맞는 시작을 고른다
    #    🔴 시간만으로는 한 칸 밀린 자리도 똑같이 맞는다(첫 음이 빠지면) — 동점이면 칸마다 「그 높이의 소리가 실제로 있나」로 가른다.
    cands = sorted({(s - i * step) // 320 * 320 for s, _ in ev for i in range(len(freqs))})
    tol = int(RATE * 0.04)
    votes = {c: sum(any(abs(s - (c + i * step)) < tol for i in range(len(freqs))) for s, _ in ev) for c in cands}
    top_v = max(votes.values())

    def slot_match(c):
        tot = 0.0
        for i, f0 in enumerate(freqs):
            lo_, hi_ = c + i * step + n // 4, c + i * step + n - n // 4
            if lo_ < 0 or hi_ > len(a_):
                continue
            X, f = spectrum(a_[lo_:hi_])
            tot += X[np.abs(f - f0) < 40].sum() / (X[f > 100].sum() + 1e-9)
        return tot
    t0 = max((c for c in cands if votes[c] >= top_v - 1), key=slot_match)
    for i, f0 in enumerate(freqs):
        s = t0 + i * step
        if s + n > len(a_):
            rows.append(dict(hz=f0, found=False, verdict="못 찾음"))
            continue
        rows.append(dict(note_report(a_, s, s + n, f0), found=True))
    top = max((r["fund"] for r in rows if r["found"]), default=1.0)
    for r in rows:
        if r["found"]:
            r["db"] = 10 * np.log10(r["fund"] / top)
            weak, bent = r["db"] < WEAK_DB, not r["harm"] < CLEAN_HARM     # 너무 약하면 배음 비율은 잡음에 흔들린다
            r["verdict"] = "약함·일그러짐" if weak and bent else "약함" if weak else "일그러짐" if bent else "깨끗"
    return rows


def cmd_sweep(a):
    lo, hi = fw_chime_hz()
    d = out_dir(a.out, "sweep")
    if a.wav:                                   # 🔑 이미 받은 녹음을 다시 센다(보드 없이)
        rec = load_wav(a.wav)
        print(f"녹음 {a.wav} 다시 세기")
    else:
        b = Board()
        try:
            pcm = sweep_pcm(SWEEP_HZ)
            tmp = os.path.join(tempfile.mkdtemp(prefix="sop_sweep_"), "sweep.wav")
            save_wav(tmp, pcm)
            body, _ = b.va.wav_payload(tmp)
            rec, resp = b.record(lambda: b.spk.send(body, expect=True))
        finally:
            b.close()
        save_wav(os.path.join(d, "마이크.wav"), rec)
        ok = isinstance(resp, list) and any("재생 완료" in r for r in resp)
        print(f"재생 {'확인 ✅' if ok else '확인 안 됨 🔴'} · 녹음 {len(rec) / RATE:.1f}초 → {d}")
        if not ok:
            sys.exit(f"🔴 시험음 재생이 확인되지 않았다(응답 {resp!r}) — 이 녹음으로는 판정하지 않는다")
    rows = analyze_sweep(rec)
    print(f"\n{'높이Hz':>7} {'크기dB':>7} {'배음%':>7}  판정")
    for r in rows:
        if not r["found"]:
            print(f"{r['hz']:>7} {'—':>7} {'—':>7}  못 찾음(너무 약하거나 녹음 문제)")
            continue
        mark = "  ← 띠링" if r["hz"] in (lo, hi) else ""
        print(f"{r['hz']:>7} {r['db']:7.1f} {r['harm'] * 100:7.1f}  {r['verdict']}{mark}")
    clean = [r["hz"] for r in rows if r.get("verdict") == "깨끗"]
    print(f"\n깨끗한 높이 = {clean}")
    for f0 in (lo, hi):
        r = next((r for r in rows if r["hz"] == f0), None)
        v = r["verdict"] if r else "목록에 없음"
        print(f"펌웨어 띠링 {f0:g}Hz → {v} {'✅' if v == '깨끗' else '🔴 — 절차서 「높이 바꾸기」'}")
    json.dump(dict(rows=[{k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in r.items()}
                         for r in rows], chime=[lo, hi], clean=clean),
              open(os.path.join(d, "결과.json"), "w"), ensure_ascii=False, indent=1)


# ── chimes ──────────────────────────────────────────────────────────────
# 🔑 펌웨어 띠링 일정(ms) = 앞 여백 30 · 낮은 음 120 · 쉼 40 · 높은 음 180 · 뒤 60 — 소리가 시작된 시각에서 음 자리를 잡는다.
#    높이로 음을 찾으면 **심하게 일그러진 음은 못 찾는다**(배음이 기본음보다 커 띠 비율이 낮다) — 그러면 일그러진 음을
#    빼고 「깨끗」으로 잘못 통과한다(10/8 녹음의 1175Hz 가 그랬다).
LO_MS, GAP_MS, HI_MS = 120, 40, 180


def sound_events(a, n=320, min_ms=200, merge_frames=2):
    """소리가 난 덩어리(시작·끝 표본) — 바닥의 6배를 넘는 20ms 창이 이어진 곳(띠링 안 40ms 쉼은 붙인다).
    🔑 바닥 = 조용한 쪽 10% — 중앙값으로 두면 소리가 대부분인 녹음(sweep)에서 바닥이 소리 크기가 된다."""
    k = len(a) // n
    if k == 0:
        return []
    F = a[:k * n].reshape(k, n)
    rms = np.sqrt(((F - F.mean(axis=1, keepdims=True)) ** 2).mean(axis=1))
    hot = np.where(rms > 6 * max(np.percentile(rms, 10), 1.0))[0]
    out, cur = [], None
    for i in hot:
        if cur and i - cur[1] <= merge_frames + 1:      # merge_frames = 사이에 끼어도 붙이는 조용한 창 수
            cur[1] = i
        else:
            if cur:
                out.append(cur)
            cur = [i, i]
    if cur:
        out.append(cur)
    return [(s * n, (e + 1) * n) for s, e in out if (e - s + 1) * n >= RATE * min_ms / 1000]


def chime_notes(a, onset, lo, hi):
    """띠링 한 번 — 소리 시작에서 일정대로 두 음을 잘라 각각 잰다."""
    ms = lambda x: int(RATE * x / 1000)                  # noqa: E731
    return (note_report(a, onset, onset + ms(LO_MS), lo),
            note_report(a, onset + ms(LO_MS + GAP_MS), onset + ms(LO_MS + GAP_MS + HI_MS), hi))


def record_n(b, cmd, times=3, gap=1.2):
    def play():
        for _ in range(times):
            if b.spk.send(cmd) is not True:     # 🔑 못 보냈으면 「안 들림 = 옛 펌웨어」로 잘못 읽지 않게 멈춘다
                return False
            time.sleep(gap)
        return True
    rec, ok = b.record(play)
    if not ok:
        b.close()
        sys.exit(f"🔴 {cmd!r} 명령을 못 보냈다 — 명령 채널 끊김(보드·음성비서 확인)")
    return rec


def cmd_chimes(a):
    """🔴 재는 동안 조용히 — 말소리·손뼉도 소리 덩어리라 띠링으로 센다(띠링 3번 · 닫힘음 3번만 있어야 한다)."""
    lo, hi = (float(x) for x in a.freqs.split(",")) if a.freqs else fw_chime_hz()
    d = out_dir(a.out, "chimes")
    want = None if (a.wav or a.wav_close) else 3
    if want:
        b = Board()
        try:
            rec_b = record_n(b, b"B\n")
            rec_c = record_n(b, b"C\n")
        finally:
            b.close()
        save_wav(os.path.join(d, "띠링.wav"), rec_b)
        save_wav(os.path.join(d, "닫힘음.wav"), rec_c)
    else:
        rec_b = load_wav(a.wav) if a.wav else np.zeros(0, np.int16)
        rec_c = load_wav(a.wav_close) if a.wav_close else np.zeros(0, np.int16)
        print(f"녹음 다시 세기 — 띠링 {a.wav} · 닫힘음 {a.wav_close}")
    print(f"→ {d} · 띠링 높이 {lo:g} → {hi:g}Hz")
    A, C = rec_b.astype(np.float64), rec_c.astype(np.float64)
    notes = []
    short = 0
    for s, e in sound_events(A):
        r_lo, r_hi = chime_notes(A, s, lo, hi)
        notes += [r_lo, r_hi]
        warn = ""
        if (e - s) < RATE * 0.28:            # 띠링 소리 = 120 + 40 + 180 = 340ms — 짧으면 낮은 음이 안 잡혀 자리가 밀렸을 수 있다
            short += 1
            warn = f"  ⚠️ 덩어리 {(e - s) / RATE * 1000:.0f}ms — 자리 의심(낮은 음이 거의 안 났나)"
        print(f"  띠링 {s / RATE:6.2f}s · {lo:g}Hz 배음 {r_lo['harm'] * 100:6.1f}% · {hi:g}Hz 배음 {r_hi['harm'] * 100:6.1f}%{warn}")
    glides = []
    for s, e in sound_events(C):
        g = glide_report(C[s:e], lo, hi)
        glides.append(g)
        if g:
            print(f"  닫힘음 {s / RATE:6.2f}s · {g['start_hz']:.0f} → {g['end_hz']:.0f}Hz · 2배음 {g['harm'] * 100:5.1f}%")
    if len(C) and not glides:
        print("  닫힘음 🔴 안 들림 — 옛 펌웨어면 정상(C 를 모른다)")
    n_b = len(notes) // 2
    harm = [r["harm"] for r in notes]
    ok_count_b = (n_b == want) if want else n_b > 0
    ok_count_c = (len(glides) == want) if want else (len(glides) > 0 or not len(C))
    print("\n관문(절차서 G-b · 재기 전에 고정)")
    print(f"  띠링 {want or '≥1'}번 들림 · 자리 의심 0 : {'✅' if ok_count_b and not short else '🔴'} ({n_b} · 의심 {short})")
    print(f"  띠링 두 음 배음 < {CLEAN_HARM * 100:.0f}% : {'✅' if harm and all(h < CLEAN_HARM for h in harm) else '🔴'} "
          f"(최대 {max(harm) * 100 if harm else float('nan'):.1f}%)")
    if len(C) or want:
        good = [g for g in glides if g and g["end_hz"] < g["start_hz"] * 0.9 and g["harm"] < CLEAN_HARM]
        print(f"  닫힘음 {want or '≥1'}번 들림 : {'✅' if ok_count_c and all(glides) else '🔴'} ({len([g for g in glides if g])})")
        print(f"  닫힘음 내려감·2배음 < {CLEAN_HARM * 100:.0f}% : {'✅' if glides and len(good) == len(glides) else '🔴'} "
              f"({len(good)}/{len(glides)})")
    print("  사람 귀 — 띠링이 선명한가(딸깍·지지직 없음) · 닫힘음이 「낮아지며 꺼지는」 느낌인가 : 👀 사용자")
    json.dump(dict(chime=[lo, hi], notes=notes, glides=glides), open(os.path.join(d, "결과.json"), "w"),
              ensure_ascii=False, indent=1, default=float)


# ── score ───────────────────────────────────────────────────────────────
def _norm(t):
    return "".join(c for c in (t or "") if c.isalnum())


def _cer(a, b):
    a, b = _norm(a), _norm(b)
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        p, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (x != y))
    return d[-1] / max(1, len(b))


def score_utterances(M, log_lines=()):
    """음성비서 계측(metrics.jsonl 의 줄들)·로그 → 발화별 표시와 관문 수. 판정을 다시 하지 않는다 — 데몬이 적은 것만 센다."""
    n_close = {}
    for l in log_lines:
        m = re.search(r"대화창 닫힘\((.+?)\)", l)
        if m:
            n_close[m.group(1)] = n_close.get(m.group(1), 0) + 1
    rows, junk, after_answer, cers = [], [], [], []
    wakes = answered = echo = 0
    prev = None
    for m in M:
        wake, src, text = bool(m.get("호출어")), m.get("답변출처"), m.get("STT텍스트") or ""
        ans = bool(src) and src != "알림으로버림"
        flag = ""
        # 🔑 메아리 의심 = 호출 바로 뒤의 호출 아닌 발화가 두 글자 이하이거나 0.7초 미만 — 막으려던 것이 「아아」 같은 두 글자가
        #    질문으로 가는 것이다(한 글자만 보면 그 경우를 놓친다 · 최종 리뷰). 10/8 메아리 0.61초 · 가장 짧은 실제 질문 0.83초.
        if (prev is not None and prev.get("호출어") and not wake
                and (len(_norm(text)) <= 2 or m.get("발화초", 9) < 0.7)):
            echo += 1
            flag = "← 띠링 메아리 의심"
        if prev is not None and prev.get("답변출처") and not wake:
            after_answer.append(text)
            flag = flag or "← 답 뒤 발화"
        if ans:
            best = min(SCRIPT_Q, key=lambda q: _cer(text, q))
            c = _cer(text, best)
            cers.append((text, best, c))
            if c > 0.5:
                junk.append(text)
                flag = flag or f"← 대본 밖 질문?(가까운 것 「{best}」 {c * 100:.0f}%)"
        wakes += wake
        answered += ans
        rows.append((m, wake, ans, text, flag))
        prev = m
    gains = sorted({m.get("증폭") for m in M}, key=str)
    return dict(rows=rows, wakes=wakes, answered=answered, echo=echo, junk=junk, after_answer=after_answer,
                cers=cers, close=n_close, gains=gains)


def cmd_score(a):
    """착용 시험 채점 — 음성비서가 남긴 metrics.jsonl(발화마다)과 음성 로그만 센다."""
    mpath = os.path.join(a.audio_dir, "metrics.jsonl")
    if not os.path.exists(mpath):
        sys.exit(f"🔴 {mpath} 가 없다 — SOP_VOICE_METRICS=<폴더>/metrics.jsonl 로 띄웠나")
    M = [json.loads(l) for l in open(mpath, encoding="utf-8") if l.strip()]
    log_lines = open(a.voice_log, encoding="utf-8", errors="replace").read().splitlines() if a.voice_log else []
    r = score_utterances(M, log_lines)
    print(f"{'시각':>12} {'초':>5}  {'호출':4} {'답':4}  받아쓰기")
    for m, wake, ans, text, flag in r["rows"]:
        print(f"{m.get('t', ''):>12} {m.get('발화초', 0):5.2f}  {'✅' if wake else '  ':4} {'💬' if ans else '  ':4}  {text}  {flag}")
    good = [c for _, _, c in r["cers"] if c <= 0.5]
    import config                       # 🔑 증폭 배율의 단일 출처 — 기록이 그 값으로 돌았나
    print(f"\n발화 {len(M)} · 호출 인식 {r['wakes']} · 답 {r['answered']} · 닫힘음 {r['close'] or '로그 없음'}")
    ok_gain = r["gains"] == [config.MIC_GAIN]
    print(f"증폭 배율(계측) {r['gains']} ↔ config {config.MIC_GAIN:g} : {'✅' if ok_gain else '🔴 — 다른 배율로 돈 기록이다'}")
    if good:
        print(f"대본 질문 글자 오류율 {np.mean(good) * 100:.1f}%(대본과 가까운 답 {len(good)}개 · 가장 가까운 대본 문장 기준)")
    q0 = r["close"].get("질문 없음", 0)
    print("\n관문(절차서 G-c · 재기 전에 고정) — 👀 = 대본·타임라인을 보고 사용자와 함께 판정")
    print(f"  호출 ≥ 10/{SCRIPT_CALLS} : {'✅' if r['wakes'] >= 10 else '🔴'} ({r['wakes']}) · 👀 헛호출이 섞이면 이 수가 부풀어진다")
    print(f"  띠링 메아리 발화 0 : {'✅' if r['echo'] == 0 else '🔴'} ({r['echo']})")
    print(f"  엉뚱한 질문 0 : {'✅' if not r['junk'] else '👀'} ({r['junk']})")
    print(f"  답 뒤 헛발화 0 : {'✅' if not r['after_answer'] else '👀'} ({r['after_answer']}) · 다음 호출이면 정상")
    print(f"  질문 없는 호출 2번 → 닫힘음 「질문 없음」 2 : {'✅' if q0 == 2 else '👀'} ({q0})")
    print("  헛호출 0(조용히 30초·프레임 만지기 구간) : 👀 타임라인에서 그 구간의 ✅ 를 센다")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sweep", help="높이별 스피커 응답 — 띠링 높이를 고른다")
    p.add_argument("--out")
    p.add_argument("--wav", help="보드 없이 이미 받은 녹음(마이크.wav)을 다시 센다")
    p = sub.add_parser("chimes", help="띠링·닫힘음 3번씩 — 일그러짐·딸깍·내려감")
    p.add_argument("--out")
    p.add_argument("--wav", help="보드 없이 — 띠링(B) 녹음을 다시 센다")
    p.add_argument("--wav-close", help="보드 없이 — 닫힘음(C) 녹음을 다시 센다")
    p.add_argument("--freqs", help="띠링 두 높이(쉼표) — 기본 = 펌웨어 소스 · 옛 펌웨어 기준선 = 1175,1568")
    p = sub.add_parser("score", help="착용 시험 채점")
    p.add_argument("audio_dir")
    p.add_argument("voice_log", nargs="?")
    a = ap.parse_args()
    {"sweep": cmd_sweep, "chimes": cmd_chimes, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
