#!/usr/bin/env python3
"""시연 안내 소리 — Gemini 3.8 Flash TTS 로 만든다(🖥️ 데스크톱에서 돈다 · 표준 라이브러리만).

설계 = 상위 sop-project docs/superpowers/specs/2026-10-18-시연안내모드-design.md §5 · plans/2026-10-18-시연안내모드.md Task 7 · 8
쓰임(데스크톱 · 파이가 이 파일과 guide_lines.json 을 scp 로 보내고 ssh 로 돌린다 — 데스크톱 저장소는 건드리지 않는다):
  python3 make_guide_gemini.py --lines guide_lines.json --voice <이름> --out <폴더> [--batch 13] [--only 키 …] [--dry 3] [--each]
  · 묶음마다 문장 사이에 <long pause>(공식 문서 speech-generation 의 인라인 쉼 표시)를 넣어 한 요청 → <폴더>/batch_NN.wav
  · <폴더>/manifest.json = 모델 · 목소리 · 말투 · 만든 때 · 묶음(파일 · 키 · 문장) — 파이 make_guide.py import-gemini 가 읽고 자른다
  · --dry N = 앞 N 문장만 한 요청(시험) · --each = 문장마다 한 요청(자르기 없음 · 유료로 바꾼 뒤 · 묶음 자르기가 어색할 때)
  · 키 = 환경변수 GEMINI_API_KEY · 없으면 ~/.config/gemini/key(파일 또는 그 폴더 안의 파일 하나) — 🔴 화면 · 파일에 쓰지 않는다
  · 🔴 무료 하루 한도로 거절되면 기다려 다시 하지 않고 「무료 한도 소진」 · 종료 코드 3 — 그때까지 받은 묶음 · manifest 는 남긴다
요청 꼴 = dev/video/tools/tts_gemini.py 와 같다(Interactions REST · speech_metadata.style · speech_config.voice).
"""
import argparse
import base64
import datetime
import glob
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request

MODEL = "gemini-3.8-flash-tts"
STYLE = "시연 참여자가 처음 듣고도 놓치지 않도록, 차분하고 친절하게 조금 천천히 또박또박 안내하는 말투"   # 사용자 2026-10-18 — 표본 비교에서 고름
URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
PAUSE = "<long pause>"
QUOTA_EXIT = 3
RETRY_WAITS = (0, 20, 40)        # 분당 한도(429)면 쉬었다 다시 — tts_gemini.py 와 같다


class QuotaExhausted(Exception):
    """무료 하루 한도 — 기다려도 안 풀린다."""


def api_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    p = os.path.expanduser("~/.config/gemini/key")
    if os.path.isdir(p):
        fs = sorted(glob.glob(os.path.join(p, "*")))
        if len(fs) != 1:
            sys.exit(f"키 폴더 {p} 에 파일이 하나여야 한다({len(fs)}개)")
        p = fs[0]
    return open(p, encoding="utf-8-sig").read().strip()


def batches(keys, size, each=False):
    """소리 키 → 요청 묶음(차례 보존) · each = 한 문장씩."""
    if each:
        return [[k] for k in keys]
    return [list(keys[i:i + size]) for i in range(0, len(keys), size)]


def batch_text(texts):
    """한 요청 글 — 문장 사이에 긴 쉼 하나(파이가 그 쉼에서 자른다)."""
    return f"\n{PAUSE}\n".join(texts)


def is_daily_quota(body):
    """429 응답 본문이 하루 한도인가(분당 한도는 기다리면 풀린다)."""
    b = (body or "").lower().replace(" ", "")
    return "perday" in b or "daily" in b


def _as_wav(raw, rate=24000):
    """응답이 RIFF WAV 면 그대로 · 머리 없는 PCM 이면 24 kHz 모노 16비트 WAV 로 감싼다(문서 = 단일 응답은 WAV)."""
    if raw[:4] == b"RIFF":
        return raw
    head = b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return head + b"data" + struct.pack("<I", len(raw)) + raw


def synth(key, text, voice, style=STYLE):
    """한 요청 → WAV 바이트 · 하루 한도면 QuotaExhausted."""
    body = {"model": MODEL,
            "input": [{"type": "user_input", "content": [{"type": "text", "text": text,
                                                          "annotations": [{"type": "speech_metadata", "style": style}]}]}],
            "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": voice}]}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    last = ""
    for wait in RETRY_WAITS:
        time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            break
        except urllib.error.HTTPError as e:
            last = e.read().decode("utf-8", "replace")
            if e.code != 429:
                sys.exit(f"HTTP {e.code}: {last[:400]}")
            if is_daily_quota(last):
                raise QuotaExhausted(last[:300]) from None
    else:
        raise QuotaExhausted(f"요청 한도(429)가 세 번 다 풀리지 않음: {last[:300]}")
    aud = [c for s in d.get("steps", []) if s.get("type") == "model_output"
           for c in s.get("content", []) if c.get("type") == "audio"]
    if not aud:
        sys.exit(f"소리 없음: {text[:60]}")
    return _as_wav(base64.b64decode(aud[-1]["data"]))


def write_manifest(out, model, voice, style, batches):
    m = {"model": model, "voice": voice, "style": style,
         "made": datetime.datetime.now().isoformat(timespec="seconds"), "batches": batches}
    tmp = os.path.join(out, "manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(out, "manifest.json"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="시연 안내 소리 — Gemini TTS(데스크톱)")
    ap.add_argument("--lines", required=True, help="guide_lines.json")
    ap.add_argument("--voice", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=13)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--dry", type=int, default=0, help="앞 N 문장만 한 요청(시험)")
    ap.add_argument("--each", action="store_true", help="문장마다 한 요청")
    ap.add_argument("--style", default=STYLE)
    a = ap.parse_args(argv)
    with open(a.lines, encoding="utf-8") as f:
        lines = json.load(f)["lines"]
    keys = [k for k in lines if a.only is None or k in a.only]
    if a.only:
        unknown = sorted(set(a.only) - set(lines))
        if unknown:
            sys.exit(f"모르는 키: {unknown}")
    groups = [keys[:a.dry]] if a.dry else batches(keys, a.batch, a.each)
    os.makedirs(a.out, exist_ok=True)
    key, done = api_key(), []
    print(f"모델 {MODEL} · 목소리 {a.voice} · 요청 {len(groups)}번 · 문장 {sum(len(g) for g in groups)}개 → {a.out}")
    for i, g in enumerate(groups, 1):
        name = f"batch_{i:02d}.wav"
        try:
            wav = synth(key, batch_text([lines[k] for k in g]), a.voice, a.style)
        except QuotaExhausted as e:
            left = [k for gg in groups[i - 1:] for k in gg]
            print(f"🛑 무료 한도 소진 — 받은 묶음 {len(done)}개는 남겼다 · 유료로 바꾼 뒤 --only 로 이어서: {' '.join(left)}")
            print(f"   (응답 앞부분: {str(e)[:160]})")
            return QUOTA_EXIT
        with open(os.path.join(a.out, name), "wb") as f:
            f.write(wav)
        done.append({"file": name, "keys": g, "texts": [lines[k] for k in g]})
        write_manifest(a.out, MODEL, a.voice, a.style, done)      # 🔑 묶음마다 — 중간에 끊겨도 받은 것은 남는다
        print(f"  {name} · 문장 {len(g)}개 · {len(wav) // 1024} KB")
    print("끝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
