"""카메라 프레임 방향 보정 — 상하반전·회전의 **단일 출처.**

왜 별도 모듈인가 (2026-08-26):
    ESP32 장착 구도가 시계방향 90° 로 바뀌어 반시계 90° 회전 보정이 생겼다.
    같은 보정을 런타임(`camera_thread`)과 측정 도구(`test/tool_live`·
    `test/bench_detector`)가 **각자 복제**하면 반드시 한쪽이 어긋난다 —
    도구 기본값이 config 를 안 따라 이미 4번 물렸다(conf·ring·dwell·gap).
    `camera_thread` 는 Qt·Hailo 를 끌어와 도구가 import 할 수 없어서
    `roi_zones` 와 같은 이유로 **의존성 없는 순수 모듈**로 뺐다.

    🔴 **방향 보정을 바꿀 때는 여기만 고친다.** 다른 곳에 `cv2.flip`·
       `cv2.rotate` 를 다시 쓰지 말 것.

🔴 순서가 있다 — 반전 → (왜곡보정) → 회전.
    왜곡보정 맵은 **센서 원본 해상도(640×480) 전용**으로 만들어진다. 회전을
    먼저 하면 480×640 이 되어 `camera_thread._init_calibration` 이
    'mismatch' 로 판단해 **왜곡보정을 조용히 꺼버린다.** 렌즈 왜곡은 센서
    좌표계의 성질이므로 원본 방향에서 펴고 그 다음에 돌리는 것이 맞다.
    그래서 `flip()` 과 `rotate()` 를 따로 노출한다 — 런타임은 그 사이에
    왜곡보정을 끼우고, 왜곡보정이 없는 도구는 `apply()` 하나로 끝낸다.
"""

import cv2

import config


def flip(frame):
    """센서 상하반전 보정 — 카메라 모듈이 거꾸로 장착돼 원본이 뒤집혀 온다."""
    if config.CAMERA_FLIP_VERTICAL:
        return cv2.flip(frame, 0)
    return frame


def rotate(frame):
    """장착 구도 회전 보정 — 반시계 90°. 프레임이 640×480 → 480×640 이 된다."""
    if config.CAMERA_ROTATE_CCW90:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def apply(frame):
    """반전 + 회전. **왜곡보정을 쓰지 않는 곳**(측정 도구)이 쓴다."""
    return rotate(flip(frame))
