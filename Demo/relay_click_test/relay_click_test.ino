/*
 * relay_click_test.ino — 릴레이 4채널 딸각(클릭) 테스트
 * 부하 없이 릴레이 코일 ON/OFF 확인. console_interlock.ino 와 동일 핀맵.
 * 배선:  D7->IN1  D6->IN2  D5->IN3  D4->IN4 ,  5V->VCC , GND->GND
 * 릴레이: SZH-RLBG-009 (8ch, active LOW) -> 핀 LOW = ON, HIGH = OFF.
 * 동작: IN1->IN2->IN3->IN4 순차로 0.6s ON(딸각) -> OFF(딸각) 반복.
 */
const int PINS[4] = {7, 6, 5, 4};   // IN1, IN2, IN3, IN4
const int N = 4;
const int RELAY_ON  = LOW;          // active LOW
const int RELAY_OFF = HIGH;

void allOff() { for (int i = 0; i < N; i++) digitalWrite(PINS[i], RELAY_OFF); }

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < N; i++) { digitalWrite(PINS[i], RELAY_OFF); pinMode(PINS[i], OUTPUT); }
  pinMode(LED_BUILTIN, OUTPUT);
  allOff();
  Serial.println("[relay_click_test] start - IN1~IN4 sequential click");
}

void loop() {
  for (int i = 0; i < N; i++) {
    allOff();
    digitalWrite(PINS[i], RELAY_ON);
    digitalWrite(LED_BUILTIN, HIGH);
    Serial.print("CH"); Serial.print(i + 1);
    Serial.print(" (D"); Serial.print(PINS[i]); Serial.println(") ON");
    delay(600);
    digitalWrite(PINS[i], RELAY_OFF);
    digitalWrite(LED_BUILTIN, LOW);
    delay(250);
  }
}
