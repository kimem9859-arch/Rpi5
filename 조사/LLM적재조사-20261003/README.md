# LLM 매 요청 적재 시간 조사 (2026-10-03 · 세션 9f58cc82)

- **무엇**: 데운 상태에서도 매 요청 `load_duration`(적재)과 긴 prefill 이 나오는 원인(설계 2026-10-03 §4.2 · R3 I2). 계획서 Task 12 · 30분 상한.
- **조건**: 파이1 → 파이2 Ollama(HTTP · 유선) · 모델 `gemma4:e2b-it-qat` · `num_ctx 2048` · `keep_alive -1` · 실제 함수(`voice_llm.warm/ask` · `voice_card.build_card` · `llm_gate.STATE`). 같은 질문 3회 · 같은 카드 다른 질문 3회 · 다른 카드 같은 질문 2회.
- **원자료**: `probe.py` · `probe.json`(요청별 계측 · `/api/ps`) · `ollama_log.txt`(파이2 `journalctl -u ollama` 읽기 전용 · `ssh pi@192.168.1.12`).

## 관측
1. **모델은 계속 올라가 있었다** — 시작·예열·끝의 `/api/ps` 모두 같은 모델 · `expires_at` 무기한 · `context_length 2048`. 그런데도 **모든 요청에 「적재」 약 1.1초**가 붙었다.
2. **완전히 같은 프롬프트를 다시 보내면 prefill 이 크게 줄었다**(같은질문 2·3회째). 같은 카드라도 **질문이 바뀌면 prefill 이 처음과 같았다**(다른질문 · 다른카드 첫 회).
3. 파이2 로그: `forcing full prompt re-processing due to lack of cache data (likely due to SWA or hybrid/recurrent memory …)` · `n_swa = 512` · 체크포인트는 프롬프트 **끝**(pos_max = 전체 길이)에만 만들어지고, 같은 프롬프트일 때만 `restored context checkpoint`.
4. `prompt_eval_count` 는 캐시가 맞아도 전체 길이를 보고한다 — 캐시 여부는 `prefill_ms` 로만 보인다.

## 판정(계획서에 미리 정한 규칙대로)
| 관측 | 판정 |
|---|---|
| 적재 ≥ 0.5초가 매번 · 모델·expires_at 그대로 | **모델 재적재가 아니다.** 「적재」 표시의 정체는 로그에 드러나지 않음 — **원인 미규명** |
| 같은 질문 반복 때만 prefill 감소 | **프롬프트 캐시는 「완전 일치」에서만 돈다.** 질문만 바뀌어도 카드 전체를 다시 처리한다 — 원인 = Gemma 4 의 SWA(슬라이딩 창 주의)와 llama.cpp 체크포인트 방식(로그 문구) |
| 원인이 우리 요청인가 | **아니다** — 옵션(num_ctx 2048)은 예열·질문이 같고 재적재도 없다. 코드 변경 없음 |
| 원인이 파이2 설정인가 | **설정 하나로 풀린다는 근거를 못 찾았다.** 가능성 = SWA 전체 캐시(llama.cpp `--swa-full` 류)를 Ollama 가 노출하는지 — **미확인 · 사용자에게 제안만** |

## 남는 것
- 질문마다 prefill 이 카드 길이만큼 든다 → 지연은 Task 13 질문 세트로 잰다(p50·p95·p99 · 타임아웃 결정).
- 「적재」 약 1.1초의 정체 · SWA 전체 캐시 옵션 — ⏸(Ollama 소스·문서 확인 필요).
