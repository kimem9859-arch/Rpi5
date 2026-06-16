/* relay_idle.ino — 모든 릴레이 OFF로 고정하고 정지. 점퍼/배선 작업용 안전 스케치.
 * active LOW: HIGH = OFF. D7/D6/D5/D4 모두 OFF 후 아무 동작 안 함. */
const int PINS[4] = {7, 6, 5, 4};
void setup() {
  Serial.begin(115200);
  for (int i = 0; i < 4; i++) { digitalWrite(PINS[i], HIGH); pinMode(PINS[i], OUTPUT); }
  for (int i = 0; i < 4; i++) digitalWrite(PINS[i], HIGH);  // all OFF
  Serial.println("[relay_idle] all relays OFF - safe to wire");
}
void loop() { }
