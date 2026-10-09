# 백업한 도구 — 음성 시연 촬영 (2026-10-09)

> 쓰지 않는 도구를 지우지 않고 여기 모았다(사용자 「안 써」 · 상위 sop-project `docs/superpowers/specs/2026-10-09-공구구간-음성안내-design.md` D6).
> 🔴 **여기서는 실행되지 않는다** — 원래 자리(`Demo/voice/`)의 모듈·config 를 상대 경로로 불러 쓴다. 쓰려면 원래 자리로 되돌린다.
> 되돌리기(Rpi5 저장소 뿌리에서) = `git mv 백업/음성촬영-20261009/<파일> Demo/voice/<파일>` · 이력은 `git log --follow` 로 이어진다.

| 파일 | 원래 자리 | 왜 뺐나 | 되돌릴 때 같이 할 것 |
| --- | --- | --- | --- |
| `record_voice_demo.py` | `Demo/voice/` | 콘솔 없이 카메라·공구·음성만 찍는 음성 시연 촬영 — 지금 영상 계획(폰 촬영 + 후처리 합성)에서 안 쓴다 · **옛 CPU 공구 워커(`tool_worker.py` · `tool_v3.pt`)를 직접 띄워** 시연 모델(NPU `T-full-base`)과 다르게 찍힌다 · 웹캠 제거로 영상용 녹음 수단도 없다 | 공구를 `tool_gate.create_tool_gate()`(시연과 같은 갈래)로 바꾼다 · 아래 시험 되돌림 |
| `run_record.sh` | `Demo/voice/` | 위 도구의 런처(공구 문턱 0.30 으로 낮춤) | 바탕화면 바로가기 `~/Desktop/음성비서-시연촬영.desktop` 이 이 경로를 가리켰다 |
| `test_record_voice_demo.py` | `Demo/selftest/test_voice_tools.py` 안의 두 함수 | 위 도구의 자가 테스트(요약 집계 · 음성비서·GUI 확인) | 두 함수를 `test_voice_tools.py` 로 되돌린다 |
