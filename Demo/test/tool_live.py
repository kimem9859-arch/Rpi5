"""공구 검출 실시간 뷰어 — ESP32 스트림에 tool 모델을 얹어 눈으로 확인한다.

왜 있나 (2026-08-11):
    저장된 프레임 채점만으로는 **왜 틀리는지**가 안 보인다. 스패너를 뭐라고
    부르는지, 미니 드라이버가 왜 `wrench` 가 되는지를 공구를 손에 들고
    돌려가며 즉시 확인하려고 만들었다. 판정 근거 = 통합문서 §10.37.

⚠️ CPU 추론이다(ultralytics). Hailo 는 `.hef` 가 없어 못 쓴다.
   🔑 **추론을 별도 스레드로 돌린다** — 2026-08-11 실측으로 병목을 분리했다:
       수신 27.1fps · 수신+디코드 25.1fps · **추론 380ms/frame(2.6fps)**
   추론을 화면 루프에 묶으면 영상까지 2.6fps 로 끌려 내려간다. 분리하면
   **영상은 25fps 로 부드럽고 박스만 초당 2~3회 갱신**된다(눈확인엔 충분).
   상단 띠에 video/infer fps 를 따로 표시하니 둘을 혼동하지 말 것.

⚠️ 실행 환경: 파이 기본 Python 3.13 에는 ultralytics 가 없다(§10.35-(7) 함정).
   ✅ **이미 만들어 둔 환경이 `~/rfenv` 에 있다** — 그냥 쓰면 된다:
       ~/rfenv/bin/python tool_live.py
   없으면 다시 만든다(약 10분). 🔴 `--torch-backend cpu` 를 빼면 NVIDIA CUDA
   스택을 끌어와 디스크 5GB 를 잠식한다(파이엔 GPU 가 없다):
       uv venv --python 3.12 ~/rfenv
       VIRTUAL_ENV=~/rfenv uv pip install --torch-backend cpu ultralytics inference

🔑 **자동 캡처** — 공구를 들고 찍는 동안 키를 누를 수 없어서(2026-08-11 사용자 요청)
   **검출이 뜬 프레임만 스스로 저장**한다. 저장 위치 = `~/lab/tool-detect/tool_live_shots/`.
   파일명에 **모델·클래스·신뢰도**가 들어가 나중에 정렬·판독이 쉽다:
       v1_wrench-0.72_143052.png
   같은 장면이 쏟아지지 않게 **최소 간격(AUTO_MIN_GAP)** 을 두고, 클래스 조합이
   바뀌면 간격과 무관하게 즉시 한 장 남긴다(전환 순간이 가장 정보가 많다).

조작:
    1 / 2   모델 전환 (tool_v1 / tool_v2)
    ↑ / ↓   신뢰도 임계 ±0.05
    a       자동 캡처 켜기/끄기
    s       지금 화면을 강제로 한 장 저장
    q, ESC  종료
"""
import os
import socket
import struct
import threading
import sys
import time

import cv2
import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
import config

MODELS = {
    ord('1'): ("tool_v1", os.path.join(_DEMO, "models", "tool_v1.pt")),
    ord('2'): ("tool_v2", os.path.join(_DEMO, "models", "tool_v2.pt")),
    # 🆕 tool_v3 (2026-08-13) — 클래스가 다르다: driver·wrench·**pliers**
    #    v1·v2 의 `spanner`(몽키)는 없어졌다. 우리 오픈엔드의 정답은 `wrench`(§10.39-(6)).
    ord('3'): ("tool_v3", os.path.join(_DEMO, "models", "tool_v3.pt")),
}
# 클래스별 색(BGR) — 오분류가 한눈에 보이도록 서로 멀리 띄운다
COLOR = {"spanner": (255, 120, 0), "driver": (0, 220, 255), "wrench": (0, 255, 120),
         "pliers": (255, 80, 255)}
MAX_FRAME_BYTES = 512 * 1024

