#!/usr/bin/env python3
"""시연 안내 소리 — 목록 · 검사 · Gemini 소리 들이기 · 알림 색 이름판 만들기(파이).

설계 = 상위 sop-project docs/superpowers/specs/2026-10-18-시연안내모드-design.md §5 · plans/2026-10-18-시연안내모드.md Task 7 · 8
실행:
  python3 Demo/voice/make_guide.py --check                       — 안내 49 + 알림 9 가 다 있고 · 한도 안이고 · 모노 16비트이고 · 옛 글자가 아닌지
  ~/env/tts/.venv/bin/python Demo/voice/make_guide.py alerts      — 알림 색 이름판 9개(Supertonic · 시스템 목소리 F1)
  ~/env/tts/.venv/bin/python Demo/voice/make_guide.py import-gemini <폴더> [--dry-run] [--orig <데스크톱 원본 폴더>]
      — 데스크톱 make_guide_gemini.py 가 만든 묶음을 문장 사이 긴 쉼에서 자르고 · 최고점 맞춤 · 받아쓰기 점수 → voice/wav/ 에 깔기
        (깔기 전 그 키의 지금 소리를 voice/wav_guide_prev/ 로 · --dry-run = 깔지 않고 <폴더>/조각/ 에만)
운용(계획서 「녹음 파일 운용」): 원본 = 데스크톱 ~/data/음성/시연안내/<날짜>_<목소리>/ · 쓰는 판 = voice/wav/ · 깔린 목록 = voice/guide_audio.json(git)
🔴 기존 소리(답 · 알림 · 측정 안내)는 건드리지 않는다 — 이 도구가 쓰는 키는 cue_g… 와 alert_…_c 뿐이다.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import wave

VOICE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(VOICE_DIR))

import voice_card   # noqa: E402 — 알림 색 이름판 문장(한 곳)
import voice_tts    # noqa: E402 — 펌웨어 한도(fits)

OUT = os.path.join(VOICE_DIR, "wav")
PREV = os.path.join(VOICE_DIR, "wav_guide_prev")
LINES_PATH = os.path.join(VOICE_DIR, "guide_lines.json")
MANIFEST = os.path.join(VOICE_DIR, "guide_audio.json")
LEAD, TAIL = 0.05, 0.08          # 조각 앞뒤에 남기는 무음(초) — tts_gemini.py 와 같다
PEAK = 0.89                      # 최고점 -1 dBFS — tts_gemini.py 와 같다
SCORE_WARN = 0.8                 # 받아쓰기 일치가 이보다 낮으면 사용자가 들어 본다


def load_lines(path=LINES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def guide_keys():
    return list(load_lines()["lines"])


def alert_keys():
    return list(voice_card.color_alert_texts())


def all_texts():
    """검사 대상 = 안내 49 + 알림 9 → {키: 문장}."""
    d = dict(load_lines()["lines"])
    d.update(voice_card.color_alert_texts())
    return d


def text_sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_manifest(path=MANIFEST):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def check(wav_dir=OUT, lines=None, manifest=None):
    """문제 줄 목록(빈 목록 = 통과) — 없음 · 모노 16비트 아님 · 펌웨어 한도 초과 · 옛 글자(목록 지문 ≠ 대본) · 목록에 없음."""
    lines = all_texts() if lines is None else lines
    manifest = load_manifest() if manifest is None else manifest
    out = []
    for k, text in lines.items():
        p = os.path.join(wav_dir, f"{k}.wav")
        if not os.path.exists(p):
            out.append(f"{k}: 없음")
            continue
        try:
            with wave.open(p) as w:
                ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        except (OSError, wave.Error, EOFError) as e:
            out.append(f"{k}: 못 읽음({e})")
            continue
        if ch != 1 or sw != 2:
            out.append(f"{k}: 모노 16비트 아님({ch}채널 · {sw * 8}비트)")
        if not voice_tts.fits(n, rate):
            out.append(f"{k}: 펌웨어 한도 초과({n}샘플 · {rate}Hz)")
        info = manifest.get(k)
        if info is None:
            out.append(f"{k}: 목록(guide_audio.json)에 없음 — 어디서 만든 소리인지 모른다")
        elif info.get("text_sha1") != text_sha1(text):
            out.append(f"{k}: 옛 글자 소리 — 대본이 바뀌었다(다시 만들 것)")
    return out


def _frames(x, rate, hop_sec=0.01):
    import numpy as np
    hop = max(1, int(rate * hop_sec))
    n = len(x) // hop
    return np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1)) if n else np.zeros(0), hop


def trim(x, rate):
    """앞뒤 무음을 LEAD · TAIL 만 남기고 자른다."""
    import numpy as np
    a = np.abs(x)
    if not len(a) or a.max() <= 0:
        return x
    idx = np.where(a > 0.01 * a.max())[0]
    return x[max(0, idx[0] - int(LEAD * rate)): idx[-1] + int(TAIL * rate) + 1]


def split_batch(x, rate, n):
    """묶음 소리를 소리 없는 구간 중 가장 긴 n-1 곳의 가운데에서 잘라 n 조각 → 조각마다 trim · 모자라면 ValueError."""
    import numpy as np
    x = np.asarray(x, dtype=np.float64)
    if n <= 1:
        return [trim(x, rate)]
    e, hop = _frames(x, rate)
    if not len(e):
        raise ValueError("소리가 비었다")
    quiet = e < max(1e-4, 0.02 * e.max())
    loud = np.where(~quiet)[0]
    if not len(loud):
        raise ValueError("말소리가 없다")
    runs, i = [], loud[0]
    while i <= loud[-1]:                         # 말소리 사이(앞뒤 무음 제외)의 조용한 구간만
        if quiet[i]:
            j = i
            while j <= loud[-1] and quiet[j]:
                j += 1
            runs.append((j - i, i, j))
            i = j
        else:
            i += 1
    if len(runs) < n - 1:
        raise ValueError(f"쉼이 {len(runs)}곳뿐 — 문장 {n}개로 못 자른다")
    cuts = sorted(((s + t) // 2) * hop for _, s, t in sorted(runs, reverse=True)[:n - 1])
    edges = [0] + cuts + [len(x)]
    return [trim(x[a:b], rate) for a, b in zip(edges, edges[1:])]


def read_manifest(d):
    with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _read_float(path):
    import numpy as np
    with wave.open(path) as w:
        ch, sw, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"{path}: 16비트가 아니다({sw * 8}비트)")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _to_pcm(x):
    import numpy as np
    m = float(np.abs(x).max()) if len(x) else 0.0
    y = x * (PEAK / m) if m > 0 else x
    return (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()


def _write(path, pcm, rate):
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _save_manifest(entries):
    m = load_manifest()
    m.update(entries)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(m.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, MANIFEST)


def import_gemini(src, dry_run=False, orig=None):
    """데스크톱 묶음 → 자르기 · 최고점 · 한도 · 받아쓰기 → 깔기(또는 --dry-run 이면 <src>/조각/ 에만)."""
    from make_answers import stt_judge        # 음성비서와 같은 받아쓰기(다시 쓰지 않는다)
    man, lines = read_manifest(src), load_lines()["lines"]
    judge = stt_judge()
    got, bad = [], []
    for b in man["batches"]:
        x, rate = _read_float(os.path.join(src, b["file"]))
        parts = split_batch(x, rate, len(b["keys"]))
        for k, p in zip(b["keys"], parts):
            pcm = _to_pcm(p)
            n = len(pcm) // 2
            score = judge(pcm, rate, lines[k])
            ok = voice_tts.fits(n, rate)
            got.append((k, pcm, rate, score))
            flag = "" if ok and score >= SCORE_WARN else "  ⚠️"
            if flag:
                bad.append(k)
            print(f"  {k:14s} {n / rate:5.2f}초 · 받아쓰기 {score:.2f}{' · 한도 초과' if not ok else ''}{flag}  {lines[k]}")
    if dry_run:
        d = os.path.join(src, "조각")
        os.makedirs(d, exist_ok=True)
        for k, pcm, rate, _ in got:
            _write(os.path.join(d, f"{k}.wav"), pcm, rate)
        print(f"깔지 않음(--dry-run) — 조각 {len(got)}개 → {d}")
        return got, bad
    os.makedirs(PREV, exist_ok=True)
    made = datetime.date.today().isoformat()
    entries = {}
    for k, pcm, rate, _ in got:
        dst = os.path.join(OUT, f"{k}.wav")
        if os.path.exists(dst):
            shutil.copy2(dst, os.path.join(PREV, f"{k}.wav"))
        _write(dst, pcm, rate)
        entries[k] = {"text_sha1": text_sha1(lines[k]), "source": "gemini", "model": man["model"], "voice": man["voice"],
                      "style": man["style"], "made": made, "orig": orig or src}
    _save_manifest(entries)
    print(f"깔았다 {len(got)}개 → {OUT} · 바로 전 판 → {PREV} · 목록 → {MANIFEST}")
    return got, bad


def make_alerts():
    """알림 색 이름판 9개 — 시스템 목소리(config.TTS_ST_VOICE) · 문장 빠르기 기본 · 여러 번 만들어 받아쓰기로 고른다."""
    import config
    from make_answers import pick, stt_judge
    tts, judge = voice_tts.Tts(), stt_judge()
    made, entries = datetime.date.today().isoformat(), {}
    for k, text in voice_card.color_alert_texts().items():
        got = pick(tts, text, speed=None, judge=lambda p, r, s=text: judge(p, r, s))
        if got is None:
            print(f"  🔴 {k} 합성 실패 — {text}")
            continue
        pcm, rate, sec, score, n = got
        _write(os.path.join(OUT, f"{k}.wav"), pcm, rate)
        entries[k] = {"text_sha1": text_sha1(text), "source": "supertonic", "model": config.TTS_ENGINE,
                      "voice": config.TTS_ST_VOICE, "style": None, "made": made, "orig": None}
        print(f"  {k:18s} {n}번째 고름 · 받아쓰기 {score:.2f} · {sec:.2f}초 · {rate}Hz  {text}")
    _save_manifest(entries)


def main(argv=None):
    ap = argparse.ArgumentParser(description="시연 안내 소리 — 검사 · 들이기 · 알림")
    ap.add_argument("--check", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("alerts")
    g = sub.add_parser("import-gemini")
    g.add_argument("src")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--orig", default=None, help="데스크톱 원본 폴더(목록에 적는다)")
    a = ap.parse_args(argv)
    if a.cmd == "alerts":
        make_alerts()
    elif a.cmd == "import-gemini":
        _, bad = import_gemini(a.src, a.dry_run, a.orig)
        if bad:
            print(f"⚠️ 들어 볼 것 {len(bad)}개: {' '.join(bad)}")
    if a.check or a.cmd is None:
        probs = check()
        for p in probs:
            print(f"  ❌ {p}")
        print(f"검사 — 문제 {len(probs)}개 / 대상 {len(all_texts())}개")
        return 1 if probs else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
