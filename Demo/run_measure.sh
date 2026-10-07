#!/bin/bash
# 측정 실행기 — 시연 프로그램을 측정 기록을 켠 채 띄운다(측정 도구 정합 §4.3 적기 · D9~D19).
# 「시연」 바로가기(run_demo.sh)는 그대로 — 여기서만 SOP_MEASURE_DIR 를 준다.
cd "$(dirname "$0")" || exit 1
ask() { local v; read -rp "  $1 > " v; echo "$v"; }
echo "== 측정 세션 =="
P=$(ask "장소 (1 장소1 · 2 장소2)")
K=$(ask "세션 (0 시험 · 1 정상 · 2 위반 · 3 장갑 · 4 음성끔)")
H=$(ask "손 (1 맨손 · 2 장갑)")
W=$(ask "사람 번호 (1~9)")
L=$(ask "조명·조도 (선택 · 엔터 = 건너뜀)")
S=$(ask "대본 파일 경로 (선택 · 엔터 = 없음)")
F=$(ask "펌웨어 (엔터 = glass_voice)")
ON=$(ask "측정 기록 (1 켬 · 0 끔 — 시험 세션의 끔 회차)")
FREE=$(df -BG --output=avail . | tail -1 | tr -dc '0-9')
if [ "${FREE:-0}" -lt 1 ]; then
  read -rp "  ⚠️ 남은 공간 ${FREE}GB — 1GB 미만이다. 계속할까? (y/N) > " Y
  [ "$Y" = "y" ] || exit 1
fi
# 🔴 음성 끔은 세션 정보를 쓰기 **전에** 내보낸다 — session.json 의 「음성」이 이 값을 읽는다
if [ "$K" = "4" ]; then export SOP_VOICE=0; fi
DIR=$(python3 measure_session.py --place "$P" --kind "$K" --hand "$H" --person "$W" --light "$L" \
      ${S:+--script "$S"} --firmware "${F:-glass_voice}" --on "$ON") || exit 1
echo "  세션 폴더: $DIR"
if [ "$ON" = "1" ]; then export SOP_MEASURE_DIR="$DIR"; fi
bash ./run_demo.sh
echo "  끝 — 기록 폴더: $DIR"
read -rp "  엔터를 누르면 창을 닫는다 > " _
