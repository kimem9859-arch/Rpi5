#!/bin/bash
# 안경 ESP32-S3(XIAO) 펌웨어 굽기 — glass_voice(카메라 + 마이크 + 스피커 통합 · 남길 펌웨어). 바탕화면 아이콘에서도 부른다.
#
#   사용: flash_esp32.sh [main|sub] [--no-backup] [--jpeg-quality 10~63] [--fb-count 1~4] [--build-only]   (기본 = main)
#         --jpeg-quality · --fb-count = 빌드 옵션(옵션 없음 = 지금 펌웨어 품질 15 · 버퍼 2 · 학교 방문 준비 설계 §4.2)
#         --build-only = 컴파일만(보드 · 포트 · 백업 · 업로드 없음 · .bin md5 출력 · 집에서 변형 확인용)
#   순서: 자격증명 → 시리얼번호로 포트 → 컴파일 → 8MB 전체 백업 + 그 자리 대조 → 업로드 → 부팅 로그 IP
#
# 🔴 보드는 시리얼번호로 고른다 — ttyACM 번호는 꽂는 순서로 바뀌고, 쓰는 보드와 마지막 바이트만 다른 폐기 보드가 둘이다
#    (메인 …5D:38 ↔ 폐기 …5D:6C · 서브 …5E:58 ↔ 폐기 …5E:40). 잘못 구우면 다른 작업의 펌웨어가 통째로 날아간다.
#    번호 정본 = Rpi5/CLAUDE.md 「ESP32 실HW 함정」 · 되돌리기 = 4단계(백업)가 남긴 파일(~/lab/esp32-link/RESTORE.md 길 A).
# 🔑 포트는 /dev/serial/by-id 의 시리얼번호 이름을 끝까지 쓴다 — 백업·대조·업로드가 보드를 리셋해 USB 가 다시 잡히면
#    ttyACM 번호가 바뀔 수 있다(그 사이 다른 보드가 그 번호를 집으면 엉뚱한 보드에 굽는다 · 최종 리뷰 2026-10-09).
# 🔑 2026-10-09 — 종전에는 camera_stream_tcp 를 「첫 번째 포트」에 구웠다(남길 펌웨어는 glass_voice · 실콘솔 plan Task 11).

set -uo pipefail

BOARD="main"
BACKUP=1
BUILD_ONLY=0
JQ=""
FB=""
usage() { echo "사용: $0 [main|sub] [--no-backup] [--jpeg-quality 10~63] [--fb-count 1~4] [--build-only]"; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    main|sub) BOARD="$1" ;;
    --no-backup) BACKUP=0 ;;
    --build-only) BUILD_ONLY=1 ;;
    --jpeg-quality) [ $# -ge 2 ] || usage; JQ="$2"; shift ;;
    --fb-count) [ $# -ge 2 ] || usage; FB="$2"; shift ;;
    *) usage ;;
  esac
  shift
done
# 🔴 범위 밖 · 글자는 컴파일 전에 멈춘다 — 보드에 아무것도 하지 않는다(Review Focus 5)
isnum() { [[ "$1" =~ ^[0-9]+$ ]]; }
if [ -n "$JQ" ] && ! { isnum "$JQ" && [ "$JQ" -ge 10 ] && [ "$JQ" -le 63 ]; }; then echo "❌ --jpeg-quality 는 10~63 정수 — 「$JQ」"; usage; fi
if [ -n "$FB" ] && ! { isnum "$FB" && [ "$FB" -ge 1 ] && [ "$FB" -le 4 ]; }; then echo "❌ --fb-count 는 1~4 정수 — 「$FB」"; usage; fi
EXTRA=()
EXTRA_UP=()
OPT_NOTE="없음(지금 펌웨어 · 품질 15 · 버퍼 2)"
if [ -n "$JQ$FB" ]; then
  # --clean — 빌드 속성이 바뀌어도 캐시된 옛 오브젝트가 섞이지 않게
  EXTRA=(--clean --build-property "compiler.cpp.extra_flags=-DGLASS_JPEG_QUALITY=${JQ:-15} -DGLASS_FB_COUNT=${FB:-2}")
  # 업로드는 --clean 없이 — 3단계가 같은 속성으로 이미 빌드했다(빌드 기록이 같아 같은 바이너리 · 변형마다 몇 분 아낀다)
  EXTRA_UP=(--build-property "compiler.cpp.extra_flags=-DGLASS_JPEG_QUALITY=${JQ:-15} -DGLASS_FB_COUNT=${FB:-2}")
  OPT_NOTE="품질 ${JQ:-15} · 버퍼 ${FB:-2}"
