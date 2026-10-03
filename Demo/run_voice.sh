#!/bin/bash
# 음성비서 데몬 실행.
#   ./run_voice.sh [--ip 주소] [--once]   한 번 띄운다(종전)
#   ./run_voice.sh --forever [인자…]       죽으면 3초 뒤 다시 띄운다 — run_demo.sh 가 이것으로 함께 띄운다
#                                          (설계 2026-10-03 §4.6 · D1′). 이미 다른 음성비서가 돌면(코드 3) 감시를 멈춘다.
#
# 🔴 STT 는 ~/env/tts/.venv (파이썬 3.13) 에 있다. Demo 의 .venv 가 아니다.
#    tool_worker 가 ~/env/rfenv 를 쓰는 것과 같은 방식이다.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PY="${SOP_VOICE_PY:-$HOME/env/tts/.venv/bin/python}"     # SOP_VOICE_PY = 시험용 대체

if [ "${1:-}" != "--forever" ]; then
    exec "$PY" voice_assistant.py "$@"
fi
shift
child=""
trap '[ -n "$child" ] && kill "$child" 2>/dev/null; exit 0' TERM INT HUP
while :; do
    "$PY" voice_assistant.py "$@" &
    child=$!
    wait "$child"
    code=$?
    child=""
    if [ "$code" -eq 3 ]; then
        echo "[$(date +%T)] 음성비서가 이미 다른 곳에서 돈다 — 감시를 끝낸다"
        exit 0
    fi
    echo "[$(date +%T)] 🔴 음성비서가 끝났다(코드 $code) — 3초 뒤 다시 띄운다"
    sleep 3 &
    wait $!
done
