#!/bin/bash
# 안경 ESP32-S3(XIAO) 펌웨어 굽기 — glass_voice(카메라 + 마이크 + 스피커 통합 · 남길 펌웨어). 바탕화면 아이콘에서도 부른다.
#
#   사용: flash_esp32.sh [main|sub] [--no-backup]      (기본 = main)
#   순서: 자격증명 확인 → 시리얼번호로 포트 → 8MB 전체 백업 + 그 자리 대조 → 컴파일+업로드 → 부팅 로그 IP
#
# 🔴 보드는 시리얼번호로 고른다 — ttyACM 번호는 꽂는 순서로 바뀌고, 쓰는 보드와 마지막 바이트만 다른 폐기 보드가 둘이다
#    (메인 …5D:38 ↔ 폐기 …5D:6C · 서브 …5E:58 ↔ 폐기 …5E:40). 잘못 구우면 다른 작업의 펌웨어가 통째로 날아간다.
#    번호 정본 = Rpi5/CLAUDE.md 「ESP32 실HW 함정」 · 되돌리기 = 아래 4단계가 남긴 백업(~/lab/esp32-link/RESTORE.md 길 A).
# 🔑 2026-10-09 — 종전에는 camera_stream_tcp 를 「첫 번째 포트」에 구웠다(남길 펌웨어는 glass_voice · 실콘솔 plan Task 11).

set -uo pipefail

BOARD="main"
BACKUP=1
for a in "$@"; do
  case "$a" in
    main|sub) BOARD="$a" ;;
    --no-backup) BACKUP=0 ;;
    *) echo "사용: $0 [main|sub] [--no-backup]"; exit 2 ;;
  esac
done
case "$BOARD" in
  main) SN="68:EE:8F:4F:5D:38" ;;   # 메인 — 안경 프레임 안
  sub)  SN="3C:0F:02:DD:5E:58" ;;   # 서브 — 브레드보드
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKETCH_DIR="$HERE/glass_voice"
CAMERA_IP_FILE="$(cd "$HERE/.." && pwd)/Demo/.camera_ip"
BACKUP_DIR="$HOME/lab/esp32-link"
# ⚠️ PSRAM=opi 필수 — 빠뜨리면 카메라 프레임 버퍼 malloc 실패로 부팅 루프에 빠진다
FQBN="esp32:esp32:XIAO_ESP32S3:PSRAM=opi"
ARDUINO_CLI="${HOME}/bin/arduino-cli"

echo "══════════════════════════════════════════════"
echo "  안경 펌웨어 굽기 — glass_voice → $BOARD ($SN)"
echo "══════════════════════════════════════════════"
echo

fail() { echo; echo "❌ $1"; echo; [ -t 0 ] && read -rp "Enter 키를 누르면 닫힙니다..."; exit 1; }

# ── 1. 자격증명 확인 ──────────────────────────────
CRED="$HERE/wifi_credentials.h"
[ -f "$CRED" ] || fail "wifi_credentials.h 가 없습니다.
   $CRED 를 만들고 SSID·비밀번호를 넣으세요."
# 주석(//)은 제외하고 검사한다 — 사용법 안내 주석의 "<비밀번호>" 를 자리표시자로 오인해 굽기가 막히는 일이 있었다(2026-08-10).
if grep -v '^[[:space:]]*//' "$CRED" | grep -q '여기에\|<.*비밀번호>'; then
  fail "wifi_credentials.h 에 비밀번호가 아직 안 들어갔습니다."
fi

# ── 2. 시리얼번호로 포트 ─────────────────────────
PORT=$(python3 - "$SN" <<'EOF'
import sys
from serial.tools import list_ports
hits = [p.device for p in list_ports.comports() if (p.serial_number or "").upper() == sys.argv[1].upper()]
print(hits[0] if len(hits) == 1 else "")
EOF
)
if [ -z "$PORT" ]; then
  echo "지금 꽂힌 USB 시리얼:"
  python3 -c "from serial.tools import list_ports; [print('  ', p.device, p.serial_number) for p in list_ports.comports() if p.vid]"
  fail "$BOARD 보드($SN)를 찾을 수 없습니다 — USB 로 파이에 연결했는지 확인하세요(배터리만으로는 안 보인다)."
fi
echo "🔌 $BOARD = $PORT (시리얼번호 $SN 일치)"

# ── 3. 8MB 전체 백업 + 그 자리 대조 ─────────────────
#    🔴 --no-stub — 이 파이 + USB-JTAG 에서 스텁을 쓰면 「Packet content transfer stopped」로 죽는다(RESTORE.md).
#    🔑 대조는 백업 직후 리셋 없이 한다 — 펌웨어가 돌면 NVS(와이파이 기록)를 고쳐 써 전체 대조가 어긋난다(10/8 공장 백업 note).
if [ "$BACKUP" = "1" ]; then
  TAG=$(echo "$SN" | tr -d ':' | tail -c 5)
  BIN="$BACKUP_DIR/${BOARD}_${TAG}_full_$(date +%Y%m%d_%H%M%S).bin"
  mkdir -p "$BACKUP_DIR"
  echo
  echo "💾 백업 중 → $BIN (몇 분 걸린다)"
  esptool --port "$PORT" --no-stub --after no-reset read-flash 0 0x800000 "$BIN" || fail "백업 실패 — 굽지 않는다."
  esptool --port "$PORT" --no-stub --after no-reset verify-flash 0 "$BIN" || fail "백업 대조 실패 — 굽지 않는다."
  md5sum "$BIN" > "$BIN.md5"
  echo "✅ 백업·대조 통과 · $(cut -c1-32 "$BIN.md5")"
  echo "   되돌리기: esptool --port $PORT --no-stub write-flash 0 $BIN"
else
  echo "⚠️ 백업을 건너뛴다(--no-backup)"
fi

# ── 4. 컴파일 + 업로드 ──────────────────────────────
#    🔑 compile --upload 로 한 번에 — upload 만 하면 캐시된 옛 바이너리가 조용히 올라갈 수 있다(glass_voice 머리말).
echo
echo "🔨 컴파일 + 업로드 중..."
"$ARDUINO_CLI" compile --upload -p "$PORT" --fqbn "$FQBN" "$SKETCH_DIR" || fail "컴파일·업로드 실패 (위 오류 참조)
   ESP32의 BOOT 버튼을 누른 채 RESET을 눌렀다 떼고 다시 시도해 보세요."
echo "✅ 업로드 완료 · 소스 $(git -C "$HERE" log -1 --format='%h %ad' --date=format:'%m-%d %H:%M' -- glass_voice/glass_voice.ino)"

# ── 5. 부팅 로그에서 IP ─────────────────────────────
#    메인만 .camera_ip 에 적는다 — 데모·음성비서는 그 주소로 붙는다(서브를 쓸 때만 손으로 바꾼다 · Rpi5/CLAUDE.md).
echo
echo "📡 WiFi 연결 대기 중... (최대 40초)"
if [ "$BOARD" = "main" ]; then
  cp -p "$CAMERA_IP_FILE" "$BACKUP_DIR/camera_ip.bak-$(date +%Y%m%d_%H%M%S)" 2>/dev/null
  "$HERE/read_esp32_ip.sh" "$PORT" "$CAMERA_IP_FILE" 40
else
  TMP=$(mktemp)
  "$HERE/read_esp32_ip.sh" "$PORT" "$TMP" 40
  echo "서브 IP = $(cat "$TMP") · .camera_ip 는 그대로 둔다"
  rm -f "$TMP"
fi

echo
[ -t 0 ] && read -rp "Enter 키를 누르면 닫힙니다..."
exit 0
