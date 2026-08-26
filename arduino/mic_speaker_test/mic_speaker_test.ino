/*
 * 마이크 녹음 → 스피커 재생 — 음성비서 「가디언」 명료도 예비 확인
 *
 * 무엇을 확인하는가:
 *   **자기 목소리가 이 스피커로 알아들리는가.** 톤이 잘 들리는 것과 말이
 *   알아들리는 것은 다르다(설계 §4.3 — *"귀 옆 5cm 에서 알아들리는가는
 *   사양표로 알 수 없다"*). V6(명료도)의 예비 감각을 잡는 것이 목적이다.
 *
 * 🔴 실시간 루프백이 아니라 **녹음 후 재생**이다 — 마이크와 스피커가 가까워
 *    루프백을 하면 하울링(삐— 피드백)이 나고, 자기 목소리도 온전히 못 듣는다.
 *
 * 🔴 I2S 컨트롤러를 나눠 쓴다 — ESP32-S3 의 **PDM 수신은 I2S0 에서만** 지원된다.
 *    마이크=I2S_NUM_0(PDM RX) · 스피커=I2S_NUM_1(STD TX).
 *
 * 🔴 PDM 은 DC 오프셋(약 1000~1600)을 함께 내보낸다 — 빼지 않고 재생하면
 *    스피커가 한쪽으로 밀린 채 울려 소리가 뭉갠다(2026-08-26 마이크 시험에서 확인).
 *
 * 결선:
 *   마이크 (확장보드 온보드 PDM)  GPIO42=CLK · GPIO41=DATA
 *   스피커 (DFR0954 MAX98357A)   GPIO1=BCLK(D0) · GPIO2=LRC(D1) · GPIO3=DIN(D2)
 *     VIN←5V · GND←GND · SD←3V3(왼쪽 채널만 모드) · GAIN 미연결(9dB)
 *     🔴 OUT− 를 GND 에 대지 말 것 — BTL 출력이라 칩이 파손된다.
 *
 * 시리얼 명령 (115200):
 *   r : 3초 녹음 후 자동 재생      p : 마지막 녹음 다시 재생
 *   1~5 : 재생 음량                i : 마지막 녹음 통계
 *
 * 굽기 (🔴 ttyACM0 은 Arduino 인터록):
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 arduino/mic_speaker_test
 *   arduino-cli upload -p /dev/ttyACM1 --fqbn esp32:esp32:XIAO_ESP32S3 arduino/mic_speaker_test
 */

#include <ESP_I2S.h>
#include <math.h>

#define MIC_CLK   42
#define MIC_DATA  41
#define SPK_BCLK   1    // D0
#define SPK_LRC    2    // D1
#define SPK_DIN    3    // D2

static const uint32_t RATE     = 16000;
static const uint32_t REC_SEC  = 3;
static const size_t   N_SAMPLE = RATE * REC_SEC;      // 48,000 샘플 = 96KB

I2SClass mic;
I2SClass spk;

static int16_t rec[N_SAMPLE];
static bool    hasRec = false;

// 재생 목표 진폭 — 녹음 크기가 매번 달라지므로 **정규화**해서 일정하게 들려준다.
static const int TARGET[5] = {2000, 4000, 6000, 9000, 13000};
static int volIdx = 2;

// 마지막 녹음 통계 (판단 근거로 남긴다)
static int lastDC = 0, lastPeak = 0, lastRms = 0;

// 🔑 녹음 시작·끝을 **스피커로 알린다** — 시리얼 출력은 말하는 사람이 볼 수 없어
//    타이밍이 어긋난다(2026-08-26 실제로 신호가 -41dBFS 로 잡혔다).
void beep(int freq, int ms, int amp = 5000) {
  static int16_t f[128 * 2];
  float ph = 0;
  int total = RATE * ms / 1000;
  for (int done = 0; done < total; ) {
    int n = 0;
    while (n < 128 && done < total) {
      ph += 2.0f * (float)M_PI * freq / (float)RATE;
      f[n * 2 + 0] = (int16_t)(sinf(ph) * amp);
      f[n * 2 + 1] = 0;
      n++; done++;
    }
    spk.write((uint8_t *)f, n * 2 * sizeof(int16_t));
  }
}

