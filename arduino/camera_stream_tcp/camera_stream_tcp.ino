#include "esp_camera.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <lwip/sockets.h>

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

// =============================================================================
// [노출 상한] 자동 노출은 살리고 «최대치»만 제한한다 — 모션 블러 대책
// =============================================================================
// 🔑 왜 — 2026-09-22 데이터셋 원본 38장 측정: **74% 가 흐렸고**(선명도 중앙 59)
//    선명도와 노이즈의 상관이 **+0.87** 이었다. 노이즈가 많은(=게인이 높은
//    =노출이 짧았던) 장만 선명했다 — 우연히 짧아진 순간에만 선명했다는 뜻이다.
//    초점 가설은 기각됐다(칸별 선명도 편차가 흐린 장·선명한 장 모두 같았다).
//
// 🔑 왜 «수동 고정» 이 아니라 «상한» 인가 — 수동 고정은 조명이 바뀌면 사진이
//    타거나 깜깜해진다. 상한만 낮추면 자동 노출이 계속 밝기를 맞추되
//    **번질 만큼 길게 잡지 못한다.**
//
// 📚 1차 근거 — OV3660_CSP3_DS_1.3
//  · §3.4.5 *"From a noise point of view, it is always preferable to extend the
//    exposure time rather than increasing gain."* → 이 센서의 자동 노출은
//    **노이즈를 우선**해 노출을 최대로 늘린다. 그 대가인 모션 블러는 이 문서의
//    주제가 아니다(정지 피사체 전제).
//  · `AEC MAX EXPO` = 0x3A02/0x3A03(60Hz) · 0x3A14/0x3A15(50Hz)
//    공장 기본값 0x30C0 = 12480, **단위는 1/16 row**
//
// 🔑 그 기본값이 곧 «프레임 전체» 다 (계산으로 확인했다):
//      row 시간 = HTS / SCLK = 2300 / 50MHz = 46.0us
//      12480/16 = 780 row · 780 x 46.0us = **35.9ms** ≈ 프레임 주기 36ms
//    → 지금 카메라는 노출을 한 프레임이 꽉 차도록 쓰고 있다.
//
// 🔴 **부팅 때 0x3A0E=2(노출 상한 밴드 2 → 최대 약 9ms)를 건다** — 상위 §12.66-(18) 채택값
//    (2026-09-23 런타임 XGA 전환). 되돌리려면 시리얼 `W:3A0E:08`(공장값).
//    시리얼 `EXP:<rows>`·`EXP:0` 진단은 그대로다. 플래시 설정이 아니라 매 부팅마다 건다.

// row 한 줄을 읽는 시간(us). HTS 2300 / SCLK 50MHz — 둘 다 드라이버가 정한 값이라
// 펌웨어에서 바꾸지 않는 한 고정이다(근거 = 상위 §12.65-(1)).
static const float ROW_TIME_US = 2300.0f / 50.0f;   // = 46.0us
static const uint16_t AEC_MAX_DEFAULT = 0x30C0;     // 공장 기본값(1/16 row 단위)

// 현재 노출·게인·상한을 사람이 읽을 수 있는 단위로 찍는다.
// 🔴 이것이 있어야 「노출이 원인이었나」를 추론이 아니라 «측정» 으로 확정한다.
void printExposure(const char *tag) {
  sensor_t *sp = esp_camera_sensor_get();
  if (!sp || !sp->get_reg) { Serial.println("EXP: sensor has no get_reg"); return; }
  // 🔑 마스크가 0xFF 를 넘으면 드라이버가 여러 바이트를 한 번에 읽는다
  //    (`ov3660.c get_reg`: >0xFF → 2바이트 · >0xFFFF → 3바이트).
  //    낱개로 7번 부르지 않고 3번으로 끝낸다 — I2C 는 촬영 중에도 도는 버스다.
  int exp  = sp->get_reg(sp, 0x3500, 0x0FFFFF);  // 노출 20비트 · 하위 4비트가 1/16 row
  int gn   = sp->get_reg(sp, 0x350A, 0x03FF);    // 게인 10비트 · 1/16 배
  int mx   = sp->get_reg(sp, 0x3A02, 0xFFFF);    // 최대 노출 상한(60Hz)
  if (exp < 0 || gn < 0 || mx < 0) { Serial.println("EXP: read failed"); return; }

  float    rows = exp / 16.0f;
  float    ms   = rows * ROW_TIME_US / 1000.0f;
  float    gain = gn / 16.0f;
  uint16_t maxr = (uint16_t)mx;
  Serial.printf("EXP[%s]: %.1f row = %.2f ms · gain x%.2f · max %.1f row (%.2f ms)\n",
                tag, rows, ms, gain, maxr / 16.0f, (maxr / 16.0f) * ROW_TIME_US / 1000.0f);
}

