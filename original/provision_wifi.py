import os
import sys
import time
import serial
from dotenv import load_dotenv

SERIAL_PORT    = "/dev/ttyACM0"
BAUD_RATE      = 115200
CAMERA_IP_FILE = os.path.join(os.path.dirname(__file__), ".camera_ip")

load_dotenv()

def load_networks():
    networks = []
    i = 1
    while True:
        ssid = os.getenv(f"WIFI_{i}_SSID", "")
        if not ssid:
            break
        password = os.getenv(f"WIFI_{i}_PASSWORD", "")
        networks.append({"ssid": ssid, "password": password})
        i += 1
    return networks

def select_network(networks):
    print("사용할 네트워크를 선택하세요:")
    for idx, net in enumerate(networks, 1):
        label = f"{net['ssid']}" + (" (비밀번호 없음)" if not net["password"] else "")
        print(f"  [{idx}] {label}")
    while True:
        try:
            choice = int(input("선택: "))
            if 1 <= choice <= len(networks):
                return networks[choice - 1]
        except (ValueError, KeyboardInterrupt):
            pass
        print(f"1 ~ {len(networks)} 사이의 숫자를 입력하세요.")

networks = load_networks()
if not networks:
    print("Error: .env 파일에 네트워크 정보가 없습니다.")
    print("WIFI_1_SSID, WIFI_1_PASSWORD 형식으로 추가하세요.")
    sys.exit(1)

selected = select_network(networks)
ssid     = selected["ssid"]
password = selected["password"]

print(f"\n[{ssid}] 네트워크로 연결 시도합니다.")
print(f"Port: {SERIAL_PORT}")

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=15)
    print("ESP32 준비 대기 중...")

    camera_ip = None

    deadline = time.time() + 20
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"ESP32: {line}")
        if "Status: WiFi=OK IP=" in line:
            camera_ip = line.split("IP=")[1].split()[0].strip()
            break
        if "WiFi connected. IP:" in line:
            camera_ip = line.split("IP:")[-1].strip()
            break
        if "No WiFi credentials" in line or "Send credentials" in line:
            break

    if not camera_ip:
        cmd = f"WIFI:{ssid}:{password}\n"
        ser.write(cmd.encode())
        print("자격증명 전송 완료. IP 수신 대기 중...")

        deadline = time.time() + 40
        while time.time() < deadline:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                print(f"ESP32: {line}")
            if "WiFi connected. IP:" in line:
                camera_ip = line.split("IP:")[-1].strip()
                break
            if "Status: WiFi=OK IP=" in line:
                camera_ip = line.split("IP=")[1].split()[0].strip()
                break

    ser.close()

    if camera_ip:
        with open(CAMERA_IP_FILE, "w") as f:
            f.write(camera_ip)
        print(f"\nCamera IP 저장 완료: {camera_ip} → .camera_ip")
        print("python3 main.py 를 실행하세요.")
    else:
        print("\nWarning: ESP32에서 IP를 읽지 못했습니다. 연결 상태를 확인하세요.")

except serial.SerialException as e:
    print(f"Serial 오류: {e}")
    sys.exit(1)
