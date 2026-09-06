/*
 * 글라스 통합 — 카메라 + 음성비서 (시연 구현)
 *
 * 정본 = docs/superpowers/specs/2026-09-06-음성비서-시연구현-design.md
 * 계획 = docs/superpowers/plans/2026-09-06-음성비서-시연구현.md
 *
 * 🔴 카메라 코드는 `camera_stream_tcp` 에서 **그대로 복사**했다. 손대지 않는다.
 *    통신경로 과제(2026-09-06-esp32-통신경로-design.md)가 카메라 쪽을 고치면
 *    **그 diff 만 여기로 옮긴다.** 아래 「오디오 추가분」 표시가 붙은 곳만 새 것이다.
 *
 * 포트: 8888 카메라(기존) · 8889 마이크 업링크 · 8890 명령/스피커
 *
 * 🔑 Serial(USB CDC)과 WiFiClient 는 둘 다 Stream 을 상속한다 — 프로토콜 코드는
 *    유선인지 무선인지 모른 채 동작한다. 설계가 그렇게 추상화해 둔 자리다(§10.51-(1)).
 *
 * 결선 (앰프 DFR0954 = MAX98357A):
 *   마이크 CLK=GPIO42 · DATA=GPIO41   (확장보드 온보드 PDM)
 *   스피커 BCLK=D0(1) · LRC=D1(2) · DIN=D2(3) · SD←3V3(왼쪽 채널만 모드)
 *   🔴 OUT− 를 GND 에 대면 칩이 파손된다(BTL 출력).
 *   앰프 전원은 **배터리 마디**에서 뽑는다 — XIAO 5V 핀은 BAT 급전 시 무전원이다(§10.55-(4)).
 *
 * 🔴 굽기 — PSRAM=opi 필수(빠뜨리면 카메라가 부팅 루프에 빠진다):
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/glass_voice
 *   arduino-cli upload -p <포트> --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/glass_voice
 *   (포트는 `python3 Demo/serial_ports.py` 로 찾는다 — ttyACM0 은 Arduino 인터록이다)
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <lwip/sockets.h>
// ── 오디오 추가분 ──
#include <ESP_I2S.h>
#include <math.h>

// WiFi 자격증명 (SSID·비번). gitignore 처리됨 — 저장소에 비번이 올라가지 않는다.
// 배열 순서 = 연결 우선순위. 신호 세기와 무관하게 앞에 있는 SSID를 먼저 잡는다.
#include "wifi_credentials.h"

#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39
#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15
#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13

#define TCP_PORT         8888
#define FRAME_QUEUE_SIZE 2
#define MDNS_HOSTNAME    "esp32cam"

QueueHandle_t frameQueue;
int listen_sock = -1;
int client_sock = -1;

Preferences prefs;

// ═══════════════ 오디오 추가분 (여기부터) ═══════════════
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


// 🔑 Serial(USB CDC)과 WiFiClient 는 둘 다 Stream 을 상속한다.
static Stream *io = &Serial;

WiFiServer micServer(8889);     // 마이크 상시 업링크
WiFiServer cmdServer(8890);     // 명령/스피커
WiFiClient cmdClient;

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


/** 「띠링」 — 호출을 들었다는 표시. 명령 1바이트로 즉시 난다.
 *  🔑 wav 로 보내면 0.3초가 더 붙는데, 호출 응답은 즉각적이어야 한다.
 */
static void chime() {
  setSpkRate(RATE);
  beep(1175, 90); delay(40); beep(1568, 140);
}

/** 한 글자 명령을 처리한다 — 유선/무선 공통. */
static void handleCmd(char c) {
  if (c == 'W' || c == 'R') {
    String args = readLine();
    if (c == 'W') cmdWrite(args);
    else          record((uint32_t)args.toInt());
  } else if (c == 'D') { readLine(50); cmdDump(); }
  else if (c == 'P')   { readLine(50); play(); }
  else if (c == 'B')   { readLine(50); chime(); }
  else if (c == 'r')   { record(3); if (hasRec) { delay(200); play(); } }
  else if (c == 'p')   { play(); }
  else if (c >= '1' && c <= '5') {
    volIdx = c - '1';
    Serial.printf("[음량] 목표 진폭 %d (단계 %d/5)\n", TARGET[volIdx], volIdx + 1);
  }
}

