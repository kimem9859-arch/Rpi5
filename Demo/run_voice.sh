#!/bin/bash
# 음성비서 데몬 실행 — GUI(run_demo.sh)와 별개로 띄운다.
#
# 🔴 STT 는 ~/env/tts/.venv (파이썬 3.13) 에 있다. Demo 의 .venv 가 아니다.
#    tool_worker 가 ~/env/rfenv 를 쓰는 것과 같은 방식이다.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec "$HOME/env/tts/.venv/bin/python" voice_assistant.py "$@"
