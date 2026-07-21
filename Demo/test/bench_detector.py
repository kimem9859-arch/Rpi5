"""Hailo 실추론 벤치마크 — FPS·탐지율·안정성 측정.

대상 모델은 config.HEF_MODEL_PATH가 가리키는 것(현재 console_v2.hef). --hef 옵션은 없다.

실행:
    cd ~/sop-project/Rpi5/Demo
    python3 test/bench_detector.py                              # ESP32, 기본 300프레임
    python3 test/bench_detector.py --frames 100 --no-video
    python3 test/bench_detector.py --source esp32 --frames 500  # ESP32-S3(OV3660) TCP
    python3 test/bench_detector.py --source usb   --frames 500  # USB 웹캠 (B4 원인 대조)

플립(--flip, 기본 auto):
    esp32 → 수직(카메라 거꾸로 장착 보정, 추론에 필요)
    usb   → 없음(실런타임의 좌우 미러링은 표시용. 거울상은 학습 방향과 달라 검출률 왜곡)

출력 (파일명 태그 = YYYYMMDD_HHMMSS_<src>[_<condition>][_<model>]):
    <src>       = esp32 | usb
    <condition> = --condition 지정 시에만. 예: fluorescent/lowlight/daylight/cleanroom
    <model>     = config가 가리키는 모델 stem(console_v2 등) — 자동 유도
    예: test/logs/20260720_143012_esp32_lowlight_console_v2_rawdet_log.csv
    ※ 파일명 규약은 test/db_import.py의 _LOG_RE와 공유한다 — 한쪽만 바꾸면 적재에서 스킵된다.

    test/logs/YYYYMMDD_HHMMSS_<src>_perf_log.csv
    test/logs/YYYYMMDD_HHMMSS_<src>_detection_log.csv    (confirmed 트랙 ≥CONF_HIGH)
    test/logs/YYYYMMDD_HHMMSS_<src>_stability_log.csv
    test/logs/YYYYMMDD_HHMMSS_<src>_confusion_log.csv
    test/logs/YYYYMMDD_HHMMSS_<src>_rawdet_log.csv       (raw 검출 ≥CONF_LOW — B4 저신뢰 포함)
    test/videos/YYYYMMDD_HHMMSS_<src>_bench.mp4           (--no-video 생략 시)
       ⚠ 이 영상은 **검출 오버레이가 그려진** 화면이고 mp4v 손실압축이라 재분석용이 아니다.
    test/raw/YYYYMMDD_HHMMSS_<src>/f00001.png …          (--save-raw 시, 무손실)
       detector.detect()에 건네진 바로 그 배열 + manifest.json(촬영 조건).
       재생·재분석: python3 test/replay_raw.py test/raw/<dir>
"""

import argparse
import csv
import json
import os
import re
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime

import cv2
import numpy as np

# Demo 폴더를 경로에 추가 (detector.py, config.py import 위해)
_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import config
from detector import create_detector

# =============================================================================
# 경로 상수
# =============================================================================
_TEST_DIR   = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR   = os.path.join(_TEST_DIR, "logs")
_VIDEOS_DIR = os.path.join(_TEST_DIR, "videos")
_RAW_DIR    = os.path.join(_TEST_DIR, "raw")

CLASS_NAMES = ["B1", "B2", "B3", "B4", "EMO"]
CONF_WARN   = 0.70  # 이 미만이면 취약 경고

# =============================================================================
# TCP 수신 (camera_thread.py 패턴, Qt 의존 제거)
# =============================================================================
def _recv_exact(sock, length):
    data = b""
    while len(data) < length:
        try:
            chunk = sock.recv(length - len(data))
        except (socket.timeout, OSError):
            return None
        if not chunk:
            return None
        data += chunk
    return data


def _recv_latest_frame(sock):
    while True:
        header = _recv_exact(sock, 4)
        if header is None:
            return None
        length = struct.unpack("<I", header)[0]
        if length == 0 or length > config.TCP_MAX_FRAME_BYTES:
            return None
        data = _recv_exact(sock, length)
        if data is None:
            return None
        try:
            readable, _, _ = select.select([sock], [], [], 0)
        except OSError:
            return None
        if not readable:
            return data


