"""음성 시연 촬영 도구 시험 — `Demo/selftest/test_voice_tools.py` 에서 도구와 함께 옮겨 왔다(2026-10-09 · 공구 구간 설계 D6).

🔴 여기서는 돌지 않는다 — 되돌릴 때 이 두 함수를 `test_voice_tools.py` 로 되돌린다(`check` · `sys.path` 는 그 파일 것).
"""
import fcntl
import os
import tempfile


def test_record_summary_counts_llm_answers():
    """R2 I5 — 요약이 LLM 답(답변문장)도 답으로 센다."""
    print("\n[녹화] 요약 집계")
    import record_voice_demo as rvd
    rows = [{"STT_ms": 100, "호출어": True},
            {"STT_ms": 100, "답변": "wrench", "재생_ms": 1000},
            {"STT_ms": 100, "답변문장": "지금은 2단계입니다.", "재생_ms": 3000}]
    s = rvd.summarize_voice(rows)
    check(s["답변수"] == 2 and s["답변분포"] == {"wrench": 1, "LLM": 1}, f"{s}")
    check(rvd.DEMO_STATE["세션"] is True and rvd.DEMO_STATE.get("시험용") is True, "시험용 상태는 표시가 붙는다")



def test_m10_recorder_guards():
    """1단계 최종 리뷰 M10 — 녹화 도구는 음성비서가 이미 돌면(코드 3 으로 조용히 끝난다) · GUI 가 상태를 내고 있으면
    (시험용 상태로 덮어쓴다) 시작하지 않는다."""
    print("\n[녹화] 음성비서·GUI 확인")
    import json
    import record_voice_demo as rvd
    p = os.path.join(tempfile.mkdtemp(), "voice.lock")
    check(rvd.voice_busy(p) is False, "아무도 안 쥔 잠금 → 비어 있음")
    f = open(p, "w")
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        check(rvd.voice_busy(p) is True, "쥔 잠금 → 음성비서가 돈다")
    finally:
        f.close()
    st = os.path.join(tempfile.mkdtemp(), "state.json")
    check(rvd.gui_live(st) is False, "상태 파일이 없으면 GUI 없음")
    json.dump({"세션": True, "pid": os.getpid()}, open(st, "w"))
    check(rvd.gui_live(st) is True, "살아 있는 GUI 상태 → 덮어쓰지 않는다")
    json.dump(dict(rvd.DEMO_STATE, pid=os.getpid()), open(st, "w"))
    check(rvd.gui_live(st) is False, "시험용 상태(지난 촬영)는 GUI 가 아니다")
