/*
 * relay_click_test.ino — 릴레이 5채널 딸각(클릭) 테스트
 * 부하 없이 릴레이 코일 ON/OFF 확인. console_interlock.ino 와 동일 핀맵.
 * 배선:  D7->IN1  D6->IN2  D5->IN3  D4->IN4  D3->IN5 ,  5V->VCC , GND->GND
 * 릴레이: SZH-RLBG-009 (8ch, active LOW) -> 핀 LOW = ON, HIGH = OFF.
 * 동작: IN1->IN2->...->IN5 순차로 0.6s ON(딸각) -> OFF(딸각) 반복.
 *
 * 🆕 2026-09-05 — CH5(버튼 GND 차단) 추가. 8채널 모듈 교체 후
 *    **채널 순서가 1:1 로 맞는지** 확인하는 것이 이 스케치의 첫 용도다
 *    (설계 §6 검증 3). 시리얼에 찍히는 CH 번호와 실제 딸각 소리·LED 가
 *    같은 채널인지 눈·귀로 대조할 것.
 * ⚠️ **CH5 가 ON 이면 콘솔 버튼이 끊긴다.** 이 스케치는 0.6초마다 껐다 켜므로
 *    돌리는 동안 버튼이 깜빡깜빡 죽는다 — 정상이다.
 */
const int PINS[5] = {7, 6, 5, 4, 3};   // IN1, IN2, IN3, IN4, IN5
const int N = 5;
const int RELAY_ON  = LOW;          // active LOW
const int RELAY_OFF = HIGH;

void allOff() { for (int i = 0; i < N; i++) digitalWrite(PINS[i], RELAY_OFF); }

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < N; i++) { digitalWrite(PINS[i], RELAY_OFF); pinMode(PINS[i], OUTPUT); }
  pinMode(LED_BUILTIN, OUTPUT);
  allOff();
  Serial.println("[relay_click_test] start - IN1~IN5 sequential click (CH5=버튼차단)");
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
