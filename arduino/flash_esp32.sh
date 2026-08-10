#!/bin/bash
# ESP32-S3(XIAO) 카메라 펌웨어 굽기 — 바탕화면 아이콘에서 호출.
#
#   포트 자동 탐지 → 컴파일 → 업로드 → 부팅 로그에서 IP를 읽어 .camera_ip 자동 기록
#
# 펌웨어는 WiFi를 스캔해 wifi_credentials.h의 배열 순서(Eung Min → Jason)대로 연결한다.
# 따라서 장소가 바뀌어도 다시 구울 필요가 없다. IP만 바뀌면 update_ip.sh를 쓴다.

set -uo pipefail

SKETCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/camera_stream_tcp"
CAMERA_IP_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/Demo/.camera_ip"
# ⚠️ PSRAM=opi 필수 — 빠뜨리면 카메라 프레임 버퍼 malloc 실패로 부팅 루프에 빠진다
#    (cam_dma_config: frame buffer malloc failed → Camera init failed, restarting)
FQBN="esp32:esp32:XIAO_ESP32S3:PSRAM=opi"
ARDUINO_CLI="${HOME}/bin/arduino-cli"

echo "══════════════════════════════════════════════"
echo "  ESP32 카메라 펌웨어 굽기"
echo "══════════════════════════════════════════════"
echo

fail() { echo; echo "❌ $1"; echo; read -rp "Enter 키를 누르면 닫힙니다..."; exit 1; }

# ── 1. 자격증명 확인 ──────────────────────────────
CRED="$(dirname "$SKETCH_DIR")/wifi_credentials.h"
[ -f "$CRED" ] || fail "wifi_credentials.h 가 없습니다.
   $CRED 를 만들고 SSID·비밀번호를 넣으세요."
# 주석(//)은 제외하고 검사한다 — 사용법 안내 주석의 "<비밀번호>" 를
# 자리표시자로 오인해 굽기가 막히는 일이 있었다(2026-08-10).
if grep -v '^[[:space:]]*//' "$CRED" | grep -q '여기에\|<.*비밀번호>'; then
  fail "wifi_credentials.h 에 비밀번호가 아직 안 들어갔습니다."
fi

# ── 2. 포트 탐지 ─────────────────────────────────
PORT=$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null | head -1)
[ -n "$PORT" ] || fail "ESP32를 찾을 수 없습니다.
   USB 케이블로 라즈베리파이에 연결했는지 확인하세요."
echo "🔌 포트: $PORT"

# ── 3. 컴파일 ────────────────────────────────────
echo
echo "🔨 컴파일 중... (첫 실행은 몇 분 걸립니다)"
"$ARDUINO_CLI" compile --fqbn "$FQBN" "$SKETCH_DIR" || fail "컴파일 실패 (위 오류 참조)"
echo "✅ 컴파일 완료"

# ── 4. 업로드 ────────────────────────────────────
echo
echo "📤 업로드 중..."
"$ARDUINO_CLI" upload -p "$PORT" --fqbn "$FQBN" "$SKETCH_DIR" || fail "업로드 실패
   ESP32의 BOOT 버튼을 누른 채 RESET을 눌렀다 떼고 다시 시도해 보세요."
echo "✅ 업로드 완료"

# ── 5. 부팅 로그에서 IP 회수 ──────────────────────
echo
echo "📡 WiFi 연결 대기 중... (최대 40초)"
echo "   펌웨어가 Jason → Eung Min 순서로 잡습니다."
echo
"$(dirname "${BASH_SOURCE[0]}")/read_esp32_ip.sh" "$PORT" "$CAMERA_IP_FILE" 40

echo
read -rp "Enter 키를 누르면 닫힙니다..."
