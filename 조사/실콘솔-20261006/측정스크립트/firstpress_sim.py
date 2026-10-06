"""재부팅 직후(GPIO≥9 풀다운) 시연과 같은 gpiozero Button 이 첫 누름을 받는지 — 누름은 pinctrl pd/pu 로 흉내."""
import subprocess, sys, time
sys.path.insert(0, '.')
import config
from gpiozero import Button
start = sys.argv[1]                       # 'pd' = 재부팅 직후 · 'pu' = 대조
pin = 13
subprocess.run(['pinctrl', 'set', str(pin), 'ip', start]); time.sleep(0.3)
ev = []
b = Button(pin, pull_up=True, bounce_time=config.GPIO_BOUNCE_SEC)
b.when_pressed = lambda: ev.append('pressed'); b.when_released = lambda: ev.append('released')
time.sleep(0.8)
for _ in range(2):
    subprocess.run(['pinctrl', 'set', str(pin), 'ip', 'pd']); time.sleep(0.5)
    subprocess.run(['pinctrl', 'set', str(pin), 'ip', 'pu']); time.sleep(0.5)
b.close()
print(f"시작 {start}: 흉내 누름 2번 → {ev} · when_pressed {ev.count('pressed')}회")