/** 명령 채널(8890) — 무선 손님이 있으면 그쪽, 없으면 USB 시리얼. */
void audioCmdTask(void *param) {
  cmdServer.begin();
  cmdServer.setNoDelay(true);
  while (true) {
    if (!cmdClient || !cmdClient.connected()) {
      WiFiClient c = cmdServer.accept();
      if (c) {
        cmdClient = c;
        cmdClient.setNoDelay(true);
        io = &cmdClient;
        Serial.println("[audio] 명령 채널 연결됨 (8890)");
      }
    }
    if (cmdClient && cmdClient.connected() && cmdClient.available()) {
      handleCmd((char)cmdClient.read());
    } else if (Serial.available()) {
      // 🔑 USB 로 명령이 오면 그쪽이 임자다 — 현장에서 유선으로 되돌릴 수 있다.
      Stream *keep = io;
      io = &Serial;
      handleCmd((char)Serial.read());
      io = (cmdClient && cmdClient.connected()) ? keep : &Serial;
    } else {
      vTaskDelay(pdMS_TO_TICKS(10));
    }
  }
}

/** 마이크 상시 업링크(8889) — 손님이 있을 때만 읽어 보낸다.
 *
 *  🔑 DC 오프셋을 여기서 빼지 않는다. 창을 어디서 자르느냐에 따라 평균이
 *     달라지는데, 파이는 발화 구간을 알고 자르므로 거기서 빼는 편이 정확하다.
 *  🔴 손님이 없으면 읽지도 않는다 — 안 읽으면 I2S DMA 가 알아서 덮어쓴다.
 */
void micUplinkTask(void *param) {
  micServer.begin();
  micServer.setNoDelay(true);
  static int16_t buf[512];
  WiFiClient c;
  while (true) {
    if (!c || !c.connected()) {
      c = micServer.accept();
      if (c) { c.setNoDelay(true); Serial.println("[audio] 마이크 업링크 연결됨 (8889)"); }
      else   { vTaskDelay(pdMS_TO_TICKS(100)); continue; }
    }
    size_t n = mic.readBytes((char *)buf, sizeof(buf));
    if (n == 0) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    if (c.write((uint8_t *)buf, n) != n) {
      c.stop();
      Serial.println("[audio] 업링크 끊김");
    }
  }
}
// ═══════════════ 오디오 추가분 (여기까지) ═══════════════

// =============================================================================
// [링크 계측] — 진단 전용. 전송 경로를 바꾸지 않는다.
// =============================================================================
// 🔴 왜 넣나: 2026-08-13(§10.42-(7))부터 「무선이 요동친다」를 여섯 세션 쫓았는데
//    **전부 파이 쪽에서만 쟀다.** ESP32 쪽 신호 세기·채널·붙어 있는 AP 를 한 번도
//    못 봤다. 그래서 가설 5개가 전부 기각되고도 남는 것이 없었다.
//
// 🔑 `send()` 가 붙잡힌 시간을 함께 재는 이유:
//    FPS 가 **대역폭이 아니라 왕복 지연(RTT)에 매여 있는지** 가리기 위해서다.
//    lwIP 송신 윈도는 컴파일 시점에 5744B(=4×MSS 1436)로 고정돼 있고
//    (`CONFIG_LWIP_TCP_SND_BUF_DEFAULT`, 실행 중 변경 불가), 프레임은 약 11KB다.
//    한 장에 최소 2왕복이 필요하다는 뜻이라, 링크가 나빠지면 그 배수만큼 벌어진다.
//    → send 평균이 RTT 의 2~3배로 따라 움직이면 이 구조가 병목이다.
//
// ⚠️ 카운터는 태스크 간 공유지만 락을 걸지 않는다 — 진단 통계라 한두 건 어긋나도
//    무방하고, 전송 경로에 락을 넣는 쪽이 더 나쁘다.
static volatile uint32_t statCap = 0;        // 캡처 성공
static volatile uint32_t statDrop = 0;       // 큐가 차서 버린 프레임
static volatile uint32_t statSent = 0;       // 전송 완료
static volatile uint32_t statBytes = 0;      // 전송 바이트 합
static volatile uint32_t statSendMsSum = 0;  // send() 소요 합
static volatile uint32_t statSendMsMax = 0;  // send() 소요 최대

bool loadCredentials(String &ssid, String &pass) {
  prefs.begin("wifi", true);
  ssid = prefs.getString("ssid", "");
  pass = prefs.getString("pass", "");
  prefs.end();
  return ssid.length() > 0;
}

void saveCredentials(const String &ssid, const String &pass) {
  prefs.begin("wifi", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.end();
}

void clearCredentials() {
  prefs.begin("wifi", false);
  prefs.clear();
  prefs.end();
}

void captureTask(void *param) {
  while (true) {
    if (client_sock < 0) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }
    statCap++;
    if (xQueueSend(frameQueue, &fb, 0) != pdTRUE) {
      statDrop++;
      esp_camera_fb_return(fb);
    }
  }
}

