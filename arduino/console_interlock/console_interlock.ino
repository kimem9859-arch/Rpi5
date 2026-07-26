/*
 * console_interlock.ino — SOP 가디언 트랙 A 물리 인터락 (Arduino UNO R4)
 *
 * Raspberry Pi(pyserial, interlock.py)에서 한 줄 명령을 받아 릴레이 4채널로
 * 타워램프를 제어하고 ACK 를 회신한다. 설계 정본:
 *   ../../dev/interlock/결선도_초안.md  (§3.2 핀맵 · §4 상태표 · §5 프로토콜)
 *
 * 릴레이 모듈: 8채널 5V SZH-RLBG-009 (칩 JQC-3FF-S-Z), **active LOW**
 *   → 핀 LOW = 채널 ON, 핀 HIGH = 채널 OFF.
 *
 * 핀맵 (결선도 §3.2):
 *   D7 → IN1 → 타워램프 적   (BLOCK)
 *   D6 → IN2 → 타워램프 황   (WARNING)
 *   D5 → IN3 → 타워램프 녹   (정상/RUN)
 *   D4 → IN4 → 부저          (BLOCK)
 *
 * 프로토콜 (결선도 §5, 개행 종단):
 *   RUN    → 녹 ON, 적·황·부저 OFF        (정상 가동)
 *   WARN   → 황 ON, 녹·적·부저 OFF        (경고, 아직 차단 전)
 *   BLOCK  → 적+부저 ON, 녹·황 OFF        (차단 — 녹 OFF 로 가동중단 표시)
 *   수신할 때마다 "ACK\n" 회신.
 *
 * 부팅 시 안전 초기상태 = 정상(녹 ON). EMO 는 Pi GPIO 가 직접 감지하므로
 * 여기서는 별도 처리 없이 Pi 가 보내는 BLOCK 으로 동작한다.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * ⚠️ 보드 = Arduino UNO R4 **Minima** (WiFi 아님!).
 *    실물 USB PID 0x0069(정상)/0x0369(DFU)로 확인됨. Minima 는 dfu-util,
 *    WiFi 는 bossac 으로 업로드 → FQBN 을 반드시 minima 로 쓸 것.
 *
 * 빌드·업로드 (라즈베리파이, arduino-cli — IDE 아님):
 *   arduino-cli core install arduino:renesas_uno            # 최초 1회
 *   arduino-cli compile --fqbn arduino:renesas_uno:minima console_interlock
 *   arduino-cli upload  --fqbn arduino:renesas_uno:minima console_interlock
 *   # 업로드 시 1200bps 터치로 DFU 모드 진입 → dfu-util 자동 플래시.
 *   # DFU 는 raw USB(libusb) 라 권한 필요 — udev 룰 설치 완료:
 *   #   /etc/udev/rules.d/99-arduino-unor4.rules (ATTRS{idVendor}=="2341", MODE="0666")
 *   #   룰 적용 전이면 upload 가 LIBUSB_ERROR_ACCESS → sudo 로 dfu-util 직접 실행.
 * ─────────────────────────────────────────────────────────────────────────
 */

const int PIN_RED   = 7;  // IN1 타워램프 적 (BLOCK)
const int PIN_YELLOW = 6; // IN2 타워램프 황 (WARNING)
const int PIN_GREEN = 5;  // IN3 타워램프 녹 (정상/RUN)
const int PIN_BUZZER = 4; // IN4 부저 (BLOCK)

const int RELAY_ON  = LOW;   // active LOW: LOW = 채널 ON
const int RELAY_OFF = HIGH;

String buf = "";  // 시리얼 라인 버퍼

// 릴레이 4채널을 한 번에 설정 (red, yellow, green, buzzer; true=ON)
void setRelays(bool red, bool yellow, bool green, bool buzzer) {
  digitalWrite(PIN_RED,    red    ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_YELLOW, yellow ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_GREEN,  green  ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_BUZZER, buzzer ? RELAY_ON : RELAY_OFF);
}

void setup() {
  // 핀을 OUTPUT 으로 만들기 전에 OFF 값을 먼저 써 글리치(순간 ON)를 막는다.
  digitalWrite(PIN_RED,    RELAY_OFF);
  digitalWrite(PIN_YELLOW, RELAY_OFF);
  digitalWrite(PIN_GREEN,  RELAY_OFF);
  digitalWrite(PIN_BUZZER, RELAY_OFF);
  pinMode(PIN_RED,    OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN,  OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  // 안전 초기상태 = 정상 가동(녹 ON)
  setRelays(false, false, true, false);

  Serial.begin(115200);
  buf.reserve(16);
}

// 한 줄 명령 처리 → 릴레이 제어 → ACK
void handleCommand(const String &cmd) {
  if (cmd == "RUN") {
    setRelays(false, false, true, false);   // 녹 ON
  } else if (cmd == "WARN") {
    setRelays(false, true, false, false);   // 황 ON
  } else if (cmd == "BLOCK") {
    setRelays(true, false, false, true);    // 적 + 부저 ON, 녹 OFF
  } else {
    // 미지 명령: 안전을 위해 상태 변경 없이 ACK 만 (Pi 가 로그로 감지)
  }
  Serial.print("ACK\n");
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length() > 0) {
        handleCommand(buf);
        buf = "";
      }
    } else if (buf.length() < 15) {
      buf += c;
    } else {
      buf = "";  // 오버플로 방지 — 비정상 입력 폐기
    }
  }
}
