"""인터락 송신·응답 시각(측정 도구 정합 14) — 가짜 시리얼로.

실행: python3 Demo/selftest/test_measure_interlock.py
"""
import os
import sys
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import interlock

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _FakeSer:
    is_open = True

    def __init__(self, reply=b"ACK\n", delay=0.02):
        self.reply, self.delay, self.sent = reply, delay, []

    def reset_input_buffer(self):
        pass

    def write(self, b):
        self.sent.append(b)

    def flush(self):
        pass

    def readline(self):
        time.sleep(self.delay)
        return self.reply


def make(got):
    # 🔴 enabled=False — 실제 포트를 찾거나 재연결·전송 스레드를 띄우지 않는다(보드가 꽂혀 있어도 릴레이를 안 건드림).
    #    _write_now 는 꺼진 채로도 직접 부를 수 있다(필요한 속성은 비활성 조기 return 앞에서 만든다).
    return interlock.InterlockController(enabled=False, log=lambda m: None, on_cmd=lambda *a: got.append(a))


def test_ack_times():
    print("\n[인터락 기록] 보낸 시각 < 응답 시각 · ACK")
    got = []
    il = make(got)
    il._ser = _FakeSer()
    il._write_now("WARN", force=True)
    check(len(got) == 1, f"콜백 {got}")
    cmd, t_send, t_ack, ok, tries = got[0]
    check(cmd == "WARN" and ok and tries == 0 and 0.015 <= t_ack - t_send < 0.5, f"{got[0]}")


def test_not_connected():
    print("\n[인터락 기록] 미연결 = 응답 없음으로 남긴다")
    got = []
    il = make(got)
    il._ser = None
    il._write_now("RUN", force=True)
    check(got and got[0][0] == "RUN" and got[0][2] is None and got[0][3] is False, f"{got}")


def test_block_no_ack_retries():
    print("\n[인터락 기록] BLOCK 무응답 = 재시도 끝에 한 번 · ack False · tries = 재시도 수")
    got = []
    il = make(got)
    il._on_fault = None
    il._ser = _FakeSer(reply=b"\n", delay=0.0)
    il._write_now("BLOCK", force=True)
    check(len(got) == 1 and got[0][0] == "BLOCK" and got[0][3] is False and got[0][4] == il._block_retries,
          f"{got}")


def test_send_error():
    print("\n[인터락 기록] 보내기 실패도 응답 없음으로 남긴다")
    got = []
    il = make(got)

    class _Broken(_FakeSer):
        def write(self, b):
            raise OSError("끊김")

    il._ser = _Broken()
    il._write_now("RUN", force=True)
    check(len(got) == 1 and got[0][0] == "RUN" and got[0][2] is None and got[0][3] is False, f"{got}")


if __name__ == "__main__":
    test_ack_times()
    test_send_error()
    test_not_connected()
    test_block_no_ack_retries()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 인터락 측정 기록 검증 통과")
