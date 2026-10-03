#!/bin/bash
# 시험용(버림) — 파이 Hailo-8 에서 버튼 검출 HEF 하나를 ① 혼자 ② 손 모델 2개와 30fps 로 함께 ③ 함께 최대로 돌린다.
# 사용: pi_bench.sh <HEF> <태그>   결과 = 같은 폴더 bench_<태그>_{alone,mix30,mixmax}.json · .txt
set -u
HEF=$1; TAG=$2; OUT=$(dirname "$0")
PALM=/home/pi/lab/hoi/hailo8/palm_detection_lite.hef
HAND=/home/pi/lab/hoi/hailo8/hand_landmark_lite.hef
if fuser /dev/hailo0 >/dev/null 2>&1; then echo "🔴 Hailo 사용 중 — 멈춤"; fuser -v /dev/hailo0; exit 1; fi
hailortcli parse-hef "$HEF" | grep -E "Network group name|Input "
hailortcli run2 -t 10 --measure-latency --measure-overall-latency -j "$OUT/bench_${TAG}_alone.json" \
  set-net "$HEF" --batch-size 1 > "$OUT/bench_${TAG}_alone.txt" 2>&1
hailortcli run2 -t 15 -j "$OUT/bench_${TAG}_mix30.json" \
  set-net "$PALM" --batch-size 1 --framerate 30 \
  set-net "$HAND" --batch-size 1 --framerate 30 \
  set-net "$HEF" --batch-size 1 --framerate 30 > "$OUT/bench_${TAG}_mix30.txt" 2>&1
hailortcli run2 -t 15 -j "$OUT/bench_${TAG}_mixmax.json" \
  set-net "$PALM" --batch-size 1 \
  set-net "$HAND" --batch-size 1 \
  set-net "$HEF" --batch-size 1 > "$OUT/bench_${TAG}_mixmax.txt" 2>&1
for k in alone mix30 mixmax; do echo "== $k"; grep -vE '^\s*$' "$OUT/bench_${TAG}_$k.txt" | tail -12; done
