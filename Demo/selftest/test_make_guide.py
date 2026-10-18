"""시연 안내 소리 만들기 · 검사(상위 specs/2026-10-18-시연안내모드-design.md §5 · plans/2026-10-18-시연안내모드.md Task 7).

실행: python3 Demo/selftest/test_make_guide.py   (네트워크 · 합성 모델 없음 — 순수 부분만)
"""
import json
import os
import sys
import tempfile
import wave

import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "voice"))

import make_guide as MG
import make_guide_gemini as GG

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def write_wav(path, x, rate=22050, ch=1):
    a = (np.clip(x, -1, 1) * 30000).astype(np.int16)
    if ch == 2:
        a = np.repeat(a[:, None], 2, axis=1)
    with wave.open(path, "w") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())


def tone(sec, rate=24000, f=220.0):
    t = np.arange(int(sec * rate)) / rate
    return 0.5 * np.sin(2 * np.pi * f * t)


def test_keys():
    print("\n[키] 안내 49 · 알림 9")
    g, a = MG.guide_keys(), MG.alert_keys()
    check(len(g) == 49 and len(a) == 9, f"49 · 9({len(g)} · {len(a)})")
    check(not set(g) & set(a), "겹침 없음")
    check(g[0] == "cue_g1_1" and g[-1] == "cue_gx_emo", "대본 차례 그대로")
    check(all(k.endswith("_c") for k in a), "알림 키 = 원래 키 + _c")


def test_check_reports():
    print("\n[검사] 빠짐 · 한도 초과 · 스테레오 · 옛 글자")
    lines = {"cue_g1_1": "가", "cue_g1_2a": "나", "cue_g1_2b": "다", "cue_g1_3a": "라", "cue_g1_3b": "마"}
    with tempfile.TemporaryDirectory() as d:
        write_wav(os.path.join(d, "cue_g1_1.wav"), tone(1.0, 22050))                  # 정상
        write_wav(os.path.join(d, "cue_g1_2a.wav"), tone(240001 / 22050 + 0.01, 22050))   # 한도 초과
        write_wav(os.path.join(d, "cue_g1_2b.wav"), tone(1.0, 22050), ch=2)             # 스테레오
        write_wav(os.path.join(d, "cue_g1_3a.wav"), tone(1.0, 22050))                  # 옛 글자
        man = {"cue_g1_1": {"text_sha1": MG.text_sha1("가")}, "cue_g1_3a": {"text_sha1": MG.text_sha1("옛 문장")}}
        probs = MG.check(d, lines=lines, manifest=man)
        txt = "\n".join(probs)
        check("cue_g1_1" not in txt, "정상 키는 문제 목록에 없다")
        check("cue_g1_2a" in txt and "한도" in txt, "한도 초과를 잡는다")
        check("cue_g1_2b" in txt and "모노" in txt, "스테레오를 잡는다")
        check("cue_g1_3a" in txt and "옛 글자" in txt, "옛 글자 소리를 잡는다(목록 지문 ≠ 대본)")
        check("cue_g1_3b" in txt and "없음" in txt, "빠진 소리를 잡는다")


def test_split_batch():
    print("\n[자르기] 가장 긴 쉼 n-1 곳")
    r = 24000
    sil = np.zeros(int(0.7 * r))
    short = np.zeros(int(0.15 * r))
    x = np.concatenate([tone(0.6), sil, tone(0.2), short, tone(0.2), sil, tone(0.5)])
    parts = MG.split_batch(x, r, 3)
    lens = [len(p) / r for p in parts]
    check(len(parts) == 3, f"조각 3개({len(parts)})")
    want = (0.6, 0.55, 0.5)
    check(all(abs(a - b) <= 0.15 for a, b in zip(lens, want)), f"길이가 톤과 맞다({[round(v, 2) for v in lens]})")
    try:
        MG.split_batch(x, r, 5)
        ok = False
    except ValueError:
        ok = True
    check(ok, "쉼이 모자라면 ValueError")


def test_batches():
    print("\n[묶음] 13개씩 · 차례 · --only · --each")
    keys = MG.guide_keys()
    b = GG.batches(keys, 13)
    check(len(b) == 4 and sum(len(x) for x in b) == 49, f"4묶음 · 49({[len(x) for x in b]})")
    check([k for x in b for k in x] == keys, "차례 보존")
    check(GG.batches(keys[:3], 13) == [keys[:3]], "적으면 한 묶음")
    check(GG.batches(keys[:3], 13, each=True) == [[k] for k in keys[:3]], "--each = 한 문장씩")
    t = GG.batch_text(["가.", "나."])
    check(t.count("<long pause>") == 1 and t.startswith("가.") and t.endswith("나."), f"문장 사이 긴 쉼 한 번({t!r})")


def test_quota_detect():
    print("\n[한도] 하루 한도 문구")
    check(GG.is_daily_quota('{"error": {"code": 429, "message": "Quota exceeded for metric: ... per day ..."}}'), "per day")
    check(GG.is_daily_quota('{"error": {"status": "RESOURCE_EXHAUSTED", "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}'), "PerDay quotaId")
    check(not GG.is_daily_quota('{"error": {"code": 429, "message": "per minute"}}'), "분당 한도는 하루 한도가 아니다")


def test_manifest_roundtrip():
    print("\n[목록] 데스크톱 manifest → 파이 읽기")
    with tempfile.TemporaryDirectory() as d:
        GG.write_manifest(d, model="m", voice="v", style="s", batches=[{"file": "batch_01.wav", "keys": ["cue_g3_1"],
                                                                        "texts": ["노랑 버튼을 눌러 주세요."]}])
        m = MG.read_manifest(d)
        check(m["voice"] == "v" and m["batches"][0]["keys"] == ["cue_g3_1"], "그대로 읽힌다")


if __name__ == "__main__":
    for fn in (test_keys, test_check_reports, test_split_batch, test_batches, test_quota_detect, test_manifest_roundtrip):
        try:
            fn()
        except Exception as e:                       # noqa: BLE001
            check(False, f"{fn.__name__} 예외: {type(e).__name__}: {e}")
    if _fails:
        print(f"\n❌ {len(_fails)}건 실패")
        sys.exit(1)
    print("\n✅ 시연 안내 소리 만들기 시험 통과")