SHOT_DIR = os.path.expanduser("~/lab/tool-detect/tool_live_shots")
AUTO_MIN_GAP = 1.5      # 초 — 같은 장면이 수백 장 쌓이는 것을 막는다
AUTO_MAX_SHOTS = 300    # 디스크·검토 부담 상한. 넘으면 자동 캡처만 멈춘다


def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv_latest(sock):
    """가장 최신 프레임만 돌려준다 — 밀린 프레임을 버려야 지연이 안 쌓인다."""
    import select
    while True:
        head = recv_exact(sock, 4)
        if head is None:
            return None
        size = struct.unpack('<I', head)[0]
        if size == 0 or size > MAX_FRAME_BYTES:
            return None
        data = recv_exact(sock, size)
        if data is None:
            return None
        readable, _, _ = select.select([sock], [], [], 0)
        if not readable:
            return data


class Inferencer:
    """최신 프레임만 물고 추론하는 워커.

    화면 루프와 분리하는 것이 목적이다 — 큐를 쌓지 않고 **항상 마지막 프레임만**
    본다(밀리면 오래된 박스가 늦게 그려져 오히려 헷갈린다).
    """

    def __init__(self, model, conf):
        self._model = model
        self._conf = conf
        self._frame = None
        self._dets = []
        self._fps = 0.0
        self._lock = threading.Lock()
        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def submit(self, frame):
        with self._lock:
            self._frame = frame

    def result(self):
        with self._lock:
            return list(self._dets), self._fps

    def set_model(self, model):
        with self._lock:
            self._model = model
            self._dets = []

    def set_conf(self, conf):
        with self._lock:
            self._conf = conf

    def stop(self):
        self._running = False
        self._t.join(timeout=2)

    def _loop(self):
        last = time.time()
        while self._running:
            with self._lock:
                frame, model, conf = self._frame, self._model, self._conf
                self._frame = None
            if frame is None:
                time.sleep(0.005)
                continue
            r = model.predict(frame, conf=conf, verbose=False)[0]
            dets = [(int(b.cls), float(b.conf), tuple(int(v) for v in b.xyxy[0]))
                    for b in r.boxes]
            now = time.time()
            with self._lock:
                self._dets = dets
                self._fps = 0.7 * self._fps + 0.3 / max(1e-6, now - last)
            last = now


def save_shot(shown, raw, dets, names, tag):
    """검출 내용을 파일명에 담아 저장한다 — 나중에 파일명만 보고 정렬·판독한다.

    🔴 **박스를 그린 것(`shown`)과 원본(`raw`)을 둘 다 남긴다.** 그린 이미지에
       다른 모델을 다시 돌리면 사각형·글자가 판정에 섞여 **오염된 비교**가 된다
       (2026-08-11에 실제로 겪음 — v1 박스가 그려진 77장에 v2를 돌렸다).
       사람이 볼 것은 `shown`, 재추론에 쓸 것은 `raw/` 다.
    """
    os.makedirs(os.path.join(SHOT_DIR, "raw"), exist_ok=True)
    if dets:
        top = sorted(dets, key=lambda d: -d[1])[:2]
        part = "_".join(f"{names[c]}-{s:.2f}" for c, s, _ in top)
    else:
        part = "none"
    name = f"{tag}_{part}_{time.strftime('%H%M%S')}.png"
    path = os.path.join(SHOT_DIR, name)
    cv2.imwrite(path, shown)
    cv2.imwrite(os.path.join(SHOT_DIR, "raw", name), raw)
    return path


