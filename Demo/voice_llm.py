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
import time
import urllib.error
import urllib.request

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

import config  # noqa: E402

# 🔑 규칙마다 막는 것이 있다(§10.53-(4)):
#      ①수치 지어냄·②모르는 상태를 안다고 함  ← 사실에만 근거 / 지어내지 않는다
#      ⑤상태 모르면서 허가함                  ← 스스로 허가하지 않는다
#      ⑥묻지 않은 위험 행동 제안              ← 두 문장을 넘기지 않는다
SYSTEM = (
    "너는 반도체 PECVD 장비 정비(PM) 작업자를 돕는 음성 비서다. "
    "작업자는 장갑을 끼고 화면을 보지 않는다. 반드시 한국어로 답한다.\n\n"
    "[규칙]\n"
    "- 아래 [사실] 에 적힌 것에만 근거해 답한다.\n"
    "- [사실] 에 없는 것을 물으면 \"확인할 수 없습니다\" 라고 말한다.\n"
    "- 수치·부품명·상태를 추측하거나 지어내지 않는다.\n"
    "- 작업을 진행해도 되는지 묻는 질문에는 스스로 허가하지 않는다.\n"
    "- 두 문장을 넘기지 않는다."
)


def ask(card, question, url=None, model=None, timeout=None, num_predict=None):
    """`(문장, 계측)` — 실패하면 `(None, 계측)`."""
    url = url or config.LLM_URL
    body = json.dumps({
        "model": model or config.LLM_MODEL,
        "system": SYSTEM,
        "prompt": f"{card}\n[질문] {question}",
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": config.LLM_NUM_CTX,
            "num_predict": num_predict or config.LLM_NUM_PREDICT,
            "temperature": 0.0,
        },
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
