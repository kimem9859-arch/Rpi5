#include "esp_camera.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <lwip/sockets.h>

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
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 15;
  config.fb_count     = 1;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("Camera init failed, restarting in 3s...");
    delay(3000);
    ESP.restart();
  }
  Serial.println("Camera OK");

  String ssid, pass;
  if (!loadCredentials(ssid, pass)) {
    waitForSerialCredentials();
    loadCredentials(ssid, pass);
  }

  Serial.printf("Connecting to: %s\n", ssid.c_str());
  WiFi.begin(ssid.c_str(), pass.c_str());
  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 30) {
    delay(1000);
    Serial.print(".");
    retry++;
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nWiFi connect failed. Retrying in 5s...");
    delay(5000);
    ESP.restart();
  }
  Serial.printf("\nWiFi connected. IP: %s\n", WiFi.localIP().toString().c_str());

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
