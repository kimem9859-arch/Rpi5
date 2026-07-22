#!/usr/bin/env bash
# console_v2 실테스트 실행 런처 (바탕화면 바로가기용).
#
# 왜 있나: 클린룸 등 키보드를 들고 들어가기 어려운 환경에서 클릭 한 번으로 세션을 돌리기 위함.
# 조건 슬러그를 인자로 받는다 — 조건별 .desktop 파일이 각자 슬러그를 넘긴다.
#
#   ./run_bench_test.sh cleanroom            # 300프레임, raw 5프레임마다
#   ./run_bench_test.sh cleanroom 300 1      # raw 전 프레임 (test 이미지 수집 겸용)
#
# 결과 판정 기준(설계 승인분): 5클래스 중 raw 검출 0회가 있거나 평균 conf < 0.70 이면 중단.
# 세션 종료 후 이 스크립트가 그 판정을 자동 출력한다 — 현장에서 바로 읽을 수 있게.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

COND="${1:-}"
if [ -z "$COND" ]; then
    echo "사용법: $0 <조건슬러그>   (예: cleanroom)"
    read -rp "Enter 키를 누르면 닫힙니다..."
    exit 1
fi

FRAMES="${2:-300}"
# raw 저장 간격. 기본 5 = 학습 촬영(7/13)과 동일해 조건 간 비교가 대등하다.
# 클린룸은 test 이미지 수집을 겸하므로 1(전 프레임)로 넘긴다.
RAW_EVERY="${3:-5}"

if [ "$RAW_EVERY" -eq 1 ]; then RAW_DESC="전 프레임"; else RAW_DESC="${RAW_EVERY}프레임마다"; fi

echo "══════════════════════════════════════════════"
echo "  console_v2 실테스트 — 조건: $COND"
echo "══════════════════════════════════════════════"
echo "  프레임: $FRAMES · raw 저장: $RAW_DESC"
echo

# ESP32 도달 확인 — 못 붙으면 촬영을 헛돌리지 않고 여기서 멈춘다.
# ping 은 "전원 꺼짐/IP 바뀜"을 빠르게 걸러 주는 1차 관문일 뿐이다.
CAM_IP="$(cat .camera_ip 2>/dev/null)"
echo "📡 ESP32 카메라 확인 중... (${CAM_IP:-미설정})"
if [ -z "$CAM_IP" ] || ! ping -c 2 -W 2 "$CAM_IP" >/dev/null 2>&1; then
    echo
    echo "❌ ESP32($CAM_IP)에 닿지 않습니다."
    echo "   - ESP32 전원이 켜져 있는지"
    echo "   - 파이와 ESP32가 같은 WiFi에 붙어 있는지 (현재 파이: $(iwgetid -r 2>/dev/null))"
    echo "   - IP가 바뀌었다면 바탕화면 'ESP32 IP 갱신'을 먼저 실행"
    echo
    read -rp "Enter 키를 누르면 닫힙니다..."
    exit 1
fi

# 🔴 ping 통과 = 정상이 아니다. 실제로 프레임을 받아 속도를 재고 나서 촬영을 허락한다.
#    2026-07-20에 라우팅 경유 연결이 ping을 통과해 0.9fps(정상 12.5)로 한 세션을 통째로 버렸다.
python3 test/cam_probe.py
case $? in
    0) ;;                                    # 정상 — 그대로 진행
    2)  echo
        read -rp "느린 상태로 촬영하시겠습니까? (y = 진행 / 그 외 = 중단) " ans
        case "$ans" in
            y|Y) ;;
            *)   echo "촬영을 취소했습니다."; read -rp "Enter 키를 누르면 닫힙니다..."; exit 1 ;;
        esac ;;
    *)  echo
        echo "   (IP가 바뀌었다면 바탕화면 'ESP32 IP 갱신'을 먼저 실행)"
        echo
        read -rp "Enter 키를 누르면 닫힙니다..."
        exit 1 ;;
esac
echo
echo "▶ 촬영을 시작합니다. 5개 버튼(B1~B4·EMO)이 화면에 들어오게 하세요."
echo

python3 test/bench_detector.py \
    --source esp32 \
    --condition "$COND" \
    --frames "$FRAMES" \
    --save-raw --raw-every "$RAW_EVERY"
status=$?

echo
if [ $status -ne 0 ]; then
    echo "❌ 벤치마크가 비정상 종료했습니다 (exit $status)."
else
    echo "══════════════════════════════════════════════"
    echo "  자동 판정"
    echo "══════════════════════════════════════════════"
    python3 test/verdict.py --condition "$COND"
fi

echo
read -rp "Enter 키를 누르면 닫힙니다..."