void sendTask(void *param) {
  while (true) {
    if (client_sock < 0) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    camera_fb_t *fb = NULL;
    if (xQueueReceive(frameQueue, &fb, pdMS_TO_TICKS(1000)) != pdTRUE) {
      continue;
    }
    uint32_t len = fb->len;
    uint32_t t0 = millis();          // ← 계측: send() 가 붙잡히는 시간
    int sent = send(client_sock, (uint8_t *)&len, 4, 0);
    if (sent != 4) {
      close(client_sock);
      client_sock = -1;
      esp_camera_fb_return(fb);
      continue;
    }
    sent = send(client_sock, fb->buf, fb->len, 0);
    if (sent != (int)fb->len) {
      close(client_sock);
      client_sock = -1;
    } else {
      uint32_t dt = millis() - t0;
      statSent++;
      statBytes += fb->len;
      statSendMsSum += dt;
      if (dt > statSendMsMax) statSendMsMax = dt;
    }
    esp_camera_fb_return(fb);
  }
}

void acceptTask(void *param) {
  listen_sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  int yes = 1;
  setsockopt(listen_sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

  struct sockaddr_in addr;
  addr.sin_family      = AF_INET;
  addr.sin_port        = htons(TCP_PORT);
  addr.sin_addr.s_addr = INADDR_ANY;
  bind(listen_sock, (struct sockaddr *)&addr, sizeof(addr));
  listen(listen_sock, 1);
  Serial.printf("TCP server ready: port %d\n", TCP_PORT);

  while (true) {
    struct sockaddr_in client_addr;
    socklen_t client_len = sizeof(client_addr);
    int new_sock = accept(listen_sock, (struct sockaddr *)&client_addr, &client_len);
    if (new_sock < 0) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    int flag = 1;
    setsockopt(new_sock, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(int));
    // 🔴 이 줄은 **아무 일도 하지 않는다** (2026-09-05 확인, 남겨 둔 이유는 아래).
    //    이 툴체인은 `CONFIG_LWIP_SO_SNDBUF` 가 꺼져 있어(esp32s3-libs 3.3.10
    //    sdkconfig) lwIP 가 SO_SNDBUF 설정을 받지 않는다. 송신 버퍼는 컴파일 시점
    //    값 `CONFIG_LWIP_TCP_SND_BUF_DEFAULT = 5744`(=4×MSS 1436)로 고정이며
    //    실행 중에는 못 바꾼다.
    //    ⚠️ §10.34-(4) 의 *"프레임 10.1KB 에 버퍼 32KB 로 이미 3배 여유"* 는 이
    //    줄이 먹힌다는 전제에서 나온 서술이라 **사실과 다르다.** 실제 여유는
    //    3배가 아니라 0.5배(11KB 프레임 vs 5.7KB 윈도)다.
    //    지우지 않는 이유 = 실패해도 무해하고, 툴체인이 바뀌어 켜지면 그때는
    //    실제로 효과가 있다. 대신 아래 계측(send 소요)이 진짜 상태를 보여준다.
    int sndbuf = 32768;
    setsockopt(new_sock, SOL_SOCKET, SO_SNDBUF, &sndbuf, sizeof(sndbuf));
    Serial.printf("Client connected: %s\n", inet_ntoa(client_addr.sin_addr));
    if (client_sock >= 0) close(client_sock);
    camera_fb_t *fb;
    while (xQueueReceive(frameQueue, &fb, 0) == pdTRUE) {
      esp_camera_fb_return(fb);
    }
    client_sock = new_sock;
  }
}

// 주변 SSID를 스캔해 WIFI_CREDS 배열 순서(=우선순위)대로 연결한다.
// 신호 세기 기준이 아니다 — 1순위가 보이면 약하더라도 그쪽에 붙는다.
// 이유: 파이도 같은 우선순위를 쓰므로, 규칙이 같아야 둘이 같은 서브넷에 모인다.
//       (다른 네트워크에 붙으면 TCP 직결이 불가능하다.)
bool tryConnect(const char* ssid, const char* pass, int timeoutSec) {
  Serial.printf("Connecting to: %s ", ssid);
  WiFi.begin(ssid, pass);
  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < timeoutSec) {
    delay(1000);
    Serial.print(".");
    retry++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWiFi connected. SSID: %s  IP: %s\n",
                  ssid, WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.printf("\n  -> failed (%s)\n", ssid);
  WiFi.disconnect();
  return false;
}

void connectWiFiByPriority() {
  WiFi.mode(WIFI_STA);
  // 절전 끔 — 기본값(WIFI_PS_MIN_MODEM)은 AP의 DTIM 주기에만 깨어나 RTT 가
  // 20~250ms 로 요동친다. 스트리밍은 지연 균일성이 곧 FPS 라 절전을 끈다.
  // 대가는 소비전력 증가뿐이며, 이 보드는 상시 전원으로 쓴다.
  WiFi.setSleep(false);

  while (true) {
    Serial.println("Scanning networks...");
    int n = WiFi.scanNetworks();

    // 우선순위 배열을 앞에서부터 훑어, 스캔에 잡힌 첫 SSID에 연결 시도
    for (int i = 0; i < WIFI_CRED_COUNT; i++) {
      bool found = false;
      for (int j = 0; j < n; j++) {
        if (WiFi.SSID(j) == WIFI_CREDS[i].ssid) { found = true; break; }
      }
      if (!found) {
        Serial.printf("  [%d] %s : not in range\n", i + 1, WIFI_CREDS[i].ssid);
        continue;
      }
      Serial.printf("  [%d] %s : found\n", i + 1, WIFI_CREDS[i].ssid);
      WiFi.scanDelete();
      if (tryConnect(WIFI_CREDS[i].ssid, WIFI_CREDS[i].pass, 20)) return;
      break;   // 잡혔는데 연결 실패 → 다시 스캔부터 (비번 오류 등)
    }
    WiFi.scanDelete();

    // 비상 폴백: 등록된 SSID가 하나도 안 잡히면 NVS에 저장된 자격증명 사용
    // (시리얼 WIFI: 명령으로 임시 주입한 네트워크 — 현장 대응용)
    String ssid, pass;
    if (loadCredentials(ssid, pass)) {
      Serial.printf("Fallback to saved credentials: %s\n", ssid.c_str());
      if (tryConnect(ssid.c_str(), pass.c_str(), 15)) return;
    }

    Serial.println("No known network. Rescan in 5s...");
    delay(5000);
  }
}

void waitForSerialCredentials() {
  Serial.println("No WiFi credentials found.");
  Serial.println("Send credentials via: WIFI:<ssid>:<password>");

  while (true) {
    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd.startsWith("WIFI:")) {
        int sep = cmd.indexOf(':', 5);
        if (sep > 0) {
          String ssid = cmd.substring(5, sep);
          String pass = cmd.substring(sep + 1);
          saveCredentials(ssid, pass);
          Serial.printf("Credentials saved: SSID=%s\n", ssid.c_str());
          return;
        } else {
          Serial.println("Invalid format. Use: WIFI:<ssid>:<password>");
        }
      }
    }
    delay(100);
  }
}

