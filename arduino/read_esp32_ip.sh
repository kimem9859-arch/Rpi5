#!/bin/bash
# ESP32 시리얼 로그에서 IP를 읽어 Demo/.camera_ip 에 기록한다.
#
# 사용: read_esp32_ip.sh [포트] [.camera_ip 경로] [타임아웃초]
#
# 펌웨어는 부팅·연결 시 다음 형식으로 출력한다:
#   WiFi connected. SSID: Jason  IP: 192.168.137.x
# 이미 연결된 상태라면 5초마다 나오는 상태 줄에서도 IP를 얻는다:
#   Status: WiFi=OK IP=192.168.137.x Stream=waiting
#
# ⚠️ 펌웨어를 굽지 않는다. 시리얼을 읽기만 한다(3~10초).

set -uo pipefail

PORT="${1:-$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -1)}"
IP_FILE="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/Demo/.camera_ip}"
TIMEOUT="${3:-25}"

if [ -z "$PORT" ]; then
  echo "❌ ESP32를 찾을 수 없습니다. USB 연결을 확인하세요."
  exit 1
fi

stty -F "$PORT" 115200 raw -echo 2>/dev/null

OLD_IP=$(cat "$IP_FILE" 2>/dev/null || echo "(없음)")

# 시리얼을 읽으며 IP 패턴을 찾는다. 연결 직후 로그와 주기 상태줄 둘 다 대응.
IP=$(timeout "$TIMEOUT" cat "$PORT" 2>/dev/null \
  | stdbuf -oL grep -m1 -oE 'IP[:=] ?[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')

if [ -z "$IP" ] || [ "$IP" = "0.0.0.0" ]; then
  echo "❌ IP를 읽지 못했습니다."
  echo "   • ESP32가 WiFi에 연결되지 않았을 수 있습니다(핫스팟 켜져 있나요?)"
  echo "   • ESP32의 RESET 버튼을 눌러 재부팅한 뒤 다시 실행해 보세요."
  echo "   현재 기록된 IP: $OLD_IP"
  exit 1
fi

echo "$IP" > "$IP_FILE"

echo "✅ ESP32 IP: $IP"
if [ "$OLD_IP" != "$IP" ]; then
  echo "   ($OLD_IP → $IP 로 갱신)"
else
  echo "   (변경 없음)"
fi

# 파이와 같은 서브넷인지 확인 — 다르면 TCP 직결이 불가능하다.
PI_IP=$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
if [ -n "$PI_IP" ]; then
  if [ "${PI_IP%.*}" = "${IP%.*}" ]; then
    echo "✅ 파이($PI_IP)와 같은 네트워크입니다."
  else
    echo
    echo "⚠️  파이($PI_IP)와 ESP32($IP)가 다른 네트워크입니다!"
    echo "    이대로는 카메라 연결이 안 됩니다."
    echo "    파이의 WiFi를 ESP32와 같은 것으로 바꾸세요:"
    echo "      nmcli connection up Jason"
  fi
fi