def draw(frame, dets, names, model_tag, conf_th, fps, auto=None):
    for cls, score, (x1, y1, x2, y2) in dets:
        name = names[cls]
        color = COLOR.get(name, (200, 200, 200))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{name} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
        cv2.putText(frame, label, (x1 + 3, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

    bar = (f"{model_tag}  conf>={conf_th:.2f}  "
           f"video {fps[0]:4.1f}fps / infer {fps[1]:4.1f}fps  det={len(dets)}")
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(frame, bar, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    if auto is not None:
        txt = f"AUTO {'ON' if auto[0] else 'OFF'}  shots={auto[1]}"
        col = (0, 255, 120) if auto[0] else (120, 120, 120)
        cv2.putText(frame, txt, (frame.shape[1] - 210, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    cv2.putText(frame, "1/2=model  UP/DOWN=conf  a=auto  s=save  q=quit",
                (8, frame.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return frame


def main():
    from ultralytics import YOLO

    host = config.CAMERA_TCP_HOST
    port = config.CAMERA_TCP_PORT
    # 시작 모델은 인자로 고른다: `tool_live.py 1` → tool_v1 로 시작.
    # 기본은 tool_v3 — v1·v2 는 폐기된 모델이라 비교 기준선으로만 남겨 둔다.
    start = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("1", "2", "3") else "3"
    tag, path = MODELS[ord(start)]
    print(f"모델 로드: {tag}")
    model = YOLO(path)
    conf_th = 0.60      # 낮으면 키보드·손 같은 배경을 오탐한다(2026-08-11 관찰)

    print(f"ESP32 연결: {host}:{port}")
    sock = socket.socket()
    sock.settimeout(10)
    sock.connect((host, port))
    print("✅ 연결됨 — 창을 보세요 (q 로 종료)")

    win = "tool live"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1280, 960)
    worker = Inferencer(model, conf_th)
    last, vfps = time.time(), 0.0
    auto_on, shots, last_shot, last_combo = True, 0, 0.0, None
    print(f"자동 캡처 ON — 검출될 때만 저장합니다: {SHOT_DIR}")

    try:
        while True:
            data = recv_latest(sock)
            if data is None:
                print("스트림 종료")
                break
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if config.CAMERA_FLIP_VERTICAL:
                frame = cv2.flip(frame, 0)

            # ⚠️ draw() 가 프레임을 제자리에서 고치므로 **그리기 전에** 원본을 뜬다.
            #    이 사본이 다른 모델로 재추론할 때 쓰는 오염 없는 입력이다.
            frame_raw = frame.copy()

            # 🔑 추론은 워커에 맡기고 화면은 받는 대로 그린다 — 박스는 마지막
            #    추론 결과를 재사용한다(초당 2~3회 갱신).
            worker.submit(frame_raw)
            dets, ifps = worker.result()

            now = time.time()
            vfps = 0.8 * vfps + 0.2 / max(1e-6, now - last)
            last = now
            shown = draw(frame, dets, model.names, tag, conf_th, (vfps, ifps),
                         (auto_on, shots))

            # 🔑 자동 캡처 — 검출이 있을 때만. 클래스 조합이 바뀌면 간격을 무시하고
            #    즉시 남긴다(오분류가 바뀌는 순간이 가장 정보가 많다).
            if auto_on and dets and shots < AUTO_MAX_SHOTS:
                combo = tuple(sorted(model.names[c] for c, _, _ in dets))
                if combo != last_combo or now - last_shot >= AUTO_MIN_GAP:
                    save_shot(shown, frame_raw, dets, model.names, tag)
                    shots += 1
                    last_shot, last_combo = now, combo

            cv2.imshow(win, shown)

            k = cv2.waitKey(1) & 0xFF
            if k in (ord('q'), 27):
                break
            if k in MODELS:
                tag, path = MODELS[k]
                print(f"모델 전환: {tag}")
                model = YOLO(path)
                worker.set_model(model)
            elif k == 82:                      # ↑
                conf_th = min(0.95, conf_th + 0.05)
                worker.set_conf(conf_th)
            elif k == 84:                      # ↓
                conf_th = max(0.05, conf_th - 0.05)
                worker.set_conf(conf_th)
            elif k == ord('a'):
                auto_on = not auto_on
                print(f"자동 캡처 {'ON' if auto_on else 'OFF'}")
            elif k == ord('s'):
                print(f"저장: {save_shot(shown, frame_raw, dets, model.names, tag)}")
    finally:
        worker.stop()
        sock.close()
        cv2.destroyAllWindows()
        print(f"자동 캡처 {shots}장 저장됨 → {SHOT_DIR}")


if __name__ == "__main__":
    main()