// 최대 노출 상한을 rows(정수 row) 로 건다. rows=0 이면 공장 기본값으로 되돌린다.
// 50Hz·60Hz 양쪽에 같은 값을 쓴다 — 조명 주파수 판정이 어느 쪽으로 가든 상한이 걸리게.
bool setExposureLimitRows(uint16_t rows) {
  sensor_t *sp = esp_camera_sensor_get();
  if (!sp || !sp->set_reg) return false;
  uint16_t v = rows ? (uint16_t)(rows * 16) : AEC_MAX_DEFAULT;
  // 16비트 마스크 = 2바이트를 한 번에 쓴다(0x3A02+0x3A03 · 0x3A14+0x3A15).
  int a = sp->set_reg(sp, 0x3A02, 0xFFFF, v);   // 60Hz 상한
  int b = sp->set_reg(sp, 0x3A14, 0xFFFF, v);   // 50Hz 상한
  return a >= 0 && b >= 0;
}

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
  config.frame_size   = FRAMESIZE_XGA;   // 1024x768 — 2026-09-23 런타임 XGA 전환(런타임이 첫 프레임 크기로 맞춘다)
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
  // 🔑 센서 모델을 부팅 로그에 남긴다 — 문서에 OV3660/OV5640 이 섞여 있어 실물로 확정해야 한다.
  {
    sensor_t *ss = esp_camera_sensor_get();
    if (ss) Serial.printf("Sensor: PID=0x%04x VER=0x%02x MIDH=0x%02x MIDL=0x%02x\n",
                          ss->id.PID, ss->id.VER, ss->id.MIDH, ss->id.MIDL);
  }
  // 노출 상한 밴드 = 2 → 최대 노출 약 9ms (상위 §12.66-(18) 채택 · 해상도와 무관 — 한 줄 읽는 시간이 같다 §12.68-(3))
  {
    sensor_t *se = esp_camera_sensor_get();
    if (se && se->set_reg) { se->set_reg(se, 0x3A0E, 0xFF, 0x02); delay(300); }
  }
  printExposure("boot");

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
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "RESET_WIFI") {
      Serial.println("Clearing WiFi credentials...");
      clearCredentials();
      ESP.restart();
    } else if (cmd.startsWith("R:") || cmd.startsWith("W:")) {
      // ── 범용 레지스터 읽기·쓰기 (진단 전용) ─────────────────────────────
      //   R:3A00       → 그 레지스터를 읽어 출력
      //   W:3A00:00    → 그 레지스터에 값을 쓴다
      //   R:3500:FFFFF → 마스크를 주면 여러 바이트를 한 번에 (ov3660.c get_reg)
      //
      // 🔴 **왜 범용으로 두나** — 레지스터 하나를 확인할 때마다 다시 구우면
      //    실HW 조작 횟수가 늘고, 그것이 사고가 된다(2026-09-22 보드 오인).
      //    굽기는 한 번, 확인은 시리얼로.
      // ⚠️ 잘못 쓰면 화면이 깨지거나 센서가 멎는다. **전원을 껐다 켜면 전부
      //    공장값으로 돌아간다** — 플래시에 남지 않는다.
      sensor_t *sp = esp_camera_sensor_get();
      if (!sp || !sp->get_reg || !sp->set_reg) { Serial.println("REG: no sensor"); }
      else if (cmd.startsWith("R:")) {
        String rest = cmd.substring(2);
        int c = rest.indexOf(':');
        long reg  = strtol((c < 0 ? rest : rest.substring(0, c)).c_str(), NULL, 16);
        long mask = (c < 0) ? 0xFF : strtol(rest.substring(c + 1).c_str(), NULL, 16);
        int v = sp->get_reg(sp, (int)reg, (int)mask);
        if (v < 0) Serial.printf("R 0x%04lX: read failed\n", reg);
        else       Serial.printf("R 0x%04lX (mask 0x%lX) = 0x%X (%d)\n", reg, mask, v, v);
      } else {
        String rest = cmd.substring(2);
        int c = rest.indexOf(':');
        if (c < 0) { Serial.println("W: use W:<hex reg>:<hex val>"); }
        else {
          long reg = strtol(rest.substring(0, c).c_str(), NULL, 16);
          long val = strtol(rest.substring(c + 1).c_str(), NULL, 16);
          long mask = (val > 0xFF) ? 0xFFFF : 0xFF;
          int r = sp->set_reg(sp, (int)reg, (int)mask, (int)val);
          Serial.printf("W 0x%04lX = 0x%lX -> %s\n", reg, val, r >= 0 ? "OK" : "FAIL");
          delay(300);
          printExposure("after-W");
        }
      }
    } else if (cmd.startsWith("EXP:")) {
      // `EXP:217` = 최대 노출을 217 row(약 10ms)로 제한 · `EXP:0` = 공장값 복귀
      // 🔑 다시 굽지 않고 여러 단계를 시험하려고 둔 입구다. 굽기는 실HW 조작이라
      //    한 번이라도 줄이는 편이 안전하다(§12.65-(7) 보드 오인 사고).
      long rows = cmd.substring(4).toInt();
      if (rows < 0 || rows > 4095) {
        Serial.println("EXP: out of range (0~4095 rows, 0=default)");
      } else if (setExposureLimitRows((uint16_t)rows)) {
        Serial.printf("EXP: limit set to %ld row (%.2f ms)%s\n",
                      rows, rows * ROW_TIME_US / 1000.0f, rows ? "" : " [factory default]");
        delay(400);            // 자동 노출이 새 상한에 수렴할 시간
        printExposure("after");
      } else {
        Serial.println("EXP: set failed");
      }
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

  // 🔑 노출·게인을 상시로 남긴다 — 촬영 회차마다 «그때 실제 노출» 을 알아야
  //    선명도와 대조할 수 있다. 값이 없으면 또 추론으로 돌아간다.
  printExposure("run");

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
