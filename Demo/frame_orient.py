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
    왜곡보정 맵은 **센서 원본 해상도 전용**으로 만들어진다(해상도별 파일
    `camera_calibration_<w>x<h>.npz` — `calibration_path`). 회전을 먼저 하면 가로세로가
    뒤바뀌어 'mismatch' 로 판단돼 **왜곡보정이 조용히 꺼진다.** 렌즈 왜곡은 센서
    좌표계의 성질이므로 원본 방향에서 펴고 그 다음에 돌리는 것이 맞다.
    그래서 `flip()` 과 `rotate()` 를 따로 노출한다 — 런타임은 그 사이에
    왜곡보정을 끼우고, 왜곡보정이 없는 도구는 `apply()` 하나로 끝낸다.
"""

import os

import cv2
import numpy as np

import config


def flip(frame):
    """센서 상하반전 보정 — 카메라 모듈이 거꾸로 장착돼 원본이 뒤집혀 온다."""
    if config.CAMERA_FLIP_VERTICAL:
        return cv2.flip(frame, 0)
    return frame


def rotate(frame):
    """장착 구도 회전 보정 — 반시계 90°. 가로 프레임이 세로가 된다(VGA 640×480 → 480×640)."""
    if config.CAMERA_ROTATE_CCW90:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def apply(frame):
    """반전 + 회전. **왜곡보정을 쓰지 않는 곳**(측정 도구)이 쓴다."""
    return rotate(flip(frame))


def calibration_path(w, h, base_dir=None):
    """(w, h) 센서 원본 크기에 맞는 보정 파일 — (경로, 'ok'|'missing'|'mismatch').

    ① `camera_calibration_<w>x<h>.npz`(test/calib_capture.py 가 만든다) 를 먼저 찾고
    ② 없으면 기존 `camera_calibration.npz` 를 **image_size 가 맞을 때만** 쓴다.
    🔴 크기가 안 맞는 파일은 절대 쓰지 않는다 — 다른 해상도의 보정은 틀린 보정이다.
    """
    d = base_dir or os.path.dirname(config.YOLO_CALIBRATION_PATH)
    per = os.path.join(d, f"camera_calibration_{w}x{h}.npz")
    legacy = os.path.join(d, os.path.basename(config.YOLO_CALIBRATION_PATH))
    cand = [p for p in (per, legacy) if os.path.exists(p)]
    if not cand:
        return None, "missing"
    for p in cand:
        data = np.load(p)
        if "image_size" not in data or tuple(int(v) for v in data["image_size"]) == (w, h):
            return p, "ok"
    return None, "mismatch"


def load_undistort(w, h, base_dir=None):
    """→ (맵 또는 None, 상태, 쓴 파일 경로). 런타임·도구가 모두 이것을 쓴다.

    🔴 None 을 받으면 **보정 없이 조용히 진행하지 말고 경고를 띄운다** — 조용히
       꺼지는 것이 이 함정의 본질이다(로그 한 줄만 남고 화면은 멀쩡해 보인다).
    """
    path, status = calibration_path(w, h, base_dir)
    if path is None:
        return None, status, None
    data = np.load(path)
    cam_mat, dist = data["camera_matrix"], data["dist_coeffs"]
    new_mat, _ = cv2.getOptimalNewCameraMatrix(cam_mat, dist, (w, h), config.CALIB_ALPHA, (w, h))
    maps = cv2.initUndistortRectifyMap(cam_mat, dist, None, new_mat, (w, h), cv2.CV_16SC2)
    return maps, "ok", path


def undistort_map(w, h):
    """기존 호출부 호환 — 맵만. 없거나 크기가 다르면 None(호출부가 경고를 책임진다)."""
    return load_undistort(w, h)[0]


def px_scale(w, h):
    """픽셀 설정 배율 — VGA(640×480) 기준값에 곱한다. 긴 변 기준이라 회전 전후가 같다."""
    return max(w, h) / 640.0


def ring_px(w, h):
    """ROI 링(1단계) 폭 px — config.HAND_ROI_RING_PX_VGA × px_scale. 런타임·도구 공통(XGA → 40)."""
    return int(round(config.HAND_ROI_RING_PX_VGA * px_scale(w, h)))


def undistort(frame, maps):
    """맵이 None 이면 원본을 그대로 돌려준다(호출부가 경고를 책임진다)."""
    if maps is None:
        return frame
    return cv2.remap(frame, maps[0], maps[1], cv2.INTER_LINEAR)


def apply_full(frame, maps):
    """런타임과 같은 전체 순서 — 반전 → 왜곡보정 → 회전."""
    return rotate(undistort(flip(frame), maps))


def _selftest() -> int:
    """있는 보정 파일마다 순서·크기 규약을 확인한다."""
    for (w, h) in ((640, 480), (1024, 768)):
        maps, st, p = load_undistort(w, h)
        if maps is None:
            print(f"  {w}×{h}: 보정 파일 없음({st}) — 건너뜀"); continue
        f = np.zeros((h, w, 3), np.uint8)
        out = apply_full(f, maps)
        exp = (h, w) if config.CAMERA_ROTATE_CCW90 else (w, h)
        assert (out.shape[1], out.shape[0]) == exp, out.shape
        print(f"  {w}×{h}: {os.path.basename(p)} OK")
    print("selftest OK")
    return 0
