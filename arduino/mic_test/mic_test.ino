/*
 * PDM 마이크 단독 시험 — 음성비서 「가디언」 V0 (부품 0개)
 *
 * 무엇을 확인하는가:
 *   XIAO ESP32S3 **Sense** 확장보드에 내장된 PDM 마이크(MSM261D3526H1CPM)가
 *   실제로 소리를 잡는가. **그것 하나만** 본다.
 *
 * 🔴 여기서 욕심내지 않는다 — 음질·호출어·무선 전송은 각각 V2·V5 다.
 *    한 번에 여러 개를 넣으면 실패했을 때 어디가 문제인지 못 가린다.
 *
 * 핀 (Seeed 공식 예제 기준, 코어 3.0.x+ 문법):
 *   GPIO42 = PDM 클럭 · GPIO41 = PDM 데이터
 *   ⚠️ 카메라(GPIO10~18·38~40·47·48)와 겹치지 않는다 — 동시 사용 가능.
 *   ⚠️ 마이크를 쓰면 D11·D12 를 쓸 수 없다. GPIO41/42 는 ADC 가 없다.
 *
 * 읽는 법:
 *   200ms 마다 RMS(실효값)와 최대 진폭을 막대로 찍는다.
 *   **조용할 때 낮고, 말하거나 손뼉을 치면 확 올라가면 성공**이다.
 *   값이 계속 0 이면 마이크를 못 잡은 것이고, 계속 최대면 배선·설정 문제다.
 *
 * 굽기 (🔴 포트를 반드시 지정할 것 — ttyACM0 은 Arduino 인터록이다):
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 arduino/mic_test
 *   arduino-cli upload -p /dev/ttyACM1 --fqbn esp32:esp32:XIAO_ESP32S3 arduino/mic_test
 */

#include <ESP_I2S.h>

I2SClass I2S;

static const uint32_t SAMPLE_RATE = 16000;   // 설계 §8.2 = 16kHz·16bit·모노
static const size_t   WINDOW      = 3200;    // 200ms 분량
static int16_t        buf[WINDOW];

void setup() {
  Serial.begin(115200);
  delay(1500);                                // USB CDC 가 올라올 때까지
  Serial.println();
  Serial.println("=== PDM 마이크 단독 시험 (XIAO ESP32S3 Sense) ===");
  Serial.printf("설정: %lu Hz · 16bit · 모노 · CLK=GPIO42 · DATA=GPIO41\n",
                (unsigned long)SAMPLE_RATE);

  I2S.setPinsPdmRx(42, 41);                   // (클럭, 데이터)
  if (!I2S.begin(I2S_MODE_PDM_RX, SAMPLE_RATE,
                 I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("[FAIL] I2S PDM 초기화 실패 — Sense 확장보드가 붙어 있는지 확인하라.");
    while (true) delay(1000);
  }
  Serial.println("[OK] I2S 시작. 말하거나 손뼉을 쳐 보세요.");
  Serial.println("     (조용할 때 낮고 소리에 반응해 올라가면 성공)");
  Serial.println();
}

void loop() {
  size_t got = I2S.readBytes((char *)buf, sizeof(buf));
  size_t n = got / sizeof(int16_t);
  if (n == 0) {
    Serial.println("[WARN] 읽은 샘플이 없다 — 드라이버가 데이터를 안 준다.");
    delay(500);
    return;
  }

  // 🔴 DC 오프셋을 먼저 뺀다 — PDM 마이크는 큰 상수 성분을 함께 내보낸다.
  //    빼지 않으면 RMS 가 그 상수에 눌려 **소리를 내도 값이 안 움직인다**
  //    (2026-08-26 실제로 물렸다: RMS≈peak≈1400 고정).
  double mean = 0;
  for (size_t i = 0; i < n; i++) mean += buf[i];
  mean /= n;

  // RMS = 실효값. 평균이 아니라 제곱평균제곱근이라 소리 크기를 대표한다.
  double sq = 0;
  int32_t peak = 0;
  for (size_t i = 0; i < n; i++) {
    double v = buf[i] - mean;
    sq += v * v;
    if (fabs(v) > peak) peak = (int32_t)fabs(v);
  }
  int rms = (int)sqrt(sq / n);

  // 막대 — 로그 스케일. 사람 귀가 로그로 듣고, 선형으로는 작은 소리가 안 보인다.
  int bars = 0;
  if (rms > 0) {
    double db = 20.0 * log10((double)rms / 32768.0);   // dBFS (−90 ~ 0)
    bars = (int)((db + 70.0) / 70.0 * 40.0);           // −70dB~0dB 를 0~40칸
    if (bars < 0) bars = 0;
    if (bars > 40) bars = 40;
  }

  Serial.printf("RMS %5d  peak %5ld  DC %6d  |", rms, (long)peak, (int)mean);
  for (int i = 0; i < bars; i++) Serial.print('#');
  for (int i = bars; i < 40; i++) Serial.print(' ');
  Serial.println('|');
}
