#!/usr/bin/env python3
"""예상 질문 세트 평가 — 한 문장 60자 구성 · 안전 규칙 · LLM 시간(설계 2026-10-03 §4.7 · D2′).

실행(파이1 · 파이2 LLM 필요 · 합성 때문에 tts venv):
  ~/env/tts/.venv/bin/python Demo/voice/eval_questions.py --split dev --out 조사/질문세트평가-<날짜>/dev
🔴 실제 함수를 그대로 쓴다 — 카드 voice_card.build_card · 호출 voice_llm.ask · 다듬기·안전 규칙
   voice_card.finalize · 합성 voice_tts.Tts · 한도 voice_tts.fits. 재구현하지 않는다(측정도구 규칙).
🔒 dev 로만 고친다. holdout 은 고칠 것을 커밋으로 얼린 뒤 **한 번만** 돈다(계획 관문 ②).
🔑 `--repeat N` — 같은 문항을 N 바퀴 묻고 답이 몇 가지로 갈렸는지 센다(사용자 요청 2026-10-03 ·
   「같은 질문에 다른 답을 하는가」). 바퀴 단위로 돌아 같은 질문이 연달아 오지 않는다 — 파이2 의 프롬프트
   캐시를 다시 쓰는 경우와 새로 계산하는 경우가 섞인다. 합격 기준·시간 통계는 **1바퀴만**으로 낸다.
"""
import argparse
import json
import os
import random
import statistics
import sys
import time

_VOICE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_VOICE))
sys.path.insert(0, _VOICE)
import config  # noqa: E402
import question_set  # noqa: E402
import voice_card  # noqa: E402
import voice_llm  # noqa: E402
import voice_tts  # noqa: E402

_UNSURE = ("확인할 수 없", "알 수 없")


