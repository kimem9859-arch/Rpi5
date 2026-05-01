import cv2
import numpy as np
import socket
import struct
import sys
import time
import threading
import os
from datetime import datetime
from hailo_platform import HEF, VDevice, InferVStreams, ConfigureParams, InputVStreamParams, OutputVStreamParams, HailoStreamInterface

# === ESP32 TCP 설정 ===
ip = "10.220.25.235"
port = 8888
if len(sys.argv) > 1:
    ip = sys.argv[1]

# === Hailo YOLOv8s 설정 ===
MODEL_PATH = '/usr/share/hailo-models/yolov8s_h8.hef'
CONF_HIGH = 0.65      # 신규 객체 등록 임계값 (오탐지 차단)
CONF_LOW  = 0.50      # 기존 객체 유지 임계값 (끊김 방지)
IOU_MATCH = 0.3       # 같은 객체 판단 IoU
MAX_MISS  = 3         # 탐지 누락 허용 프레임 수
INPUT_SIZE = 640
VIDEO_DIR = '/home/pi/Videos/YOLOv8s_8l.hef_test_videos'
LOG_DIR   = '/home/pi/Documents/YOLOv8s_8l.hef_test_Log'

COCO_CLASSES = [
    'person','bicycle','car','motorcycle','airplane','bus','train','truck','boat',
    'traffic light','fire hydrant','stop sign','parking meter','bench','bird','cat',
    'dog','horse','sheep','cow','elephant','bear','zebra','giraffe','backpack',
    'umbrella','handbag','tie','suitcase','frisbee','skis','snowboard','sports ball',
    'kite','baseball bat','baseball glove','skateboard','surfboard','tennis racket',
    'bottle','wine glass','cup','fork','knife','spoon','bowl','banana','apple',
    'sandwich','orange','broccoli','carrot','hot dog','pizza','donut','cake','chair',
    'couch','potted plant','bed','dining table','toilet','tv','laptop','mouse',
    'remote','keyboard','cell phone','microwave','oven','toaster','sink','refrigerator',
    'book','clock','vase','scissors','teddy bear','hair drier','toothbrush'
]

# === 공유 프레임 (TCP 수신 → 메인 추론) ===
latest_frame = None
frame_lock = threading.Lock()
running = True
rx_count = 0
net_log_file = None  # 네트워크 로그 핸들

def recv_exact(sock, length):
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("소켓 연결 끊김")
        data += chunk
    return data

def receive_stream():
    global latest_frame, running, rx_count
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(10)
        sock.connect((ip, port))
        print(f"[TCP] 연결됨: {ip}:{port}")
    except Exception as e:
        print(f"[TCP] 연결 실패: {e}")
        running = False
        return

    prev_done = None   # 이전 프레임 수신 완료 시각
    lat_sum = 0.0      # 수신시간 합(최근 N)
    gap_sum = 0.0      # 프레임간격 합(최근 N)
    n = 0
    WINDOW = 30

    try:
        while running:
            # 헤더 수신 시작 시각 = 프레임 수신 시작
            t_start = time.perf_counter()
            header = recv_exact(sock, 4)
            length = struct.unpack('<I', header)[0]
            if length == 0 or length > 200000:
                print(f"[TCP] 비정상 프레임 크기: {length}")
                break
            data = recv_exact(sock, length)
            t_done = time.perf_counter()

            recv_ms = (t_done - t_start) * 1000.0
            gap_ms = (t_start - prev_done) * 1000.0 if prev_done else 0.0
            prev_done = t_done

            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            frame = cv2.flip(frame, 0)
            with frame_lock:
                latest_frame = frame
            rx_count += 1

            # 네트워크 로그 기록
            if net_log_file is not None:
                ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                net_log_file.write(f'{ts},{rx_count},{length},{recv_ms:.2f},{gap_ms:.2f}\n')

            # 30프레임마다 평균 출력
            lat_sum += recv_ms
            gap_sum += gap_ms
            n += 1
            if n >= WINDOW:
                avg_recv = lat_sum / n
                avg_gap = gap_sum / n
                kbps = (length * 8 / 1024) / (recv_ms / 1000.0) if recv_ms > 0 else 0
                print(f"[NET] #{rx_count} 평균 수신:{avg_recv:.1f}ms 간격:{avg_gap:.1f}ms 크기:{length//1024}KB 속도:{kbps:.0f}kbps")
                lat_sum = gap_sum = 0.0
                n = 0
    except Exception as e:
        print(f"[TCP] 수신 오류: {e}")
    finally:
        sock.close()
        running = False

# === 전처리 / 후처리 ===
def preprocess(frame):
    img = cv2.resize(frame, (INPUT_SIZE, INPUT_SIZE))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return img.astype(np.uint8)

def postprocess(output, orig_h, orig_w):
    detections = []
    raw = list(output.values())[0][0]
    for cls_id, dets in enumerate(raw):
        dets = np.array(dets)
        if dets.ndim != 2 or dets.shape[0] == 0:
            continue
        for det in dets:
            ymin, xmin, ymax, xmax, score = det
            if score < CONF_LOW:
                continue
            x1, y1 = int(xmin * orig_w), int(ymin * orig_h)
            x2, y2 = int(xmax * orig_w), int(ymax * orig_h)
            detections.append((cls_id, score, x1, y1, x2, y2))
    return detections

def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)

