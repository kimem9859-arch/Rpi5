#!/bin/bash
# ESP32 IP 갱신 — 펌웨어를 굽지 않는다. 시리얼만 읽어 .camera_ip 를 갱신한다(수 초).
#
# 언제 쓰나: 장소·핫스팟이 바뀌어 ESP32의 IP가 달라졌을 때.
#          (펌웨어가 WiFi를 자동으로 잡으므로 재업로드는 불필요하다.)

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "══════════════════════════════════════════════"
echo "  ESP32 IP 갱신"
echo "══════════════════════════════════════════════"
echo
echo "📡 시리얼에서 IP 읽는 중... (최대 25초)"
echo "   IP가 안 잡히면 ESP32의 RESET 버튼을 눌러보세요."
echo

"$DIR/read_esp32_ip.sh"

echo
read -rp "Enter 키를 누르면 닫힙니다..."