void setup() {
  Serial.begin(115200);
  delay(3000);
  setCpuFrequencyMhz(240);
  Serial.println("=== TCP Streaming Start ===");
  Serial.printf("CPU: %dMHz\n", getCpuFrequencyMhz());

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size   = FRAMESIZE_VGA;
  config.pixel_format = PIXFORMAT_JPEG;
  // 버퍼 2개 + LATEST — fb_count=1 이면 전송이 끝나야 다음 캡처가 시작돼
  // 캡처·전송 태스크를 코어까지 나눠 놓고도 직렬화된다(2026-08-10 실측:
  // 프레임 간격 93ms 고정 ≈ 10.7fps, 대역폭은 1.2%만 사용). 버퍼를 2개로
  // 두어 캡처와 전송을 겹치고, 밀리면 최신 프레임을 우선한다(지연 누적 방지).
  config.grab_mode    = CAMERA_GRAB_LATEST;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 15;
  config.fb_count     = 2;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera init failed, restarting in 3s...");
    delay(3000);
    ESP.restart();
  }
  Serial.println("Camera OK");

  // ── 오디오 추가분: PSRAM 버퍼 + 마이크(I2S0/PDM) + 스피커(I2S1/STD) ──
  // 🔴 초기화에 실패해도 멈추지 않는다 — 카메라는 되는데 오디오만 안 될 때
  //    그 사실을 봐야 원인이 갈린다.
  rec = (int16_t *)ps_malloc(MAX_SAMPLE * sizeof(int16_t));
  if (rec == nullptr) {
    Serial.println("[FAIL] PSRAM 할당 실패 — PSRAM=opi 로 굽지 않았다.");
  } else {
    Serial.printf("[OK] PSRAM 버퍼 %u샘플 (%uKB · 최대 %u초)\n",
                  (unsigned)MAX_SAMPLE, (unsigned)(MAX_SAMPLE * 2 / 1024),
                  (unsigned)MAX_SEC);
  }

  if (!mic.setPort(I2S_NUM_0)) {
    Serial.println("[FAIL] 마이크 포트 설정 실패");
  } else {
    mic.setPinsPdmRx(MIC_CLK, MIC_DATA);
    if (!mic.begin(I2S_MODE_PDM_RX, RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO))
      Serial.println("[FAIL] 마이크 초기화 실패 — 확장보드 결합을 확인하라.");
    else
      Serial.println("[OK] 마이크(I2S0/PDM) GPIO42=CLK GPIO41=DATA");
  }

  if (!spk.setPort(I2S_NUM_1)) {
    Serial.println("[FAIL] 스피커 포트 설정 실패");
  } else {
    spk.setPins(SPK_BCLK, SPK_LRC, SPK_DIN);
    if (!spk.begin(I2S_MODE_STD, RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
      Serial.println("[FAIL] 스피커 초기화 실패 — 핀·결선을 확인하라.");
    } else {
      spkRate = RATE;
      Serial.println("[OK] 스피커(I2S1/STD) BCLK=D0 LRC=D1 DIN=D2");
      chime();                                  // 부팅 신호 = 「띠링」
    }
  }

  connectWiFiByPriority();

  if (MDNS.begin(MDNS_HOSTNAME)) {
    Serial.printf("mDNS ready: %s.local\n", MDNS_HOSTNAME);
  } else {
    Serial.println("mDNS start failed");
  }
  Serial.printf("Stream: %s.local:%d\n", MDNS_HOSTNAME, TCP_PORT);

  frameQueue = xQueueCreate(FRAME_QUEUE_SIZE, sizeof(camera_fb_t *));

  xTaskCreatePinnedToCore(captureTask, "capture", 8192, NULL, 5, NULL, 0);
  xTaskCreatePinnedToCore(sendTask,    "send",    8192, NULL, 5, NULL, 1);
  xTaskCreatePinnedToCore(acceptTask,  "accept",  4096, NULL, 3, NULL, 1);

  // ── 오디오 추가분 ──
  // 🔴 업링크를 코어 1 에 붙인다 — 카메라 캡처가 코어 0 우선순위 5 에 있어서
  //    같은 코어에 두면 프레임을 민다.
  xTaskCreatePinnedToCore(audioCmdTask,  "audiocmd", 8192, NULL, 2, NULL, 0);
  xTaskCreatePinnedToCore(micUplinkTask, "micup",    8192, NULL, 2, NULL, 1);
  Serial.println("[audio] 서버 준비 — 8889 마이크 업링크 · 8890 명령/스피커");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "RESET_WIFI") {
      Serial.println("Clearing WiFi credentials...");
      clearCredentials();
      ESP.restart();
    }
  }
  delay(5000);
  Serial.printf("Status: WiFi=%s IP=%s Stream=%s\n",
    WiFi.status() == WL_CONNECTED ? "OK" : "NG",
    WiFi.localIP().toString().c_str(),
    client_sock >= 0 ? "connected" : "waiting");

  // ── 링크 계측 (진단 전용) ──────────────────────────────────────────
  // 🔑 BSSID·채널을 함께 찍는 이유: 폰 핫스팟은 채널을 자동으로 옮긴다
  //    (2026-09-04 파이 로그에 ch6 → ch11 이동이 1분 만에 잡혔다). ESP32 는
  //    부팅 때 한 번 붙고 재스캔하지 않으므로, 여기 값이 파이 쪽 `iw dev wlan0
  //    link` 와 어긋나면 그것만으로 원인이 하나 확정된다.
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("  Link: RSSI=%ddBm ch=%d BSSID=%s\n",
      WiFi.RSSI(), WiFi.channel(), WiFi.BSSIDstr().c_str());
  }

  // 카운터를 읽고 즉시 0 으로 되돌린다 — 이 5초 구간의 값이라는 뜻이다.
  uint32_t cap = statCap,  drop = statDrop, sent = statSent;
  uint32_t bytes = statBytes, msSum = statSendMsSum, msMax = statSendMsMax;
  statCap = statDrop = statSent = statBytes = statSendMsSum = statSendMsMax = 0;
  if (sent > 0) {
    Serial.printf("  Frame: cap=%lu sent=%lu drop=%lu · %.1fKB/장 · "
                  "send avg=%lums max=%lums\n",
      (unsigned long)cap, (unsigned long)sent, (unsigned long)drop,
      bytes / 1024.0f / sent,
      (unsigned long)(msSum / sent), (unsigned long)msMax);
  }
}