def update_tracks(tracks, detections):
    """tracks: list of dict {cls, box, score, miss, confirmed}"""
    used = [False] * len(detections)
    # 기존 트랙 매칭
    for t in tracks:
        best_i, best_iou = -1, IOU_MATCH
        for i, d in enumerate(detections):
            if used[i] or d[0] != t['cls']:
                continue
            box = (d[2], d[3], d[4], d[5])
            v = iou(t['box'], box)
            if v > best_iou:
                best_iou, best_i = v, i
        if best_i >= 0:
            d = detections[best_i]
            t['box'] = (d[2], d[3], d[4], d[5])
            t['score'] = d[1]
            t['miss'] = 0
            if d[1] >= CONF_HIGH:
                t['confirmed'] = True
            used[best_i] = True
        else:
            t['miss'] += 1
    # 남은 탐지 중 고신뢰 → 신규 트랙
    for i, d in enumerate(detections):
        if used[i] and False: continue
        if used[i]: continue
        if d[1] >= CONF_HIGH:
            tracks.append({
                'cls': d[0],
                'box': (d[2], d[3], d[4], d[5]),
                'score': d[1],
                'miss': 0,
                'confirmed': True,
            })
    # 오래된 트랙 제거
    tracks[:] = [t for t in tracks if t['miss'] <= MAX_MISS and t['confirmed']]
    return tracks

def draw(frame, detections, fps, recording):
    for cls_id, score, x1, y1, x2, y2 in detections:
        label = f"{COCO_CLASSES[cls_id]} {score:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, label, (x1, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    cv2.putText(frame, f"Objects: {len(detections)}", (10, 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
    if recording:
        cv2.circle(frame, (620, 20), 10, (0, 0, 255), -1)
        cv2.putText(frame, "REC", (590, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return frame

# === 저장 경로 ===
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
video_path = os.path.join(VIDEO_DIR, f'{timestamp}_tcp.avi')
log_path   = os.path.join(LOG_DIR,   f'{timestamp}_tcp.csv')
net_log_path = os.path.join(LOG_DIR, f'{timestamp}_tcp_network.csv')

# 네트워크 로그 파일 열기
net_log_file = open(net_log_path, 'w')
net_log_file.write('시각,프레임,크기(B),수신시간(ms),프레임간격(ms)\n')
print(f"네트워크 로그: {net_log_path}")

# === TCP 수신 스레드 시작 ===
rx_thread = threading.Thread(target=receive_stream, daemon=True)
rx_thread.start()

# 첫 프레임 수신 대기 (최대 10초)
print("첫 프레임 대기 중...")
wait_start = time.time()
while latest_frame is None and running and (time.time() - wait_start) < 10:
    time.sleep(0.1)

if latest_frame is None:
    print("프레임 수신 실패, 종료")
    running = False
    sys.exit(1)

with frame_lock:
    h, w = latest_frame.shape[:2]
print(f"프레임 크기: {w}x{h}")

# === Hailo 초기화 ===
hef = HEF(MODEL_PATH)

with VDevice() as target:
    configure_params = ConfigureParams.create_from_hef(hef, interface=HailoStreamInterface.PCIe)
    ngs = target.configure(hef, configure_params)
    ng = ngs[0]
    ng_params = ng.create_params()

    in_params  = InputVStreamParams.make(ng)
    out_params = OutputVStreamParams.make(ng)
    in_name    = ng.get_input_vstream_infos()[0].name

    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    writer = cv2.VideoWriter(video_path, fourcc, 15.0, (w, h))

    log_file = open(log_path, 'w')
    log_file.write('시각,프레임,FPS,객체명,신뢰도,x1,y1,x2,y2\n')

    print(f"Hailo YOLOv8s (COCO) + TCP 스트림 시작 - 'q' 종료")
    print(f"영상: {video_path}")
    print(f"로그: {log_path}")

    fps = 0.0
    prev_time = time.perf_counter()
    frame_count = 0
    last_rx_processed = -1
    tracks = []

    with InferVStreams(ng, in_params, out_params) as pipeline:
        with ng.activate(ng_params):
            while running:
                # 최신 프레임 가져오기 (같은 프레임 중복 처리 방지)
                with frame_lock:
                    if rx_count == last_rx_processed or latest_frame is None:
                        frame = None
                    else:
                        frame = latest_frame.copy()
                        last_rx_processed = rx_count

                if frame is None:
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                    continue

                orig_h, orig_w = frame.shape[:2]
                inp = preprocess(frame)
                output = pipeline.infer({in_name: inp[np.newaxis]})

                cur_time = time.perf_counter()
                dt = cur_time - prev_time
                fps = 1.0 / dt if dt > 0 else 0.0
                prev_time = cur_time

                detections = postprocess(output, orig_h, orig_w)
                update_tracks(tracks, detections)

                # 트랙을 화면용 detections 포맷으로 변환
                display_dets = [
                    (t['cls'], t['score'], *t['box']) for t in tracks
                ]
                frame = draw(frame, display_dets, fps, recording=True)

                writer.write(frame)

                now = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                if display_dets:
                    for cls_id, score, x1, y1, x2, y2 in display_dets:
                        log_file.write(
                            f'{now},{frame_count},{fps:.1f},'
                            f'{COCO_CLASSES[cls_id]},{score:.3f},{x1},{y1},{x2},{y2}\n'
                        )
                else:
                    log_file.write(f'{now},{frame_count},{fps:.1f},,,,,\n')

                frame_count += 1
                cv2.imshow('Hailo YOLOv8s + ESP32 TCP', frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    running = False
    writer.release()
    log_file.close()
    if net_log_file is not None:
        net_log_file.close()
    cv2.destroyAllWindows()

    print(f"\n종료 — 총 추론 프레임: {frame_count} / TCP 수신: {rx_count}")
    print(f"영상: {video_path}")
    print(f"추론 로그: {log_path}")
    print(f"네트워크 로그: {net_log_path}")
