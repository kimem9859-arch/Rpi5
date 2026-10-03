#!/bin/bash
# 시험용(버림) — 세 크기 ONNX 내보내기 → 차례로 Hailo 변환 → 프로파일. 데스크톱 WSL /tmp/res_probe 에서.
cd /tmp/res_probe || exit 1
# 내보내기는 .pt 옆에 .onnx 를 쓴다 — 원본 폴더의 console_v2.onnx 를 덮어쓰지 않게 복사본에서 내보낸다
cp -n ~/projects/dev/ai_model/console_v2.pt ./console_v2_src.pt
PT=/tmp/res_probe/console_v2_src.pt
for s in "640 640" "832 640" "1024 768"; do
  set -- $s; H=$1; W=$2; TAG=${H}x${W}
  ~/projects/.poc_venv/bin/python -c "
from ultralytics import YOLO
p = YOLO('$PT').export(format='onnx', opset=11, imgsz=($H, $W), simplify=False, dynamic=False)
import shutil; shutil.move(p, 'console_v2_${TAG}.onnx'); print('[export]', '${TAG}', 'ok')
" > export_${TAG}.log 2>&1
done
for s in "640 640" "832 640" "1024 768"; do
  set -- $s; TAG=${1}x${2}
  CUDA_VISIBLE_DEVICES=-1 ~/hailo-venv/bin/python probe.py $1 $2 > probe_${TAG}.log 2>&1
  [ -f probe_${TAG}_compiled.har ] && ~/hailo-venv/bin/hailo profiler probe_${TAG}_compiled.har --out-path profile_${TAG}.html > profile_${TAG}.log 2>&1
done
echo ALLDONE > done.flag
