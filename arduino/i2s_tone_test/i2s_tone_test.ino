/*
 * I2S 앰프·스피커 단독 확인 — 음성비서 「가디언」 V0
 *
 * 무엇을 확인하는가 (설계 §6 V0):
 *   ① 소리가 나는가  ② 잡음 수준  ③ 음량 단계별 크기
 *   ④ 🔑 **실제 사용 가능한 I2S 핀 번호 확정** (원래 V1 항목 — 여기서 미리 처리)
 *
 * 🔴 왜 예비 XIAO 인가 — 설계는 V0 를 「Pi5 직결」로 잡았으나, Pi5 는
 *    `dtoverlay=hifiberry-dac` 를 켜야 하고 그러면 **GPIO19 가 I2S LRCLK 로 넘어가
 *    인터록 B4 버튼이 죽는다**(config.py GPIO_BUTTON_PINS). 재부팅도 필요하다.
 *    카메라 없는 예비 XIAO + USB 급전이면 그 비용 없이 같은 것을 가른다.
 *
 * 결선 (V0 = USB 5V 급전, 카메라 OFF, 커패시터 불필요):
 *   DFR0954  VIN  ← XIAO 5V     🔴 3V3 에서 뽑지 말 것(MCU 젖줄, §5.3-①)
 *            GND  ← XIAO GND
 *            BCLK ← D0 (GPIO1)
 *            LRC  ← D1 (GPIO2)
 *            DIN  ← D2 (GPIO3)
 *            SD   ← 3V3        → 1.4V 초과 = **왼쪽 채널만** 모드(§5.3-③)
 *            GAIN ── 미연결 (기본 9dB)
 *            OUT+/OUT− → 스피커  🔴 **OUT− 를 GND 에 대면 칩이 파손된다**(BTL, §5.3-④)
 *
 * 🔴 SD=3V3 이라 **왼쪽 채널만** 나온다 → 모노를 **왼쪽에 싣는다**(오른쪽은 0).
 *    이걸 모르면 소리가 작거나 안 날 때 「음량 문제」로 오진한다.
 *
 * 시리얼 명령 (115200):
 *   1~5 : 음량 단계        f : 주파수 순환(220·440·880·2k Hz)
 *   w   : 스윕 200Hz~4kHz  s : 정지/재생
 *
 * 굽기 (🔴 ttyACM0 은 Arduino 인터록이다 — 포트를 반드시 지정):
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 arduino/i2s_tone_test
 *   arduino-cli upload -p /dev/ttyACM1 --fqbn esp32:esp32:XIAO_ESP32S3 arduino/i2s_tone_test
 */

#include <ESP_I2S.h>
#include <math.h>

#define PIN_BCLK 1    // D0
#define PIN_LRC  2    // D1
#define PIN_DIN  3    // D2

static const uint32_t SAMPLE_RATE = 16000;   // 설계 §8.2 = 16kHz
static const size_t   CHUNK       = 256;     // 프레임 수(L+R 한 쌍 = 1프레임)

I2SClass i2s;

// 🔴 처음부터 크게 울리지 않는다 — 스피커·귀 보호. 단계는 시리얼로 올린다.
static const int VOL_TABLE[5] = {800, 2000, 4000, 8000, 15000};
static int   volIdx   = 1;
static float freqHz   = 440.0f;
static bool  playing  = true;
static bool  sweeping = false;

static float phase    = 0.0f;
static float sweepPos = 200.0f;

void printState() {
  Serial.printf("[상태] %s · %s · 진폭 %d/32767 (단계 %d/5)\n",
                playing ? "재생" : "정지",
                sweeping ? "스윕 200~4000Hz" : String(String((int)freqHz) + "Hz").c_str(),
                VOL_TABLE[volIdx], volIdx + 1);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println();
  Serial.println("=== I2S 앰프·스피커 단독 확인 (V0) ===");
  Serial.printf("핀: BCLK=GPIO%d(D0) · LRC=GPIO%d(D1) · DIN=GPIO%d(D2)\n",
                PIN_BCLK, PIN_LRC, PIN_DIN);

  i2s.setPins(PIN_BCLK, PIN_LRC, PIN_DIN);
  if (!i2s.begin(I2S_MODE_STD, SAMPLE_RATE,
                 I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("[FAIL] I2S 초기화 실패 — 핀 번호·결선을 확인하라.");
    while (true) delay(1000);
  }
  Serial.println("[OK] I2S 시작. 스피커에서 톤이 들려야 한다.");
  Serial.println("     소리가 안 나면 ① SD 가 3V3 에 붙었는지 ② OUT+/OUT− 결선 ③ VIN 이 5V 인지 확인.");
  Serial.println("명령: 1~5 음량 · f 주파수 · w 스윕 · s 정지/재생");
  printState();
}

void handleSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c >= '1' && c <= '5') {
      volIdx = c - '1';
      printState();
    } else if (c == 'f') {
      static const float FREQS[4] = {220, 440, 880, 2000};
      static int fi = 1;
      fi = (fi + 1) % 4;
      freqHz = FREQS[fi];
      sweeping = false;
      printState();
    } else if (c == 'w') {
      sweeping = !sweeping;
      sweepPos = 200.0f;
      printState();
    } else if (c == 's') {
      playing = !playing;
      printState();
    }
  }
}

void loop() {
  handleSerial();

  static int16_t buf[CHUNK * 2];              // L,R 교대
  int amp = playing ? VOL_TABLE[volIdx] : 0;

  for (size_t i = 0; i < CHUNK; i++) {
    float f = sweeping ? sweepPos : freqHz;
    phase += 2.0f * (float)M_PI * f / (float)SAMPLE_RATE;
    if (phase > 2.0f * (float)M_PI) phase -= 2.0f * (float)M_PI;

    int16_t v = (int16_t)(sinf(phase) * amp);
    buf[i * 2 + 0] = v;                       // 🔴 왼쪽 = 신호 (SD=3V3 → 왼쪽만 재생)
    buf[i * 2 + 1] = 0;                       //    오른쪽 = 무음

    if (sweeping) {
      // 로그 스윕 — 사람 귀가 로그로 듣는다. 약 8초에 200→4000Hz.
      sweepPos *= 1.0f + (3.0f / (float)SAMPLE_RATE);
      if (sweepPos > 4000.0f) sweepPos = 200.0f;
    }
  }
  i2s.write((uint8_t *)buf, sizeof(buf));
}