def _lock_usb_exposure(index, exposure, wb_temp=None):
    """USB 웹캠의 자동 노출을 끄고 노출값을 고정. (WB는 wb_temp를 준 경우에만 고정)

    ESP32(OV3660)는 펌웨어 고정 설정으로 스트리밍하는데 USB 웹캠은 AE가 켜져 있어
    ① 시작 직후 과노출(포화 50%) ② 정반사로 버튼 색이 날아가 B1·B3가 B2로 오분류.
    두 카메라를 대등한 조건으로 비교하려면 USB 쪽 노출도 고정해야 한다.

    ※ auto_exposure=1(Manual)을 먼저 걸어야 exposure_time_absolute가 활성화된다.
    ※ WB는 기본적으로 **자동을 유지**한다. UVC 드라이버는 색온도(R↔B) 축만 제공하고
      틴트(G↔M) 축이 없어, 형광등 녹색 스파이크를 수동으로 잡을 수 없다(2026-07-10 실측:
      최대 6500K에서도 흰 버튼 G=206 vs B/R=148/145로 초록 캐스트 잔존). 자동 AWB가 더 낫다.
    """
    dev = f"/dev/video{index}"
    steps = [
        ("auto_exposure", 1),                    # 1 = Manual Mode
        ("exposure_time_absolute", exposure),
    ]
    if wb_temp is not None:
        steps += [("white_balance_automatic", 0), ("white_balance_temperature", wb_temp)]

    ok = True
    for name, val in steps:
        try:
            r = subprocess.run(["v4l2-ctl", "-d", dev, "-c", f"{name}={val}"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                print(f"[노출고정] {name}={val} 실패: {r.stderr.strip()}")
                ok = False
        except FileNotFoundError:
            print("[노출고정] v4l2-ctl 없음 — `sudo apt install v4l-utils` 필요. 자동노출 유지.")
            return False
        except Exception as e:
            print(f"[노출고정] {name} 설정 오류: {e}")
            ok = False
    if ok:
        wb_desc = f"WB={wb_temp}K(고정)" if wb_temp is not None else "WB=자동(유지)"
        print(f"[노출고정] auto_exposure=Manual  exposure={exposure}  {wb_desc}")
    return ok


def _connect_tcp(host):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        sock.settimeout(config.TCP_RECV_TIMEOUT_SEC)
        sock.connect((host, config.CAMERA_TCP_PORT))
        print(f"[TCP] 연결 성공: {host}:{config.CAMERA_TCP_PORT}")
        return sock
    except Exception as e:
        print(f"[TCP] 연결 실패: {e}")
        return None


# =============================================================================
# IoU / 트래킹 (camera_thread.py 동일 로직)
# =============================================================================
def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)


def _update_tracks(tracks, detections):
    used = [False] * len(detections)
    for t in tracks:
        best_i, best_v = -1, config.YOLO_IOU_MATCH
        for i, d in enumerate(detections):
            if used[i] or d[0] != t["cls"]:
                continue
            v = _iou(t["box"], (d[2], d[3], d[4], d[5]))
            if v > best_v:
                best_v, best_i = v, i
        if best_i >= 0:
            d = detections[best_i]
            t["box"]   = (d[2], d[3], d[4], d[5])
            t["score"] = d[1]
            t["miss"]  = 0
            if d[1] >= config.YOLO_CONF_HIGH:
                t["confirmed"] = True
            used[best_i] = True
        else:
            t["miss"] += 1
    for i, d in enumerate(detections):
        if used[i]:
            continue
        if d[1] >= config.YOLO_CONF_HIGH:
            tracks.append({
                "cls": d[0], "box": (d[2], d[3], d[4], d[5]),
                "score": d[1], "miss": 0, "confirmed": True,
                "track_id": None,  # 할당은 아래에서
            })
    tracks[:] = [t for t in tracks if t["miss"] <= config.YOLO_MAX_MISS and t["confirmed"]]
    return tracks


# =============================================================================
# 드로잉
# =============================================================================
_BOX_COLORS = {
    "B1": (0, 215, 255),   # 노랑
    "B2": (200, 200, 200), # 흰
    "B3": (180, 105, 255), # 핑크
    "B4": (60,  60,  60),  # 검정(밝게)
    "EMO":(0,   0, 220),   # 빨강
}

def _draw_detections(frame, tracks, fps, frame_no):
    for t in tracks:
        name  = CLASS_NAMES[t["cls"]] if t["cls"] < len(CLASS_NAMES) else str(t["cls"])
        color = _BOX_COLORS.get(name, (0, 255, 0))
        x1, y1, x2, y2 = t["box"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{name} {t['score']:.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.putText(frame, f"FPS:{fps:.1f}  F:{frame_no:04d}",
                (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


# =============================================================================
# 메인 벤치마크
# =============================================================================
def run_bench(args):
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    source    = args.source                       # esp32 | usb — 카메라 소스 태그
    host      = args.host or config.CAMERA_TCP_HOST
    max_frames = args.frames

    # 조건 슬러그 — 파일명·db_import 정규식이 [a-z0-9-]만 받는다. 어긋난 문자는 '-'로.
    condition = None
    if args.condition:
        condition = re.sub(r"[^a-z0-9-]+", "-", args.condition.strip().lower()).strip("-") or None

    # 사용 모델 stem (console_v1 / console_v2 …) — 실제로 로드되는 백엔드의 경로에서 유도.
    _model_path = (config.PT_MODEL_PATH if config.INFERENCE_BACKEND == "pytorch"
                   else getattr(config, "HEF_MODEL_PATH", None))
    model_name = os.path.splitext(os.path.basename(_model_path))[0] if _model_path else None

    # 플립 결정. auto = esp32:수직 / usb:없음.
    #  - ESP32 수직 플립은 카메라가 물리적으로 거꾸로 장착돼 있어 바로잡는 보정 → 추론에 필요.
    #  - USB 좌우 플립은 실런타임(UsbCameraThread)의 표시용 미러링 → 거울상 입력은 학습 데이터와
    #    방향이 달라 검출률을 떨어뜨리므로 검출 측정에서는 적용하지 않는다.
    if args.flip == "auto":
        flip_mode = ("v" if config.CAMERA_FLIP_VERTICAL else "none") if source == "esp32" else "none"
    else:
        flip_mode = args.flip

    def _apply_flip(f):
        if flip_mode == "v":  return cv2.flip(f, 0)
        if flip_mode == "h":  return cv2.flip(f, 1)
        if flip_mode == "vh": return cv2.flip(f, -1)
        return f

    os.makedirs(_LOGS_DIR, exist_ok=True)
    os.makedirs(_VIDEOS_DIR, exist_ok=True)

    # --- CSV 파일 열기 (파일명에 소스·조건·모델 접미사 → 산출물 구분) ---
    # 조건·모델을 파일명에 넣는 이유: 없으면 조건 분류가 db_import.py의 하드코딩 매핑에만
    # 의존해 새 세션이 condition=NULL로 적재된다. 모델명은 config에서 자동 유도 —
    # 손으로 적지 않아야 오기재로 v1/v2를 뒤바꾸는 사고를 막는다.
    _tag = f"{ts}_{source}"
    if condition:
        _tag += f"_{condition}"
    if model_name:
        _tag += f"_{model_name}"
    perf_path      = os.path.join(_LOGS_DIR, f"{_tag}_perf_log.csv")
    det_path       = os.path.join(_LOGS_DIR, f"{_tag}_detection_log.csv")
    stab_path      = os.path.join(_LOGS_DIR, f"{_tag}_stability_log.csv")
    conf_path      = os.path.join(_LOGS_DIR, f"{_tag}_confusion_log.csv")
    rawdet_path    = os.path.join(_LOGS_DIR, f"{_tag}_rawdet_log.csv")
    gpio_path      = os.path.join(_LOGS_DIR, f"{_tag}_gpio_log.csv")

    perf_f = open(perf_path, "w", newline="")
    det_f  = open(det_path,  "w", newline="")
    stab_f = open(stab_path, "w", newline="")
    conf_f = open(conf_path, "w", newline="")
    raw_f  = open(rawdet_path, "w", newline="")

    perf_w = csv.writer(perf_f)
    det_w  = csv.writer(det_f)
    stab_w = csv.writer(stab_f)
    conf_w = csv.writer(conf_f)
    raw_w  = csv.writer(raw_f)

    perf_w.writerow(["frame", "timestamp", "fps", "inference_ms", "detection_count"])
    det_w.writerow( ["frame", "timestamp", "cls_name", "score", "x1", "y1", "x2", "y2"])
    stab_w.writerow(["track_id", "cls_name", "start_frame", "end_frame", "duration_frames", "miss_count"])
    conf_w.writerow(["frame", "timestamp", "prev_cls", "new_cls", "iou"])
    # rawdet = 트래킹 이전 원시 검출(score≥YOLO_CONF_LOW). B4 저신뢰(0.5~0.65) 소실 구간 가시화용.
    raw_w.writerow(  ["frame", "timestamp", "source", "cls_name", "score", "x1", "y1", "x2", "y2"])

    # --- GPIO 물리 버튼 눌림 기록 (--gpio) ---
    # 왜: 비전이 "손이 어느 버튼에 있나"만 알려주는 데 반해, GPIO는 "실제로 언제 눌렸나"라는
    #     정답을 준다. 둘을 합쳐야 §9.4가 요구하는 선행시간(t_눌림 − t_도착)을 잴 수 있고,
    #     "비전이 눌림보다 먼저 감지한다"는 프로젝트 명제를 증명할 수 있다.
    # ⚠️ gpiozero 콜백은 내부 스레드에서 불린다(gpio_input.py 참조) — 메인 루프가 frame_no 를
    #     증가시키는 동안 읽으므로 락으로 보호하고, 그 안에서 writerow 까지 수행한다.
    gpio_f = gpio_w = gpio_ctl = None
    gpio_lock = threading.Lock()
    gpio_events = [0]
    frame_holder = [0]          # 콜백 스레드가 읽는 현재 프레임 번호(메인 루프가 갱신)
    if args.gpio:
        gpio_f = open(gpio_path, "w", newline="")
        gpio_w = csv.writer(gpio_f)
        gpio_w.writerow(["timestamp", "button", "frame"])

        def _on_gpio(button_id):
            # 촬영 시작 전(frame 0) 이벤트는 버린다. EMO는 NC 미배선 시 HIGH=비상으로 읽혀
            # 컨트롤러 생성 즉시 한 번 발사되는데(gpio_input.py 의 단선 fail-safe — 의도된 동작),
            # 그건 측정값이 아니라 초기 상태다. 프레임이 없으니 비전과 대조도 불가능하다.
            if frame_holder[0] == 0:
                print(f"  [GPIO] {button_id} — 촬영 시작 전 이벤트라 기록하지 않음"
                      f"{' (EMO 미배선 fail-safe로 보임)' if button_id == 'EMO' else ''}")
                return
            with gpio_lock:
                gpio_w.writerow([datetime.now().strftime("%H:%M:%S.%f")[:-3],
                                 button_id, frame_holder[0]])
                gpio_f.flush()               # 촬영 중 크래시해도 눌림 기록은 남긴다
                gpio_events[0] += 1
            print(f"  [GPIO] {button_id} 눌림 (frame {frame_holder[0]})")

        try:
            from gpio_input import GpioInputController
            # 미설치·핀 실패·비-Pi 환경에서도 예외 없이 fallback (gpio_input.py 설계)
            gpio_ctl = GpioInputController(_on_gpio, log=lambda m: print(f"  {m}"))
        except Exception as e:
            print(f"  [GPIO] 초기화 실패: {e} — 눌림 기록 없이 촬영을 계속합니다")

    # --- 영상 저장 경로 ---
    video_path = None
    if not args.no_video:
        video_path = os.path.join(_VIDEOS_DIR, f"{_tag}_bench.mp4")

    # --- raw 프레임 저장 (무손실 PNG) ---
    # 저장 대상 = detector.detect()에 실제로 건네지는 배열(플립 적용 후). 그래야 재생 시
    # 검출이 그대로 재현된다. ⚠️ 손실 압축(JPEG/mp4) 금지 — B4는 JPEG q90·블러 σ0.8만으로도
    # 사라지므로(§10.9), 증거를 저장하는 행위가 증거를 파괴한다.
    raw_dir = None
    raw_img_queue = None
    raw_img_thread = None
    if args.save_raw:
        raw_dir = os.path.join(_RAW_DIR, _tag)
        os.makedirs(raw_dir, exist_ok=True)
        import queue as _q
        raw_img_queue = _q.Queue(maxsize=32)

        def _raw_worker():
            while True:
                item = raw_img_queue.get()
                if item is None:
                    break
                idx, img = item
                cv2.imwrite(os.path.join(raw_dir, f"f{idx:05d}.png"), img,
                            [cv2.IMWRITE_PNG_COMPRESSION, 3])
                raw_img_queue.task_done()

        raw_img_thread = threading.Thread(target=_raw_worker, daemon=True)
        raw_img_thread.start()
        print(f"[raw] 무손실 PNG 저장: test/raw/{_tag}/  (매 {args.raw_every}프레임)")

    # --- Detector ---
    print("[Detector] 로드 중...")
    detector = create_detector()
    print(f"[Detector] '{detector.backend_name}' 백엔드 준비 완료.")

    # --- 프레임 소스 설정 (esp32 TCP / usb VideoCapture) ---
    sock = None
    cap  = None
    latest_raw  = [None]
    raw_lock    = threading.Lock()
    raw_event   = threading.Event()
    recv_error  = [False]
    running     = [True]

    if source == "esp32":
        sock = _connect_tcp(host)
        if sock is None:
            print("ESP32 연결 실패. 종료합니다.")
            detector.close()
            return
    else:  # usb
        cap = cv2.VideoCapture(args.usb_index)
        if not cap.isOpened():
            print(f"USB 웹캠(index {args.usb_index}) 열기 실패. 종료합니다.")
            detector.close()
            return
        print(f"[USB] 웹캠 index {args.usb_index} 열림.")
        # VideoCapture 오픈 후에 걸어야 드라이버가 되돌리지 않는다.
        if args.lock_exposure:
            _lock_usb_exposure(args.usb_index, args.exposure, args.wb)

    # VideoWriter 비동기 큐
    video_queue  = None
    video_thread = None
    if not args.no_video:
        import queue as _queue
        video_queue = _queue.Queue(maxsize=8)

        def _video_worker():
            writer = None
            while True:
                item = video_queue.get()
                if item is None:
                    break
                frm, path = item
                if writer is None:
                    h, w = frm.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(path, fourcc, 15.0, (w, h))
                writer.write(frm)
                video_queue.task_done()
            if writer:
                writer.release()

        video_thread = threading.Thread(target=_video_worker, daemon=True)
        video_thread.start()

    recv_thread = None
    if source == "esp32":
        def recv_worker():
            while running[0]:
                data = _recv_latest_frame(sock)
                if data is None:
                    recv_error[0] = True
                    raw_event.set()
                    break
                with raw_lock:
                    latest_raw[0] = data
                raw_event.set()

        recv_thread = threading.Thread(target=recv_worker, daemon=True)
        recv_thread.start()

    # --- 상태 변수 ---
    tracks        = []
    track_id_seq  = [0]
    active_tracks = {}   # track_id → {cls, start_frame, last_frame, miss_total}
    prev_boxes    = {}   # track_id → (cls_name, box) — 혼동 감지용

    frame_no    = 0
    fps         = 0.0
    prev_time   = None

    # 요약용 누적
    fps_list    = []
    cls_counts  = {n: 0   for n in CLASS_NAMES}   # confirmed 트랙 기준
    cls_conf    = {n: []  for n in CLASS_NAMES}
    raw_counts  = {n: 0   for n in CLASS_NAMES}   # raw 검출(≥CONF_LOW) 기준 — B4 저신뢰 포함
    raw_conf    = {n: []  for n in CLASS_NAMES}
    raw_frame_hit = {n: 0 for n in CLASS_NAMES}   # 해당 클래스가 1회+ 검출된 프레임 수
    b4_emo_confusion = [0]                         # B4↔EMO 트랙 클래스 전환 횟수
    raw_saved   = [0]                              # PNG로 저장된 프레임 수
    raw_dropped = [0]                              # 큐 포화로 저장 못 한 프레임 수

    # --- 워밍업: AE/AWB 수렴 대기 (USB는 시작 직후 포화 50%까지 과노출) ---
    warmup = (60 if source == "usb" else 0) if args.warmup < 0 else args.warmup
    if warmup > 0:
        print(f"[워밍업] {warmup}프레임 폐기 — 자동노출 수렴 대기...")
        got = 0
        while got < warmup:
            if source == "esp32":
                if not raw_event.wait(timeout=config.TCP_RECV_TIMEOUT_SEC):
                    print("[워밍업] 스트림 수신 없음. 중단합니다.")
                    break
                raw_event.clear()
                if recv_error[0]:
                    break
                with raw_lock:
                    if latest_raw[0] is None:
                        continue
            else:
                ok, _ = cap.read()
                if not ok:
                    print("[워밍업] USB 프레임 수신 실패. 중단합니다.")
                    break
            got += 1
        print(f"[워밍업] {got}프레임 폐기 완료.\n")

    _flip_desc = {"v": "수직", "h": "좌우", "vh": "수직+좌우", "none": "없음"}[flip_mode]
    _lock_desc = " 노출=고정" if (source == "usb" and args.lock_exposure) else ""
    print(f"\n[벤치마크 시작] 소스={source}  플립={_flip_desc}  워밍업={warmup}{_lock_desc}  "
          f"{max_frames}프레임 측정 — Ctrl+C로 중단\n")

    # manifest — 이 raw가 어떤 조건에서 찍혔는지. 없으면 나중에 PNG 더미의 의미를 잃는다.
    if raw_dir:
        with open(os.path.join(raw_dir, "manifest.json"), "w") as mf:
            json.dump({
                "timestamp":      ts,
                "source":         source,
                "condition":      condition,
                "model":          model_name,
                "gpio":           bool(args.gpio),
                "esp32_host":     host if source == "esp32" else None,
                "usb_index":      args.usb_index if source == "usb" else None,
                "flip_mode":      flip_mode,
                "warmup_frames":  warmup,
                "lock_exposure":  bool(args.lock_exposure and source == "usb"),
                "exposure":       args.exposure if (args.lock_exposure and source == "usb") else None,
                "wb":             args.wb,
                "raw_every":      args.raw_every,
                "backend":        detector.backend_name,
                "hef_path":       getattr(config, "HEF_MODEL_PATH", None),
                "yolo_conf_high": config.YOLO_CONF_HIGH,
                "yolo_conf_low":  config.YOLO_CONF_LOW,
                "yolo_input_size": config.YOLO_INPUT_SIZE,
                "class_names":    CLASS_NAMES,
                "note": "PNG = detector.detect()에 건네진 배열(플립 후). 무손실.",
            }, mf, ensure_ascii=False, indent=2)

    try:
        while frame_no < max_frames:
            if source == "esp32":
                if not raw_event.wait(timeout=config.TCP_RECV_TIMEOUT_SEC):
                    print("[타임아웃] 스트림 수신 없음. 종료합니다.")
                    break
                raw_event.clear()
                if recv_error[0]:
                    print("[오류] TCP 수신 오류. 종료합니다.")
                    break

                with raw_lock:
                    data = latest_raw[0]
                if data is None:
                    continue

                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
            else:  # usb
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("[오류] USB 웹캠 프레임 수신 실패. 종료합니다.")
                    break
            frame = _apply_flip(frame)

            frame_no += 1
            frame_holder[0] = frame_no       # GPIO 콜백 스레드가 눌림에 프레임을 붙일 수 있게
            now_str  = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # FPS
            cur_time = time.perf_counter()
            if prev_time is not None:
                dt  = cur_time - prev_time
                fps = 1.0 / dt if dt > 0 else fps
            prev_time = cur_time
            fps_list.append(fps)

            # raw 저장 — detect()에 넘기기 직전의 바로 그 배열
            if raw_img_queue is not None and (frame_no - 1) % args.raw_every == 0:
                try:
                    # 최대 0.5s 대기: PNG 인코딩이 밀려도 증거를 함부로 버리지 않는다.
                    raw_img_queue.put((frame_no, frame.copy()), timeout=0.5)
                    raw_saved[0] += 1
                except Exception:
                    raw_dropped[0] += 1

            # 추론
            t0   = time.perf_counter()
            dets = detector.detect(frame)
            infer_ms = (time.perf_counter() - t0) * 1000.0

            # --- raw 검출 로깅 (트래킹 이전, score≥CONF_LOW 전량) ---
            # confirmed 트랙(≥CONF_HIGH)만 보는 detection_log의 사각지대(B4 저신뢰) 보완.
            _seen_this_frame = set()
            for d in dets:
                cls_id, score, x1, y1, x2, y2 = d
                name = CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else str(cls_id)
                raw_w.writerow([frame_no, now_str, source, name, f"{score:.4f}", x1, y1, x2, y2])
                raw_counts[name] = raw_counts.get(name, 0) + 1
                raw_conf.setdefault(name, []).append(score)
                _seen_this_frame.add(name)
            for name in _seen_this_frame:
                raw_frame_hit[name] = raw_frame_hit.get(name, 0) + 1

            # 트래킹 + track_id 할당
            old_track_ids = {id(t): t.get("track_id") for t in tracks}
            _update_tracks(tracks, dets)

            for t in tracks:
                if t.get("track_id") is None:
                    track_id_seq[0] += 1
                    t["track_id"] = track_id_seq[0]
                    active_tracks[t["track_id"]] = {
                        "cls": CLASS_NAMES[t["cls"]] if t["cls"] < len(CLASS_NAMES) else str(t["cls"]),
                        "start_frame": frame_no,
                        "last_frame":  frame_no,
                        "miss_total":  0,
                    }
                else:
                    if t["track_id"] in active_tracks:
                        active_tracks[t["track_id"]]["last_frame"] = frame_no
                        active_tracks[t["track_id"]]["miss_total"] += t["miss"]

            # 혼동 감지 (같은 위치에서 클래스 변경)
            cur_boxes = {t["track_id"]: (CLASS_NAMES[t["cls"]] if t["cls"] < len(CLASS_NAMES) else str(t["cls"]), t["box"])
                         for t in tracks if t.get("track_id")}
            for tid, (cur_cls, cur_box) in cur_boxes.items():
                if tid in prev_boxes:
                    prev_cls, prev_box = prev_boxes[tid]
                    if prev_cls != cur_cls:
                        iou_val = _iou(prev_box, cur_box)
                        if iou_val > 0.3:
                            conf_w.writerow([frame_no, now_str, prev_cls, cur_cls, f"{iou_val:.3f}"])
                            if {prev_cls, cur_cls} == {"B4", "EMO"}:
                                b4_emo_confusion[0] += 1
            prev_boxes = cur_boxes

            # CSV 기록
            perf_w.writerow([frame_no, now_str, f"{fps:.2f}", f"{infer_ms:.2f}", len(tracks)])
            for t in tracks:
                name = CLASS_NAMES[t["cls"]] if t["cls"] < len(CLASS_NAMES) else str(t["cls"])
                x1, y1, x2, y2 = t["box"]
                det_w.writerow([frame_no, now_str, name, f"{t['score']:.4f}", x1, y1, x2, y2])
                cls_counts[name] = cls_counts.get(name, 0) + 1
                cls_conf.setdefault(name, []).append(t["score"])

            # 영상 + 실시간 미리보기
            frame_draw = _draw_detections(frame.copy(), tracks, fps, frame_no)
            if not args.no_video and video_queue is not None:
                try:
                    video_queue.put_nowait((frame_draw.copy(), video_path))
                except Exception:
                    pass  # 큐 가득 찬 경우 드롭

            # 2프레임마다 imshow (렌더링 오버헤드 절감)
            if frame_no % 2 == 0:
                cv2.imshow("bench_detector", frame_draw)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("\n[q] 사용자 중단.")
                break

            # 30프레임마다 터미널 출력
            if frame_no % 30 == 0:
                cur_dets = {CLASS_NAMES[t["cls"]]: t["score"] for t in tracks if t["cls"] < len(CLASS_NAMES)}
                print(f"[F {frame_no:04d}] FPS: {fps:.1f}  추론: {infer_ms:.1f}ms  탐지: {len(tracks)}개")
                for name, score in cur_dets.items():
                    print(f"  {name:<4} conf {score:.3f}")

    except KeyboardInterrupt:
        print("\n[중단]")
    finally:
        running[0] = False
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if recv_thread is not None:
            recv_thread.join(timeout=3)
        if cap is not None:
            cap.release()

        # 종료된 트랙 stability 기록
        alive_ids = {t.get("track_id") for t in tracks}
        for tid, info in active_tracks.items():
            duration = info["last_frame"] - info["start_frame"] + 1
            stab_w.writerow([tid, info["cls"], info["start_frame"],
                             info["last_frame"], duration, info["miss_total"]])

        if gpio_ctl is not None:
            try:
                gpio_ctl.close()             # 콜백을 먼저 끊고 나서 파일을 닫는다
            except Exception:
                pass
        if gpio_f is not None:
            with gpio_lock:
                gpio_f.close()
        perf_f.close(); det_f.close(); stab_f.close(); conf_f.close(); raw_f.close()
        if raw_img_queue is not None:
            raw_img_queue.put(None)          # 종료 신호 — 남은 큐를 다 쓰고 끝난다
            raw_img_thread.join(timeout=60)
        if video_queue is not None:
            video_queue.put(None)  # 종료 신호
            video_thread.join(timeout=10)
        cv2.destroyAllWindows()
        detector.close()

    # ==========================================================================
    # 종료 요약
    # ==========================================================================
    print(f"\n{'='*50}")
    print(f"벤치마크 결과 ({frame_no} 프레임)")
    print(f"{'='*50}")
    if fps_list:
        valid_fps = [f for f in fps_list if f > 0]
        print(f"평균 FPS   : {sum(valid_fps)/len(valid_fps):.1f}")
        print(f"최저 FPS   : {min(valid_fps):.1f}")
        print(f"최고 FPS   : {max(valid_fps):.1f}")
    print(f"\n[소스: {source}]  클래스별 누적 탐지 (confirmed 트랙 ≥{config.YOLO_CONF_HIGH}):")
    for name in CLASS_NAMES:
        count = cls_counts.get(name, 0)
        scores = cls_conf.get(name, [])
        avg_conf = sum(scores) / len(scores) if scores else 0.0
        warn = "  ⚠ 취약" if avg_conf > 0 and avg_conf < CONF_WARN else ""
        print(f"  {name:<4}: {count:4d}회  평균신뢰도 {avg_conf:.3f}{warn}")

    print(f"\nraw 검출 (≥{config.YOLO_CONF_LOW}, 트래킹 이전 — 저신뢰 포함):")
    for name in CLASS_NAMES:
        rc = raw_counts.get(name, 0)
        rs = raw_conf.get(name, [])
        ravg = sum(rs) / len(rs) if rs else 0.0
        print(f"  {name:<4}: {rc:4d}회 (프레임 {raw_frame_hit.get(name,0)})  평균 {ravg:.3f}")

    # --- B4 집중 분석 (주가설=카메라 입력 품질 vs 부가설=모델 저대비 판정용) ---
    b4 = sorted(raw_conf.get("B4", []))
    print(f"\n{'-'*50}\nB4 집중 분석")
    if b4:
        n = len(b4)
        median = b4[n // 2] if n % 2 else (b4[n//2 - 1] + b4[n//2]) / 2
        bucket = {"0.5–0.6": 0, "0.6–0.7": 0, "0.7+": 0}
        for s in b4:
            if   s < 0.6: bucket["0.5–0.6"] += 1
            elif s < 0.7: bucket["0.6–0.7"] += 1
            else:         bucket["0.7+"]    += 1
        print(f"  B4 raw 검출: {n}회 / 검출 프레임 {raw_frame_hit.get('B4',0)}")
        print(f"  score  min {b4[0]:.3f}  median {median:.3f}  max {b4[-1]:.3f}")
        print(f"  분포   0.5–0.6:{bucket['0.5–0.6']}  0.6–0.7:{bucket['0.6–0.7']}  0.7+:{bucket['0.7+']}")
    else:
        print(f"  B4 raw 검출: 0회  ← 완전 미탐지 (카메라 화질/모델 저대비 원인 후보)")
    print(f"  B4↔EMO 오인(트랙 전환): {b4_emo_confusion[0]}회 | raw EMO 총검출: {raw_counts.get('EMO',0)}회")

    if args.gpio:
        print(f"\nGPIO 눌림  : {gpio_events[0]}회 → test/logs/{_tag}_gpio_log.csv")
        if gpio_events[0] == 0:
            print("  ⚠️ 눌림이 0회다 — 배선 미연결이거나 카메라에 보이는 버튼이")
            print("     GPIO에 물린 버튼과 다를 수 있다. 분석 전에 확인할 것")
    print(f"\n저장 위치: test/logs/{_tag}_*.csv")
    if not args.no_video and video_path:
        print(f"영상 저장 : test/videos/{_tag}_bench.mp4  ⚠ 검출 오버레이본 — 재분석 불가")
    if raw_dir:
        print(f"raw 저장  : test/raw/{_tag}/  PNG {raw_saved[0]}장" +
              (f"  ⚠ 드롭 {raw_dropped[0]}장" if raw_dropped[0] else " (드롭 0)"))
        print(f"            재생: python3 test/replay_raw.py test/raw/{_tag}")


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hailo 추론 벤치마크 (모델 = config.HEF_MODEL_PATH)")
    parser.add_argument("--frames",    type=int, default=300, help="측정 프레임 수 (기본 300)")
    parser.add_argument("--host",      type=str, default=None, help="ESP32 IP 오버라이드")
    parser.add_argument("--no-video",  action="store_true",    help="영상 저장 생략")
    parser.add_argument("--source",    choices=["esp32", "usb"], default="esp32",
                        help="카메라 소스 (esp32=OV3660 TCP / usb=웹캠). B4 원인 대조용")
    parser.add_argument("--usb-index", type=int, default=0,
                        help="USB 웹캠 장치 인덱스 (--source usb, 기본 0)")
    parser.add_argument("--flip", choices=["auto", "none", "v", "h", "vh"], default="auto",
                        help="플립 보정. auto=esp32:수직(거꾸로 장착 보정)/usb:없음. "
                             "USB의 실런타임 좌우 플립은 표시용 미러링이라 검출 측정엔 해로움")
    parser.add_argument("--warmup", type=int, default=-1,
                        help="측정 전 버릴 프레임 수(AE 수렴 대기). 기본 auto = usb:60 / esp32:0")
    parser.add_argument("--lock-exposure", action="store_true",
                        help="USB 웹캠 자동노출 해제 후 고정 (ESP32와 조건 대등화). WB는 자동 유지")
    parser.add_argument("--exposure", type=int, default=250,
                        help="--lock-exposure 시 exposure_time_absolute. "
                             "기본 250 = 2026-07-10 실측 최적(5클래스 20/20, B4 conf 0.801). "
                             "값은 조명마다 다르니 test/tune_exposure.py로 재선정")
    parser.add_argument("--wb", type=int, default=None,
                        help="지정 시 white_balance_temperature(K) 고정. 미지정=자동 AWB 유지(권장). "
                             "형광등 녹색 스파이크는 색온도 축으로 못 잡아 수동 고정 시 초록 캐스트 발생")
    parser.add_argument("--save-raw", action="store_true",
                        help="detector에 들어간 프레임을 무손실 PNG로 저장(test/raw/). "
                             "저장 영상은 검출 오버레이본이라 재분석 불가 — 재현·console_v2 평가용")
    parser.add_argument("--raw-every", type=int, default=1, metavar="N",
                        help="--save-raw 시 N프레임마다 1장 저장 (기본 1=전부). 용량 절감용")
    parser.add_argument("--gpio", action="store_true",
                        help="물리 버튼(GPIO) 눌림을 <tag>_gpio_log.csv 에 기록. "
                             "비전의 '손이 어디 있나'에 '실제로 언제 눌렸나'라는 정답을 붙여 "
                             "선행시간(§9.4)과 사전 감지 성립 여부를 측정할 수 있게 한다. "
                             "gpiozero 미설치·배선 없음이면 예외 없이 촬영만 계속된다")
    parser.add_argument("--condition", type=str, default=None, metavar="SLUG",
                        help="촬영 조건 슬러그(fluorescent/lowlight/daylight/cleanroom 등). "
                             "산출물 파일명·manifest에 기록되어 db_import가 조건을 자동 분류한다. "
                             "미지정 시 기존 파일명 형식 유지(db_import의 하드코딩 매핑에 의존)")
    args = parser.parse_args()
    run_bench(args)
