/*
 * 마이크 녹음 → 스피커 재생 + 파이↔ESP32 오디오 다리 — 음성비서 「가디언」
 *
 * 무엇을 확인하는가:
 *   **자기 목소리가 이 스피커로 알아들리는가.** 톤이 잘 들리는 것과 말이
 *   알아들리는 것은 다르다(설계 §4.3 — *"귀 옆 5cm 에서 알아들리는가는
 *   사양표로 알 수 없다"*). V6(명료도)의 예비 감각을 잡는 것이 목적이다.
 *
 * 🆕 2026-09-01 — 파이와 wav 를 주고받는 길을 더했다(V1.5).
 *   그전까지는 ESP32 안에서 소리가 나고 ESP32 안에서 끝나, 명료도 판정도
 *   STT 재측정도 둘 다 막혀 있었다.
 *   설계 정본 = docs/superpowers/specs/2026-09-01-글라스-오디오다리-design.md
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
 *   [V0]  r : 3초 녹음 후 자동 재생   p : 마지막 녹음 다시 재생
 *         1~5 : 재생 음량             i : 통계
 *   [V1.5 다리]
 *         W <샘플수> <레이트>\n + int16LE 페이로드 + uint32LE 체크섬 : 적재
 *         P\n                : 담긴 것 재생
 *         R <초>\n           : 길이를 지정해 녹음 (최대 10초)
 *         D\n                : 담긴 것을 파이로 덤프
 *   짝이 되는 파이 도구 = esp32_audio.py (같은 폴더). 🔴 프로토콜을 공유하므로
 *   한쪽만 고치면 조용히 어긋난다.
 *
 * 굽기 — 🔴 포트 번호를 믿지 말 것. 꽂는 순서에 따라 ttyACM0/1 이 뒤바뀐다.
 *   PORT=$(python3 Demo/serial_ports.py --path)
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/mic_speaker_test
 *   arduino-cli upload -p "$PORT" --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/mic_speaker_test
 *   🔴 PSRAM=opi 필수 — 빠뜨리면 ps_malloc 이 NULL 을 낸다(기본값이 disabled).
 */

#include <ESP_I2S.h>
#include <math.h>

#define MIC_CLK   42
#define MIC_DATA  41
#define SPK_BCLK   1    // D0
#define SPK_LRC    2    // D1
#define SPK_DIN    3    // D2

static const uint32_t RATE       = 16000;        // 🔴 마이크 고정 (설계 §8.2)
static const uint32_t MAX_SEC    = 10;
static const uint32_t MAX_RATE   = 24000;
static const size_t   MAX_SAMPLE = MAX_SEC * MAX_RATE;   // 240,000 샘플 = 480KB

I2SClass mic;
I2SClass spk;

// 🔴 PSRAM 에 잡는다 — 내부 SRAM 에는 480KB 가 안 들어간다.
static int16_t *rec     = nullptr;
static size_t   nRec    = 0;            // 지금 담겨 있는 샘플 수
static uint32_t recRate = RATE;         // 담겨 있는 것의 샘플레이트
static bool     hasRec  = false;
static uint32_t spkRate = RATE;         // 스피커 I2S 가 지금 열려 있는 레이트

// 재생 목표 진폭 — 녹음 크기가 매번 달라지므로 **정규화**해서 일정하게 들려준다.
static const int TARGET[5] = {2000, 4000, 6000, 9000, 13000};
static int volIdx = 2;

// 마지막 녹음 통계 (판단 근거로 남긴다)
static int lastDC = 0, lastPeak = 0, lastRms = 0;

// ── 전송 계층 ────────────────────────────────────────────────
// 🔑 Serial(USB CDC)과 WiFiClient 는 둘 다 Stream 을 상속한다.
//    그래서 아래 코드는 유선인지 무선인지 모른 채로 동작하고,
//    무선 전환은 이 포인터 하나를 바꾸는 일이 된다(설계 §4.1).
static Stream *io = &Serial;

static uint32_t checksum(const int16_t *p, size_t n) {
  uint32_t s = 0;
  for (size_t i = 0; i < n; i++) s += (uint16_t)p[i];   // 오버플로 허용
  return s;
}

