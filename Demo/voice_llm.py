"""ollama 호출 — 한 파일로 격리한다.

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §6

🔴 **실패는 예외가 아니라 `None` 으로 돌려준다.** 폴백을 고르는 것은 호출부의
   몫이고, 여기서 예외를 올리면 데몬이 죽는다(A 갈래에서 실제로 물린 자리다).

🔴 **`think: false` 가 필수다.** 없으면 `gemma4:e2b` 가 생각 과정으로 생성
   예산을 다 써 **답변이 0글자**가 된다(§10.46-(4)). 속도표로는 안 걸리고
   응답을 눈으로 봐야 걸린다.

🔴 **`SYSTEM` 은 고정이다.** 실행 중에 바꾸면 ollama 가 모델을 다시 올려
   약 5초가 더 붙는다(§10.62-(4) 측정 함정).

표준 라이브러리만 쓴다 — 새 의존성을 넣지 않는다.
"""
import json
import os
import sys
import threading
import time
import urllib.request

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

import config  # noqa: E402

# 🔑 규칙마다 막는 것이 있다(§10.53-(4) · 2026-10-03 설계 §4.3·§4.4):
#      ①수치 지어냄·②모르는 상태를 안다고 함  ← 사실에만 근거 / 지어내지 않는다
#      ⑤상태 모르면서 허가함                  ← 스스로 허가하지 않는다
#      순서 위반을 권함(R3 C3)               ← 지금 버튼이 아닌 버튼을 누르라고 말하지 않는다
#      ⑥묻지 않은 위험 행동 제안 · 긴 답(P4)   ← 한 문장, 60자 안팎(D2)
#    🔴 프롬프트만 믿지 않는다 — 같은 규칙을 voice_card.finalize 가 런타임에 다시 건다.
#      비상정지 중 「B3 누르세요」(2026-10-04 holdout) ← 판단은 코드가 「지금 할 일」로 넘기고 그대로 전하게 한다
#                                                 · 비상 상황에는 아예 묻지 않는다(설계 2026-10-04 §4.7)
# 🔑 모범 문답 — 설계 2026-10-04 §4.4. 🔴 질문은 질문 세트(판 1·판 2)와 겹치지 않는다(selftest 가 본다).
# 🔑 비상 상황 예시는 넣지 않는다 — 그때는 LLM 을 부르지 않는다(설계 2026-10-04 §4.7).
EXAMPLES = (
    ("지금 할 일: B2 를 누른다", "어디 눌러?", "지금은 B2 버튼을 누를 차례입니다."),
    ("지금 할 일: 기다린다 — 렌치는 확인됐고 약 4초 뒤 자동으로 3단계로 넘어간다", "언제 넘어가?",
     "렌치는 확인됐고 약 4초 뒤 다음 단계로 넘어갑니다."),
    ("공구 상황: 렌치를 찾아야 한다", "앞에 뭐 있어?", "렌치가 보이지 않으니 렌치를 찾아 쥐세요."),
    ("공구 상황: 렌치가 보인다 — 아직 쥐지 않았다", "렌치 됐어?", "렌치가 보이니 손으로 쥐면 확인됩니다."),
    ("현재 진행 중인 단계: 4단계 「챔버 벤트」 (마지막 단계) — 아직 끝나지 않음", "다 했어?",
     "아니요, 4단계가 아직 진행 중입니다."),
    ("사실에 없음", "이 챔버 몇 년 됐어?", "그 정보는 확인할 수 없습니다."),
)
EXAMPLE_QUESTIONS = tuple(q for _, q, _ in EXAMPLES)

SYSTEM = (
    "너는 반도체 PECVD 장비 정비(PM) 작업자를 돕는 음성 비서다. "
    "작업자는 장갑을 끼고 화면을 보지 않는다. 반드시 한국어로 답한다.\n\n"
    "[규칙]\n"
    "- 아래 [사실] 에 적힌 것에만 근거해 답한다.\n"
    "- 무엇을 해야 하는지 묻는 질문에는 [사실] 의 「지금 할 일」을 그대로 전한다.\n"
    "- 끝났는지 묻는 질문은 「끝난 단계」와 「아직 끝나지 않음」 표기를 따른다.\n"
    "- [사실] 에 없는 것을 물으면 \"확인할 수 없습니다\" 라고 말한다. 「이 시스템이 모르는 것」도 그렇다.\n"
    "- 수치·부품명·상태를 추측하거나 지어내지 않는다.\n"
    "- 작업을 진행해도 되는지 묻는 질문에는 스스로 허가하지 않는다.\n"
    "- 「지금 할 일」에 없는 버튼을 누르라고 말하지 않는다.\n"
    "- 한 문장, 60자 안팎으로 답한다.\n\n"
    "[예시]\n"
    + "".join(f"- ({c}) 질문: {q} → {a}\n" for c, q, a in EXAMPLES)
)


def _options(num_predict=None):
    """질문과 예열이 **같은** 값을 쓴다 — num_ctx 가 다르면 다시 적재한다(R3 C2)."""
    return {"num_ctx": config.LLM_NUM_CTX,
            "num_predict": num_predict or config.LLM_NUM_PREDICT,
            "temperature": config.LLM_TEMPERATURE}


