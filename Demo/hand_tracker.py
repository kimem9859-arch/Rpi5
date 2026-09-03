"""손 검출(HOI) — Hailo 팜검출 + 핸드랜드마크 21점 → 검지 끝 좌표.

왜 이렇게 하나:
    MediaPipe **프레임워크**는 Python 3.13/aarch64 휠이 없어 이 파이에서 못 쓴다.
    그래서 **구글 MediaPipe의 모델 자체**(BlazePalm·BlazeHandLandmark)를 Hailo용
    `.hef` 로 변환한 것을 쓴다 — 의존성이 `hailo_platform`+numpy+cv2 뿐이라
    3.13 문제가 원천 소멸한다. 모델은 같고 실행 경로만 다르다.
    근거·실증 = `docs/superpowers/specs/2026-07-21-HOI-경로-design.md`

⚠️ **모델·소스가 없으면 조용히 비활성된다.** `detect()` 가 항상 None 을 돌려주므로
   호출부(camera_thread)는 손 검출이 없던 종전과 **정확히 같게** 동작한다.
   시연 경로에 위험을 얹지 않기 위한 설계다.

⚠️ **장치는 `hailo_device` 가 소유한다.** 여기서 VDevice 를 만들면 버튼 검출 모델과
   충돌한다(`HAILO_OUT_OF_PHYSICAL_DEVICES`).

자체 점검(카메라 불필요):
    python3 hand_tracker.py <이미지.png> [출력.png]
"""

import contextlib
import os
import sys
import threading

import config

TIP = 8          # MediaPipe 손 랜드마크 인덱스 8 = 검지 끝. 접촉 판정 기준점(§7.2)

_paths_ready = False


