#!/usr/bin/env bash
# 시연영상 촬영 런처 — 한 번 실행에 5개 영상을 동시에 남긴다.
#
# 설계 = 상위 docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md
#
# 🔴 평소 실행(바탕화면 「SOP 가디언 Demo」)과 다르다. 저쪽은 녹화를 켜지 않는다.
# 🔴 웹캠은 ffmpeg 가 직접 연다 — GUI 의 UsbCameraThread 가 /dev/video0 을
#    점유하면 3인칭 녹화가 장치를 못 연다. 그래서 SOP_USB_CAMERA=0 을 강제한다.
#
# 종료: GUI 창을 닫으면 5개 녹화가 함께 정리되고, 여기서 채택/NG 를 묻는다.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  시연영상 촬영"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 5개 동시 녹화라 여유가 없으면 중간에 끊긴다.
FREE_MB=$(df -Pm . | awk 'NR==2{print $4}')
if [ "$FREE_MB" -lt 4096 ]; then
    echo "❌ 디스크 여유 ${FREE_MB}MB — 4GB 이상 필요합니다."
    echo "   recordings/ 의 옛 파일을 정리한 뒤 다시 실행하세요."
    read -rp "Enter 키를 누르면 닫힙니다..."; exit 1
fi
if [ ! -e /dev/video0 ]; then
    echo "⚠️ USB 웹캠(/dev/video0)이 없습니다 — 3인칭 영상 없이 4개만 찍힙니다."
fi

echo
echo "  시나리오를 고르세요"
echo "    1) 정상"
echo "    2) 오답(순서 위반)"
read -rp "  > " s
case "$s" in 2) SCEN="오답" ;; *) SCEN="정상" ;; esac

echo
echo "  검출 오버레이(박스·손)를 GUI 화면에 표시할까요?"
echo "    1) 켬"
echo "    2) 끔"
read -rp "  > " o
case "$o" in 2) OVL="끔" ;; *) OVL="켬" ;; esac

echo
echo "  ▶ [$SCEN / 오버레이 $OVL] GUI 를 띄웁니다."
echo "    화면이 뜨고 카메라 영상이 들어오면 5개 녹화가 동시에 시작됩니다."
echo "    끝나면 GUI 창을 닫으세요."
echo

SOP_DEMO_CAPTURE=1 SOP_DEMO_SCENARIO="$SCEN" SOP_DEMO_OVERLAY="$OVL" \
SOP_USB_CAMERA=0 python3 main.py
status=$?

SET_DIR="$(ls -dt recordings/시연영상/촬영본/*/ 2>/dev/null | head -1)"
if [ -z "$SET_DIR" ]; then
    echo "❌ 촬영본이 없습니다 (GUI exit code: $status)"
    read -rp "Enter 키를 누르면 닫힙니다..."; exit 1
fi

echo
echo "  ▪ 촬영본 — $SET_DIR"
sed 's/^/    /' "$SET_DIR/촬영정보.txt" 2>/dev/null
echo
read -rp "  이번 테이크를 채택하시겠습니까? (y = 채택 / 그 외 = NG보관) " a
case "$a" in y|Y) DEST="recordings/시연영상/채택" ;; *) DEST="recordings/시연영상/NG보관" ;; esac

# 🔴 지우지 않는다 — NG 도 보관한다.
mkdir -p "$DEST" && mv "$SET_DIR" "$DEST/" \
    && echo "  → $DEST/ 로 옮겼습니다" \
    || echo "  ⚠️ 이동 실패 — $SET_DIR 에 그대로 있습니다"

read -rp "Enter 키를 누르면 닫힙니다..."
