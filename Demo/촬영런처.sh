#!/usr/bin/env bash
# 시연영상 촬영 런처 — 한 번 실행에 5개 영상을 동시에 남긴다.
#
# 설계 = 상위 docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md
#
# 🔴 평소 실행(바탕화면 「SOP 가디언 Demo」)과 다르다. 저쪽은 녹화를 켜지 않는다.
# 🔴 웹캠은 ffmpeg 가 직접 연다 — GUI 의 UsbCameraThread 가 /dev/video0 을
#    점유하면 3인칭 녹화가 장치를 못 연다. 그래서 SOP_USB_CAMERA=0 을 강제한다.
#
# 종료: GUI 창을 닫으면 그 회차의 녹화가 함께 정리되고, 여기서 채택/NG 를 묻는다.

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
echo "  무엇을 찍으시겠습니까?"
echo "    1) 1인칭 + GUI   — ESP32 를 USB 로 연결한 유선 회차"
echo "    2) 3인칭 웹캠만  — ESP32 없이 연기하는 무선 회차"
echo "    3) 전부          — 기존 방식(한 번에 4개)"
read -rp "  > " tsel
case "$tsel" in
    2) TARGETS="webcam" ;;
    3) TARGETS="all" ;;
    *) TARGETS="fpv+gui" ;;
esac

echo
echo "  시나리오를 고르세요"
echo "    1) 정상"
echo "    2) 오답(순서 위반)"
read -rp "  > " s
case "$s" in 2) SCEN="오답" ;; *) SCEN="정상" ;; esac

if [ "$TARGETS" = "webcam" ]; then
    # 🔴 GUI 는 띄우되 녹화하지 않는다 — 배경·오버레이는 이 회차 산출물에 안 나온다.
    HIDE=0; OVL="켬"
    echo
    echo "  ▶ [$SCEN / 3인칭 웹캠만] GUI 를 띄웁니다 (버튼·타워램프는 그대로 반응)."
    echo "    ESP32 없이 연기하시면 됩니다. 녹화는 웹캠 하나만 남습니다."
    echo "    끝나면 GUI 창을 닫으세요."
    echo
    SOP_DEMO_CAPTURE=1 SOP_DEMO_SCENARIO="$SCEN" SOP_DEMO_OVERLAY="$OVL" \
    SOP_DEMO_HIDE_VIDEO="$HIDE" SOP_DEMO_TARGETS="$TARGETS" \
    SOP_USB_CAMERA=0 python3 main.py
    status=$?
else

echo
echo "  GUI 배경을 고르세요"
echo "    1) 실시간 1인칭 영상을 보여준다"
echo "    2) 검정 배경 + UI 만  (🔴 이 회차는 따로 찍어야 한다 — 이 UI 는 모든 UI 가"
echo "                          영상 위에 떠 있어 나중에 덧칠하면 UI 까지 지워진다)"
read -rp "  > " b
if [ "$b" = "2" ]; then HIDE=1; else HIDE=0; fi

if [ "$HIDE" = "1" ]; then
    # 배경이 검정이면 박스·랜드마크는 어차피 안 보인다(영상 위에 그리므로).
    OVL="켬"
    echo
    echo "  ▶ [$SCEN / UI만(검정 배경)] GUI 를 띄웁니다."
else
    echo
    echo "  검출 오버레이(박스·손)를 GUI 화면에 표시할까요?"
    echo "    1) 켬"
    echo "    2) 끔"
    read -rp "  > " o
    case "$o" in 2) OVL="끔" ;; *) OVL="켬" ;; esac
    echo
    echo "  ▶ [$SCEN / 오버레이 $OVL] GUI 를 띄웁니다."
fi
echo "    화면이 뜨고 카메라 영상이 들어오면 이 회차의 녹화 4개가 동시에 시작됩니다."
echo "    끝나면 GUI 창을 닫으세요."
echo

SOP_DEMO_CAPTURE=1 SOP_DEMO_SCENARIO="$SCEN" SOP_DEMO_OVERLAY="$OVL" \
SOP_DEMO_HIDE_VIDEO="$HIDE" SOP_DEMO_TARGETS="$TARGETS" \
SOP_USB_CAMERA=0 python3 main.py
status=$?
fi

SET_DIR="$(ls -dt recordings/시연영상/촬영본/*/ 2>/dev/null | head -1)"
if [ -z "$SET_DIR" ]; then
    echo "❌ 촬영본이 없습니다 (GUI exit code: $status)"
    read -rp "Enter 키를 누르면 닫힙니다..."; exit 1
fi

echo
echo "  ▪ 촬영 마무리 중 (GUI화면만 만들기 · 1인칭 규격 맞추기)..."
echo "    🔴 촬영 중에는 CPU 를 아끼려고 원본만 담는다 — 규격 맞추기는 여기서 한다."
python3 demo_postprocess.py "$SET_DIR"

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
