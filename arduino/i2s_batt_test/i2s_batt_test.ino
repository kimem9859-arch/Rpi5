/*
 * 배터리 구동 전압 강하 시험 — 음성비서 「가디언」 V1 (커패시터 판정)
 *
 * 무엇을 가르는가 (설계 §4.4 · V1 재는 것 ⑥):
 *   앰프가 소리를 낼 때 공유 전원이 주저앉아 **ESP32 가 브라운아웃되는가**,
 *   그리고 그것을 막는 **최소 커패시터 용량**은 얼마인가.
 *
 * 🔑 커패시터는 앰프가 아니라 **ESP32 를 지키는 부품**이다(설계 §4.4).
 *    그래서 판정 대상은 소리 품질이 아니라 **ESP32 가 살아 있는가**이다.
 *
 * 🔴 왜 별도 스케치인가 — `i2s_tone_test`(V0)는 **시리얼 명령 대기형**이라
 *    USB 를 뽑으면 소리를 낼 트리거가 없다. 이 시험은 USB 를 뽑아야 성립하므로
 *    (USB 5V 는 내부저항이 낮고 3.3V 까지 여유가 1.7V 라 강하가 안 나타난다)
 *    **부팅하자마자 스스로 최대 음량으로 우는** 판이 따로 필요하다.
 *
 * 🔑 계측기 없이 판정하는 법 — **부팅음으로 리셋 사유를 알린다.**
 *    ESP32 는 브라운아웃으로 죽으면 재부팅하며 `ESP_RST_BROWNOUT` 을 남긴다.
 *      · 높은 「삑」 1회      = 정상 부팅
 *      · 낮은 「뿌뿌뿌」 3회  = 🔴 브라운아웃 리셋 (= 전압이 무너졌다는 증거)
 *    스윕 도중 낮은 소리가 끼어들면 그 조건은 탈락이다.
 *
 * 시험 절차:
 *   ① USB 로 굽는다 → ② USB 를 뽑는다 → ③ 배터리로 전원 ON → ④ 3분 듣는다
 *   커패시터를 **없음 → 100µF → 220µF** 으로 올려가며 반복(작을수록 유리 — 돌입 전류).
 *   조건마다 **배터리 무부하 전압**을 멀티미터로 적어 둔다.
 *
 * 🔴 전원 ON 순간 부팅음조차 안 나면 그것도 결과다 — **돌입 전류로 부팅 실패**.
 *
 * 결선 (V0 와 동일 · 커패시터만 추가):
 *   DFR0954  VIN ← XIAO 5V   GND ← XIAO GND   SD ← 3V3(왼쪽 채널만)
 *            BCLK ← D0(GPIO1) · LRC ← D1(GPIO2) · DIN ← D2(GPIO3)
 *            OUT+/OUT− → 스피커   🔴 **OUT− 를 GND 에 대면 칩이 파손된다**(BTL)
 *   커패시터 (전해) + → 앰프 VIN 행 · − → 앰프 GND 행, 최대한 가깝게
 *            🔴 극성 반대로 꽂으면 터진다 — 긴 다리가 +, 흰 띠 쪽이 −
 *
 * 굽기 (🔴 ttyACM0 은 Arduino 인터록이다 — 포트를 반드시 지정):
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/i2s_batt_test
 *   arduino-cli upload -p /dev/ttyACM1 --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/i2s_batt_test
 */

#include <ESP_I2S.h>
#include <math.h>
#include <esp_system.h>

#define PIN_BCLK 1    // D0
#define PIN_LRC  2    // D1
#define PIN_DIN  3    // D2

static const uint32_t SAMPLE_RATE = 16000;
static const size_t   CHUNK       = 256;

// 🔴 이 시험은 일부러 최대 음량이다 — 전류를 가장 많이 끌어야 강하가 드러난다.
//    (V0 의 단계 1~5 중 5단계와 같은 값)
static const int AMP_MAX = 15000;

