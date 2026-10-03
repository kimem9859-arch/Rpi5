"""음성 도구 정리 — 설계 2026-10-03 §4.9 (주소 · gate_check · 녹화 도구).

실행: python3 Demo/selftest/test_voice_tools.py
"""
import fcntl
import os
import subprocess
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RPI5 = os.path.dirname(_DEMO_DIR)
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "voice"))
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_audio_ip_untracked():
    print("\n[주소] .audio_ip 추적 해제(R1 I1)")
    r = subprocess.run(["git", "-C", _RPI5, "ls-files", "Demo/.audio_ip"], capture_output=True, text=True)
    check(r.stdout.strip() == "", "저장소가 .audio_ip 를 추적하지 않는다")
    gi = open(os.path.join(_RPI5, ".gitignore"), encoding="utf-8").read().split()
    check(".audio_ip" in gi, ".gitignore 에 있다")
    for f in ("voice_assistant.py", os.path.join("voice", "gate_check.sh")):
        check(".audio_ip" not in open(os.path.join(_DEMO_DIR, f), encoding="utf-8").read(), f"{f} 가 .audio_ip 를 안 본다")


def _empty_file():
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".camera_ip")
    f.close()
    return f.name


def test_gate_check_empty_address_stops_before_hw():
    """최종 리뷰 I7 — 주소 파일이 비면 G0 에서 끝난다(ping·재생·카메라 접속 전) — 시험이 HW 에 닿지 않는 안전판."""
    print("\n[gate_check] 빈 주소 → G0 에서 끝")
    p = os.path.join(tempfile.mkdtemp(), "voice.lock")       # 아무도 안 쥔 잠금
    r = subprocess.run(["bash", os.path.join(_DEMO_DIR, "voice", "gate_check.sh")],
                       env=dict(os.environ, SOP_VOICE_LOCK=p, SOP_CAM_IP_FILE=_empty_file()),
                       capture_output=True, text=True, timeout=20)
    check(r.returncode == 1 and "비었다" in r.stdout, f"코드 {r.returncode} · {r.stdout.strip()[-60:]}")
    check("ping" not in r.stdout and "G2" not in r.stdout, "G2 이후로 가지 않았다")


def test_gate_check_refuses_when_daemon_runs():
    """M10 — 음성비서가 돌면 8889·8890 을 빼앗고 거짓 통과한다 — 시작하지 않는다."""
    print("\n[gate_check] 데몬이 돌면 거절")
    p = os.path.join(tempfile.mkdtemp(), "voice.lock")
    f = open(p, "w")
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        # 🔴 빈 주소 파일을 함께 준다 — 잠금 검사가 회귀해도 G0 에서 끝나 실제 보드에 닿지 않는다(최종 리뷰 I7)
        r = subprocess.run(["bash", os.path.join(_DEMO_DIR, "voice", "gate_check.sh")],
                           env=dict(os.environ, SOP_VOICE_LOCK=p, SOP_CAM_IP_FILE=_empty_file()),
                           capture_output=True, text=True, timeout=20)
    finally:
        f.close()
    check(r.returncode != 0 and "음성비서가 돌고 있다" in r.stdout, f"코드 {r.returncode} · {r.stdout.strip()[:80]}")
    src = open(os.path.join(_DEMO_DIR, "voice", "gate_check.sh"), encoding="utf-8").read()
    check(" ack " not in src, "없는 ack 를 재생하지 않는다")
    check("판정하지 않는다" in src, "업링크 없이 잰 FPS 는 판정하지 않는다(거짓 통과)")


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


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 음성 도구 정리 검증 통과")