def run_items(items, f, tts, pass_no=1):
    rows = []
    if True:
        for k, it in enumerate(items, 1):
            state = dict(it["상태"], 쓴시각=time.time()) if it["상태"] else None
            dets, fresh = it["공구"]
            facts = voice_card.card_facts(state, dets, fresh)
            row = {k2: it[k2] for k2 in ("id", "상태키", "유형", "질문", "분할")}
            row["회차"] = pass_no
            if not facts["세션"]:
                row["경로"] = "고정-작업전"
            else:
                card = voice_card.build_card(state, dets, fresh)
                raw, m = voice_llm.ask(card, it["질문"])
                row.update(m)
                if raw is None:
                    row["경로"] = "LLM실패"
                else:
                    said, src, bad = voice_card.finalize(raw, facts)
                    row.update({"원문": raw, "원문자수": len(raw), "문장": said, "경로": src,
                                "안전규칙": bad, "잘림": m.get("생성토큰") == config.LLM_NUM_PREDICT})
                    if said and pass_no == 1:          # 합성 길이는 1바퀴에서만 잰다
                        row["최종규칙"] = voice_card.check_safety(said, facts) if src == "LLM" else []
                        got = tts.synth(said)
                        if got:
                            pcm, rate, sec = got
                            row.update({"말하는초": round(sec, 2), "한도안": voice_tts.fits(len(pcm) // 2, rate)})
                        else:
                            row["합성실패"] = True
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{pass_no}회차 {k}/{len(items)}] {row['id']} {row.get('경로')} {row.get('LLM_ms', '')} {row.get('문장', '')}",
                  flush=True)
    return rows


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def summarize(rows):
    spoken = [r for r in rows if r.get("문장")]
    llm = [r for r in rows if r.get("경로") in ("LLM", "대체-안전규칙", "빈답", "LLM실패")]
    ms = sorted(r["LLM_ms"] for r in llm if r.get("LLM_ms") and r.get("경로") != "LLM실패")
    q = statistics.quantiles(ms, n=100) if len(ms) >= 2 else [None] * 99
    outside = [r for r in spoken if r["유형"] == "카드밖"]
    return {
        "문항": len(rows), "LLM호출": len(llm),
        "한문장60자_%": _pct(sum(1 for r in spoken if voice_card.is_one_sentence(r["문장"])
                                and len(r["문장"]) <= voice_card.ANSWER_MAX_CHARS), len(spoken)),
        "합성10초이하_%": _pct(sum(1 for r in spoken if r.get("말하는초") is not None
                                and r["말하는초"] <= 10.0 and r.get("한도안")), len(spoken)),
        "최종규칙위반_건": sum(1 for r in spoken if r.get("최종규칙")),
        "원문60자이하_%": _pct(sum(1 for r in llm if r.get("원문자수", 999) <= 60), len(llm)),
        "안전규칙발동_%": _pct(sum(1 for r in llm if r.get("안전규칙")), len(llm)),
        "안전규칙_종류": {k: sum(1 for r in llm if k in (r.get("안전규칙") or [])) for k in ("허가", "다른버튼", "진행단정")},
        "토큰잘림_%": _pct(sum(1 for r in llm if r.get("잘림")), len(llm)),
        "카드밖_확인불가_%": _pct(sum(1 for r in outside if any(w in r["문장"] for w in _UNSURE)), len(outside)),
        "LLM_ms_p50": q[49], "LLM_ms_p95": q[94], "LLM_ms_p99": q[98],
        "LLM실패_건": sum(1 for r in rows if r.get("경로") == "LLM실패"),
        "합성실패_건": sum(1 for r in rows if r.get("합성실패")),
        "조건": {"모델": config.LLM_MODEL, "num_predict": config.LLM_NUM_PREDICT,
                 "num_ctx": config.LLM_NUM_CTX, "타임아웃": config.LLM_TIMEOUT_SEC,
                 "temperature": config.LLM_TEMPERATURE},
    }


def repeat_summary(rows):
    """같은 문항(상태·질문)을 여러 바퀴 물었을 때 답이 몇 가지로 갈렸나. `(요약, 갈린 문항들)`."""
    by = {}
    for r in rows:
        if r.get("경로") in ("LLM", "대체-안전규칙", "빈답"):
            by.setdefault(r["id"], []).append(r)
    raw_n, said_n, diff = {}, {}, []
    for iid, rs in sorted(by.items()):
        a = len({r.get("원문") for r in rs})
        b = len({r.get("문장") for r in rs})
        raw_n[a] = raw_n.get(a, 0) + 1
        said_n[b] = said_n.get(b, 0) + 1
        if a > 1:
            diff.append((iid, rs))
    return {"문항": len(by), "원문_가짓수별_문항수": raw_n, "말한문장_가짓수별_문항수": said_n}, diff


def review_sheet(rows, path, n=30, seed=0):
    """사람 표본 30 — 안전 규칙 발동(최대 10) → 허가·진행단정 유도(합쳐 20까지) → 나머지 무작위."""
    spoken = [r for r in rows if r.get("문장")]
    pick = [r for r in spoken if r.get("안전규칙")][:10]
    pick += [r for r in spoken if r["유형"] in ("허가유도", "진행단정유도") and r not in pick][:20 - len(pick)]
    rest = [r for r in spoken if r not in pick]
    random.Random(seed).shuffle(rest)
    pick += rest[:n - len(pick)]
    with open(path, "w", encoding="utf-8") as f:
        f.write("| # | 상태 | 질문 | 말한 문장 | 출처 | 판정(O/X) |\n|---|---|---|---|---|---|\n")
        for k, r in enumerate(pick, 1):
            f.write(f"| {k} | {r['상태키']} | {r['질문']} | {r['문장']} | {r['경로']} |  |\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["dev", "holdout"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N문항만(시운전)")
    ap.add_argument("--temperature", type=float, default=None,
                    help="config.LLM_TEMPERATURE 를 이 실행에서만 바꾼다(「같은 질문에 다르게」 비교 · 사용자 요청 2026-10-03)")
    ap.add_argument("--from-q", type=int, default=1, help="질문 번호가 이 이상인 문항만(추가분만 돌릴 때 · 34)")
    ap.add_argument("--to-q", type=int, default=999, help="질문 번호가 이 이하인 문항만(기존분만 비교할 때 · 33)")
    ap.add_argument("--repeat", type=int, default=1, help="같은 문항을 N 바퀴(답이 갈리는지 · 기준·시간은 1바퀴)")
    a = ap.parse_args()
    if a.temperature is not None:
        config.LLM_TEMPERATURE = a.temperature
    os.makedirs(a.out, exist_ok=True)
    items = [i for i in question_set.build_items() if i["분할"] == a.split and a.from_q <= i["번호"] <= a.to_q]
    if a.limit:
        items = items[:a.limit]
    ok, m = voice_llm.warm()
    if not ok:
        sys.exit(f"🔴 LLM 예열 실패 — 파이2 를 확인하라: {m}")
    tts = voice_tts.Tts()
    rows = []
    with open(os.path.join(a.out, "결과.jsonl"), "w", encoding="utf-8") as f:
        for p in range(1, a.repeat + 1):
            rows += run_items(items, f, tts, p)
    s = summarize([r for r in rows if r["회차"] == 1])
    if a.repeat > 1:
        s["반복"], diff = repeat_summary(rows)
        with open(os.path.join(a.out, "반복.md"), "w", encoding="utf-8") as f:
            f.write(f"# 같은 질문 {a.repeat}바퀴 — 답이 갈린 문항 {len(diff)}개\n\n")
            for iid, rs in diff:
                f.write(f"## {iid} · 「{rs[0]['질문']}」\n\n")
                for r in rs:
                    f.write(f"- {r['회차']}회차 · {r.get('경로')} · 원문: {r.get('원문')} → 말함: {r.get('문장')}\n")
                f.write("\n")
    with open(os.path.join(a.out, "요약.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "요약.md"), "w", encoding="utf-8") as f:
        f.write(f"# 질문 세트 평가 — {a.split}\n\n| 지표 | 값 |\n|---|---|\n")
        for k, v in s.items():
            f.write(f"| {k} | {v} |\n")
    if a.split == "holdout":
        review_sheet(rows, os.path.join(a.out, "검토표.md"))
    print(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
