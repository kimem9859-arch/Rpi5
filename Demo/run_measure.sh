#!/bin/bash
# 측정 실행기 — 시연 프로그램을 측정 기록을 켠 채 띄운다(측정 도구 정합 §4.3 적기 · D9~D19).
# 「시연」 바로가기(run_demo.sh)는 그대로 — 여기서만 SOP_MEASURE_DIR 를 준다.
cd "$(dirname "$0")" || exit 1
# 🔴 리허설 전용 변수가 남은 셸에서는 실제 측정을 시작하지 않는다 — 가상 작업자가 시연 버튼을 누르거나, 세션이 리허설 폴더 ·
#    가짜 카메라 주소로 간다(학교 방문 준비 최종 리뷰 Minor 8). 리허설은 SOP_REHEARSAL=1 을 함께 준다.
if [ "${SOP_REHEARSAL:-}" != "1" ]; then
  STRAY=$(env | grep -oE '^SOP_(CAMERA_HOST|MEASURE_BASE|REHEARSE_[A-Z_]+)=' | tr -d '=' | tr '\n' ' ')
  if [ -n "$STRAY" ]; then
    echo "❌ 리허설 변수가 셸에 남아 있다: ${STRAY}— 새 터미널을 열고 다시 실행하세요(대처 V9)"
    read -rp "  엔터를 누르면 창을 닫는다 > " _
    exit 1
  fi
fi
ask() { local v; read -rp "  $1 > " v; echo "$v"; }
echo "== 측정 세션 =="
P=$(ask "장소 (1 장소1 · 2 장소2 · 3 장소3)")
K=$(ask "세션 (0 시험 · 1 정상 · 2 위반 · 3 장갑 · 4 음성끔)")
H=$(ask "손 (1 맨손 · 2 장갑)")
W=$(ask "사람 번호 (1~9)")
L=$(ask "조명·조도 (선택 · 엔터 = 건너뜀)")
echo "  대본 목록:"; python3 measure_session.py --list-scripts
S=$(ask "대본 (번호 또는 파일 경로 · 엔터 = 없음)")
FR=$(ask "몇 판부터 (엔터 = 1 · 시연이 죽었을 때 그 판부터 다시)")
F=$(ask "펌웨어 (엔터 = glass_voice)")
G=$(ask "안경 전원 (엔터 = 무선·배터리 · 2 = 유선·USB)")
# 🔑 처리 설정은 번호로 — 환경변수를 손으로 치지 않는다 · 셸에 남은 값을 먼저 지운다(학교 방문 준비 설계 §3.4 · Review Focus 1)
unset SOP_ORIENT_ONE_REMAP SOP_DISPLAY_PAINT SOP_DISPLAY_EVERY SOP_INFER_MODEL SOP_PIPELINE2
echo "  처리 설정: 1 1단계(기본) · 2 종전 · 3 1단계+화면 덜 그리기 · 4 1단계+2a · 5 1단계+2a+2b"
PR=$(ask "처리 설정 (엔터 = 1)")
case "${PR:-1}" in
  1) ;;
  2) export SOP_ORIENT_ONE_REMAP=0 SOP_DISPLAY_PAINT=0 ;;
  3) export SOP_DISPLAY_EVERY=2 ;;
  4) export SOP_INFER_MODEL=1 ;;
  5) export SOP_INFER_MODEL=1 SOP_PIPELINE2=1 ;;
  *) echo "  ❌ 처리 설정 「${PR}」 은(는) 1~5 가운데 하나여야 한다 — 다시 실행하세요"
     read -rp "  엔터를 누르면 창을 닫는다 > " _
     exit 1 ;;
esac
ON=$(ask "측정 기록 (1 켬 · 0 끔 — 시험 세션의 끔 회차)")
# 🔴 음성 끔은 세션 정보를 쓰기 **전에** 내보낸다 — session.json 의 「음성」이 이 값을 읽는다
if [ "$K" = "4" ]; then export SOP_VOICE=0; fi
# 🔑 측정에서는 음성 알림을 끈다(측정 진행 도우미 설계 2026-10-11 D9 · 사용자 「알림은 시연용 기능」) — session.json 설정 VOICE_ALERTS 에 남는다
VA=$(ask "음성 알림 (엔터 = 끔 · 1 = 켬)")
if [ "$VA" = "1" ]; then export SOP_VOICE_ALERTS=1; else export SOP_VOICE_ALERTS=0; fi
# 남은 공간 — 올림 없는 값으로(GB 단위 df 는 올려서 0.3GB 도 1G 로 보였다 · 리뷰 I-2)
FREE=$(python3 measure_session.py --free-gb)
if awk -v f="${FREE:-0}" 'BEGIN { exit !(f < 1) }'; then
  read -rp "  ⚠️ 남은 공간 ${FREE}GB — 1GB 미만이다. 계속할까? (y/N) > " Y
  [ "$Y" = "y" ] || exit 1
fi
if ! DIR=$(python3 measure_session.py --place "$P" --kind "$K" --hand "$H" --person "$W" --light "$L" \
      ${S:+--script "$S"} --firmware "${F:-glass_voice}" --power "${G:-1}" \
      --from-run "${FR:-1}" --processing "${PR:-1}" --on "$ON"); then
  # 🔴 창이 말없이 닫히지 않게 — 위 오류(argparse)를 읽고 다시 실행한다(리뷰 I-3)
  echo "  ❌ 세션 정보를 만들지 못했다 — 위 오류를 보고 다시 실행하세요"
  read -rp "  엔터를 누르면 창을 닫는다 > " _
  exit 1
fi
echo "  세션 폴더: $DIR"
echo "  📣 노트북 SSH 창: bash ~/sop-project/Rpi5/Demo/run_guide.sh  (안내 소리 · N = NG · U = 취소)"
# 끔 회차는 물려받은 값도 지운다 — 기록이 저절로 켜지지 않게
if [ "$ON" = "1" ]; then export SOP_MEASURE_DIR="$DIR"; else unset SOP_MEASURE_DIR; fi
# SOP_DEMO_LAUNCHER = 시험에서만(시연 대신 환경변수를 적는 스크립트) — 평소에는 없다
bash "${SOP_DEMO_LAUNCHER:-./run_demo.sh}"
# 시연을 닫으면 세기(보고 도구)가 바로 센다 — 측정 설계 D10 · 기록 끔 회차는 셀 것이 없다
if [ "$ON" = "1" ]; then
  # 음성 데몬은 run_demo.sh 종료(kill) 뒤에야 끝 사건(measure_end)을 쓴다 — 최대 5초 기다린 뒤 센다
  for _ in 1 2 3 4 5; do pgrep -f "voice_assistant.py" >/dev/null || break; sleep 1; done
  python3 test/measure_report.py "$DIR" || echo "  ⚠️ 세기 실패 — 위 오류를 보고 나중에 다시: python3 test/measure_report.py \"$DIR\""
fi
echo "  끝 — 기록 폴더: $DIR"
read -rp "  엔터를 누르면 창을 닫는다 > " _