fi
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
ARDUINO_CLI="${ARDUINO_CLI_OVERRIDE:-${HOME}/bin/arduino-cli}"   # OVERRIDE = 시험에서만(기록하는 가짜)
ESPTOOL="${ESPTOOL_OVERRIDE:-esptool}"

echo "══════════════════════════════════════════════"
echo "  안경 펌웨어 굽기 — glass_voice → $BOARD ($SN)"
echo "  빌드 옵션: $OPT_NOTE$([ "$BUILD_ONLY" = 1 ] && echo ' · 컴파일만(--build-only)')"
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

# ── 1-2. 컴파일만(--build-only) — 보드 · 포트 · 백업 · 업로드 없이 · 집에서 변형이 빌드되는지 본다 ──
if [ "$BUILD_ONLY" = "1" ]; then
  OUT="${FLASH_BUILD_DIR:-$BACKUP_DIR/build}/q${JQ:-15}_fb${FB:-2}"
  mkdir -p "$OUT"
  echo "🔨 컴파일만 · 출력 $OUT"
  "$ARDUINO_CLI" compile --fqbn "$FQBN" "${EXTRA[@]}" --output-dir "$OUT" "$SKETCH_DIR" || fail "컴파일 실패 (위 오류 참조)"
  BINF="$OUT/glass_voice.ino.bin"
  if [ -f "$BINF" ]; then echo "✅ 컴파일 통과 · $(md5sum "$BINF" | cut -c1-32) · $(stat -c %s "$BINF") 바이트"; else echo "✅ 컴파일 통과"; fi
  exit 0
fi

# ── 2. 시리얼번호로 포트 ─────────────────────────
#    by-id 이름 = …_<시리얼번호>-if00 — 정확히 하나일 때만 쓴다
mapfile -t HITS < <(ls /dev/serial/by-id/ 2>/dev/null | grep -F "_${SN}-if" || true)
if [ "${#HITS[@]}" -ne 1 ]; then
  echo "지금 꽂힌 USB 시리얼(by-id):"
  ls -l /dev/serial/by-id/ 2>/dev/null | sed -n '2,$p' | sed 's/^/   /'
  fail "$BOARD 보드($SN)를 정확히 하나 찾지 못했습니다(${#HITS[@]}개) — USB 로 파이에 연결했는지 확인하세요(배터리만으로는 안 보인다)."
fi
PORT="/dev/serial/by-id/${HITS[0]}"
echo "🔌 $BOARD = $PORT → $(readlink -f "$PORT")"

# ── 3. 컴파일 먼저 — 몇 분 걸리는 백업 전에 소스 오류를 안다 ─────────────
DIRTY=""
git -C "$HERE" diff --quiet HEAD -- glass_voice 2>/dev/null || DIRTY=" (⚠️ 커밋 안 된 수정 포함)"
SRC="$(git -C "$HERE" log -1 --format='%h %ad' --date=format:'%m-%d %H:%M' -- glass_voice/glass_voice.ino)$DIRTY"
echo
echo "🔨 컴파일 중... · 소스 $SRC"
"$ARDUINO_CLI" compile --fqbn "$FQBN" "${EXTRA[@]}" "$SKETCH_DIR" || fail "컴파일 실패 (위 오류 참조) — 보드에는 아무것도 하지 않았다."
echo "✅ 컴파일 통과"
mkdir -p "$BACKUP_DIR"