void record() {
  Serial.println("[녹음] 신호음 3번 뒤 3초간 녹음합니다.");
  // 카운트다운 — 낮은 톤 3번, 그다음 높은 톤이 「지금 말하세요」
  for (int i = 0; i < 3; i++) { beep(660, 120); delay(380); }
  beep(1320, 200);
  delay(150);                                  // 신호음 잔향이 녹음에 섞이지 않게

  size_t got = 0;
  while (got < N_SAMPLE) {
    size_t want = (N_SAMPLE - got) * sizeof(int16_t);
    size_t n = mic.readBytes((char *)(rec + got), want);
    if (n == 0) break;
    got += n / sizeof(int16_t);
  }
  if (got < N_SAMPLE / 2) {
    Serial.printf("[FAIL] 샘플이 부족하다(%u) — 마이크를 못 읽었다.\n", (unsigned)got);
    hasRec = false;
    return;
  }

  // ① DC 오프셋 제거
  double sum = 0;
  for (size_t i = 0; i < got; i++) sum += rec[i];
  int dc = (int)(sum / got);

  double sq = 0;
  int peak = 0;
  for (size_t i = 0; i < got; i++) {
    int v = rec[i] - dc;
    rec[i] = (int16_t)v;
    sq += (double)v * v;
    if (abs(v) > peak) peak = abs(v);
  }
  lastDC = dc;
  lastPeak = peak;
  lastRms = (int)sqrt(sq / got);
  hasRec = true;

  beep(880, 90); delay(60); beep(880, 90);     // 끝났음을 알린다
  Serial.printf("[녹음 완료] %u샘플 · DC %d · RMS %d · peak %d (%.1f dBFS)\n",
                (unsigned)got, lastDC, lastRms, lastPeak,
                peak > 0 ? 20.0 * log10((double)peak / 32768.0) : -99.0);
  if (peak < 300) Serial.println("  ⚠️ 신호가 매우 작다 — 마이크에 더 가까이 말해 보라.");
}

void play() {
  if (!hasRec) {
    Serial.println("[재생] 녹음이 없다. 먼저 r 을 누르라.");
    return;
  }
  // ② 정규화 — 녹음 크기가 들쭉날쭉해도 일정한 음량으로 들려준다.
  float gain = (lastPeak > 0) ? (float)TARGET[volIdx] / lastPeak : 1.0f;
  Serial.printf("[재생] 목표 진폭 %d · 배율 %.1f배\n", TARGET[volIdx], gain);

  static int16_t frame[256 * 2];
  size_t i = 0;
  while (i < N_SAMPLE) {
    size_t n = 0;
    while (n < 256 && i < N_SAMPLE) {
      int v = (int)(rec[i] * gain);
      if (v > 32767) v = 32767;
      if (v < -32768) v = -32768;
      frame[n * 2 + 0] = (int16_t)v;    // 🔴 왼쪽 = 신호 (SD=3V3 → 왼쪽만 재생)
      frame[n * 2 + 1] = 0;
      n++; i++;
    }
    spk.write((uint8_t *)frame, n * 2 * sizeof(int16_t));
  }
  Serial.println("[재생 완료]");
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println();
  Serial.println("=== 마이크 녹음 → 스피커 재생 ===");

  // 마이크 — PDM 은 I2S0 에서만 된다
  if (!mic.setPort(I2S_NUM_0)) {
    Serial.println("[FAIL] 마이크 포트 설정 실패");
    while (true) delay(1000);
  }
  mic.setPinsPdmRx(MIC_CLK, MIC_DATA);
  if (!mic.begin(I2S_MODE_PDM_RX, RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("[FAIL] 마이크 초기화 실패 — 확장보드 결합을 확인하라.");
    while (true) delay(1000);
  }

  // 스피커 — 표준 I2S 송신은 I2S1
  if (!spk.setPort(I2S_NUM_1)) {
    Serial.println("[FAIL] 스피커 포트 설정 실패");
    while (true) delay(1000);
  }
  spk.setPins(SPK_BCLK, SPK_LRC, SPK_DIN);
  if (!spk.begin(I2S_MODE_STD, RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("[FAIL] 스피커 초기화 실패 — 핀·결선을 확인하라.");
    while (true) delay(1000);
  }

  Serial.println("[OK] 마이크(I2S0/PDM) + 스피커(I2S1/STD) 준비됨");
  Serial.printf("     마이크 CLK=GPIO%d DATA=GPIO%d · 스피커 BCLK=GPIO%d LRC=GPIO%d DIN=GPIO%d\n",
                MIC_CLK, MIC_DATA, SPK_BCLK, SPK_LRC, SPK_DIN);
  Serial.println("명령: r 녹음+재생 · p 다시 재생 · 1~5 음량 · i 통계");
}

void loop() {
  if (!Serial.available()) { delay(20); return; }
  char c = Serial.read();
  if (c == 'r') {
    record();
    if (hasRec) { delay(200); play(); }
  } else if (c == 'p') {
    play();
  } else if (c >= '1' && c <= '5') {
    volIdx = c - '1';
    Serial.printf("[음량] 목표 진폭 %d (단계 %d/5)\n", TARGET[volIdx], volIdx + 1);
  } else if (c == 'i') {
    if (hasRec) {
      Serial.printf("[통계] DC %d · RMS %d · peak %d\n", lastDC, lastRms, lastPeak);
    } else {
      Serial.println("[통계] 녹음 없음");
    }
  }
}
