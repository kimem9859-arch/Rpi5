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

# ESP32 로 실제로 나가는 경로가 있는지 커널에 묻는다 — 인터페이스를 고정하지 않는다.
# 🔴 2026-09-06 이전에는 **wlan0 과 대역을 비교**했는데, ESP32 가 공유기(eth0 대역)로
#    옮겨간 뒤로는 **정상인데도 「다른 네트워크」라고 오경고**하고 엉뚱한 조치
#    (`nmcli connection up Jason`)를 안내했다. 파이는 무선·유선 두 길을 동시에
#    쓰므로 «어느 인터페이스냐»가 아니라 «경로가 있느냐»를 물어야 한다.
# 🔴 「경로가 있느냐」로는 못 가른다 — 기본 게이트웨이가 있으면 커널은 **어떤 IP에도**
#    경로를 내준다(2026-09-06 검증에서 실제로 물렸다: 203.0.113.99 에도 경로 있음).
#    갈라 주는 것은 **`via` 의 유무**다.
#      같은 망      → "192.168.1.19 dev eth0 src ..."            (via 없음 = 직결)
#      밖으로 나감  → "203.0.113.99 via 192.168.45.1 dev wlan0 ..." (via 있음)
ROUTE=$(ip -4 -o route get "$IP" 2>/dev/null)
PI_IP=$(echo "$ROUTE" | grep -oE 'src [0-9.]+' | awk '{print $2}')
IFACE=$(echo "$ROUTE" | grep -oE 'dev [^ ]+'   | awk '{print $2}')
if [ -n "$PI_IP" ] && ! echo "$ROUTE" | grep -q ' via '; then
  echo "✅ 파이($PI_IP, $IFACE)와 ESP32($IP)가 같은 네트워크입니다."
else
  echo
  echo "⚠️  파이와 ESP32($IP)가 같은 네트워크가 아닙니다!"
  echo "    이대로는 카메라 연결이 안 됩니다(게이트웨이 밖으로 나가려 합니다)."
  echo "    ESP32가 붙은 망에 파이도 연결되어 있는지 확인하세요"
  echo "    — 공유기 경유라면 랜선, 핫스팟 경유라면 같은 SSID."
fi