# ── 4. 8MB 전체 백업 + 그 자리 대조 ─────────────────
#    🔴 --no-stub — 이 파이 + USB-JTAG 에서 스텁을 쓰면 「Packet content transfer stopped」로 죽는다(RESTORE.md).
#    🔑 대조는 백업 직후 리셋 없이 한다 — 펌웨어가 돌면 NVS(와이파이 기록)를 고쳐 써 전체 대조가 어긋난다(10/8 공장 백업 note).
if [ "$BACKUP" = "1" ]; then
  TAG=$(echo "$SN" | tr -d ':' | tail -c 5)
  BIN="$BACKUP_DIR/${BOARD}_${TAG}_full_$(date +%Y%m%d_%H%M%S).bin"
  STUCK="   보드가 다운로드 모드에 머물러 펌웨어가 안 돈다 — USB(배터리)를 뺐다 꽂으면 원래 펌웨어로 돌아온다."
  echo
  echo "💾 백업 중 → $BIN (몇 분 걸린다)"
  "$ESPTOOL" --port "$PORT" --no-stub --after no-reset read-flash 0 0x800000 "$BIN" || fail "백업 실패 — 굽지 않는다.
$STUCK"
  "$ESPTOOL" --port "$PORT" --no-stub --after no-reset verify-flash 0 "$BIN" || fail "백업 대조 실패 — 굽지 않는다.
$STUCK"
  md5sum "$BIN" > "$BIN.md5"
  echo "✅ 백업·대조 통과 · $(cut -c1-32 "$BIN.md5")"
  echo "   되돌리기: esptool --port $PORT --no-stub write-flash 0 $BIN"
else
  echo "⚠️ 백업을 건너뛴다(--no-backup)"
fi

# ── 5. 업로드 ───────────────────────────────────────
#    🔑 compile --upload 로 — upload 만 하면 캐시된 옛 바이너리가 조용히 올라갈 수 있다(glass_voice 머리말 · 3단계 덕에 빠르다).
echo
echo "📤 업로드 중..."
[ -e "$PORT" ] || fail "업로드 직전에 $PORT 가 사라졌다 — USB 연결 확인(굽지 않았다)."
"$ARDUINO_CLI" compile --upload -p "$PORT" --fqbn "$FQBN" "${EXTRA_UP[@]}" "$SKETCH_DIR" || fail "업로드 실패 (위 오류 참조)
   ESP32의 BOOT 버튼을 누른 채 RESET을 눌렀다 떼고 다시 시도해 보세요."
echo "✅ 업로드 완료 · 소스 $SRC"

# ── 6. 부팅 로그에서 IP ─────────────────────────────
#    메인만 .camera_ip 에 적는다 — 데모·음성비서는 그 주소로 붙는다(서브를 쓸 때만 손으로 바꾼다 · Rpi5/CLAUDE.md).
echo
echo "📡 WiFi 연결 대기 중... (최대 40초)"
IP_OK=1
if [ "$BOARD" = "main" ]; then
  cp -p "$CAMERA_IP_FILE" "$BACKUP_DIR/camera_ip.bak-$(date +%Y%m%d_%H%M%S)" 2>/dev/null
  "$HERE/read_esp32_ip.sh" "$PORT" "$CAMERA_IP_FILE" 40 || IP_OK=0
else
  TMP=$(mktemp)
  "$HERE/read_esp32_ip.sh" "$PORT" "$TMP" 40 || IP_OK=0
  [ -s "$TMP" ] && echo "서브 IP = $(cat "$TMP") · .camera_ip 는 그대로 둔다"
  rm -f "$TMP"
fi
[ "$IP_OK" = "1" ] || echo "⚠️ IP 를 못 읽었다 — 굽기는 끝났다 · arduino/read_esp32_ip.sh 로 다시 읽는다"

echo
[ -t 0 ] && read -rp "Enter 키를 누르면 닫힙니다..."
[ "$IP_OK" = "1" ]
