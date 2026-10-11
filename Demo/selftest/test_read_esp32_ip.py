"""안경 IP 읽기 — 포트를 안 주면 메인 안경을 시리얼번호로만 찾는다(인터락을 읽지 않는다) · 부팅 로그의 굽은 값 줄을 보인다.

최종 리뷰 Important 3 · 4(학교 방문 준비) — 실행: python3 Demo/selftest/test_read_esp32_ip.py(가상 시리얼 · 장치 없음)
"""
import os
import pty
import subprocess
import sys
import tempfile
import threading
import time
import tty

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(os.path.dirname(_DEMO_DIR), "arduino", "read_esp32_ip.sh")
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_no_main_board():
    print("\n[포트] 메인 안경(…5D:38)이 by-id 에 없으면 다른 포트(인터락)를 읽지 않고 멈춘다")
    d = tempfile.mkdtemp()
    os.symlink("/dev/null", os.path.join(d, "usb-Arduino_UNO_R4_ABC-if00"))     # 인터락만 꽂힘
    ipf = os.path.join(d, "camera_ip")
    r = subprocess.run(["bash", SCRIPT, "", ipf, "2"], capture_output=True, text=True, timeout=20,
                       env=dict(os.environ, ESP32_BYID_DIR=d))
    check(r.returncode != 0 and "메인 안경" in r.stdout and not os.path.exists(ipf), f"멈춤 · {r.stdout.strip()[:120]}")


def test_main_board_ip_and_camera_line():
    print("\n[읽기] 메인 안경을 시리얼번호로 찾아 IP 를 적고 부팅 로그의 「Camera OK … 굽은 값」 줄을 보인다")
    d = tempfile.mkdtemp()
    m, s = pty.openpty()
    tty.setraw(s)
    os.symlink(os.ttyname(s), os.path.join(d, "usb-Espressif_USB_JTAG_serial_debug_unit_68:EE:8F:4F:5D:38-if00"))
    ipf = os.path.join(d, "camera_ip")

    def talk():
        time.sleep(0.8)
        os.write(m, b"boot\r\nCamera OK jpeg_quality=20 fb_count=3\r\nWiFi connected. SSID: x  IP: 192.168.1.23\r\n")
    threading.Thread(target=talk, daemon=True).start()
    r = subprocess.run(["bash", SCRIPT, "", ipf, "5"], capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, ESP32_BYID_DIR=d))
    os.close(m)
    os.close(s)
    got = open(ipf).read().strip() if os.path.exists(ipf) else None
    check(got == "192.168.1.23", f"IP 기록 {got} · {r.stdout[-200:]}")
    check("jpeg_quality=20 fb_count=3" in r.stdout, "굽은 값 줄을 보인다")


if __name__ == "__main__":
    test_no_main_board()
    test_main_board_ip_and_camera_line()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 안경 IP 읽기 검증 통과")
