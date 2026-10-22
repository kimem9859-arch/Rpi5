"""시연 안내 대본 정본(상위 specs/2026-10-18-시연안내모드-design.md §4 · §4.1 · §4.3) — 글자 그대로인지.

실행: python3 Demo/selftest/test_guide_lines.py
🔴 문구는 사용자가 정했다 — 이 표가 바뀌면 설계서 §4 부터 고친다.
"""
import json
import os
import sys

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import config
import voice_card

LINES_PATH = os.path.join(_DEMO, "voice", "guide_lines.json")
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


LINES = {
    "cue_g1_0a": "안녕하세요.",   # 0a~0c = 안내 음성 소개(사용자 2026-10-18 — 시스템 기능이 아님을 먼저 알림)
    "cue_g1_0b": "저는 오늘 시연을 도와 드릴 안내 음성 \"배리어\"입니다.",
    "cue_g1_0c": "제 목소리는 시연을 위한 안내이며, 시스템의 기능이 아닙니다.",
    "cue_g1_1": "지금부터 장비 정비 순서를 지키는지 지켜보는 시연을 해 보겠습니다.",
    "cue_g1_2a": "정비는 노랑, 흰색, 분홍, 파랑 버튼 순서로 진행합니다.",
    "cue_g1_2b": "빨간 버튼은 비상정지 버튼입니다.",
    "cue_g1_3a": "순서를 벗어나면 경고와 차단 알림이 울립니다.",
    "cue_g1_3b": "안내에 따라 한 단계씩 해 보겠습니다.",
    "cue_g2_1": "그럼 작업을 시작하겠습니다.",
    "cue_g3_1": "노랑 버튼을 눌러 주세요.",
    "cue_g4_1a": "5초 동안 기다려 주세요.",
    "cue_g4_1b": "기다리는 동안 다른 버튼에 손을 가져가지 마세요.",
    "cue_g4_2": "5초가 지났습니다.",   # 4-1a 「5초 동안 기다려」와 낱말 맞춤(사용자 2026-10-18)
    "cue_g5_1a": "이번에는 스침 행동을 해 보겠습니다.",
    "cue_g5_1b": "다음 차례가 아닌 버튼 위를 손이 잠깐 스쳐 지나가는 것은 실수가 아니므로, 경고가 울리지 않습니다.",
    "cue_g5_2": "분홍 버튼 위를 멈추지 말고 빠르게 스쳐 지나가 주세요.",
    "cue_g5_3": "손이 스쳐 지나가기만 해서 경고가 울리지 않았습니다.",
    "cue_g5_ra": "손이 버튼 위에 머물러 경고가 울렸습니다.",
    "cue_g5_rb": "손을 떼고, 이번에는 더 빠르게 지나가 주세요.",
    "cue_g6_1": "흰색 버튼을 눌러 주세요.",
    "cue_g6_2": "이제 공구를 확인하는 단계입니다.",
    "cue_g7_1a": "이번에는 일부러 틀린 공구를 잡아 보겠습니다.",
    "cue_g7_1b": "틀린 공구를 잡으면 화면에 경고가 뜹니다.",
    "cue_g7_2": "공구함에서 드라이버를 잡아 주세요.",
    "cue_g8_1a": "필요하지 않은 공구를 잡으셨습니다.",
    "cue_g8_1b": "공구함에 다시 넣어 주세요.",
    "cue_g9_1": "이번에는 공구함에서 렌치를 잡아 주세요.",
    "cue_g9_2": "렌치를 잡은 손을 바라봐 주세요.",
    "cue_g9_3a": "렌치를 잡았는지 확인하고 있습니다.",
    "cue_g9_3b": "렌치를 계속 잡고 바라봐 주세요.",
    "cue_g9_4": "렌치 확인이 끝났습니다.",
    "cue_g9_5": "렌치를 공구함에 다시 넣어 주세요.",
    "cue_g10_1a": "이번에는 머무름 행동을 해 보겠습니다.",
    "cue_g10_1b": "다음 차례가 아닌 버튼 위에 손을 올려 두면 경고 알림이 울립니다.",
    "cue_g10_2a": "흰색 버튼을 누르지 않고, 버튼 위에 손만 올려 주세요.",
    "cue_g10_2b": "경고 알림이 울려도 버튼은 누르지 마세요.",
    "cue_g11_1": "경고 알림을 끄려면 흰색 버튼 위에서 손을 떼 주세요.",
    "cue_g12_1a": "이번에는 순서 위반을 해 보겠습니다.",
    "cue_g12_1b": "다음 차례가 아닌 버튼에 손을 가져가면 경고 알림이, 그 버튼을 누르면 차단 알림이 울립니다.",
    "cue_g12_2": "파랑 버튼을 눌러 주세요.",
    "cue_g13_1a": "작업 순서에 맞지 않는 버튼을 누르셨습니다.",
    "cue_g13_1b": "화면의 차단 해제 버튼을 눌러 주세요.",
    "cue_g14_1": "분홍 버튼을 눌러 주세요.",
    "cue_g15_1a": "이번에는 음성비서를 불러 보겠습니다.",
    "cue_g15_1b": "호출어를 부른 뒤 {띠링} 소리가 나면 \"지금 몇 단계야?\"라고 물어보세요.",   # {띠링} = 실제 띠링 소리(사용자 2026-10-18)
    "cue_g15_1c": "지금 바로 \"가디언\"이라고 불러 주세요.",
    "cue_g15_r1": "{띠링} 소리가 나지 않았다면, 조금 더 크게 \"가디언\"이라고 불러 주세요.",
    "cue_g15_r2a": "주변 소음으로 인해 호출어 인식이 불안정합니다.",
    "cue_g15_r2b": "다음 단계로 넘어가겠습니다.",
    "cue_g16_2a": "작업이 완료되었습니다.",
    "cue_g16_2b": "작업 결과창을 확인해 주세요.",
    "cue_gx_emo": "처음부터 다시 하려면 화면의 작업 시작 버튼을 눌러 주세요.",
}
RESTING = {"cue_g4_1b", "cue_g9_3a"}     # 10/22 대본에서 뺀 소리(「기다리는 동안 …」 · 「렌치를 잡았는지 확인하고 있습니다.」)
SENTENCE_IDS = ("1-1 1-2 1-3 2-1 3-1 4-1 4-2 5-1 5-2 5-3 5-R 6-1 6-2 7-1 7-2 8-1 9-1 9-2 9-3 9-4 9-5 "
                "10-1 10-2 11-1 12-1 12-2 12-2b 13-1 14-1 14-2 14-3 15-1 15-R1 15-R2 16-1 16-2 X-EMO").split()


