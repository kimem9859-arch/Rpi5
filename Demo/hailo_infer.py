"""처리 2단계 2a — Hailo 추론을 InferModel 방식으로(추론하는 동안 파이썬 자물쇠 GIL 을 놓는다).

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §3.2 · 스위치 config.INFER_MODEL(SOP_INFER_MODEL=1 · 기본 끔)
🔑 지금 방식(InferVStreams.infer)은 추론 중 GIL 을 쥐어 받기 · 화면 스레드가 멈춘다(버림용 실험: 다른 스레드 계산량 39%) ·
   InferModel.run 은 놓는다(같은 실험 100% · 한 번 약 8ms).
🔴 장치는 hailo_device 의 공유 VDevice(ROUND_ROBIN) — 스위치를 켜면 시연의 모든 모델(버튼 · 공구 · 손바닥 · 손 관절)이 이 방식으로 간다.
   한 장치에 network group 방식과 섞어 올리지 않는다(섞어도 되는지 확인하지 않았다).
"""
import os
import threading

TIMEOUT_MS = 2000


class InferRunner:
    """모델 하나 — 입출력 버퍼를 한 번 만들어 재사용한다. infer({이름: 배열}) → {출력 이름: 배열(앞에 배치 축 1)}."""

    def __init__(self, hef_path):
        from contextlib import ExitStack

        import numpy as np
        from hailo_platform import FormatType

        import hailo_device
        self._lock = threading.Lock()
        self._stack = ExitStack()
        self._im = hailo_device.get_vdevice().create_infer_model(os.path.abspath(hef_path))
        self._im.input().set_format_type(FormatType.UINT8)
        for o in self._im.outputs:
            o.set_format_type(FormatType.FLOAT32)          # 지금 방식(InferVStreams FLOAT32)과 같은 역양자화 값
        self._cfg = self._stack.enter_context(self._im.configure())
        self._bind = self._cfg.create_bindings()
        self.input_name = self._im.input().name
        self._in_shape = tuple(self._im.input().shape)
        self._outs = {o.name: np.empty(o.shape, np.float32) for o in self._im.outputs}
        for name, buf in self._outs.items():
            self._bind.output(name).set_buffer(buf)
        self.output_names = list(self._outs)

    def infer(self, inputs):
        import numpy as np
        x = np.ascontiguousarray(next(iter(inputs.values())), dtype=np.uint8).reshape(self._in_shape)
        with self._lock:
            self._bind.input().set_buffer(x)
            self._cfg.run([self._bind], TIMEOUT_MS)
            return {k: v.copy()[np.newaxis] for k, v in self._outs.items()}   # 배치 축 — InferVStreams 결과와 같은 모양

    def close(self):
        self._stack.close()


def nms_classes(hef_path):
    """NMS 출력의 클래스 수(HEF 에서)."""
    from hailo_platform import HEF
    return HEF(os.path.abspath(hef_path)).get_output_vstream_infos()[0].nms_shape.number_of_classes


def parse_nms_by_class(flat, n_cls):
    """NMS(클래스별) 평평한 출력 → 클래스마다 (k, 5) [ymin, xmin, ymax, xmax, score] — 클래스마다 개수 뒤에 상자가 빈틈없이 이어진다."""
    import numpy as np
    flat = np.asarray(flat, np.float32).reshape(-1)
    out, k = [], 0
    for _ in range(n_cls):
        cnt = int(flat[k]) if k < flat.size else 0
        k += 1
        out.append(flat[k:k + cnt * 5].reshape(cnt, 5))
        k += cnt * 5
    return out
