# 실콘솔 현장 작업 — 2026-10-06

> spec = 상위 `docs/superpowers/specs/2026-10-06-실콘솔-현장작업-design.md` · plan = 상위 `docs/superpowers/plans/2026-10-06-실콘솔-현장작업.md`

## P3 GPIO 초기화 실패 표시 (출발 전 · 콘솔 불필요)

- 방법 — `gpiomon -c gpiochip0 5` 가 B1(GPIO5) 줄을 잡은 채 `SOP_VOICE_ALERTS=0 python3 -u main.py`(30초 뒤 화면 캡처 · 2회 · 10:29·10:31).
- 결과 ✅
  - GUI 로그(`Demo/logs/20261006_103117_log.txt` 2행) — `[입력] B1(GPIO5) 초기화 실패: 'GPIO busy' — fallback`
  - 연결 상태바(점검 1차와 같은 출처 `precheck.run_stage1`) — 카메라 초록 · 인터락 초록 · **GPIO 빨강**(`P3_gpio실패_상태표시.png`). `gpio_input.available` = 실패가 하나라도 있으면 False · 사유 = 실패 목록.
  - 한계 — 점검 패널(메뉴 → 점검) 행은 열어 보지 않았다. 같은 `run_stage1` 결과로 칠해진다(코드 `safety_console._run_manual_check`).
- 발견(사소 · 범위 밖) — 실패 직후 요약 줄 `[입력] GPIO 입력 활성 — 버튼 ['B1', 'B2', 'B3', 'B4'] + EMO(GPIO26)` 가 실패한 B1 까지 나열한다(`gpio_input.py` 요약 줄이 설정값을 그대로 찍음).
- 참고 — 이때 아두이노가 파이에 꽂혀 있어 시연 프로그램이 `RUN` 을 보냈다(옛 NC 펌웨어 · 정상 상태 명령이라 변화 없음).
