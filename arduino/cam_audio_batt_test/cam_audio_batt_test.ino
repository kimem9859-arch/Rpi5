/*
 * 카메라 + 오디오 동시 가동 · 배터리 전압 강하 시험 — 「가디언」 V1/V3 예비
 *
 * 무엇을 가르는가:
 *   ① 🔑 **앰프가 울 때 ESP32 가 브라운아웃되는가** (설계 §4.4 · V1 재는 것 ⑥)
 *      → 커패시터가 실제로 필요한지, 필요하면 **최소 용량**은 얼마인지
 *   ② 카메라(LCD_CAM)와 스피커(I2S1)가 **한 스케치에서 공존하는가**
 *      → 작업로그 ⏸ 「카메라+마이크+스피커 동시 가동 미검증」의 절반
 *
 * 🔴 왜 이 스케치가 따로 필요한가 — `i2s_batt_test` 는 앰프만 돌아 ~300mA 다.
 *    실제 운용은 **카메라+WiFi 150~250mA 가 이미 흐르는 위에** 앰프가 얹혀
 *    최악 ~600mA 가 된다(설계 §5.4). **전류가 2배면 강하도 2배**이므로,
 *    카메라를 끈 채 「멀쩡하다」고 판정하면 지켜야 할 대상이 없는 상태에서
 *    안전하다고 말하는 셈이 된다.
 *
 * 🔑 카메라 코드는 `camera_stream_tcp` 를 **그대로** 쓴다(사용자 지시).
 *    핀·해상도·큐·태스크 배치·WiFi 우선순위까지 손대지 않았다 — 이 시험의
 *    목적은 전원이지 영상 성능이 아니고, 조건이 달라지면 §10.34 와 대조가 깨진다.
 *    ⬇ 아래 「오디오 추가분」 표시가 붙은 곳만 새로 더한 부분이다.
 *
 * 🔑 계측기 없이 판정하는 법 — **부팅음으로 리셋 사유를 알린다.**
 *      · 높은 「삑」 1회      = 정상 부팅
 *      · 낮은 「뿌뿌뿌」 3회  = 🔴 브라운아웃 리셋 (= 전압이 무너졌다는 증거)
 *
 * ⚠️ **앞 30초는 무음이다 — 카메라 단독 기준선 구간.**
 *    이 구간에 이상이 나면 오디오 탓이 아니다. 오디오를 켜고 흔들렸을 때
 *    「오디오 탓인지 원래 그런 건지」를 못 가르는 것이 이 갈래의 함정이다.
 *
 * 시험 절차:
 *   ① USB 로 굽는다 → ② USB 를 뽑는다 → ③ 배터리로 전원 ON
 *   → ④ 파이에서 스트림 붙이고(선택) 3분 듣는다
 *   커패시터를 **없음 → 100µF → 220µF** 으로 올려가며 반복(작을수록 유리 — 돌입 전류).
 *   조건마다 **무부하 전압**과 **재생 중 전압**을 같은 지점에서 적어 둔다.
 *
 * 🔴 전원 구성 (2026-09-04 정정) — 앰프는 **배터리 마디**에서 뽑는다.
 *      배터리 → 충전모듈 BAT± ─┬→ XIAO 뒷면 BAT±
 *                              └→ 앰프 VIN / GND  + 커패시터(VIN—GND 병렬)
 *    🔴 **XIAO 「5V」 핀에서 뽑지 말 것** — BAT 급전 시 그 핀에는 전원이 실리지
 *       않는다(실측 2.15V·앰프 최소 2.5V 미달, 2026-09-04). 앰프가 굶으면
 *       전류를 안 당겨 **시험 자체가 성립하지 않는다.**
 *    🔴 **XIAO 「3V3」 에서도 뽑지 말 것** — MCU 젖줄이다(설계 §5.3-①).
 *
 * 결선 (앰프 DFR0954 = MAX98357A):
 *   BCLK ← D0(GPIO1) · LRC ← D1(GPIO2) · DIN ← D2(GPIO3)
 *   SD ← 3V3 → 1.4V 초과 = **왼쪽 채널만** 모드 → 모노를 왼쪽에 싣는다(§5.3-③)
 *   OUT+/OUT− → 스피커   🔴 **OUT− 를 GND 에 대면 칩이 파손된다**(BTL, §5.3-④)
 *   커패시터(전해) 🔴 극성 — 긴 다리 +, 흰 띠 쪽 −. 반대로 꽂으면 터진다.
 *
 * 굽기 (🔴 ttyACM0 은 Arduino 인터록이다 — 포트를 반드시 지정):
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/cam_audio_batt_test
 *   arduino-cli upload -p /dev/ttyACM1 --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi arduino/cam_audio_batt_test
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
#include <esp_system.h>

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

// ─────────────── 오디오 추가분 (여기부터) ───────────────
#define PIN_BCLK 1    // D0
#define PIN_LRC  2    // D1
#define PIN_DIN  3    // D2

static const uint32_t A_RATE  = 16000;
static const size_t   A_CHUNK = 256;

// 🔴 일부러 최대 음량이다 — 전류를 가장 많이 끌어야 강하가 드러난다.
static const int AMP_MAX = 15000;

// 🔑 카메라 단독 기준선 구간. 이 구간에 이상이 나면 오디오 탓이 아니다.
static const uint32_t SILENT_MS = 30000;

// 리셋을 넘어 살아남는다(전원을 완전히 끊으면 0 으로 돌아간다).
RTC_DATA_ATTR static uint32_t bootCount     = 0;
RTC_DATA_ATTR static uint32_t brownoutCount = 0;

I2SClass i2s;
static bool audioReady = false;

/** 한 음을 정해진 시간만큼 낸다(부팅음 전용 — 블로킹). */
static void beep(float freq, uint32_t ms, int amp) {
  const size_t frames = (size_t)((uint64_t)A_RATE * ms / 1000);
  static int16_t buf[A_CHUNK * 2];
  float ph = 0.0f;
  for (size_t done = 0; done < frames; done += A_CHUNK) {
    for (size_t i = 0; i < A_CHUNK; i++) {
      ph += 2.0f * (float)M_PI * freq / (float)A_RATE;
      if (ph > 2.0f * (float)M_PI) ph -= 2.0f * (float)M_PI;
      buf[i * 2 + 0] = (int16_t)(sinf(ph) * amp);   // 왼쪽만(SD=3V3)
      buf[i * 2 + 1] = 0;
    }
    i2s.write((uint8_t *)buf, sizeof(buf));
  }
}

