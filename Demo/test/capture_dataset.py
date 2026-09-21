"""데이터셋 촬영 전용 — 검출을 돌리지 않고 런타임과 같은 그림만 저장한다.

왜 전용 도구인가 (2026-09-21):
    지금까지 촬영이 **본업이 따로 있는 도구 두 곳에 얹혀** 있었다 —
    `bench_detector --save-raw`(측정 재현용, 왜곡보정 없음)와
    `tool_probe --save-clean`(공구 판정 점검의 곁다리). 데이터셋 촬영에는
    **검출이 필요 없다**(평가용 사진에 모델 프리라벨을 쓰지 않기로 했다).
    추론을 빼면 그만큼 CPU 가 남아 프레임을 더 건진다.

🔴 전처리는 런타임과 같은 순서다 — 수신 → 반전 → 왜곡보정 → 회전.
   회전을 먼저 하면 480×640 이 되어 캘리브레이션이 'mismatch' 로 빠지고
   **왜곡보정이 조용히 꺼진다**(로그 한 줄만 남고 화면은 멀쩡해 보인다).

🔴 저장은 무손실 PNG 다 — B4(파란 스티커)는 손실 압축만으로도 사라진다.

장면 목록은 데이터확보 설계서 §5 의 8종이다. 화면에 띄워 **그 자체가 촬영
지시서**가 되게 한다 — 「무엇을 몇 번 찍어라」를 말로 전하면 혼선이 생겨
재촬영을 부른다.

사용법:
    python3 test/capture_dataset.py                      # 촬영(미리보기 + 키 조작)
    python3 test/capture_dataset.py --every 0.5          # 저장 간격 0.5초
    python3 test/capture_dataset.py --bench 60 --esp-port /dev/ttyACM1
    python3 test/capture_dataset.py --bench 60 --no-save # 저장 비용 분리
    python3 test/capture_dataset.py --selftest

키:  space=녹화 시작/정지   s=장면   p=장소   q=종료
"""
from __future__ import annotations
import argparse
import json
import os
import re
import socket
import struct
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import config
import frame_orient

# 데이터확보 설계서 §5 촬영 장면 8종
SCENES = ["1 콘솔전체", "2 버튼누르기", "3 손지나감", "4 머리움직임",
          "5 빛반사", "6 놓인공구", "7 쥔공구", "8 배경"]
PLACES = ["장소1", "장소2", "장소3"]

# 펌웨어가 5초마다 자동으로 찍는 줄. cap 과 sent 의 차이가 핵심이다 —
# 잡았는데 못 보냈으면 전송이, 애초에 적게 잡았으면 카메라·펌웨어가 병목이다.
_FRAME_RE = re.compile(r"Frame: cap=(\d+) sent=(\d+) drop=(\d+) · ([\d.]+)KB/장 · "
                       r"send avg=(\d+)ms max=(\d+)ms")


class Session:
    """한 회차의 저장 폴더와 메타를 들고 있는다."""

    def __init__(self, root: Path, place: str, scene: str, every: float, meta: dict):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = root / f"{stamp}_{place}_{scene.split()[0]}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.place, self.scene, self.every = place, scene, every
        self.meta = dict(meta)
        self.n = 0
        self.started = time.time()

    def save(self, img) -> None:
        self.n += 1
        cv2.imwrite(str(self.dir / f"f{self.n:05d}.png"), img,
                    [cv2.IMWRITE_PNG_COMPRESSION, 3])

    def close(self, stages: dict) -> None:
        self.meta.update({
            "place": self.place, "scene": self.scene, "every_sec": self.every,
            "frames": self.n, "seconds": round(time.time() - self.started, 1),
            "stages": dict(stages),
        })
        (self.dir / "session.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")


# ───────────────────────────────────────────────────────────── 수신
def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except (socket.timeout, OSError):
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_frame(sock):
    head = _recv_exact(sock, 4)
    if head is None:
        return None
    ln = struct.unpack("<I", head)[0]
    if ln == 0 or ln > config.TCP_MAX_FRAME_BYTES:
        return None
    return _recv_exact(sock, ln)


