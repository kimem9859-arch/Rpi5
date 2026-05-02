# Project: Vision AI 작업자 안전 콘솔

ESP32-S3 카메라(OV3660)로 작업자 손 위치를 추적하여 휴먼 에러를 사전 예방하는 PyQt5 GUI 애플리케이션.

- **현재 상태**: 프로토타입 / Windows 테스트 단계
- **최종 타겟**: Raspberry Pi 5 + Hailo AI 가속기

## Active Code (Demo/ — 현재 개발 중)

```
Demo/
├── main.py                    진입점
├── config.py                  전역 설정 (YOLO, ROI, FSM, TCP)
├── safety_console.py          메인 GUI + FSM 로직
├── camera_thread.py           TCP 수신 + MediaPipe + YOLO
├── wifi_dialog.py             WiFi 프로비저닝 팝업
├── provision_wifi.py          WiFi 설정 CLI 독립 스크립트
├── calibrate_camera.py        카메라 캘리브레이션
├── yolov8n.pt                 YOLO 모델
├── camera_calibration.npz     렌즈 보정 데이터
└── .env / .camera_ip          WiFi 자격증명, ESP32 IP 캐시 (gitignored)

arduino/camera_stream_tcp/
└── camera_stream_tcp.ino      ESP32-S3 TCP 스트림 펌웨어 (포트 8888)
```

> 일부 기능(ROI 라벨 등)은 이전 프로토타입의 잔재이며, 실제 프로젝트 요구사항에 맞춰 수정 예정.

## RPi Reference (라즈베리파이 이식 참고용)

```
main_original.py                              초기 단일 파일 버전 (구조 참고)
arduino/camera_stream_tcp/yolo_hailo_tcp.py   Hailo AI 추론 (RPi 프로덕션 핵심)
scripts/yolo_camera.py                        RPi USB 카메라 + YOLO 단독 실행
scripts/serial_monitor.py                     ESP32 시리얼 모니터링 유틸
arduino/camera_stream/                        구버전 HTTP MJPEG 스트림
arduino/{hello_test, wifi_test}/              ESP32 하드웨어 테스트
```

## Entry Points

- `cd Demo && python main.py` — 메인 앱 실행
- `python Demo/provision_wifi.py` — ESP32 WiFi 초기 설정
- `python Demo/calibrate_camera.py <IP>` — 카메라 캘리브레이션
