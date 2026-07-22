#!/usr/bin/env bash
# 시나리오 촬영 런처 — GUI + 화면녹화 + 웹캠(3인칭)녹화를 한 번에 시작한다.
#
# 왜: 시연 시나리오를 기록하려면 ①GUI 화면(FSM 상태·로그) ②3인칭 영상(타워램프·손·모니터)
#     ③버튼 눌림 로그 ④1인칭 ESP32 영상이 **같은 시각으로** 남아야 한다.
#     따로 켜면 시작 시각이 어긋나 나중에 대조가 안 된다.
#
# 사용:
#   ./run_scenario.sh 1        # 시나리오 1 (정상: B1→B2→B3→B4)
#   ./run_scenario.sh 2        # 시나리오 2 (B1 정상 → B3 위반 → 경고 → 해제)
#   ./run_scenario.sh 3        # 시나리오 3 (시작 직후 B2 위반 → 경고 → 해제)
#
# 종료: GUI 창을 닫으면 녹화 둘도 자동으로 정리된다.
#
# 🔴 이 런처는 config.USB_CAMERA_ENABLED 를 False 로 강제한다(환경변수).
#    GUI 의 UsbCameraThread 가 /dev/video0 을 점유하면 웹캠 녹화가 장치를 못 연다.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

SCENARIO="${1:-}"
if [ -z "$SCENARIO" ]; then
    echo "사용법: $0 <시나리오번호 1|2|3>"
    read -rp "Enter 키를 누르면 닫힙니다..."
    exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
OUT="scenario/${TS}_s${SCENARIO}"
mkdir -p "$OUT"

SCREEN_MP4="$OUT/screen.mp4"
WEBCAM_MP4="$OUT/webcam.mp4"
DISPLAY_ID="${DISPLAY:-:0}"

echo "══════════════════════════════════════════════"
echo "  시나리오 $SCENARIO 촬영"
echo "══════════════════════════════════════════════"
echo "  산출물: $OUT/"
echo

# --- 사전 점검 -----------------------------------------------------------
# 디스크: 1080p 두 갈래를 동시에 쓰므로 여유가 없으면 중간에 끊긴다.
FREE_MB=$(df -Pm . | awk 'NR==2{print $4}')
if [ "$FREE_MB" -lt 2048 ]; then
    echo "❌ 디스크 여유 ${FREE_MB}MB — 2GB 이상 필요합니다."
    echo "   recordings/ 의 옛 파일을 정리한 뒤 다시 실행하세요."
    read -rp "Enter 키를 누르면 닫힙니다..."
    exit 1
fi

if [ ! -e /dev/video0 ]; then
    echo "❌ USB 웹캠(/dev/video0)이 없습니다. 연결 후 다시 실행하세요."
    read -rp "Enter 키를 누르면 닫힙니다..."
    exit 1
fi

echo "📡 ESP32 카메라 확인 중..."
python3 test/cam_probe.py || {
    echo
    read -rp "그래도 진행하시겠습니까? (y = 진행 / 그 외 = 중단) " a
    case "$a" in y|Y) ;; *) exit 1 ;; esac
}
echo

# --- 녹화 시작 -----------------------------------------------------------
# ⚠️ 웹캠은 **ffmpeg 가 직접 v4l2 로** 연다. OpenCV 는 기본 GStreamer 백엔드로 열려
#    MJPG 지정이 무시되고 YUYV(=1080p 5fps)로 떨어진다(2026-07-22 실측).
ffmpeg -hide_banner -loglevel error -y \
    -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 30 -i /dev/video0 \
    -vf "drawtext=text='%{localtime\:%H\\\\\:%M\\\\\:%S}':x=12:y=12:fontsize=32:fontcolor=yellow:box=1:boxcolor=black@0.5" \
    -c:v libx264 -preset ultrafast -crf 26 -pix_fmt yuv420p \
    "$WEBCAM_MP4" &
WEBCAM_PID=$!

ffmpeg -hide_banner -loglevel error -y \
    -f x11grab -framerate 15 -video_size 1920x1080 -i "$DISPLAY_ID" \
    -c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p \
    "$SCREEN_MP4" &
SCREEN_PID=$!

sleep 2
if ! kill -0 "$WEBCAM_PID" 2>/dev/null; then echo "⚠️ 웹캠 녹화가 시작되지 못했습니다"; fi
if ! kill -0 "$SCREEN_PID" 2>/dev/null; then echo "⚠️ 화면 녹화가 시작되지 못했습니다"; fi

cleanup() {
    echo
    echo "▪ 녹화 종료 중..."
    kill -INT "$WEBCAM_PID" "$SCREEN_PID" 2>/dev/null
    wait "$WEBCAM_PID" "$SCREEN_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

echo "🔴 녹화 시작 — 화면 + 웹캠(3인칭)"
echo
case "$SCENARIO" in
  1) echo "  ▶ 시나리오 1 (정상): [공정 시작] → B1 → B2 → B3 → B4" ;;
  2) echo "  ▶ 시나리오 2 (위반): [공정 시작] → B1 → **B3** → 경고 → 경고 해제" ;;
  3) echo "  ▶ 시나리오 3 (위반): [공정 시작] → **B2** → 경고 → 경고 해제" ;;
esac
echo
echo "  종료하려면 GUI 창을 닫으세요."
echo

# --- GUI (전면) ----------------------------------------------------------
# USB_CAMERA_ENABLED=0 → GUI 가 웹캠을 점유하지 않는다(위 주석 참조).
SOP_USB_CAMERA=0 SOP_FULLSCREEN=1 python3 main.py
status=$?

cleanup
trap - EXIT

# --- 산출물 정리 ---------------------------------------------------------
LOG_SRC="$(ls -t logs/*.txt 2>/dev/null | head -1)"
REC_SRC="$(ls -t recordings/*.avi 2>/dev/null | head -1)"
[ -n "$LOG_SRC" ] && cp "$LOG_SRC" "$OUT/app_log.txt"
[ -n "$REC_SRC" ] && ln -sf "../../$REC_SRC" "$OUT/esp32_fpv.avi" 2>/dev/null

echo
echo "══════════════════════════════════════════════"
echo "  시나리오 $SCENARIO 산출물 — $OUT/"
echo "══════════════════════════════════════════════"
ls -lh "$OUT/" | tail -n +2 | awk '{printf "  %-18s %s\n", $9, $5}'
echo
echo "  (GUI exit code: $status)"
read -rp "Enter 키를 누르면 닫힙니다..."
