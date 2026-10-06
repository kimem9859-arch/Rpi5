#!/bin/bash
# 장소2 손·공구 장면 — 재학습 모델 3종 NPU 동시(plan Task 2-2) · 정지 장면 측정(npu_정지장면_측정.sh)과 같은 방식
# 사용: bash npu_장소2_측정.sh s2|s6|s7   — 사용자 동작별로 묶는다(s2 = 손을 콘솔 앞에서 좌우로 · s6 = B1→B4 반복 누름 · s7 = 공구 3종 차례로 들어 보이기 + 눈 확인 영상)
G=$1
T=/home/pi/.claude/jobs/a8325699/tmp; O=$T/npu2; mkdir -p $O
B=/home/pi/sop-project/Rpi5/Demo/test/bench_detector.py
E0B=/home/pi/data/학습실험/E0b-button-s0/model.hef; E0C=/home/pi/data/학습실험/E0c-tool-f120/model.hef
declare -A ARGS=( [B]="--hef $E0B" [C]="--hef $E0B --tool-hef $E0C" [D]="--hef $E0B --tool-hef $E0C --tool-interval 1.0" )
case $G in
  s2) RUNS="D:S2:1:300 D:S2:2:300 B:S2:1:300 C:S2:1:300" ;;
  s6) RUNS="D:S6:1:900" ;;
  s7) RUNS="D:S7:1:300" ;;
  s7b) RUNS="D:S7:2:600" ;;   # r1 이 18초라 pliers 를 못 보임(사용자) → 600프레임(약 36초) + 영상 r2 900
  *) echo "s2|s6|s7|s7b"; exit 1 ;;
esac
cd /home/pi/sop-project/Rpi5/Demo
for run in $RUNS; do
  IFS=: read c s r n <<< "$run"; tag=$c-$s-r$r
  python3 - $O/cpu_$tag.txt <<'PY' &
import psutil, sys, time, subprocess
f = open(sys.argv[1], "w"); psutil.cpu_percent()
for _ in range(150):
    time.sleep(1)
    t = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True).stdout.strip()
    f.write(f"{psutil.cpu_percent():.1f} {t}\n"); f.flush()
PY
  SAMP=$!
  (sleep 12; timeout 7 hailortcli monitor > $O/hmon_$tag.txt 2>&1) &
  MON=$!
  HAILO_MONITOR=1 DISPLAY=:0 timeout $((n / 4 + 60)) python3 $B --frames $n --no-video --hand --undistort ${ARGS[$c]} --condition place2-$tag > $O/bench_$tag.txt 2>&1
  wait $MON; kill $SAMP 2>/dev/null; wait $SAMP 2>/dev/null
  echo "$tag 끝 $(date +%H:%M:%S) $(grep '평균 FPS' $O/bench_$tag.txt)"
  sleep 3
done
# 눈 확인 영상 — 박스를 그린 영상 저장 · 이 회차 FPS 는 판정에 쓰지 않는다 · s7b = 다시(사용자 · r1 600프레임이 짧음 → 900)
case $G in s7) V=1; VN=600 ;; s7b) V=2; VN=900 ;; *) V= ;; esac
if [ -n "$V" ]; then
  DISPLAY=:0 timeout 300 python3 $B --frames $VN --hand --undistort ${ARGS[D]} --condition place2-D-video-r$V > $O/bench_D-video-r$V.txt 2>&1
  echo "D-video-r$V 끝 $(date +%H:%M:%S) $(grep -E '평균 FPS|영상' $O/bench_D-video-r$V.txt | head -2)"
fi
echo 전부끝
