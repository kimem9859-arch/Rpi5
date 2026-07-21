"""Swappable inference backend abstraction.

Phase A uses PyTorchDetector (best.pt, ultralytics CPU inference).
Phase B switches to HailoDetector (best.hef, Hailo-8 accelerated inference)
by changing config.INFERENCE_BACKEND to "hailo".
"""

import os
import threading

import config


class BaseDetector:
    """Common interface for all inference backends."""

    backend_name = "base"

    def detect(self, frame):
        """Run inference on a BGR frame.

        Returns a list of (cls_id, score, x1, y1, x2, y2) tuples.
        """
        raise NotImplementedError

    def class_name(self, cls_id):
        """Map a class id to its display name."""
        raise NotImplementedError

    def close(self):
        """Release backend resources. Optional."""
        pass


class PyTorchDetector(BaseDetector):
    """Phase A backend: best.pt via ultralytics, CPU inference."""

    backend_name = "pytorch"

    def __init__(self):
        from ultralytics import YOLO

        if not os.path.exists(config.PT_MODEL_PATH):
            raise FileNotFoundError(f"PyTorch 모델이 없습니다: {config.PT_MODEL_PATH}")

        self._model = YOLO(config.PT_MODEL_PATH)
        self._names = dict(self._model.names)
        self._lock = threading.Lock()

    def detect(self, frame):
        with self._lock:
            results = self._model(
                frame, imgsz=config.YOLO_INPUT_SIZE, verbose=False
            )[0]
        detections = []
        for box in results.boxes:
            score = float(box.conf[0])
            if score < config.YOLO_CONF_LOW:
                continue
            cls_id = int(box.cls[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append((cls_id, score, x1, y1, x2, y2))
        return detections

    def class_name(self, cls_id):
        return self._names.get(cls_id, str(cls_id))


class HailoDetector(BaseDetector):
    """Phase B backend: best.hef via Hailo-8 accelerator.

    Requires the best.pt -> best.hef conversion (done on x86_64 WSL2) and the
    hailo_platform package installed in this venv. Imports are lazy so that
    Phase A runs without hailo_platform present. The inference path follows
    the proven pattern from claude-project-old/camera_stream_tcp/yolo_hailo_tcp.py.
    This implementation is unverified until Phase B hardware testing.
    """

    backend_name = "hailo"

    def __init__(self):
        from contextlib import ExitStack

        from hailo_platform import InferVStreams, InputVStreamParams, OutputVStreamParams

        import hailo_device

        self._lock = threading.Lock()
        self._stack = ExitStack()

        # 장치는 hailo_device 가 소유한다(공유). 여기서 VDevice 를 만들면
        # 손 검출 등 다른 모델을 올릴 수 없다 — HAILO_OUT_OF_PHYSICAL_DEVICES.
        network_group = hailo_device.configure(config.HEF_MODEL_PATH)
        in_params = InputVStreamParams.make(network_group)
        out_params = OutputVStreamParams.make(network_group)
        self._in_name = network_group.get_input_vstream_infos()[0].name
        self._pipeline = self._stack.enter_context(
            InferVStreams(network_group, in_params, out_params)
        )
        # ⚠️ network_group.activate() 를 부르지 않는다 — ROUND_ROBIN 스케줄러가
        #    컨텍스트 전환을 관리한다. 수동 활성화는 장치를 독점해 다른 모델을 막는다.

        self._names = {0: "B1", 1: "B2", 2: "B3", 3: "B4", 4: "EMO"}

    def detect(self, frame):
        import cv2
        import numpy as np

        h, w = frame.shape[:2]
        img = cv2.resize(frame, (config.YOLO_INPUT_SIZE, config.YOLO_INPUT_SIZE))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.uint8)

        with self._lock:
            output = self._pipeline.infer({self._in_name: img[np.newaxis]})

        detections = []
        raw = list(output.values())[0][0]
        for cls_id, cls_dets in enumerate(raw):
            arr = np.array(cls_dets)
            if arr.ndim != 2 or arr.shape[0] == 0:
                continue
            for det in arr:
                ymin, xmin, ymax, xmax, score = det
                if score < config.YOLO_CONF_LOW:
                    continue
                detections.append((
                    cls_id, float(score),
                    int(xmin * w), int(ymin * h),
                    int(xmax * w), int(ymax * h),
                ))
        return detections

    def class_name(self, cls_id):
        return self._names.get(cls_id, str(cls_id))

    def close(self):
        """자기 추론 파이프라인만 닫는다.

        공유 VDevice 는 건드리지 않는다 — 닫으면 같은 장치를 쓰는 다른 모델
        (손 검출 등)이 함께 죽는다. 장치 해제가 정말 필요하면 hailo_device.shutdown().
        """
        self._stack.close()


def create_detector():
    """Build the detector selected by config.INFERENCE_BACKEND."""
    backend = config.INFERENCE_BACKEND
    if backend == "pytorch":
        return PyTorchDetector()
    if backend == "hailo":
        return HailoDetector()
    raise ValueError(f"알 수 없는 INFERENCE_BACKEND: {backend!r}")
