"""측정 기록 모듈(측정 도구 정합 §4.3 적기) — 큐 + 쓰기 전용 스레드 · 꺼지면 아무것도 안 함.

실행: python3 Demo/selftest/test_measure_log.py
"""
import csv
import json
import os
import sys
import tempfile
import time

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import measure_log as ML

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_null_when_env_missing():
    print("\n[기록] 환경변수 없으면 NullLog")
    os.environ.pop("SOP_MEASURE_DIR", None)
    lg = ML.open_from_env(["frames", "events"])
    check(isinstance(lg, ML.NullLog) and not lg.enabled, f"{type(lg).__name__}")
    lg.row("frames", [1, 2]); lg.event("x"); lg.close()
    check(True, "NullLog 호출은 예외 없이 지나간다")


def test_write_rows_and_events():
    print("\n[기록] 줄 · 사건 · 머리줄 · 닫기")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["frames", "events"])
    lg.row("frames", [1] + [0] * (len(ML.HEADERS["frames"]) - 1))
    lg.event("press", t=12.5, button="B1", source="gpio")
    lg.close()
    fr = rows(os.path.join(d, "frames.csv"))
    ev = rows(os.path.join(d, "events.csv"))
    check(fr[0] == ML.HEADERS["frames"] and fr[1][0] == "1", f"frames {fr[:2]}")
    check(ev[0] == ["t_ms", "kind", "data"], f"events 머리 {ev[0]}")
    check(ev[1][0] == "12500.0" and ev[1][1] == "press"
          and json.loads(ev[1][2]) == {"button": "B1", "source": "gpio"}, f"사건 {ev[1]}")
    check(ev[-1][1] == "measure_end" and json.loads(ev[-1][2]) == {"dropped": 0, "failed": False},
          f"끝 사건 {ev[-1]}")


def test_reopen_appends():
    print("\n[기록] 다시 열면 이어 쓴다 — 음성 데몬이 세션 도중 다시 떠도 앞 기록이 남는다")
    d = tempfile.mkdtemp()
    a = ML.MeasureLog(d, ["voice_events"], event_file="voice_events")
    a.event("alert", key="k1")
    a.close()
    b = ML.MeasureLog(d, ["voice_events"], event_file="voice_events")
    b.event("alert", key="k2")
    b.close()
    ev = rows(os.path.join(d, "voice_events.csv"))
    check(sum(1 for r in ev if r == ["t_ms", "kind", "data"]) == 1, f"머리줄은 한 번 {ev}")
    keys = [json.loads(r[2]).get("key") for r in ev[1:] if r[1] == "alert"]
    check(keys == ["k1", "k2"], f"두 번의 기록이 모두 남는다 {keys}")


def test_flush_without_close():
    print("\n[기록] 닫지 않아도 주기적으로 비운다(도중에 꺼진 세션)")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["events"], flush_sec=0.1)
    lg.event("run_start")
    time.sleep(0.5)
    ev = rows(os.path.join(d, "events.csv"))
    check(len(ev) == 2 and ev[1][1] == "run_start", f"닫기 전에 읽힘 {ev}")
    lg.close()


def test_queue_overflow_counts_drops():
    print("\n[기록] 큐가 차면 버리고 센다 — 호출부는 막히지 않는다")
    d = tempfile.mkdtemp()
    lg = ML.MeasureLog(d, ["events"], qmax=5, flush_sec=0.05)
    lg._pause.set()                       # 쓰기 스레드를 잠깐 멈춘 상태로 넣는다(시험용 문)
    time.sleep(0.2)                       # 🔑 기다리던 get(0.05초)이 끝나 멈춤 고리에 들어간 뒤 넣는다 — 안 그러면
                                          #    첫 항목을 쓰기 스레드가 집어 가 버린 수가 14 가 되는 경쟁이 생긴다
    t0 = time.monotonic()
    for i in range(20):
        lg.event("x", i=i)
    check(time.monotonic() - t0 < 0.5, "넣기가 막히지 않는다")
    check(lg.dropped == 15, f"버린 수 {lg.dropped}")
    lg._pause.clear()
    lg.close()
    ev = rows(os.path.join(d, "events.csv"))
    check(json.loads(ev[-1][2])["dropped"] == 15, f"끝 사건에 버린 수 {ev[-1]}")


def test_write_error_does_not_raise():
    print("\n[기록] 쓰기 오류는 로그 한 줄 · 예외 없음")
    d = tempfile.mkdtemp()
    said = []
    lg = ML.MeasureLog(d, ["events"], log=said.append)
    lg._files["events"][0].close()        # 파일이 갑자기 닫힌 상황
    lg.event("x")
    lg.close()
    check(lg.failed and any("측정 기록" in s for s in said), f"failed={lg.failed} · 로그 {said}")


def test_now_ms():
    print("\n[기록] now_ms")
    check(ML.now_ms(1.2345678) == 1234.568, f"{ML.now_ms(1.2345678)}")


if __name__ == "__main__":
    test_null_when_env_missing()
    test_write_rows_and_events()
    test_reopen_appends()
    test_flush_without_close()
    test_queue_overflow_counts_drops()
    test_write_error_does_not_raise()
    test_now_ms()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 측정 기록 모듈 검증 통과")
