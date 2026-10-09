"""연출 시험본 1단계 — 오버레이 없는 원본 영상에 시연 모델을 다시 돌려 프레임별 박스·손 21점을 JSON 으로.

python3 extract.py <원본.mp4> <출력.json> <시작프레임> <끝프레임>
검출·추적은 런타임 모듈을 그대로 부른다(재구현 없음): detector.HailoDetector · camera_thread._update_tracks · hand_tracker.
"""
import json
import os
import sys

DEMO = "/home/pi/sop-project/Rpi5/Demo"
sys.path.insert(0, DEMO)
os.chdir(DEMO)

import cv2  # noqa: E402

import config  # noqa: E402
from detector import HailoDetector  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402

# 🔴 camera_thread 를 import 하면 그 뒤 새로 만든 HailoDetector 의 첫 추론이 멈춘다(2026-10-09 실측).
#    그래서 추적 함수(_iou·_update_tracks·_one_per_class)만 소스에서 꺼내 config 값으로 실행한다 — 런타임 코드 그대로.
import ast  # noqa: E402
_src = open(os.path.join(DEMO, "camera_thread.py"), encoding="utf-8").read()
_want = {"_iou", "_update_tracks", "_one_per_class"}
_mod = ast.Module(body=[n for n in ast.parse(_src).body if isinstance(n, ast.FunctionDef) and n.name in _want],
                  type_ignores=[])
ct_ns = {k: getattr(config, k) for k in ("YOLO_IOU_MATCH", "YOLO_CONF_HIGH", "YOLO_CONFIRM_HITS", "YOLO_MAX_MISS")}
exec(compile(_mod, "camera_thread.py", "exec"), ct_ns)

src, out, f0, f1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
btn_det = HailoDetector()
hand = HandTracker()
# 🔴 공구 검출기를 손보다 먼저 올리면 공구 추론이 멈춘다(2026-10-09 실측 · 버튼 → 손 → 공구 순서만 됨)
tool_det = HailoDetector(config.TOOL_HEF_PATH, dict(enumerate(config.TOOL_NAMES)))
print("hand available:", hand.available, hand.reason)

cap = cv2.VideoCapture(src)
cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
tracks, rows = [], []
for f in range(f0, f1):
    ok, fr = cap.read()
    if not ok:
        break
    tracks = ct_ns["_update_tracks"](tracks, btn_det.detect(fr))
    btn = [[btn_det.class_name(t["cls"]), round(float(t["score"]), 3), *map(int, t["box"])]
           for t in tracks if t["confirmed"]]
    tools = [[tool_det.class_name(c), round(float(s), 3), int(x1), int(y1), int(x2), int(y2)]
             for c, s, x1, y1, x2, y2 in tool_det.detect(fr) if s >= config.TOOL_CONF]
    hand.detect(fr)
    lm = None if hand.last_landmarks is None else [[round(float(x), 1), round(float(y), 1)]
                                                    for x, y, _z in hand.last_landmarks]
    rows.append({"f": f, "btn": btn, "tool": tools, "hand": lm})
    if f % 60 == 0:
        print(f, len(btn), len(tools), lm is not None, flush=True)

json.dump({"src": src, "fps": cap.get(cv2.CAP_PROP_FPS), "rows": rows}, open(out, "w"))
print("done", len(rows))