def _connect(host):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(config.TCP_RECV_TIMEOUT_SEC)
    sock.connect((host, config.CAMERA_TCP_PORT))
    # 🔴 폰 핫스팟 고착은 조용한 고장이다 — 영상도 GUI 도 정상으로 보이고 FPS 만 떨어진다.
    if host.startswith("10.47."):
        print(f"🔴 [경고] ESP32 가 폰 핫스팟에 붙어 있다({host}). ESP32 만 전원 재투입할 것.")
    else:
        print(f"[TCP] 연결: {host}:{config.CAMERA_TCP_PORT}")
    return sock


def _esp_stats(port: str, stop: threading.Event, out: list) -> None:
    """ESP32 시리얼에서 송신 통계를 모은다. USB 가 꽂혀 있을 때만 쓴다."""
    try:
        import serial
    except ImportError:
        print("[ESP32] pyserial 없음 — 송신 통계 생략")
        return
    try:
        s = serial.Serial(port, 115200, timeout=1)
    except Exception as e:
        print(f"[ESP32] 시리얼 열기 실패({port}): {e} — 송신 통계 생략")
        return
    while not stop.is_set():
        try:
            line = s.readline().decode("utf-8", "replace")
        except Exception:
            break
        m = _FRAME_RE.search(line)
        if m:
            out.append({"cap": int(m.group(1)), "sent": int(m.group(2)),
                        "drop": int(m.group(3)), "kb": float(m.group(4)),
                        "send_avg_ms": int(m.group(5)), "send_max_ms": int(m.group(6))})
    s.close()


