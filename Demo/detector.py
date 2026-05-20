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

        from hailo_platform import (
            HEF, VDevice, InferVStreams, ConfigureParams,
            InputVStreamParams, OutputVStreamParams, HailoStreamInterface,
        )

        if not os.path.exists(config.HEF_MODEL_PATH):
            raise FileNotFoundError(
                f"HEF 모델이 없습니다: {config.HEF_MODEL_PATH} "
                "(WSL2에서 best.pt -> best.hef 변환 후 배치하세요)"
            )

        self._lock = threading.Lock()
        self._stack = ExitStack()

        hef = HEF(config.HEF_MODEL_PATH)
        target = self._stack.enter_context(VDevice())
        cfg = ConfigureParams.create_from_hef(
            hef, interface=HailoStreamInterface.PCIe
        )
        network_group = target.configure(hef, cfg)[0]
        in_params = InputVStreamParams.make(network_group)
        out_params = OutputVStreamParams.make(network_group)
        self._in_name = network_group.get_input_vstream_infos()[0].name
        self._pipeline = self._stack.enter_context(
            InferVStreams(network_group, in_params, out_params)
        )
        self._stack.enter_context(network_group.activate(network_group.create_params()))

        # best.pt is a single-class model; keep names in sync after conversion.
        self._names = {0: "person"}

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
        self._stack.close()


def create_detector():
    """Build the detector selected by config.INFERENCE_BACKEND."""
    backend = config.INFERENCE_BACKEND
    if backend == "pytorch":
        return PyTorchDetector()
    if backend == "hailo":
        return HailoDetector()
    raise ValueError(f"알 수 없는 INFERENCE_BACKEND: {backend!r}")
