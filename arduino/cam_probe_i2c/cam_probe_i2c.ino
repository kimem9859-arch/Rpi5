/*
 * 카메라 SCCB(I2C) 진단 — 「Detected camera not supported」의 원인 가르기
 *
 * 🔴 OV 센서는 **XCLK 가 돌아야** SCCB 에 응답한다. 그냥 I2C 스캔만 하면
 *    멀쩡한 카메라도 「없음」으로 나온다 — 그래서 LEDC 로 20MHz 를 먼저 태운다.
 *
 * 판정:
 *   · 주소가 하나도 안 잡힌다  → 카메라가 전기적으로 연결돼 있지 않다(리본·확장보드)
 *   · 0x30 응답               → OV2640
 *   · 0x3C 응답               → OV3660 (XIAO Sense 기본)
 *   · 다른 주소               → 다른 센서
 */
#include <Wire.h>
#include <driver/ledc.h>

#define XCLK_PIN 10
#define SIOD_PIN 40
#define SIOC_PIN 39

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n=== 카메라 SCCB 진단 ===");

  Wire.begin(SIOD_PIN, SIOC_PIN, 100000);
  Serial.println("I2C: SDA=GPIO40 SCL=GPIO39 @100kHz");

  // 🔑 클럭 주파수를 바꿔가며 스캔한다 — ledcAttach 가 실패했거나 20MHz 가
  //    이 코어에서 안 나오면, 멀쩡한 센서도 「없음」으로 나온다. 그 의심을 닫는다.
  const uint32_t FREQS[3] = {0, 10000000, 20000000};
  int total = 0;
  for (int k = 0; k < 3; k++) {
    if (FREQS[k] == 0) {
      ledcDetach(XCLK_PIN);
      Serial.println("\n[XCLK 없음 — 대조군]");
    } else {
      bool ok = ledcAttach(XCLK_PIN, FREQS[k], 1);
      ledcWrite(XCLK_PIN, 1);
      Serial.printf("\n[XCLK %lu MHz] ledcAttach=%s · 실제 주파수 %lu Hz\n",
                    (unsigned long)(FREQS[k] / 1000000), ok ? "성공" : "🔴실패",
                    (unsigned long)ledcReadFreq(XCLK_PIN));
      delay(200);
    }
    int found = 0;
    for (uint8_t a = 1; a < 127; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) { Serial.printf("  ✅ 응답: 0x%02X\n", a); found++; }
    }
    if (!found) Serial.println("  🔴 응답 없음");
    total += found;
  }
  const int found = total;

  // OV3660 (16비트 레지스터) PID/VER 읽기 시도
  Wire.beginTransmission(0x3C);
  Wire.write(0x30); Wire.write(0x0A);
  if (Wire.endTransmission(false) == 0 && Wire.requestFrom((uint8_t)0x3C, (uint8_t)2) == 2) {
    uint8_t p = Wire.read(), v = Wire.read();
    Serial.printf("OV3660? PID=0x%02X VER=0x%02X (기대 0x36 0x60)\n", p, v);
  } else {
    Serial.println("OV3660 PID 읽기 실패");
  }

  // OV2640 (8비트) PID/VER
  Wire.beginTransmission(0x30);
  Wire.write(0x0A);
  if (Wire.endTransmission(false) == 0 && Wire.requestFrom((uint8_t)0x30, (uint8_t)2) == 2) {
    uint8_t p = Wire.read(), v = Wire.read();
    Serial.printf("OV2640? PID=0x%02X VER=0x%02X (기대 0x26 0x42)\n", p, v);
  } else {
    Serial.println("OV2640 PID 읽기 실패");
  }
  // ── SCCB 선의 전기적 상태 — 카메라가 물려 있으면 풀업이 잡혀 HIGH 다 ──
  // 🔑 마이크는 핀 2개(41/42), 카메라는 14개다. XIAO↔확장보드 B2B 커넥터가
  //    한쪽만 살짝 뜨면 「마이크는 되는데 카메라만 죽는」 모습이 나온다.
  //    풀업이 읽히면 최소한 그 선의 전기적 경로는 살아 있다는 뜻이다.
  pinMode(SIOD_PIN, INPUT);  pinMode(SIOC_PIN, INPUT);
  delay(5);
  int d_f = digitalRead(SIOD_PIN), c_f = digitalRead(SIOC_PIN);
  pinMode(SIOD_PIN, INPUT_PULLDOWN);  pinMode(SIOC_PIN, INPUT_PULLDOWN);
  delay(5);
  int d_p = digitalRead(SIOD_PIN), c_p = digitalRead(SIOC_PIN);
  Serial.printf("SDA(40): 플로팅=%d 내부풀다운=%d\n", d_f, d_p);
  Serial.printf("SCL(39): 플로팅=%d 내부풀다운=%d\n", c_f, c_p);
  Serial.println(( d_p && c_p )
    ? "→ 외부 풀업이 잡힌다: SCCB 선의 전기적 경로는 살아 있다(센서만 무응답)"
    : "→ 외부 풀업이 없다: 카메라 쪽으로 가는 선이 끊겨 있다(B2B·FPC 접촉 의심)");

  Serial.println("=== 끝 ===");
}

void loop() { delay(5000); }
