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
 *   ⚠️ 표의 「차단 ON/OFF」는 **논리**(버튼을 끊느냐)다. NO 접점이라 **CH5 코일·LED 는 반대** —
 *      RUN·WARN = CH5 코일 ON(LED 켜짐 · 버튼 통전) · BLOCK = CH5 코일 OFF(LED 꺼짐 · 버튼 끊김).
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
 *    버려졌다. CH5 가 **B1~B4 의 공통 GND 를 NO 접점으로 이어 두었다가
 *    끊어** 그 주장을 사실로 만든다(평소 코일 ON = 닫힘 · 차단 = 코일 OFF = 열림).
 *
 *    B1 GND ─┐
 *    B2 GND ─┤  와고 5P ├─1가닥─→ [CH5 NO─COM] ─→ Pi GND   (NC 는 비움)
 *    B3 GND ─┤
 *    B4 GND ─┘
 *
 *    🔴 **EMO(GPIO26)는 와고에 넣지 않는다** — NC 배선 fail-safe 라 끊으면
 *       비상정지가 죽는다. 차단 중에도 EMO 는 살아 있어야 한다(설계 §3.2).
 *    🆕 **2026-09-11 개정 — NC → NO**(설계 §11 · 사용자 결정 2026-09-04·09-11).
 *       **NO 접점이라 아두이노·릴레이 전원이 죽으면 버튼도 죽는다**(차단 유지 ·
 *       de-energize to trip = 산업 표준). 대신 USB 가 빠지는 등 **전원을 잃으면**
 *       버튼 4개가 전부 죽어 콘솔이 먹통이 된다 — 사용자가 감수했다.
 *       · 시리얼 데이터만 끊기면(파이 프로그램 종료·포트 닫힘) 릴레이는 마지막 상태 그대로다.
 *       · 아두이노가 리셋되면 부팅 순간만 영향이 있고 끝나면 RUN(버튼 통전)이다. 그래서
 *         BLOCK 중에 리셋되면 파이가 다시 맞출 때까지(재연결 약 3초 + 부팅 대기 2초) 버튼이
 *         살아 있다 — NC 때와 같다(회귀 아님).
 *       🔴 「fail-safe」라는 말은 **전원 상실에만** 해당하고, 실물 검증(설계 §11.5-6 · USB 를
 *       뽑으면 버튼이 죽고 다시 꽂으면 살아남)을 통과한 뒤에만 쓴다(설계 §11.6).
 *    ⚠️ 동시 ON 코일은 최대 2채널(정상 = 녹+CH5 코일 · BLOCK = 적+부저 ≈150mA).
 *       Arduino 5V 급전(방법 A) 유지 — USB 500mA 한계 안이다(설계 §3.4).
 * ─────────────────────────────────────────────────────────────────────────
 *
 * ─────────────────────────────────────────────────────────────────────────
 * ⚠️ 보드 = Arduino UNO R4 **Minima** (WiFi 아님!).
 *    실물 USB PID 0x0069(정상)/0x0369(DFU)로 확인됨. Minima 는 dfu-util,
 *    WiFi 는 bossac 으로 업로드 → FQBN 을 반드시 minima 로 쓸 것.
 *
 * 빌드·업로드 (라즈베리파이, arduino-cli — IDE 아님):
 *   arduino-cli core install arduino:renesas_uno            # 최초 1회
 *   arduino-cli compile --upload -p <포트> --fqbn arduino:renesas_uno:minima console_interlock
 *   # 포트 = 설명에 「UNO R4」 가 든 것(ttyACM 번호는 꽂는 순서로 바뀐다) · compile 없이 upload 만
 *   #   하면 캐시된 옛 바이너리가 조용히 올라갈 수 있다.
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
const int PIN_CUT   = 3;  // IN5 버튼 공통 GND 차단 (BLOCK) — NO 접점: OFF = 버튼이 끊긴다

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
  digitalWrite(PIN_CUT,    cut    ? RELAY_OFF : RELAY_ON);   // NO: 코일 OFF = 끊김
}

void setup() {
  // 초기값을 쓴 뒤 OUTPUT 으로 만든다. ⚠️ 이 보드(Renesas 코어)의 pinMode(OUTPUT) 은 핀 설정을
  //    통째로 다시 써 출력을 LOW(= active LOW 모듈에선 ON)로 만든다 — 앞의 OFF 가 남지 않아
  //    램프·부저가 수 µs ON 이 된다. 릴레이가 붙는 시간(수 ms)보다 훨씬 짧아 실제 영향은 없고,
  //    바로 아래 setRelays() 가 맞춘다. CH5 는 원래 ON(통전)을 원하므로 NO 설계와 무관하다.
  digitalWrite(PIN_RED,    RELAY_OFF);
  digitalWrite(PIN_YELLOW, RELAY_OFF);
  digitalWrite(PIN_GREEN,  RELAY_OFF);
  digitalWrite(PIN_BUZZER, RELAY_OFF);
  digitalWrite(PIN_CUT,    RELAY_ON);    // 🔴 NO: ON = 버튼 통전 — 부팅 중에도 살려 둔다
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