def load():
    with open(LINES_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_lines_exact():
    print("\n[대본] 49 문장 글자 그대로")
    d = load()
    lines = d.get("lines") or {}
    check(len(LINES) == 52, f"표 52개({len(LINES)})")
    check(set(lines) == set(LINES), f"키 집합이 같다(빠짐 {sorted(set(LINES) - set(lines))} · 더함 {sorted(set(lines) - set(LINES))})")
    bad = [k for k, v in LINES.items() if lines.get(k) != v]
    check(not bad, f"문장이 글자 그대로 같다(다름 {bad})")
    marked = sorted(k for k, v in lines.items() if "{띠링}" in v)
    check(marked == ["cue_g15_1b", "cue_g15_r1"], f"실제 띠링 소리 자리 표시는 두 문장뿐({marked})")
    check(not any("띠링" in v.replace("{띠링}", "") for v in lines.values()), "낱말 「띠링」을 소리 내 읽는 문장이 없다")


def test_sentences_cover_4_3():
    print("\n[대본] §4.3 문장 번호 → 소리 키")
    d = load()
    lines, sents = d.get("lines") or {}, d.get("sentences") or {}
    check(list(sents) == SENTENCE_IDS, f"문장 번호 차례가 §4.3 과 같다({list(sents)})")
    miss = [(s, k) for s, ks in sents.items() for k in ks if k not in lines]
    check(not miss, f"모든 소리 키가 lines 에 있다(없음 {miss})")
    check(all(k.startswith("cue_g") for k in lines), "모든 키가 cue_g 로 시작(CueWatcher 는 cue_ 만 낸다)")
    check(sents.get("1-1") == ["cue_g1_0a", "cue_g1_0b", "cue_g1_0c", "cue_g1_1"], "1-1 = 안내 음성 소개 3문장 + 시연 소개")
    check(sents.get("12-2b") == ["cue_g3_1"], "12-2b = 노랑(분홍을 눌러 버렸을 때 대체)")
    check(sents.get("14-2") == ["cue_g4_1a"] and sents.get("14-3") == ["cue_g4_2"], "14-2 · 14-3 은 4번 소리 재사용")
    check(sents.get("16-1") == ["cue_g12_2"], "16-1 = 파랑(12-2 재사용)")
    used = {k for ks in sents.values() for k in ks}
    # 🔑 10/22(상위 spec §12) 대본에서 뺀 두 소리는 녹음 · 목록에 남긴다(되돌리기 = sentences 만 되돌리면 된다)
    check(set(lines) - used == RESTING, f"쓰이지 않는 소리 = 10/22 뺀 두 개뿐({sorted(set(lines) - used)})")


def test_sentences_1022():
    print("\n[대본] 10/22 시연 점검 뒤 — 4-1 줄임 · 당부를 10-1 끝으로 · 9-3 은 「계속 잡고 바라봐 주세요」 하나")
    s = load().get("sentences") or {}
    check(s.get("4-1") == ["cue_g4_1a"], f"4-1 = 「5초 동안 기다려 주세요.」만({s.get('4-1')})")
    check(s.get("10-1") == ["cue_g10_1a", "cue_g10_1b", "cue_g10_2b"], f"10-1 끝 = 당부({s.get('10-1')})")
    check(s.get("10-2") == ["cue_g10_2a"], f"10-2 = 「…손만 올려 주세요.」만({s.get('10-2')})")
    check(s.get("9-3") == ["cue_g9_3b"], f"9-3 = 「렌치를 계속 잡고 바라봐 주세요.」만({s.get('9-3')})")


def test_guide_tempo_1022():
    print("\n[소리] 안내 소리 52개 모두 1.1배(사용자 10/22 「1.1배가 적당」 · 음 높이 그대로)")
    with open(os.path.join(os.path.dirname(LINES_PATH), "guide_audio.json"), encoding="utf-8") as f:
        reg = json.load(f)
    lines = load().get("lines") or {}
    bad = sorted(k for k in lines if (reg.get(k) or {}).get("tempo") != 1.1)
    check(not bad, f"목록의 빠르기 = 1.1({bad[:6]}{' …' if len(bad) > 6 else ''})")


def test_color_alert_texts():
    print("\n[알림] 색 이름판 9개")
    t = voice_card.color_alert_texts()
    check(len(t) == 9, f"9개({len(t)})")
    check(t.get("alert_warn_B3_c") == "순서가 다르니 손을 떼고 분홍 버튼을 누르세요.", f"경고 B3 = 분홍({t.get('alert_warn_B3_c')})")
    check(t.get("alert_block_B1_c") == "차단 중이니 차단 해제 버튼을 누른 뒤 노랑 버튼부터 다시 누르세요.",
          f"차단 B1 = 노랑 · 「차단 해제 버튼을」(사용자 2026-10-18 · {t.get('alert_block_B1_c')})")
    check(all("차단 해제 버튼을 누른 뒤" in t.get(f"alert_block_{b}_c", "") for b in ("B1", "B2", "B3", "B4")),
          "차단 알림 4개 모두 「차단 해제 버튼을 누른 뒤」")
    check(t.get("alert_emo_c") == "비상정지 중이니 비상정지 버튼을 원래대로 되돌린 뒤 차단 해제를 누르세요.",
          f"비상정지 = 비상정지 버튼({t.get('alert_emo_c')})")
    left = [k for k, v in t.items() if any(w in v for w in ("B1", "B2", "B3", "B4", "EMO"))]
    check(not left, f"번호 · EMO 글자가 남지 않는다({left})")
    check(config.BUTTON_COLOR_NAMES == {"B1": "노랑", "B2": "흰색", "B3": "분홍", "B4": "파랑"}, "색 이름 한 곳(config)")


def test_color_alert_rule_miss_raises():
    print("\n[알림] 바꾸기 규칙이 안 걸리면 멈춘다")
    orig = voice_card.alert_texts
    voice_card.alert_texts = lambda: {"alert_warn_B1": "규칙이 걸리지 않는 문장."}
    try:
        try:
            voice_card.color_alert_texts()
            ok = False
        except ValueError:
            ok = True
    finally:
        voice_card.alert_texts = orig
    check(ok, "ValueError — 원래 문장이 바뀌어도 조용히 번호판이 나가지 않는다")


if __name__ == "__main__":
    for fn in (test_lines_exact, test_sentences_cover_4_3, test_sentences_1022, test_guide_tempo_1022,
               test_color_alert_texts, test_color_alert_rule_miss_raises):
        try:
            fn()
        except Exception as e:                       # noqa: BLE001 — 시험 하나가 터져도 나머지를 본다
            check(False, f"{fn.__name__} 예외: {type(e).__name__}: {e}")
    if _fails:
        print(f"\n❌ {len(_fails)}건 실패")
        sys.exit(1)
    print("\n✅ 시연 안내 대본 시험 통과")