def _prepare_paths():
    """blaze 소스를 import 경로에 넣는다(최초 1회)."""
    global _paths_ready
    if _paths_ready:
        return
    for sub in ("blaze_common", "blaze_hailo"):
        p = os.path.join(config.HAND_BLAZE_DIR, sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    _paths_ready = True


class _NoActivateGroup:
    """network_group 얇은 감싸개 — deprecated `activate()` 만 가로챈다.

    🔴 왜 필요한가: blaze 소스가 **추론할 때마다** `network_group.activate()` 를
       부른다(blazedetector.py:199 · blazelandmark.py:126 · hailo_inference.py:134·156).
       우리는 ROUND_ROBIN 스케줄러를 쓰므로 pyhailort 는 그 호출을 **무시하고
       경고만** 낸다(pyhailort.py:581) — 손 추론이 도는 프레임마다 터미널에
       "Calls to `activate()` when working with scheduler are deprecated!" 가 쌓인다.

    ⚠️ 감싸개를 여기 두는 이유: blaze 소스는 **repo 밖**(`~/lab/hoi/`)이라
       고쳐도 클론·sop-pi-2 에 따라가지 않는다. 우리가 넘겨주는 쪽을 감싸면
       repo 코드만으로 어디서나 같게 동작한다.

    동작은 바뀌지 않는다 — 스케줄러가 켜져 있으면 pyhailort 의 activate() 도
    아무 일도 하지 않고 빈 컨텍스트 매니저를 돌려줄 뿐이다(같은 pyhailort.py:583).
    """

    def __init__(self, network_group):
        self._ng = network_group

    def activate(self, network_group_params=None):
        return contextlib.nullcontext()

    def __getattr__(self, name):
        # InferVStreams 는 `_configured_network` 같은 비공개 속성도 직접 집는다.
        return getattr(self._ng, name)


class _SharedInference:
    """blaze 의 HailoInference 를 흉내 내되 **공유 VDevice** 를 쓴다.

    원본은 생성자에서 자체 `VDevice()` 를 만들어 버튼 모델과 충돌한다.
    필요한 속성만 채워 넣고 장치는 `hailo_device` 것을 그대로 쓴다.
    """

    def __init__(self):
        import hailo_device
        self.target = hailo_device.get_vdevice()
        self.hef_cnt = 0
        self.hef_list = []
        self.network_group_list = []
        self.network_group_params_list = []
        self.input_vstreams_params_list = []
        self.output_vstreams_params_list = []

    def _configure_and_get_network_group(self, hef, target):
        """원본 그대로 올리되, 돌려주는 network_group 을 감싼다(위 _NoActivateGroup)."""
        _prepare_paths()
        from hailo_inference import HailoInference
        ng = HailoInference._configure_and_get_network_group(self, hef, target)
        return _NoActivateGroup(ng)

    # blaze 의 HailoInference 메서드를 그대로 빌려 쓴다
    def __getattr__(self, name):
        _prepare_paths()
        from hailo_inference import HailoInference
        attr = getattr(HailoInference, name)
        return attr.__get__(self, _SharedInference)


class HandTracker:
    """프레임 → 검지 끝 좌표. 사용 불가 환경에서는 조용히 비활성된다."""

    def __init__(self, log=None):
        self._log = log or (lambda m: print(m))
        self._lock = threading.Lock()
        self._det = self._lm = None
        self.available = False
        self.reason = ""
        # 마지막 프레임의 손 랜드마크 21점(numpy Nx3). 손이 없으면 None.
        # 🔑 반환값은 종전대로 검지 끝 하나다 — 이건 판정 좌표를 바꿔볼 때
        #    쓰는 **읽기 전용 부산물**이다(점검 도구용, 런타임은 안 쓴다).
        self.last_landmarks = None

        if not getattr(config, "HAND_ENABLED", False):
            self.reason = "config.HAND_ENABLED=False"
            self._log(f"[손검출] 비활성 — {self.reason}")
            return

        palm = os.path.join(config.HAND_MODELS_DIR, "palm_detection_lite.hef")
        hand = os.path.join(config.HAND_MODELS_DIR, "hand_landmark_lite.hef")
        missing = [p for p in (palm, hand) if not os.path.exists(p)]
        if missing or not os.path.isdir(config.HAND_BLAZE_DIR):
            self.reason = f"모델/소스 없음: {missing or config.HAND_BLAZE_DIR}"
            self._log(f"[손검출] 비활성 — {self.reason} (버튼 검출은 정상)")
            return

        try:
            _prepare_paths()
            from blazedetector import BlazeDetector
            from blazelandmark import BlazeLandmark
            infer = _SharedInference()
            self._det = BlazeDetector("blazepalm", infer)
            self._det.set_debug(debug=False)
            self._det.load_model(palm)
            self._lm = BlazeLandmark("blazehandlandmark", infer)
            self._lm.set_debug(debug=False)
            self._lm.load_model(hand)
            self.available = True
            self._log("[손검출] Hailo 팜+핸드 준비 완료 (MediaPipe 모델·NPU 실행)")
        except Exception as e:
            self.reason = f"{type(e).__name__}: {e}"
            self._log(f"[손검출] 초기화 실패 — {self.reason} (버튼 검출은 정상)")
            self._det = self._lm = None

    def detect(self, frame_bgr, draw_on=None):
        """검지 끝 (x, y) 픽셀 좌표. 손이 없거나 비활성이면 None.

        draw_on 을 주면 그 이미지에 랜드마크와 검지 끝을 그린다(원본과 같은 배열 가능).
        """
        if not self.available:
            return None
        import cv2
        import numpy as np
        self.last_landmarks = None
        try:
            with self._lock:                       # NPU 접근 직렬화
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                img1, scale1, pad1 = self._det.resize_pad(rgb)
                norm = self._det.predict_on_image(img1)
                if len(norm) == 0:
                    return None
                dets = self._det.denormalize_detections(norm, scale1, pad1)
                xc, yc, sc, theta = self._det.detection2roi(dets)
                roi_img, roi_affine, _box = self._lm.extract_roi(rgb, xc, yc, theta, sc)
                res = self._lm.predict(roi_img)    # 손 모델은 3값(flag, lm, handedness)
                flags, norm_lm = res[0], res[1]
                lms = self._lm.denormalize_landmarks(norm_lm, roi_affine)
            if len(lms) == 0 or flags is None:
                return None
            if float(np.max(flags)) < config.HAND_MIN_SCORE:
                return None
            hand = lms[0]
            self.last_landmarks = hand
            tip = (int(hand[TIP][0]), int(hand[TIP][1]))
            if draw_on is not None and getattr(config, "HAND_DRAW", True):
                for x, y, _z in hand:
                    cv2.circle(draw_on, (int(x), int(y)), 3, (0, 255, 0), -1)
                cv2.circle(draw_on, tip, 12, (255, 0, 255), -1)
                cv2.circle(draw_on, tip, 14, (255, 255, 255), 2)
            return tip
        except Exception as e:
            # 한 프레임 실패로 파이프라인을 죽이지 않는다 — 버튼 검출은 계속돼야 한다
            self._log(f"[손검출] 프레임 처리 실패: {type(e).__name__}: {e}")
            return None

    def close(self):
        self._det = self._lm = None
        self.available = False


# =============================================================================
# 자체 점검 — 카메라 없이 정지 이미지로 확인
# =============================================================================
if __name__ == "__main__":
    import cv2
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    img = cv2.imread(sys.argv[1])
    if img is None:
        print(f"이미지를 읽을 수 없습니다: {sys.argv[1]}")
        sys.exit(2)
    t = HandTracker()
    print(f"available={t.available}" + (f" ({t.reason})" if t.reason else ""))
    tip = t.detect(img, draw_on=img)
    print(f"검지 끝: {tip}")
    if len(sys.argv) > 2:
        cv2.imwrite(sys.argv[2], img)
        print(f"시각화 저장: {sys.argv[2]}")
    t.close()