// 개행까지 한 줄을 읽는다. 타임아웃이면 지금까지 읽은 것.
static String readLine(uint32_t ms = 2000) {
  String s;
  uint32_t t0 = millis();
  while (millis() - t0 < ms) {
    while (io->available()) {
      char c = io->read();
      if (c == '\n') return s;
      if (c != '\r') s += c;
      t0 = millis();
    }
    delay(1);
  }
  return s;
}

// 정확히 len 바이트를 채운다. 🔴 여기서 블로킹으로 읽기 때문에
//    오디오 안에 'r'·'p' 바이트가 섞여도 명령으로 오해되지 않는다.
//    실패하면 몇 바이트에서 멈췄는지 남긴다 — 원인 규명에 그 숫자가 필요하다.
static size_t lastGot = 0;
static bool readExact(uint8_t *dst, size_t len, uint32_t ms = 15000) {
  size_t got = 0;
  uint32_t t0 = millis();
  while (got < len && millis() - t0 < ms) {
    int n = io->readBytes((char *)dst + got, len - got);
    if (n > 0) { got += n; t0 = millis(); }
  }
  lastGot = got;
  return got == len;
}

// 스피커 I2S 를 원하는 레이트로 (필요할 때만) 다시 연다.
static bool setSpkRate(uint32_t r) {
  if (r == spkRate) return true;
  spk.end();
  spk.setPins(SPK_BCLK, SPK_LRC, SPK_DIN);
  if (!spk.begin(I2S_MODE_STD, r, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.printf("[FAIL] 스피커를 %luHz 로 열지 못했다.\n", (unsigned long)r);
    return false;
  }
  spkRate = r;
  return true;
}

// 🔑 녹음 시작·끝을 **스피커로 알린다** — 시리얼 출력은 말하는 사람이 볼 수 없어
//    타이밍이 어긋난다(2026-08-26 실제로 신호가 -41dBFS 로 잡혔다).
void beep(int freq, int ms, int amp = 5000) {
  static int16_t f[128 * 2];
  float ph = 0;
  int total = spkRate * ms / 1000;
  for (int done = 0; done < total; ) {
    int n = 0;
    while (n < 128 && done < total) {
      ph += 2.0f * (float)M_PI * freq / (float)spkRate;
      f[n * 2 + 0] = (int16_t)(sinf(ph) * amp);
      f[n * 2 + 1] = 0;
      n++; done++;
    }
    spk.write((uint8_t *)f, n * 2 * sizeof(int16_t));
  }
}

void record(uint32_t sec) {
  if (sec < 1) sec = 1;
  if (sec > MAX_SEC) sec = MAX_SEC;
  size_t want_n = (size_t)RATE * sec;

  // 🔴 앞서 22050Hz 를 재생했다면 신호음이 엉뚱한 음높이로 난다 — 되돌린다.
  if (!setSpkRate(RATE)) return;

  Serial.printf("[녹음] 신호음 3번 뒤 %lu초간 녹음합니다.\n", (unsigned long)sec);
  // 카운트다운 — 낮은 톤 3번, 그다음 높은 톤이 「지금 말하세요」
  for (int i = 0; i < 3; i++) { beep(660, 120); delay(380); }
  beep(1320, 200);
  delay(150);                                  // 신호음 잔향이 녹음에 섞이지 않게

  size_t got = 0;
  while (got < want_n) {
    size_t want = (want_n - got) * sizeof(int16_t);
    size_t n = mic.readBytes((char *)(rec + got), want);
    if (n == 0) break;
    got += n / sizeof(int16_t);
  }
  if (got < want_n / 2) {
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
  nRec    = got;      // 🔑 이제 길이가 가변이다
  recRate = RATE;     // 마이크는 항상 16kHz

  beep(880, 90); delay(60); beep(880, 90);     // 끝났음을 알린다
  Serial.printf("[녹음 완료] %u샘플 · DC %d · RMS %d · peak %d (%.1f dBFS)\n",
                (unsigned)got, lastDC, lastRms, lastPeak,
                peak > 0 ? 20.0 * log10((double)peak / 32768.0) : -99.0);
  if (peak < 300) Serial.println("  ⚠️ 신호가 매우 작다 — 마이크에 더 가까이 말해 보라.");
}

void play() {
  if (!hasRec) {
    Serial.println("[재생] 담긴 것이 없다. 먼저 r 또는 W 를 쓰라.");
    return;
  }
  if (!setSpkRate(recRate)) return;

  // ② 정규화 — 녹음 크기가 들쭉날쭉해도 일정한 음량으로 들려준다.
  float gain = (lastPeak > 0) ? (float)TARGET[volIdx] / lastPeak : 1.0f;
  Serial.printf("[재생] %u샘플 · %luHz · 목표 진폭 %d · 배율 %.1f배\n",
                (unsigned)nRec, (unsigned long)recRate, TARGET[volIdx], gain);

  static int16_t frame[256 * 2];
  size_t i = 0;
  while (i < nRec) {
    size_t n = 0;
    while (n < 256 && i < nRec) {
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

// "W <샘플수> <레이트>" + int16LE 페이로드 + uint32LE 체크섬
static void cmdWrite(const String &args) {
  long n = 0, r = 0;
  if (sscanf(args.c_str(), "%ld %ld", &n, &r) != 2) {
    Serial.println("[FAIL] W 인자를 못 읽었다. 형식: W <샘플수> <레이트>");
    return;
  }
  if (n <= 0 || (size_t)n > MAX_SAMPLE) {
    Serial.printf("[FAIL] 샘플수 %ld — 1~%u 범위를 벗어났다.\n", n, (unsigned)MAX_SAMPLE);
    return;
  }
  if (r < 8000 || r > (long)MAX_RATE) {
    Serial.printf("[FAIL] 레이트 %ld — 8000~%u 범위를 벗어났다.\n", r, (unsigned)MAX_RATE);
    return;
  }
  // 🔴 조각내어 받고 조각마다 「다음」을 보낸다 — 흐름 제어.
  //    2026-09-01: 64KB 를 한 번에 밀어 넣었더니 USB CDC 수신 버퍼가 넘쳐
  //    페이로드가 끊겼다. 파이가 빠르고 ESP32 가 느린 것이 정상 상황이므로
  //    「받을 만큼만 보내라」를 프로토콜에 넣는다. 무선(TCP)에서도 같은 문제가
  //    나므로 전송 계층이 아니라 여기서 푸는 것이 맞다(설계 §4.2).
  const size_t CHUNK = 2048;
  size_t total = (size_t)n * sizeof(int16_t);
  size_t done = 0;
  io->printf("[준비] chunk=%u total=%u\n", (unsigned)CHUNK, (unsigned)total);
  while (done < total) {
    size_t want = total - done;
    if (want > CHUNK) want = CHUNK;
    if (!readExact((uint8_t *)rec + done, want, 8000)) {
      Serial.printf("[FAIL] 페이로드가 도중에 끊겼다 — %u/%u 바이트 (조각에서 %u/%u)\n",
                    (unsigned)(done + lastGot), (unsigned)total,
                    (unsigned)lastGot, (unsigned)want);
      hasRec = false;
      return;
    }
    done += want;
    io->println("[다음]");
  }
  uint8_t cs[4];
  if (!readExact(cs, 4, 3000)) {
    Serial.println("[FAIL] 체크섬 4바이트가 안 왔다.");
    hasRec = false;
    return;
  }
  uint32_t want = (uint32_t)cs[0] | ((uint32_t)cs[1] << 8)
                | ((uint32_t)cs[2] << 16) | ((uint32_t)cs[3] << 24);
  uint32_t got = checksum(rec, (size_t)n);
  if (want != got) {
    // 🔴 여기서 멈추는 이유: 잘린 전송도 그럴듯한 소리를 낸다.
    //    그 소리로 판정하면 "STT 가 나쁘다"로 오진한다(설계 §4.2).
    Serial.printf("[FAIL] 체크섬 불일치 — 보낸 값 %lu · 받은 값 %lu\n",
                  (unsigned long)want, (unsigned long)got);
    hasRec = false;
    return;
  }
  nRec = (size_t)n;
  recRate = (uint32_t)r;
  hasRec = true;
  // 적재된 것은 파이가 이미 만든 소리다. 정규화 기준만 다시 잡는다.
  lastPeak = 0;
  lastDC = 0;
  double sq = 0;
  for (size_t i = 0; i < nRec; i++) {
    if (abs(rec[i]) > lastPeak) lastPeak = abs(rec[i]);
    sq += (double)rec[i] * rec[i];
  }
  lastRms = (int)sqrt(sq / nRec);
  Serial.printf("[적재] n=%u rate=%lu sum=%lu ok\n",
                (unsigned)nRec, (unsigned long)recRate, (unsigned long)got);
}

// "D" → "D <샘플수> <레이트> <체크섬>" + int16LE 페이로드
static void cmdDump() {
  if (!hasRec) { Serial.println("[FAIL] 담긴 것이 없다."); return; }
  uint32_t cs = checksum(rec, nRec);
  io->printf("D %u %lu %lu\n", (unsigned)nRec, (unsigned long)recRate, (unsigned long)cs);
  io->write((uint8_t *)rec, nRec * sizeof(int16_t));
  io->flush();
}

void setup() {
  // 🔴 기본 수신 버퍼(256B)로는 오디오 페이로드가 넘친다. begin() 전에 키운다.
  Serial.setRxBufferSize(8192);
  Serial.begin(115200);
  delay(1500);
  Serial.println();
  Serial.println("=== 마이크 녹음 → 스피커 재생 + 오디오 다리 (V1.5) ===");

  rec = (int16_t *)ps_malloc(MAX_SAMPLE * sizeof(int16_t));
  if (rec == nullptr) {
    // 🔴 여기서 멈추는 이유: 조용히 실패하면 "녹음이 안 된다"로 오진한다.
    Serial.println("[FAIL] PSRAM 할당 실패 — PSRAM=opi 로 굽지 않았다.");
    Serial.println("       arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi ...");
    while (true) delay(1000);
  }
  Serial.printf("[OK] PSRAM 버퍼 %u샘플 (%uKB · 최대 %u초)\n",
                (unsigned)MAX_SAMPLE, (unsigned)(MAX_SAMPLE * 2 / 1024), (unsigned)MAX_SEC);

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
  spkRate = RATE;

  Serial.println("[OK] 마이크(I2S0/PDM) + 스피커(I2S1/STD) 준비됨");
  Serial.printf("     마이크 CLK=GPIO%d DATA=GPIO%d · 스피커 BCLK=GPIO%d LRC=GPIO%d DIN=GPIO%d\n",
                MIC_CLK, MIC_DATA, SPK_BCLK, SPK_LRC, SPK_DIN);
  Serial.println("명령: r 녹음+재생 · p 다시 재생 · 1~5 음량 · i 통계");
  Serial.println("      W 적재 · P 재생 · R <초> 녹음 · D 덤프  (파이 도구 = esp32_audio.py)");
}

void loop() {
  if (!io->available()) { delay(20); return; }
  char c = io->read();
  if (c == 'W' || c == 'R') {                 // 인자가 있는 명령
    String args = readLine();
    if (c == 'W') cmdWrite(args);
    else          record((uint32_t)args.toInt());
  } else if (c == 'D') {
    readLine(50);                              // 남은 개행 버림
    cmdDump();
  } else if (c == 'P') {
    readLine(50);
    play();
  } else if (c == 'r') {
    record(3);
    if (hasRec) { delay(200); play(); }
  } else if (c == 'p') {
    play();
  } else if (c >= '1' && c <= '5') {
    volIdx = c - '1';
    Serial.printf("[음량] 목표 진폭 %d (단계 %d/5)\n", TARGET[volIdx], volIdx + 1);
  } else if (c == 'i') {
    if (hasRec) Serial.printf("[통계] n %u · rate %lu · DC %d · RMS %d · peak %d\n",
                              (unsigned)nRec, (unsigned long)recRate, lastDC, lastRms, lastPeak);
    else        Serial.println("[통계] 담긴 것 없음");
  }
}
