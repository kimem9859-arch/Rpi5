"""ollama 호출 검증 — 🔴 실패가 예외로 새지 않는지를 본다.

실행: python3 Demo/selftest/test_voice_llm.py

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §6·§10

⚠️ **모델을 부르지 않는다** — 여기서 pi2 를 부르면 테스트가 수십 초가 되고
   네트워크에 매인다. 표준 라이브러리 http.server 로 ollama 를 흉내낸다.
   프롬프트 품질(그라운딩·허가 거절)은 Demo/voice/llm_gate.py 의 몫이다.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import config
import voice_llm

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


_seen = {}


class Fake(BaseHTTPRequestHandler):
    MODE = "ok"

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        _seen["body"] = json.loads(self.rfile.read(n))
        if Fake.MODE == "slow":
            time.sleep(0.5)          # 🔴 타임아웃을 결정론적으로 만든다
        if Fake.MODE == "500":
            self.send_response(500)
            self.end_headers()
            return
        if Fake.MODE == "empty":
            body = {"response": "   ", "prompt_eval_count": 300, "eval_count": 0,
                    "prompt_eval_duration": 2e8, "eval_duration": 1e8, "load_duration": 1e9}
        else:
            body = {"response": "2단계에 필요한 공구는 렌치입니다.",
                    "prompt_eval_count": 320, "eval_count": 27,
                    "prompt_eval_duration": 2.5e8, "eval_duration": 3.8e9,
                    "load_duration": 1.13e9}
        raw = json.dumps(body).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass      # 🔑 느린 모드에서 클라이언트가 먼저 끊는다 — 정상이다

    def log_message(self, *a):
        pass


def _wait_idle(c, sec=2.0):
    end = time.time() + sec
    while c.warming and time.time() < end:
        time.sleep(0.01)


def test_client_skip_and_rewarm():
    """LlmClient — 예열 전 묻지 않음 · 실패한 예열은 skip_sec 마다 · 연속 실패 3회 → 60초 건너뜀 + 다시 데움
    (Review Focus 5 — 파이2 가 꺼졌다 켜져도 질문마다 15초 기다리지 않고 스스로 회복)."""
    print("── LlmClient")
    t = [0.0]
    calls = {"ask": 0, "warm": 0}
    warm_ok = [False]
    answers = []

    def fake_ask(card, q):
        calls["ask"] += 1
        return answers.pop(0)

    def fake_warm():
        calls["warm"] += 1
        return warm_ok[0], {"예열_ms": 1}

    c = voice_llm.LlmClient(ask_fn=fake_ask, warm_fn=fake_warm, fail_limit=3, skip_sec=60,
                            clock=lambda: t[0])
    text, m = c.ask("카드", "질문")
    check(text is None and m["LLM오류"] == "예열 전" and calls["ask"] == 0, "예열 전에는 묻지 않는다")
    _wait_idle(c)
    check(calls["warm"] == 1, "예열 전 질문이 데우기를 건다")
    c.ask("카드", "질문")
    _wait_idle(c)
    check(calls["warm"] == 1, "실패한 예열은 skip_sec 안에 다시 걸지 않는다")
    t[0] = 61.0
    c.available()
    _wait_idle(c)
    check(calls["warm"] == 2, "skip_sec 뒤에는 다시 데운다")
    warm_ok[0] = True
    t[0] = 122.0
    c.available()
    _wait_idle(c)
    check(c.ready, "예열이 되면 쓸 수 있다")
    answers[:] = [("답", {})]
    check(c.ask("카드", "질문")[0] == "답", "쓸 수 있으면 묻는다")
    answers[:] = [(None, {"LLM오류": "시간 초과"})] * 3
    for _ in range(3):
        c.ask("카드", "질문")
    _wait_idle(c)
    check(calls["ask"] == 4, "실패 3번까지는 묻는다")
    check(calls["warm"] == 4, "3번 이어 실패하면 배경에서 다시 데운다")
    text, m = c.ask("카드", "질문")
    check(calls["ask"] == 4 and m["LLM오류"] == "건너뜀(연속 실패)", "건너뛰는 동안은 묻지 않는다")
    t[0] += 61.0
    answers[:] = [("다시 답", {})]
    check(c.ask("카드", "질문")[0] == "다시 답", "skip_sec 뒤에는 다시 묻는다")


def main():
    test_client_skip_and_rewarm()
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/api/generate"
    card = "[사실]\n현재 진행 중인 단계: 2단계 「펌프/퍼지」\n"
    try:
        print("── 정상 응답")
        text, m = voice_llm.ask(card, "이번 단계에 무슨 공구 필요해?", url=url)
        check(text == "2단계에 필요한 공구는 렌치입니다.", "문장을 그대로 돌려준다")
        check(m["LLM_ms"] > 0 and m["생성토큰"] == 27, "계측이 함께 온다")

        print("── 🔴 보낸 요청의 모양")
        b = _seen["body"]
        check(b.get("think") is False, "🔴 think:false 가 반드시 들어간다(§10.46-(4))")
        check(b["options"]["temperature"] == config.LLM_TEMPERATURE, "temperature = config 값")
        check(b["stream"] is False, "스트리밍을 안 쓴다")
        check(b["system"] == voice_llm.SYSTEM, "시스템 프롬프트는 모듈 상수 그대로(고정)")
        check("[사실]" in b["prompt"] and "[질문]" in b["prompt"],
              "카드와 질문이 한 프롬프트에 담긴다")

        print("── 🔴 실패는 None 으로 (예외로 새지 않는다)")
        Fake.MODE = "500"
        text, m = voice_llm.ask(card, "뭐야", url=url)
        check(text is None and "LLM오류" in m, "서버 오류면 None + 오류 계측")
        Fake.MODE = "empty"
        text, m = voice_llm.ask(card, "뭐야", url=url)
        check(text is None, "빈 문자열이면 None")
        Fake.MODE = "ok"
        text, m = voice_llm.ask(card, "뭐야", url="http://127.0.0.1:1/api/generate")
        check(text is None and "LLM오류" in m, "못 붙으면 None")
        Fake.MODE = "slow"
        text, m = voice_llm.ask(card, "뭐야", url=url, timeout=0.05)
        check(text is None and "LLM오류" in m,
              "🔴 타임아웃이면 None — 서버가 0.5초 자게 해 하드웨어 속도에 안 매이게 잰다")
        Fake.MODE = "ok"

        print("── 🔑 상주·예열(설계 2026-10-03 §4.2 · D1)")
        voice_llm.ask(card, "뭐야", url=url)
        b = _seen["body"]
        check(b.get("keep_alive") == -1, "모든 질문에 keep_alive -1(D1 상주)")
        ok, wm = voice_llm.warm(url=url)
        w = _seen["body"]
        check(ok is True, "예열 성공")
        check(not w.get("prompt"), "예열은 프롬프트 없이 — 적재만 한다(Ollama FAQ 「Preloading」)")
        check(w.get("options", {}).get("num_ctx") == b["options"]["num_ctx"],
              "🔴 예열과 질문의 num_ctx 가 같다 — 다르면 다시 적재한다(R3 C2)")
        check(w.get("keep_alive") == -1, "예열도 상주")
        Fake.MODE = "slow"
        ok, wm = voice_llm.warm(url=url, timeout=0.05)
        check(ok is False and "LLM오류" in wm, "예열 실패는 (False, 오류)")
        Fake.MODE = "ok"
        check("한 문장" in voice_llm.SYSTEM and "두 문장" not in voice_llm.SYSTEM, "SYSTEM = 한 문장 규칙(D2)")

        print("── temperature 는 config 한 곳(기본 0.8 · 사용자 규칙 판정 2026-10-03 「같은 질문에도 조금씩 다르게」)")
        old_t = config.LLM_TEMPERATURE
        check(old_t == 0.8, f"기본은 0.8 — 같은 질문에도 조금씩 다르게(사용자 규칙 판정 2026-10-03) — {old_t}")
        config.LLM_TEMPERATURE = 0.3
        try:
            voice_llm.ask(card, "뭐야", url=url)
            check(_seen["body"]["options"]["temperature"] == 0.3, "질문이 config 값을 쓴다")
            voice_llm.warm(url=url)
            check(_seen["body"]["options"]["temperature"] == 0.3, "예열도 같은 값")
        finally:
            config.LLM_TEMPERATURE = old_t
    finally:
        srv.shutdown()

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
