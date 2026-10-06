"""안경 화면 밝기 재기 — 장소1 사진(중앙 107 · 10~90% 79~141)과 비교. 프레임 1장을 PNG 로 남긴다."""
import os, sys, time, cv2, numpy as np
D = '/home/pi/sop-project/Rpi5/Demo'
sys.path.insert(0, D + '/test'); sys.path.insert(0, D); os.chdir(D)
import config
from bench_detector import _connect_tcp, _recv_latest_frame
import frame_orient
host = open('.camera_ip').read().strip() if os.path.exists('.camera_ip') else config.ESP32_IP
s = _connect_tcp(host); _recv_latest_frame(s)
m = []; dark = []; img = None
t0 = time.time()
while time.time() - t0 < 3:
    b = _recv_latest_frame(s)
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); m.append(g.mean()); dark.append((g < 30).mean() * 100)
s.close()
out = sys.argv[1] if len(sys.argv) > 1 else '/home/pi/.claude/jobs/a8325699/tmp/bright.png'
try:
    img = frame_orient.apply(img)
except Exception:
    pass
cv2.imwrite(out, img)
print(f"{len(m)}장 · 평균 밝기 중앙 {np.median(m):.0f} (범위 {min(m):.0f}~{max(m):.0f}) · 어두운 화소(<30) {np.median(dark):.1f}% · 저장 {out}")
