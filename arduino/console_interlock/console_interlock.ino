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
 *   D3 → IN5 → **버튼 공통 GND 차단** (BLOCK) 🆕 2026-09-05
 *
 * 프로토콜 (결선도 §5, 개행 종단):
 *   RUN    → 녹 ON,  적·황·부저·차단 OFF        (정상 가동, 버튼 동작)
 *   WARN   → 황 ON,  녹·적·부저·차단 OFF        (경고 — 🔴 여기서는 끊지 않는다)
 *   BLOCK  → 적+부저+**차단** ON, 녹·황 OFF     (버튼 전기 신호를 실제로 끊는다)
 *   수신할 때마다 "ACK\n" 회신.
 *
 * 부팅 시 안전 초기상태 = 정상(녹 ON, 차단 OFF) → 버튼이 살아 있는 채로 시작.
 * EMO 는 Pi GPIO 가 직접 감지하므로 여기서는 별도 처리 없이 Pi 가 보내는
 * BLOCK 으로 동작한다.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * 🆕 **물리 차단 (2026-09-05)** — 설계 정본 = 상위
 *    `docs/superpowers/specs/2026-09-05-인터록-물리차단-design.md`
 *
 *    종전의 「차단」은 램프 색 + 소프트웨어 무시(`fsm.py` 의 `if state == BLOCK:
 *    return`)였다. 버튼 신호는 끝까지 들어와 로그에 쌓인 뒤 마지막 if 에서만
 *    버려졌다. CH5 가 **B1~B4 의 공통 GND 를 NC 접점으로 끊어** 그 주장을
 *    사실로 만든다.
 *
 *    B1 GND ─┐
 *    B2 GND ─┤  와고 5P ├─1가닥─→ [CH5 COM─NC] ─→ Pi GND
 *    B3 GND ─┤
 *    B4 GND ─┘
 *
 *    🔴 **EMO(GPIO26)는 와고에 넣지 않는다** — NC 배선 fail-safe 라 끊으면
 *       비상정지가 죽는다. 차단 중에도 EMO 는 살아 있어야 한다(설계 §3.2).
 *    ⚠️ **NC 접점이라 전원이 죽으면 버튼이 살아난다**(차단이 풀린다). 산업
 *       표준(de-energize to trip)과 반대 방향이며 **의도된 선택**이다 —
 *       시리얼 끊김 이력 때문에 시연 중 콘솔이 먹통이 되는 쪽을 피했다.
 *       🔴 이 때문에 **이 시스템을 fail-safe 라고 부르지 않는다**(설계 §7-④).
 *    ⚠️ BLOCK 은 3채널 동시 ON = 코일 약 225mA. Arduino 5V 급전(방법 A)
 *       유지 — USB 500mA 한계 안이다(설계 §3.4).
 * ─────────────────────────────────────────────────────────────────────────
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
const int PIN_CUT   = 3;  // IN5 버튼 공통 GND 차단 (BLOCK) — ON = 버튼이 끊긴다

const int RELAY_ON  = LOW;   // active LOW: LOW = 채널 ON
const int RELAY_OFF = HIGH;

String buf = "";  // 시리얼 라인 버퍼

// 릴레이 5채널을 한 번에 설정 (red, yellow, green, buzzer, cut; true=ON)
// 🔴 cut=true 면 버튼 공통 GND 가 끊긴다 — BLOCK 에서만 true 다.
void setRelays(bool red, bool yellow, bool green, bool buzzer, bool cut) {
  digitalWrite(PIN_RED,    red    ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_YELLOW, yellow ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_GREEN,  green  ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_BUZZER, buzzer ? RELAY_ON : RELAY_OFF);
  digitalWrite(PIN_CUT,    cut    ? RELAY_ON : RELAY_OFF);
}

void setup() {
  // 핀을 OUTPUT 으로 만들기 전에 OFF 값을 먼저 써 글리치(순간 ON)를 막는다.
  digitalWrite(PIN_RED,    RELAY_OFF);
  digitalWrite(PIN_YELLOW, RELAY_OFF);
  digitalWrite(PIN_GREEN,  RELAY_OFF);
  digitalWrite(PIN_BUZZER, RELAY_OFF);
  digitalWrite(PIN_CUT,    RELAY_OFF);   // 🔴 OFF = 버튼 통전 — 부팅 중에도 살려 둔다
  pinMode(PIN_RED,    OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN,  OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_CUT,    OUTPUT);

  // 안전 초기상태 = 정상 가동(녹 ON, 차단 OFF → 버튼 동작)
  setRelays(false, false, true, false, false);

  Serial.begin(115200);
  buf.reserve(16);
}

// 한 줄 명령 처리 → 릴레이 제어 → ACK
void handleCommand(const String &cmd) {
  if (cmd == "RUN") {
    setRelays(false, false, true, false, false);  // 녹 ON · 버튼 동작
  } else if (cmd == "WARN") {
    // 🔴 경고에서는 끊지 않는다 — 오경보가 남아 있어(§10.31) 정상 작업 중에도
    //    콘솔이 먹통이 될 수 있다. 「누르기 전에 끊기」는 별도 과제(설계 §2 비목표).
    setRelays(false, true, false, false, false);  // 황 ON · 버튼 동작
  } else if (cmd == "BLOCK") {
    setRelays(true, false, false, true, true);    // 적+부저+**차단** ON, 녹 OFF
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
