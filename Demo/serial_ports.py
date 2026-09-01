"""USB 신원으로 시리얼 장치를 찾는다 — 포트 번호(ttyACM0/1)를 쓰지 않기 위해.

🔴 왜 번호를 안 쓰나: 꽂는 순서·개수에 따라 ttyACM0 과 ttyACM1 이 뒤바뀐다.
   2026-09-01 실제로 config.py 의 INTERLOCK_PORT="/dev/ttyACM0" 이 ESP32 를
   가리키고 있었다(인터록 Arduino 미연결 상태에서 ESP32 가 0번을 차지).
   앞으로 인터록·디스플레이 터치·오디오가 두 포트를 나눠 쓰므로 번호는 못 믿는다.

설계 정본 = docs/superpowers/specs/2026-09-01-글라스-오디오다리-design.md §4.5
"""
from serial.tools import list_ports

# (vid, pid) — XIAO ESP32S3 의 네이티브 USB(USB JTAG/serial). ROM 페리페럴이라
# 앱 펌웨어가 죽어도 이 신원은 사라지지 않는다.
ESP32_S3 = (0x303A, 0x1001)


def resolve(vid, pid=None, serial_number=None):
    """조건에 맞는 첫 장치 경로를 준다. 없으면 None."""
    for p in list_ports.comports():
        if p.vid != vid:
            continue
        if pid is not None and p.pid != pid:
            continue
        if serial_number is not None and p.serial_number != serial_number:
            continue
        return p.device
    return None


def describe():
    """붙어 있는 시리얼 장치를 사람이 읽을 줄로. 진단·오류 메시지용."""
    out = []
    for p in list_ports.comports():
        if p.vid is None:
            continue
        out.append(
            f"{p.device}  vid={p.vid:04x} pid={p.pid:04x}  "
            f"{p.product or '?'}  sn={p.serial_number}"
        )
    return out


if __name__ == "__main__":
    import sys

    # --path : 경로만 한 줄로 (셸에서 $(...) 로 받으려고). 못 찾으면 종료코드 1.
    if "--path" in sys.argv:
        path = resolve(*ESP32_S3)
        if not path:
            print("ESP32-S3 를 못 찾았다", file=sys.stderr)
            sys.exit(1)
        print(path)
        sys.exit(0)

    print("붙어 있는 USB 시리얼 장치:")
    for line in describe() or ["  (없음)"]:
        print("  " + line)
    print()
    print(f"ESP32-S3 → {resolve(*ESP32_S3) or '못 찾음'}")
