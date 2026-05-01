import serial, time
import serial.tools.list_ports

def find_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if 'CP210' in p.description or 'CH340' in p.description or 'USB Serial' in p.description or 'USB 직렬' in p.description:
            return p.device
    return ports[0].device if ports else None

while True:
    try:
        port = find_port()
        if not port:
            print('포트 없음. 대기중...')
            time.sleep(1)
            continue
        print(f'포트: {port}')
        s = serial.Serial(port, 115200, timeout=1)
        s.dtr = False  # GPIO0=HIGH (일반 부팅)
        s.rts = True   # EN=LOW (리셋 시작)
        time.sleep(0.1)
        s.rts = False  # EN=HIGH (리셋 해제)
        print('리셋 완료. 출력 대기중...')
        while True:
            line = s.readline()
            if line:
                print(line.decode('utf-8', errors='ignore'), end='', flush=True)
    except serial.SerialException:
        print('재연결 중...')
        time.sleep(0.5)
    except KeyboardInterrupt:
        break
