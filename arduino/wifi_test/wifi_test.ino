#include <WiFi.h>

const char* ssid = "Public WiFi Free";

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("시작!");
  WiFi.begin(ssid);
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("연결 성공! IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("연결 중...");
  }
  delay(2000);
}
