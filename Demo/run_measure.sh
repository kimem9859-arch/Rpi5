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
echo "  대본 목록:"; python3 measure_session.py --list-scripts
S=$(ask "대본 (번호 또는 파일 경로 · 엔터 = 없음)")
F=$(ask "펌웨어 (엔터 = glass_voice)")
G=$(ask "안경 전원 (엔터 = 무선·배터리 · 2 = 유선·USB)")
ON=$(ask "측정 기록 (1 켬 · 0 끔 — 시험 세션의 끔 회차)")
# 🔴 음성 끔은 세션 정보를 쓰기 **전에** 내보낸다 — session.json 의 「음성」이 이 값을 읽는다
if [ "$K" = "4" ]; then export SOP_VOICE=0; fi
# 남은 공간 — 올림 없는 값으로(GB 단위 df 는 올려서 0.3GB 도 1G 로 보였다 · 리뷰 I-2)
FREE=$(python3 measure_session.py --free-gb)
if awk -v f="${FREE:-0}" 'BEGIN { exit !(f < 1) }'; then
  read -rp "  ⚠️ 남은 공간 ${FREE}GB — 1GB 미만이다. 계속할까? (y/N) > " Y
  [ "$Y" = "y" ] || exit 1
fi
if ! DIR=$(python3 measure_session.py --place "$P" --kind "$K" --hand "$H" --person "$W" --light "$L" \
      ${S:+--script "$S"} --firmware "${F:-glass_voice}" --power "${G:-1}" --on "$ON"); then
  # 🔴 창이 말없이 닫히지 않게 — 위 오류(argparse)를 읽고 다시 실행한다(리뷰 I-3)
  echo "  ❌ 세션 정보를 만들지 못했다 — 위 오류를 보고 다시 실행하세요"
  read -rp "  엔터를 누르면 창을 닫는다 > " _
  exit 1
fi
echo "  세션 폴더: $DIR"
# 끔 회차는 물려받은 값도 지운다 — 기록이 저절로 켜지지 않게
if [ "$ON" = "1" ]; then export SOP_MEASURE_DIR="$DIR"; else unset SOP_MEASURE_DIR; fi
bash ./run_demo.sh
# 시연을 닫으면 세기(보고 도구)가 바로 센다 — 측정 설계 D10 · 기록 끔 회차는 셀 것이 없다
if [ "$ON" = "1" ]; then
  # 음성 데몬은 run_demo.sh 종료(kill) 뒤에야 끝 사건(measure_end)을 쓴다 — 최대 5초 기다린 뒤 센다
  for _ in 1 2 3 4 5; do pgrep -f "voice_assistant.py" >/dev/null || break; sleep 1; done
  python3 test/measure_report.py "$DIR" || echo "  ⚠️ 세기 실패 — 위 오류를 보고 나중에 다시: python3 test/measure_report.py \"$DIR\""
fi
echo "  끝 — 기록 폴더: $DIR"
read -rp "  엔터를 누르면 창을 닫는다 > " _
