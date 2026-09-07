#!/usr/bin/env bash
# 음성비서 시연 촬영 런처 (바탕화면 바로가기용)
#
# 🔴 시스템 python3 로 돈다 — cv2 가 거기 있다. 음성비서만 ~/env/tts/.venv 로
#    따로 뜬다(sherpa-onnx 가 그쪽에만 있다).
# 산출물 = Demo/voice/촬영본/<시각>/ (영상 3벌 + 계측.jsonl + 요약.json)
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1     # → Demo

SEC="${1:-}"
if [ -z "$SEC" ]; then
  echo "촬영 길이를 초 단위로 입력하세요 (엔터 = 90초)"
  read -rp "  초: " SEC
  SEC="${SEC:-90}"
fi

echo
echo "════════════════════════════════════════════"
echo "  음성비서 시연 촬영 — ${SEC}초"
echo "════════════════════════════════════════════"
echo "  ① 렌치를 글라스 카메라 앞에      → 보라 박스"
echo "  ② \"가디언\" → 띠링 → \"앞에 보이는 게 뭐야?\""
echo "  ③ 드라이버로 교체                → 시안 박스"
echo "  ④ ② 반복"
echo
echo "  🔑 마이크는 글라스(ESP32), 녹음은 웹캠 마이크입니다."
echo "  🔴 공구는 한 번에 하나씩 보여주세요."
echo

# 🔴 시연 촬영 한정으로 공구 임계를 낮춘다(기본 0.65 → 0.30).
#    공구가 카메라에서 멀면 0.65 를 못 넘는다(2026-09-07 실측: 최고 0.44).
#    런타임 기본값은 안 바뀐다 — 요약.json 에 쓴 값이 함께 적힌다.
# 🔑 촬영 전에 3인칭 구도를 10초 보여준다(촬영 중에는 ffmpeg 이 장치를 독점한다).
python3 voice/record_voice_demo.py --sec "$SEC" --conf 0.30 --check-webcam 10 --preview
status=$?

echo
if [ "$status" -ne 0 ]; then
  echo "🔴 오류로 끝났습니다 (코드 $status). 위 메시지를 확인하세요."
fi
read -rp "Enter 를 누르면 닫힙니다..."
