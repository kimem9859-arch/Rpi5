#!/usr/bin/env bash
# SOP 가디언 Demo 실행 런처 (바탕화면 바로가기용)
# main.py 는 같은 폴더의 모듈을 상대 import 하므로 반드시 Demo 디렉터리에서 실행한다.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

echo "=== SOP 가디언 Demo 실행 ==="
echo "경로: $(pwd)"
echo

# 🔑 음성비서를 함께 띄운다(설계 2026-10-03 §4.6 · D1′) — 죽으면 run_voice.sh 가 다시 띄운다.
#    끄려면 SOP_VOICE=0 ./run_demo.sh · 로그 = logs/voice_<시각>.log(「준비 상태」 줄을 본다)
VOICE_PID=""
stop_voice() {
    if [ -n "$VOICE_PID" ]; then
        kill "$VOICE_PID" 2>/dev/null
        VOICE_PID=""
    fi
}
trap stop_voice EXIT
if [ "${SOP_VOICE:-1}" != "0" ]; then
    mkdir -p logs
    VLOG="logs/voice_$(date +%Y%m%d_%H%M%S).log"
    ./run_voice.sh --forever >>"$VLOG" 2>&1 &
    VOICE_PID=$!
    echo "음성비서 함께 시작 (로그 = $VLOG)"
fi

python3 main.py
status=$?
stop_voice              # 🔴 오류로 창을 붙잡아 둘 때도 음성비서는 먼저 끈다

echo
echo "=== 종료 (exit code: $status) ==="

# 🔴 정상 종료면 **창도 함께 닫는다** — 시연 중에 빈 터미널이 남지 않게.
#    오류로 죽었을 때만 붙잡아 둔다. 그때는 여기가 원인을 볼 유일한 자리다
#    (GUI 로그는 logs/ 에 남지만 파이썬 트레이스백은 이 창에만 나온다).
if [ "$status" -ne 0 ]; then
    echo "창을 닫으려면 Enter 를 누르세요."
    read -r _
fi
exit "$status"
