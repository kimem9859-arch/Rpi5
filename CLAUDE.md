# Project: Vision AI 작업자 안전 콘솔

ESP32-S3 카메라(OV3660)로 작업자 손 위치를 추적하여 휴먼 에러를 사전 예방하는 PyQt5 GUI 애플리케이션.

- **현재 상태**: 프로토타입 / Windows 테스트 단계
- **최종 타겟**: Raspberry Pi 5 + Hailo AI 가속기

## RPi Reference (이전 라즈베리파이 원본 파일 참고용)

main_original.py                              초기 단일 파일 버전 (구조 참고)
arduino/camera_stream_tcp/yolo_hailo_tcp.py   Hailo AI 추론 (RPi 프로덕션 핵심)
scripts/yolo_camera.py                        RPi USB 카메라 + YOLO 단독 실행
scripts/serial_monitor.py                     ESP32 시리얼 모니터링 유틸
arduino/camera_stream/                        구버전 HTTP MJPEG 스트림
arduino/{hello_test, wifi_test}/              ESP32 하드웨어 테스트
```

## Workflow Notes

- **ESP32 펌웨어(.ino) 작업**: Arduino CLI 사용 (Arduino IDE 아님)
- **ESP32 코드 편집/컴파일 위치**: Raspberry Pi에서만 수행 (Windows 노트북에는 Arduino CLI 미설치)
- **Windows 노트북**: Demo/ 의 Python GUI 개발 / 테스트 전용
