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
    }
  }
  delay(5000);
  Serial.printf("Status: WiFi=%s IP=%s Stream=%s\n",
    WiFi.status() == WL_CONNECTED ? "OK" : "NG",
    WiFi.localIP().toString().c_str(),
    client_sock >= 0 ? "connected" : "waiting");
}