# ───────────────────────────────────────────────────────────── 촬영
def run(args) -> int:
    host = args.host or config.CAMERA_TCP_HOST
    sock = _connect(host)

    # 🔑 맵은 **첫 프레임의 실제 크기**로 만든다 — config 에 해상도 상수가 없다.
    umap, umap_ready = None, False
    root = Path(os.path.expanduser(args.out))
    place_i, scene_i = 0, 0
    sess, last_save = None, 0.0
    stages = {"recv": 0, "decode": 0, "orient": 0, "saved": 0}
    print("space=녹화 시작/정지  s=장면  p=장소  q=종료")

    while True:
        data = _recv_frame(sock)
        if data is None:
            print("[수신 끊김] 종료한다.")
            break
        stages["recv"] += 1
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        stages["decode"] += 1

        if not umap_ready:
            h0, w0 = frame.shape[:2]
            umap, umap_ready = frame_orient.undistort_map(w0, h0), True
            if umap is None:
                print(f"🔴 [왜곡보정] {w0}×{h0} 용 맵 없음 — 런타임과 다른 그림이 된다.")
                if not args.force:
                    print("   --force 를 주면 그래도 진행한다. 지금은 멈춘다.")
                    sock.close()
                    return 1
        frame = frame_orient.apply_full(frame, umap)
        stages["orient"] += 1

        if sess is not None and (time.time() - last_save) >= args.every:
            sess.save(frame)
            stages["saved"] += 1
            last_save = time.time()

        view = frame.copy()
        state = f"REC {sess.n}" if sess else "대기"
        cv2.putText(view, f"{PLACES[place_i]} | {SCENES[scene_i]} | {state}",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.imshow("capture_dataset", view)

        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord(" "):
            if sess is None:
                sess = Session(root, PLACES[place_i], SCENES[scene_i], args.every,
                               {"host": host, "frame_size": "VGA", "jpeg_quality": 15,
                                "undistort": umap is not None})
                last_save = 0.0
                print(f"[녹화 시작] {sess.dir}")
            else:
                sess.close(stages)
                print(f"[녹화 정지] {sess.n}장 → {sess.dir}")
                sess = None
        # 🔑 장면·장소는 녹화 중에 못 바꾼다 — 한 폴더에 두 조건이 섞이면 나중에 가를 수 없다.
        if k == ord("s") and sess is None:
            scene_i = (scene_i + 1) % len(SCENES)
        if k == ord("p") and sess is None:
            place_i = (place_i + 1) % len(PLACES)

    if sess is not None:
        sess.close(stages)
        print(f"[녹화 정지] {sess.n}장 → {sess.dir}")
    sock.close()
    cv2.destroyAllWindows()
    return 0


# ───────────────────────────────────────────────────────── 기준선 측정
def run_bench(args) -> int:
    host = args.host or config.CAMERA_TCP_HOST
    sock = _connect(host)
    umap, umap_ready = None, False      # 첫 프레임 크기로 만든다(run 과 같은 이유)
    esp, stop = [], threading.Event()
    if args.esp_port:
        threading.Thread(target=_esp_stats, args=(args.esp_port, stop, esp),
                         daemon=True).start()

    out = Path(os.path.expanduser(args.out)) / f"bench_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    t_end = time.time() + args.bench
    n = {"recv": 0, "decode": 0, "orient": 0, "saved": 0}
    ms = {"decode": [], "orient": [], "save": []}
    bytes_total = 0
    t0 = time.time()

    while time.time() < t_end:
        data = _recv_frame(sock)
        if data is None:
            break
        n["recv"] += 1
        bytes_total += len(data)
        a = time.perf_counter()
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        b = time.perf_counter()
        n["decode"] += 1
        if not umap_ready:
            h0, w0 = frame.shape[:2]
            umap, umap_ready = frame_orient.undistort_map(w0, h0), True
            if umap is None:
                print(f"🔴 [왜곡보정] {w0}×{h0} 용 맵 없음 — 보정 없이 잰다(조건에 기록된다)")
        frame = frame_orient.apply_full(frame, umap)
        c = time.perf_counter()
        n["orient"] += 1
        ms["decode"].append((b - a) * 1000)
        ms["orient"].append((c - b) * 1000)
        if not args.no_save:
            cv2.imwrite(str(out / f"f{n['saved'] + 1:05d}.png"), frame,
                        [cv2.IMWRITE_PNG_COMPRESSION, 3])
            ms["save"].append((time.perf_counter() - c) * 1000)
            n["saved"] += 1

    stop.set()
    dur = time.time() - t0
    sock.close()

    def avg(xs):
        return (sum(xs) / len(xs)) if xs else 0.0

    res = {
        "seconds": round(dur, 1), "no_save": bool(args.no_save), "host": host,
        "counts": n,
        "fps": {k: round(v / dur, 2) for k, v in n.items()},
        "ms_avg": {k: round(avg(v), 2) for k, v in ms.items()},
        "kbps": round(bytes_total / 1024 / dur, 1),
        "esp32": esp,
        "frame_size": "VGA", "jpeg_quality": 15, "undistort": umap is not None,
    }
    (out / "bench.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"\n결과 → {out / 'bench.json'}")
    return 0


# ───────────────────────────────────────────────────────────── 자가시험
def _selftest() -> int:
    """저장 폴더 이름·PNG 무손실·session.json 필수 키를 확인한다."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sess = Session(Path(d), place="장소1", scene="8 배경", every=0.0,
                       meta={"frame_size": "VGA", "jpeg_quality": 15})
        img = np.full((640, 480, 3), 7, np.uint8)
        sess.save(img)
        sess.save(img)
        sess.close(stages={"recv": 2, "decode": 2, "orient": 2, "saved": 2})
        files = sorted(p.name for p in sess.dir.glob("f*.png"))
        assert files == ["f00001.png", "f00002.png"], files
        back = cv2.imread(str(sess.dir / "f00001.png"))
        assert (back == 7).all(), "PNG 가 무손실이 아니다"
        meta = json.loads((sess.dir / "session.json").read_text(encoding="utf-8"))
        for k in ("place", "scene", "frames", "stages", "frame_size", "jpeg_quality"):
            assert k in meta, k
        assert meta["frames"] == 2, meta["frames"]
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None, help="ESP32 IP(기본: config)")
    ap.add_argument("--out", default="~/data/capture", help="저장 뿌리")
    ap.add_argument("--every", type=float, default=0.2,
                    help="저장 간격(초). 기본 0.2 = 초당 5장 — 시연영상 추출과 같은 밀도")
    ap.add_argument("--force", action="store_true", help="왜곡보정 없이도 진행")
    ap.add_argument("--bench", type=float, default=0.0, metavar="초",
                    help="지정 시 촬영 대신 성능 측정만 한다(화면 없음)")
    ap.add_argument("--no-save", action="store_true",
                    help="--bench 에서 PNG 저장을 뺀다 — 저장 비용을 분리해 보려고")
    ap.add_argument("--esp-port", default=None, metavar="/dev/ttyACMx",
                    help="ESP32 시리얼 포트. 주면 송신 통계(cap/sent/drop)를 함께 모은다")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    return run_bench(a) if a.bench > 0 else run(a)


if __name__ == "__main__":
    sys.exit(main())
