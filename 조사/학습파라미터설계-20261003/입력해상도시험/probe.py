"""시험용(버림) — console_v2 구조(yolov8n · 5클래스)를 입력 크기만 바꿔 Hailo-8 용으로 변환해 컨텍스트 수·예상 속도를 본다.

실행(데스크톱 WSL · hailo-venv): python probe.py H W
- ONNX 는 미리 export.sh 가 만든 console_v2_<H>x<W>.onnx 를 쓴다.
- 최적화 수준 0 · 캘리브 64장(내용 무관 — 컨텍스트·속도만 본다). 정확도용 결과물이 아니다.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from hailo_sdk_client import ClientRunner

H, W = int(sys.argv[1]), int(sys.argv[2])
HERE = Path(__file__).resolve().parent
TAG = f"{H}x{W}"
NET = "yolov8n"
ENDS = ["/model.22/cv2.0/cv2.0.2/Conv", "/model.22/cv3.0/cv3.0.2/Conv",
        "/model.22/cv2.1/cv2.1.2/Conv", "/model.22/cv3.1/cv3.1.2/Conv",
        "/model.22/cv2.2/cv2.2.2/Conv", "/model.22/cv3.2/cv3.2.2/Conv"]

t0 = time.time()
nms = {
    "nms_scores_th": 0.2, "nms_iou_th": 0.7, "image_dims": [H, W], "max_proposals_per_class": 100,
    "classes": 5, "regression_length": 16, "background_removal": False,
    "bbox_decoders": [
        {"name": f"{NET}/bbox_decoder41", "stride": 8, "reg_layer": f"{NET}/conv41", "cls_layer": f"{NET}/conv42"},
        {"name": f"{NET}/bbox_decoder52", "stride": 16, "reg_layer": f"{NET}/conv52", "cls_layer": f"{NET}/conv53"},
        {"name": f"{NET}/bbox_decoder62", "stride": 32, "reg_layer": f"{NET}/conv62", "cls_layer": f"{NET}/conv63"},
    ],
}
nms_path = HERE / f"nms_{TAG}.json"
nms_path.write_text(json.dumps(nms, indent=2))

runner = ClientRunner(hw_arch="hailo8")
runner.translate_onnx_model(str(HERE / f"console_v2_{TAG}.onnx"), NET, start_node_names=["images"],
                            end_node_names=ENDS, net_input_shapes={"images": [1, 3, H, W]})
runner.load_model_script("\n".join([
    "normalization1 = normalization([0.0, 0.0, 0.0], [255.0, 255.0, 255.0])",
    "change_output_activation(conv42, sigmoid)",
    "change_output_activation(conv53, sigmoid)",
    "change_output_activation(conv63, sigmoid)",
    f'nms_postprocess("{nms_path}", meta_arch=yolov8, engine=cpu)',
    "allocator_param(width_splitter_defuse=disabled)",
    "model_optimization_flavor(optimization_level=0)",
    "model_optimization_config(calibration, calibset_size=64)",
]))
imgs = sorted(Path("/mnt/d/Hailo_DFC/calib_images").glob("*.jpg"))[:64]
calib = np.stack([cv2.cvtColor(cv2.resize(cv2.imread(str(p)), (W, H)), cv2.COLOR_BGR2RGB) for p in imgs]).astype(np.uint8)
print(f"[probe] {TAG} 캘리브 {calib.shape} · 번역 {time.time() - t0:.0f}s", flush=True)
runner.optimize(calib)
print(f"[probe] {TAG} 최적화 끝 {time.time() - t0:.0f}s", flush=True)
hef = runner.compile()
(HERE / f"probe_{TAG}.hef").write_bytes(hef)
runner.save_har(str(HERE / f"probe_{TAG}_compiled.har"))
print(f"[probe] {TAG} 컴파일 끝 {time.time() - t0:.0f}s · HEF {len(hef) / 1e6:.1f}MB", flush=True)