def ask(card, question, url=None, model=None, timeout=None, num_predict=None):
    """`(문장, 계측)` — 실패하면 `(None, 계측)`."""
    url = url or config.LLM_URL
    body = json.dumps({
        "model": model or config.LLM_MODEL,
        "system": SYSTEM,
        "prompt": f"{card}\n[질문] {question}",
        "stream": False,
        "think": False,
        "keep_alive": config.LLM_KEEP_ALIVE,
        "options": _options(num_predict),
    }, ensure_ascii=False).encode("utf-8")

    t0 = time.time()
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or config.LLM_TIMEOUT_SEC) as f:
            r = json.load(f)
    except Exception as e:                     # noqa: BLE001 — 무엇이 나도 데몬은 살아야 한다
        return None, {"LLM_ms": round((time.time() - t0) * 1000),
                      "LLM오류": f"{type(e).__name__}: {e}"[:120]}

    ns = 1e6
    m = {
        "LLM_ms": round((time.time() - t0) * 1000),
        "프롬프트토큰": r.get("prompt_eval_count", 0),
        "생성토큰": r.get("eval_count", 0),
        "적재_ms": round(r.get("load_duration", 0) / ns),
        "prefill_ms": round(r.get("prompt_eval_duration", 0) / ns),
    }
    text = (r.get("response") or "").strip()
    if not text:
        m["LLM오류"] = "빈 응답"
        return None, m
    return text, m


def warm(url=None, model=None, timeout=None):
    """모델을 올려 둔다 — 프롬프트 없는 요청은 적재만 한다(Ollama FAQ 「Preloading」). `(성공, 계측)`.

    🔴 타임아웃을 길게 — 끊으면 Ollama 가 적재를 취소한다(R3 C2 · 끊은 뒤 85초까지 미적재 확인).
    """
    url = url or config.LLM_URL
    body = json.dumps({"model": model or config.LLM_MODEL, "stream": False,
                       "keep_alive": config.LLM_KEEP_ALIVE, "options": _options()}).encode("utf-8")
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or config.LLM_WARM_TIMEOUT_SEC) as f:
            r = json.load(f)
    except Exception as e:                     # noqa: BLE001 — 무엇이 나도 데몬은 살아야 한다
        return False, {"예열_ms": round((time.time() - t0) * 1000),
                       "LLM오류": f"{type(e).__name__}: {e}"[:120]}
    return True, {"예열_ms": round((time.time() - t0) * 1000),
                  "적재_ms": round(r.get("load_duration", 0) / 1e6)}


class LlmClient:
    """LLM 가용성 — 예열 · 연속 실패 건너뛰기 · 다시 데우기(설계 2026-10-03 §4.2 · D1).

    상태는 셋이다.
      예열 전   ready=False — 묻지 않는다(콜드 모델은 데몬 요청으로 안 데워진다 · R3 C2)
      쓸 수 있음 — 묻는다
      건너뜀    연속 `fail_limit` 번 실패 뒤 `skip_sec` 초 — 묻지 않는다(질문마다 타임아웃까지 기다리지 않게)
    쓸 수 없을 때 호출부는 A 갈래로 답한다.
    🔑 `available()` 은 묻기만 하지 않는다 — 예열 전이고 데우는 중이 아니면 `skip_sec` 마다 다시 데운다
       (파이2 가 늦게 켜져도 사람이 손대지 않고 회복하게 · Review Focus 5).
    """

    def __init__(self, ask_fn=None, warm_fn=None, fail_limit=None, skip_sec=None,
                 clock=time.monotonic, log=None):
        self._ask = ask_fn or ask
        self._warm = warm_fn or warm
        self.fail_limit = fail_limit or config.LLM_FAIL_LIMIT
        self.skip_sec = config.LLM_SKIP_SEC if skip_sec is None else skip_sec
        self._clock = clock
        self._log = log or (lambda m: None)
        self._lock = threading.Lock()
        self.ready = False
        self.warming = False
        self.fails = 0
        self.skip_until = 0.0
        self._warm_end = None               # 마지막 예열이 끝난 시각(실패 포함)

    def start_warm(self, on_done=None):
        """배경에서 데운다 — 이미 데우는 중이면 아무것도 안 한다. 시작했으면 True."""
        with self._lock:
            if self.warming:
                return False
            self.warming = True

        def work():
            ok, m = self._warm()
            with self._lock:
                self.warming = False
                self._warm_end = self._clock()
                if ok:
                    self.ready = True
            self._log(f"LLM 예열 {'끝' if ok else '실패'} — {m}")
            if on_done:
                on_done(ok, m)

        threading.Thread(target=work, name="llm-warm", daemon=True).start()
        return True

    def available(self):
        now = self._clock()
        if not self.ready:
            if not self.warming and (self._warm_end is None or now - self._warm_end >= self.skip_sec):
                self.start_warm()
            return False
        return now >= self.skip_until

    def ask(self, card, question):
        if not self.available():
            return None, {"LLM오류": "예열 전" if not self.ready else "건너뜀(연속 실패)"}
        text, m = self._ask(card, question)
        if text is None:
            self.fails += 1
            if self.fails >= self.fail_limit:
                self.fails = 0
                self.skip_until = self._clock() + self.skip_sec
                self._log(f"🔴 LLM 이 {self.fail_limit}번 이어 실패했다 — "
                          f"{self.skip_sec:.0f}초 동안 건너뛰고 배경에서 다시 데운다")
                self.start_warm()
        else:
            self.fails = 0
        return text, m