static void silence(uint32_t ms) {
  const size_t frames = (size_t)((uint64_t)A_RATE * ms / 1000);
  static int16_t buf[A_CHUNK * 2] = {0};
  for (size_t done = 0; done < frames; done += A_CHUNK)
    i2s.write((uint8_t *)buf, sizeof(buf));
}

/** 앞 SILENT_MS 는 무음(카메라 단독 기준선), 이후 최대 음량 사이렌 반복. */
void audioTask(void *param) {
  const uint32_t t0 = millis();
  static int16_t buf[A_CHUNK * 2];
  float phase = 0.0f, sweepPos = 200.0f;
  bool announced = false;

  while (true) {
    const bool quiet = (millis() - t0) < SILENT_MS;
    if (!quiet && !announced) {
      Serial.println("[audio] 기준선 구간 종료 — 최대 음량 사이렌 시작");
      announced = true;
    }
    for (size_t i = 0; i < A_CHUNK; i++) {
      phase += 2.0f * (float)M_PI * sweepPos / (float)A_RATE;
      if (phase > 2.0f * (float)M_PI) phase -= 2.0f * (float)M_PI;
      buf[i * 2 + 0] = quiet ? 0 : (int16_t)(sinf(phase) * AMP_MAX);  // 왼쪽만
      buf[i * 2 + 1] = 0;
      // 로그 스윕 — 약 8초에 200→4000Hz.
      sweepPos *= 1.0f + (3.0f / (float)A_RATE);
      if (sweepPos > 4000.0f) sweepPos = 200.0f;
    }
    i2s.write((uint8_t *)buf, sizeof(buf));
  }
}
// ─────────────── 오디오 추가분 (여기까지) ───────────────

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
    if (xQueueSend(frameQueue, &fb, 0) != pdTRUE) {
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

  // ── 오디오 추가분: 리셋 사유부터 소리로 알린다 (카메라보다 먼저) ──
  {
    const esp_reset_reason_t reason = esp_reset_reason();
    const bool brownout = (reason == ESP_RST_BROWNOUT);
    bootCount++;
    if (brownout) brownoutCount++;

    i2s.setPins(PIN_BCLK, PIN_LRC, PIN_DIN);
    audioReady = i2s.begin(I2S_MODE_STD, A_RATE,
                           I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
    if (!audioReady) {
      Serial.println("[FAIL] I2S 초기화 실패 — 핀 번호·결선을 확인하라.");
    } else {
      if (brownout) {
        for (int i = 0; i < 3; i++) { beep(400.0f, 150, AMP_MAX / 2); silence(120); }
      } else {
        beep(2000.0f, 200, AMP_MAX / 3);
      }
      silence(300);
    }
    Serial.printf("리셋 사유: %d %s\n", (int)reason,
                  brownout ? "🔴 BROWNOUT — 전압이 무너졌다" : "(정상)");
    Serial.printf("부팅 %lu 회 · 그중 브라운아웃 %lu 회 (전원을 끊으면 0)\n",
                  (unsigned long)bootCount, (unsigned long)brownoutCount);
  }

  Serial.println("=== 카메라+오디오 배터리 시험 ===");
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

  // ── 오디오 추가분 ── 캡처(코어0·우선순위5)를 방해하지 않도록 우선순위를 낮춘다.
  if (audioReady) {
    xTaskCreatePinnedToCore(audioTask, "audio", 4096, NULL, 2, NULL, 0);
    Serial.printf("[audio] 앞 %lu 초는 무음(카메라 단독 기준선), 이후 사이렌\n",
                  (unsigned long)(SILENT_MS / 1000));
  }
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
  Serial.printf("        부팅 %lu 회 · 브라운아웃 %lu 회\n",
                (unsigned long)bootCount, (unsigned long)brownoutCount);
}
