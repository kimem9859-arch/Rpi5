import time
import subprocess
import requests
import sys

ip = "10.220.25.235"
mode = "hotspot"
if len(sys.argv) > 1:
    ip = sys.argv[1]
if len(sys.argv) > 2:
    mode = sys.argv[2]

log_file = f"/home/pi/claude-project/camera_stream/latency_log_{mode}.txt"
log_f = open(log_file, "w")

def log(msg=""):
    print(msg)
    log_f.write(msg + "\n")
    log_f.flush()

log(f"=== ESP32 네트워크 지연시간 측정 [{mode.upper()}] ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===")
log(f"대상: {ip}\n")

# 1. Ping 테스트 (10회)
log("--- Ping 테스트 (10회) ---")
result = subprocess.run(
    ["ping", "-c", "10", "-i", "0.5", ip],
    capture_output=True, text=True
)
for line in result.stdout.strip().split('\n'):
    log(line)

# 2. HTTP 응답 시간 테스트
log("\n--- HTTP 응답 시간 테스트 (10회) ---")
http_times = []
for i in range(10):
    try:
        start = time.time()
        r = requests.get(f"http://{ip}/", stream=True, timeout=5)
        for chunk in r.iter_content(chunk_size=1024):
            break
        r.close()
        elapsed = (time.time() - start) * 1000
        http_times.append(elapsed)
        log(f"  #{i+1}: {elapsed:.1f} ms")
    except Exception as e:
        log(f"  #{i+1}: 실패 - {e}")
    time.sleep(0.5)

if http_times:
    log(f"\n  평균: {sum(http_times)/len(http_times):.1f} ms")
    log(f"  최소: {min(http_times):.1f} ms")
    log(f"  최대: {max(http_times):.1f} ms")

# 3. 전송 속도 테스트 (5초간 스트림 수신)
log("\n--- 전송 속도 테스트 (5초간) ---")
try:
    r = requests.get(f"http://{ip}/", stream=True, timeout=5)
    total = 0
    frames = 0
    buf = b''
    start = time.time()

    for chunk in r.iter_content(chunk_size=4096):
        total += len(chunk)
        buf += chunk

        while True:
            s = buf.find(b'\xff\xd8')
            e = buf.find(b'\xff\xd9')
            if s == -1 or e == -1 or e <= s:
                break
            buf = buf[e+2:]
            frames += 1

        if time.time() - start > 5:
            break

    r.close()
    elapsed = time.time() - start
    speed_kbs = (total / 1024) / elapsed
    log(f"  수신 데이터: {total:,} bytes")
    log(f"  수신 시간: {elapsed:.1f}초")
    log(f"  전송 속도: {speed_kbs:.1f} KB/s")
    log(f"  프레임 수: {frames}")
    log(f"  평균 FPS: {frames/elapsed:.1f}")
    if frames > 0:
        log(f"  평균 프레임 크기: {total//frames:,} bytes")

except Exception as e:
    log(f"  실패: {e}")

# 4. 결론
log("\n--- 분석 결과 ---")
if http_times:
    avg_http = sum(http_times) / len(http_times)
    if avg_http < 50:
        log("  HTTP 지연: 양호 (<50ms)")
    elif avg_http < 200:
        log("  HTTP 지연: 보통 (50~200ms)")
    else:
        log("  HTTP 지연: 느림 (>200ms)")

if 'speed_kbs' in dir():
    log(f"  전송 속도: {speed_kbs:.1f} KB/s")
    need_kbs = 20 * 28
    log(f"  640x480 28FPS 필요 속도: ~{need_kbs} KB/s")
    log(f"  현재 대비: {speed_kbs/need_kbs*100:.1f}% 충족")

log_f.close()
log(f"\n로그 저장: {log_file}")
