#!/bin/bash
# 정지 장면(안경 책상 위 · 천장) — 세 조합을 번갈아 3회 · FPS + NPU 사용률(hailortcli monitor) + 파이 CPU·온도
T=/home/pi/.claude/jobs/a8325699/tmp; O=$T/npu; mkdir -p $O
B=/home/pi/sop-project/Rpi5/Demo/test/bench_detector.py
E0B=/home/pi/data/학습실험/E0b-button-s0/model.hef; E0C=/home/pi/data/학습실험/E0c-tool-f120/model.hef
declare -A ARGS=( [A]="" [B]="--hef $E0B" [C]="--hef $E0B --tool-hef $E0C" )
declare -A SLUG=( [A]=static-desk-cur [B]=static-desk-e0b [C]=static-desk-3npu )
for r in 1 2 3; do for c in A B C; do
  tag=${c}-r$r
  python3 - $O/cpu_$tag.txt <<'PY' &
import psutil, sys, time, subprocess
f = open(sys.argv[1], "w"); psutil.cpu_percent()
for _ in range(60):
    time.sleep(1)
    t = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True).stdout.strip()
    f.write(f"{psutil.cpu_percent():.1f} {t}\n"); f.flush()
PY
  SAMP=$!
  (sleep 12; timeout 7 hailortcli monitor > $O/hmon_$tag.txt 2>&1) &
  MON=$!
  HAILO_MONITOR=1 DISPLAY=:0 timeout 120 python3 $B --frames 300 --no-video --hand --undistort ${ARGS[$c]} --condition ${SLUG[$c]}-r$r > $O/bench_$tag.txt 2>&1
  wait $MON; kill $SAMP 2>/dev/null; wait $SAMP 2>/dev/null
  echo "$tag 끝 $(grep '평균 FPS' $O/bench_$tag.txt)"
  sleep 3
done; done
echo 전부끝
