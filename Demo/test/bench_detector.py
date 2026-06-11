"""console_v1.hef 성능 벤치마크 — Hailo 실추론 FPS·탐지율·안정성 측정.

실행:
    cd ~/sop-project/Rpi5/Demo
    python3 test/bench_detector.py                        # 기본 300프레임
    python3 test/bench_detector.py --frames 100 --no-video
    python3 test/bench_detector.py --frames 500 --host 10.157.207.235

출력:
    test/logs/YYYYMMDD_HHMMSS_perf_log.csv
    test/logs/YYYYMMDD_HHMMSS_detection_log.csv
    test/logs/YYYYMMDD_HHMMSS_stability_log.csv
    test/logs/YYYYMMDD_HHMMSS_confusion_log.csv
    test/videos/YYYYMMDD_HHMMSS_bench.mp4   (--no-video 생략 시)
"""

import argparse
import csv
import os
import select
import socket
import struct
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
    host      = args.host or config.CAMERA_TCP_HOST
    max_frames = args.frames

    # --- CSV 파일 열기 ---
    perf_path      = os.path.join(_LOGS_DIR, f"{ts}_perf_log.csv")
    det_path       = os.path.join(_LOGS_DIR, f"{ts}_detection_log.csv")
    stab_path      = os.path.join(_LOGS_DIR, f"{ts}_stability_log.csv")
    conf_path      = os.path.join(_LOGS_DIR, f"{ts}_confusion_log.csv")

    perf_f = open(perf_path, "w", newline="")
    det_f  = open(det_path,  "w", newline="")
    stab_f = open(stab_path, "w", newline="")
    conf_f = open(conf_path, "w", newline="")

    perf_w = csv.writer(perf_f)
    det_w  = csv.writer(det_f)
    stab_w = csv.writer(stab_f)
    conf_w = csv.writer(conf_f)

    perf_w.writerow(["frame", "timestamp", "fps", "inference_ms", "detection_count"])
    det_w.writerow( ["frame", "timestamp", "cls_name", "score", "x1", "y1", "x2", "y2"])
    stab_w.writerow(["track_id", "cls_name", "start_frame", "end_frame", "duration_frames", "miss_count"])
    conf_w.writerow(["frame", "timestamp", "prev_cls", "new_cls", "iou"])

    # --- 영상 저장 경로 ---
    video_path = None
    if not args.no_video:
        video_path = os.path.join(_VIDEOS_DIR, f"{ts}_bench.mp4")

    # --- Detector ---
    print("[Detector] 로드 중...")
    detector = create_detector()
    print(f"[Detector] '{detector.backend_name}' 백엔드 준비 완료.")

    # --- TCP 수신 스레드 ---
    sock = _connect_tcp(host)
    if sock is None:
        print("ESP32 연결 실패. 종료합니다.")
        detector.close()
        return

    latest_raw  = [None]
    raw_lock    = threading.Lock()
    raw_event   = threading.Event()
    recv_error  = [False]
    running     = [True]

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
    cls_counts  = {n: 0   for n in CLASS_NAMES}
    cls_conf    = {n: []  for n in CLASS_NAMES}

    print(f"\n[벤치마크 시작] {max_frames}프레임 측정 — Ctrl+C로 중단\n")

    try:
        while frame_no < max_frames:
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
            if config.CAMERA_FLIP_VERTICAL:
                frame = cv2.flip(frame, 0)

            frame_no += 1
            now_str  = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # FPS
            cur_time = time.perf_counter()
            if prev_time is not None:
                dt  = cur_time - prev_time
                fps = 1.0 / dt if dt > 0 else fps
            prev_time = cur_time
            fps_list.append(fps)

            # 추론
            t0   = time.perf_counter()
            dets = detector.detect(frame)
            infer_ms = (time.perf_counter() - t0) * 1000.0

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
        try:
            sock.close()
        except Exception:
            pass
        recv_thread.join(timeout=3)

        # 종료된 트랙 stability 기록
        alive_ids = {t.get("track_id") for t in tracks}
        for tid, info in active_tracks.items():
            duration = info["last_frame"] - info["start_frame"] + 1
            stab_w.writerow([tid, info["cls"], info["start_frame"],
                             info["last_frame"], duration, info["miss_total"]])

        perf_f.close(); det_f.close(); stab_f.close(); conf_f.close()
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
    print(f"\n클래스별 누적 탐지:")
    for name in CLASS_NAMES:
        count = cls_counts.get(name, 0)
        scores = cls_conf.get(name, [])
        avg_conf = sum(scores) / len(scores) if scores else 0.0
        warn = "  ⚠ 취약" if avg_conf > 0 and avg_conf < CONF_WARN else ""
        print(f"  {name:<4}: {count:4d}회  평균신뢰도 {avg_conf:.3f}{warn}")
    print(f"\n저장 위치: test/logs/{ts}_*.csv")
    if not args.no_video and video_path:
        print(f"영상 저장 : test/videos/{ts}_bench.mp4")


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="console_v1 Hailo 추론 벤치마크")
    parser.add_argument("--frames",   type=int, default=300, help="측정 프레임 수 (기본 300)")
    parser.add_argument("--host",     type=str, default=None, help="ESP32 IP 오버라이드")
    parser.add_argument("--no-video", action="store_true",    help="영상 저장 생략")
    args = parser.parse_args()
    run_bench(args)
