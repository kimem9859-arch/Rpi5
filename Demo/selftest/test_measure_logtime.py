"""사람이 읽는 로그 시각 = ms(측정 도구 정합 D15).

실행: python3 Demo/selftest/test_measure_logtime.py
"""
import os
import re
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, os.path.join(_DEMO_DIR, "test"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import config
config.RECORDING_ENABLED = False
config.CAMERA_TCP_HOST = "127.0.0.1"
config.TCP_RECV_TIMEOUT_SEC = 0.3
config.TCP_RECONNECT_DELAY_SEC = 0.1
config.STATE_SHM_DIR = tempfile.mkdtemp(prefix="sop_state_test_")

from PyQt6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

_fails = []
MS = re.compile(r"^\[\d\d:\d\d:\d\d\.\d{3}\] ")


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_console_log_ms():
    print("\n[ms] 시연 로그")
    config.GPIO_INPUT_ENABLED = False
    config.INTERLOCK_ENABLED = False
    from safety_console import SafetyConsole
    win = SafetyConsole()
    win._append_log("[시험] 한 줄")
    last = win.log_browser.toPlainText().splitlines()[-1]
    check(bool(MS.match(last)), f"화면 로그 {last!r}")
    with open(win._log_file_path, encoding="utf-8") as f:
        check(bool(MS.match(f.read().splitlines()[-1])), "파일 로그도 ms")
    win.close()


def test_voice_log_ms():
    print("\n[ms] 음성 로그")
    import voice_assistant as va
    s = va.ms_clock(1_700_000_000.1234)
    check(bool(re.fullmatch(r"\d\d:\d\d:\d\d\.123", s)), f"ms_clock {s!r}")


def test_parsers_accept_ms():
    print("\n[ms] 조사 파서가 ms 줄도 읽는다")
    p = os.path.join(os.path.dirname(_DEMO_DIR), "조사", "실콘솔-20261006", "측정스크립트", "스침_GUI로그분석.py")
    src = open(p, encoding="utf-8").read()
    pat = re.search(r"re\.match\(r'(.+?)', line\)", src).group(1)
    check(re.match(pat, "[12:00:01.234] [FPS] 14.0") is not None, "ms 줄")
    check(re.match(pat, "[12:00:01] [FPS] 14.0") is not None, "옛 초 단위 줄")



def test_voice_watch_lines_ms():
    print("\n[ms] 음성 감시 스크립트 줄도 ms(리뷰 M-8)")
    with open(os.path.join(_DEMO_DIR, "run_voice.sh"), encoding="utf-8") as f:
        sh = f.read()
    check("date +%T)" not in sh and sh.count("date +%T.%3N") >= 2, "run_voice.sh 의 date 가 ms")


if __name__ == "__main__":
    test_console_log_ms()
    test_voice_log_ms()
    test_parsers_accept_ms()
    test_voice_watch_lines_ms()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 로그 시각 ms 검증 통과")
