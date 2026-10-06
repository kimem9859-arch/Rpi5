#!/bin/bash
# GPIO 초기화 실패 표시 확인 — B1(GPIO5) 줄을 gpiomon 이 잡은 채 시연 프로그램을 띄운다(콘솔 불필요)
T=/home/pi/.claude/jobs/a8325699/tmp
gpiomon -c gpiochip0 5 > $T/gpiomon.log 2>&1 &
GM=$!
sleep 1
cd /home/pi/sop-project/Rpi5/Demo
DISPLAY=:0 SOP_VOICE_ALERTS=0 timeout 45 python3 -u main.py > $T/gpio_fail_main.log 2>&1 &
MP=$!
sleep 30
DISPLAY=:0 scrot -o $T/gpio_fail.png
sleep 2
kill $MP 2>/dev/null; wait $MP 2>/dev/null
kill $GM 2>/dev/null; wait $GM 2>/dev/null
echo done
