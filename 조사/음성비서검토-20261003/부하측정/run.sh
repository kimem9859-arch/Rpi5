#!/bin/bash
# 일회용 — 조건 C0~C3 순서대로. 시각표 = timeline.txt
SP="$(cd "$(dirname "$0")" && pwd)"; DEMO=/home/pi/sop-project/Rpi5/Demo; TTSPY=$HOME/env/tts/.venv/bin/python
cd "$SP"; : > timeline.txt; mark(){ echo "$(date +%T) $*" | tee -a timeline.txt; }
cleanup(){ mark 정리; kill $TTS $VOICE $GLASS $TOOL 2>/dev/null; [ -n "$DEMO_PID" ] && kill -- -$DEMO_PID 2>/dev/null; kill $CAM 2>/dev/null; sleep 3; pkill -f sop_tool_probe 2>/dev/null; }
trap cleanup EXIT
mark C0 시작; python3 sampler.py C0_대기 30 c0.json > c0.txt; mark C0 끝
python3 -u mock_cam.py > cam.log 2>&1 & CAM=$!
for i in $(seq 120); do grep -q '\[cam\] [0-9]' cam.log && break; sleep 1; done; mark 모의카메라 준비 "$(head -1 cam.log)"
DISPLAY=:0 setsid python3 -u launch_demo.py > demo.log 2>&1 & DEMO_PID=$!
sleep 45; mark C1 시작; python3 sampler.py C1_시연 120 c1.json > c1.txt; mark C1 끝
python3 -u tool_feed.py > tool.log 2>&1 & TOOL=$!
sleep 25; mark C2 시작; python3 sampler.py C2_시연+공구 120 c2.json > c2.txt; mark C2 끝
(cd /home/pi/sop-project/Rpi5 && exec $TTSPY -u Demo/test/fake_glass.py "$SP/mic2x.wav") > glass.log 2>&1 & GLASS=$!
sleep 2
(cd $DEMO && exec $TTSPY -u voice_assistant.py --ip 127.0.0.1) > voice.log 2>&1 & VOICE=$!
$TTSPY -u tts_loop.py > tts.log 2>&1 & TTS=$!
sleep 25; mark C3 시작; python3 sampler.py C3_시연+공구+음성 120 c3.json > c3.txt; mark C3 끝