// 리셋을 넘어 살아남는다(전원을 완전히 끊으면 0 으로 돌아간다).
RTC_DATA_ATTR static uint32_t bootCount      = 0;
RTC_DATA_ATTR static uint32_t brownoutCount  = 0;

I2SClass i2s;

static float phase    = 0.0f;
static float sweepPos = 200.0f;

/** 한 음을 정해진 시간만큼 낸다(부팅음 전용 — 블로킹). */
static void beep(float freq, uint32_t ms, int amp) {
  const size_t frames = (size_t)((uint64_t)SAMPLE_RATE * ms / 1000);
  static int16_t buf[CHUNK * 2];
  float ph = 0.0f;
  for (size_t done = 0; done < frames; done += CHUNK) {
    for (size_t i = 0; i < CHUNK; i++) {
      ph += 2.0f * (float)M_PI * freq / (float)SAMPLE_RATE;
      if (ph > 2.0f * (float)M_PI) ph -= 2.0f * (float)M_PI;
      buf[i * 2 + 0] = (int16_t)(sinf(ph) * amp);   // 왼쪽만(SD=3V3)
      buf[i * 2 + 1] = 0;
    }
    i2s.write((uint8_t *)buf, sizeof(buf));
  }
}

/** 무음을 흘린다 — 부팅음 사이를 벌려 귀로 셀 수 있게 한다. */
static void silence(uint32_t ms) {
  const size_t frames = (size_t)((uint64_t)SAMPLE_RATE * ms / 1000);
  static int16_t buf[CHUNK * 2] = {0};
  for (size_t done = 0; done < frames; done += CHUNK)
    i2s.write((uint8_t *)buf, sizeof(buf));
}

void setup() {
  Serial.begin(115200);           // USB 를 꽂고 구울 때만 쓰인다. 배터리 구동엔 없다.

  const esp_reset_reason_t reason = esp_reset_reason();
  const bool brownout = (reason == ESP_RST_BROWNOUT);
  bootCount++;
  if (brownout) brownoutCount++;

  i2s.setPins(PIN_BCLK, PIN_LRC, PIN_DIN);
  if (!i2s.begin(I2S_MODE_STD, SAMPLE_RATE,
                 I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("[FAIL] I2S 초기화 실패 — 핀 번호·결선을 확인하라.");
    while (true) delay(1000);
  }

  // 🔑 부팅음 = 계측기 없는 판정 수단.
  if (brownout) {
    for (int i = 0; i < 3; i++) { beep(400.0f, 150, AMP_MAX / 2); silence(120); }
  } else {
    beep(2000.0f, 200, AMP_MAX / 3);
  }
  silence(400);

  Serial.println();
  Serial.println("=== 배터리 전압 강하 시험 (V1) ===");
  Serial.printf("리셋 사유: %d %s\n", (int)reason,
                brownout ? "🔴 BROWNOUT — 전압이 무너졌다" : "(정상)");
  Serial.printf("부팅 %lu 회 · 그중 브라운아웃 %lu 회  (전원을 끊으면 0 으로 돌아간다)\n",
                (unsigned long)bootCount, (unsigned long)brownoutCount);
  Serial.println("이제 최대 음량 스윕을 반복한다. 스윕 중 낮은 「뿌뿌뿌」가 끼어들면 그 조건은 탈락.");
}

void loop() {
  static int16_t buf[CHUNK * 2];

  for (size_t i = 0; i < CHUNK; i++) {
    phase += 2.0f * (float)M_PI * sweepPos / (float)SAMPLE_RATE;
    if (phase > 2.0f * (float)M_PI) phase -= 2.0f * (float)M_PI;

    buf[i * 2 + 0] = (int16_t)(sinf(phase) * AMP_MAX);   // 왼쪽만
    buf[i * 2 + 1] = 0;

    // 로그 스윕 — 약 8초에 200→4000Hz (V0 와 같은 기울기).
    sweepPos *= 1.0f + (3.0f / (float)SAMPLE_RATE);
    if (sweepPos > 4000.0f) sweepPos = 200.0f;
  }
  i2s.write((uint8_t *)buf, sizeof(buf));
}
