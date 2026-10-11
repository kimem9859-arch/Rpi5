#!/bin/bash
# ESP32 시리얼 로그에서 IP를 읽어 Demo/.camera_ip 에 기록한다.
#
# 사용: read_esp32_ip.sh [포트] [.camera_ip 경로] [타임아웃초]
#
# 펌웨어는 부팅·연결 시 다음 형식으로 출력한다:
#   WiFi connected. SSID: <데스크톱 핫스팟 SSID>  IP: 192.168.137.x
# 이미 연결된 상태라면 5초마다 나오는 상태 줄에서도 IP를 얻는다:
#   Status: WiFi=OK IP=192.168.137.x Stream=waiting
#
# ⚠️ 펌웨어를 굽지 않는다. 시리얼을 읽기만 한다(3~10초).

set -uo pipefail

MAIN_SN="68:EE:8F:4F:5D:38"                          # 메인 안경(프레임 안) — 번호 정본 = Rpi5/CLAUDE.md 「ESP32 실HW 함정」
BYID_DIR="${ESP32_BYID_DIR:-/dev/serial/by-id}"      # 시험에서만 바꾼다
# 🔴 포트를 안 주면 메인 안경을 시리얼번호로만 찾는다 — 「첫 ttyACM」은 인터락 아두이노일 수 있다(25초 동안 인터락을
#    읽고 엉뚱한 안내를 냈다 · 시연 중이면 ACK 도 가로챈다). 다른 보드는 포트를 직접 준다.
if [ -n "${1:-}" ]; then
  PORT="$1"
else
  PORT=$(ls "$BYID_DIR"/*"_${MAIN_SN}-if"* 2>/dev/null | head -1)
  if [ -z "$PORT" ]; then
    echo "❌ 메인 안경(…5D:38)을 USB 로 찾지 못했습니다 — 안경을 USB-C 로 파이에 꽂으세요(배터리만으로는 안 보인다)."
    echo "   다른 보드는 포트를 직접 주세요: $0 /dev/serial/by-id/<그 보드>"
    exit 1
  fi
fi
IP_FILE="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/Demo/.camera_ip}"
TIMEOUT="${3:-25}"

if [ -z "$PORT" ]; then
  echo "❌ ESP32를 찾을 수 없습니다. USB 연결을 확인하세요."
  exit 1
fi

stty -F "$PORT" 115200 raw -echo 2>/dev/null

OLD_IP=$(cat "$IP_FILE" 2>/dev/null || echo "(없음)")

# 시리얼을 읽으며 IP 패턴을 찾는다. 연결 직후 로그와 주기 상태줄 둘 다 대응.
# 🔑 읽은 줄은 잠시 남겨 부팅 로그의 「Camera OK jpeg_quality=… fb_count=…」(굽은 값)를 함께 보인다(대처 V20)
SERIAL_LOG=$(mktemp)
IP=$(timeout "$TIMEOUT" cat "$PORT" 2>/dev/null \
  | tee "$SERIAL_LOG" \
  | stdbuf -oL grep -m1 -oE 'IP[:=] ?[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')
CAM_LINE=$(grep -a "Camera OK" "$SERIAL_LOG" 2>/dev/null | tail -1 | tr -d '\r')
rm -f "$SERIAL_LOG"

if [ -z "$IP" ] || [ "$IP" = "0.0.0.0" ]; then
  echo "❌ IP를 읽지 못했습니다."
  echo "   • ESP32가 WiFi에 연결되지 않았을 수 있습니다(핫스팟 켜져 있나요?)"
  echo "   • ESP32의 RESET 버튼을 눌러 재부팅한 뒤 다시 실행해 보세요."
  echo "   현재 기록된 IP: $OLD_IP"
  exit 1
fi

echo "$IP" > "$IP_FILE"

echo "✅ ESP32 IP: $IP"
if [ -n "$CAM_LINE" ]; then
  echo "📷 부팅 카메라 설정: $CAM_LINE"
else
  echo "📷 부팅 줄 없음 — 이미 켜져 있던 보드다(굽은 값을 보려면 RESET 뒤 다시 · 굽기 직후에는 나온다)"
fi
if [ "$OLD_IP" != "$IP" ]; then
  echo "   ($OLD_IP → $IP 로 갱신)"
else
  echo "   (변경 없음)"
fi

# ESP32 로 실제로 나가는 경로가 있는지 커널에 묻는다 — 인터페이스를 고정하지 않는다.
# 🔴 2026-09-06 이전에는 **wlan0 과 대역을 비교**했는데, ESP32 가 공유기(eth0 대역)로
#    옮겨간 뒤로는 **정상인데도 「다른 네트워크」라고 오경고**하고 엉뚱한 조치
#    (`nmcli connection up <데스크톱 핫스팟 SSID>`)를 안내했다. 파이는 무선·유선 두 길을 동시에
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
