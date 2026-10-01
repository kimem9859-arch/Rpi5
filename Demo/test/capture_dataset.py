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

장면 목록은 데이터확보 설계서 §5 장면에 0 정지를 더하고 5 빛반사를 뺀 것이다(SCENES). 화면에 띄워 **그 자체가 촬영
지시서**가 되게 한다 — 「무엇을 몇 번 찍어라」를 말로 전하면 혼선이 생겨
재촬영을 부른다. 시간표·현장 절차 = `docs/촬영지시서.md`.

사용법:
    python3 test/capture_dataset.py --place 장소2               # 촬영(미리보기 + 키 조작)
    python3 test/capture_dataset.py --place 장소2 --count       # 촬영 직후 현장 장수 세기
    python3 test/capture_dataset.py --place 장소2 --every 0.5   # 저장 간격 0.5초
    python3 test/capture_dataset.py --bench 60 --esp-port /dev/ttyACM1
    python3 test/capture_dataset.py --bench 60 --no-save # 저장 비용 분리
    python3 test/capture_dataset.py --selftest

키:  space=녹화 시작/정지   s=장면   q=종료   (장소는 --place 로 고정 — 촬영 중 못 바꾼다)
"""
from __future__ import annotations
import argparse
import functools
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

# 데이터확보 설계서 §5 촬영 장면 — 번호는 설계서 그대로 둔다(폴더 이름 끝에 남는다).
#   0 정지 = 묶음 도구(review_batch --template)가 요구하는 같은 장소의 정지 장면.
#   5 빛반사 는 뺐다 — 반사를 만들 조명이 없다(사용자 2026-10-01).
SCENES = ["0 정지", "1 콘솔전체", "2 버튼누르기", "3 손지나감", "4 머리움직임",
          "6 놓인공구", "7 쥔공구", "8 배경"]
PLACES = ["장소1", "장소2", "장소3"]

# 🔴 화면 글씨는 Pillow + 한글 글꼴로 그린다 — cv2.putText 는 한글을 `???` 로 찍어
#    2026-10-01 시운전에서 장면 이름을 못 읽어 장면 7 녹화를 못 했다(calib_capture 와 같은 처방).
FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"
BANNER_H = 64                    # 미리보기 위쪽 안내 띠 높이(px) — 저장 사진에는 그리지 않는다
HELP = "space 녹화 시작/정지  ·  s 다음 장면(대기 중에만)  ·  q 종료"

# 현장 장수 세기의 최소 기준 — 거른 뒤(깨짐·검은 화면·중복) 남아야 할 장수. 근거 = 2026-10-01
# 장소1 실측(b001~b004 사람 검토 800장): 공구 장면 사진 한 장에 driver 가 있을 비율 0.308(세 공구 중 최저).
#   장소2 6+7 — 장소1 과 합쳐 클래스당 1,500(설계서 §6): (1,500 − 장소1 추정 895) ÷ 0.308 ≈ 1,964 → 2,000
#   장소3 6+7 — 시험 세트 클래스당 300(사용자 2026-10-01): 300 ÷ 0.308 ≈ 974 → 1,000
#   장소3 7·8 — 쥔 공구 300 · 배경 100 에 라벨러 제외(3~4%) 여유
MIN_KEEP = {"장소2": {"6+7": 2000}, "장소3": {"6+7": 1000, "7": 320, "8": 110}}

# 펌웨어가 5초마다 자동으로 찍는 줄. cap 과 sent 의 차이가 핵심이다 —
# 잡았는데 못 보냈으면 전송이, 애초에 적게 잡았으면 카메라·펌웨어가 병목이다.
_FRAME_RE = re.compile(r"Frame: cap=(\d+) sent=(\d+) drop=(\d+) · ([\d.]+)KB/장 · "
                       r"send avg=(\d+)ms max=(\d+)ms")


class Session:
    """한 회차의 저장 폴더와 메타를 들고 있는다."""

    def __init__(self, root: Path, place: str, scene: str, every: float, meta: dict,
                 stages0: dict | None = None):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 🔑 같은 초에 정지→다시 시작하면 이름이 같아 앞 녹화를 덮어쓴다 — 시각 끝에 b·c… 를 붙인다.
        #    장면 번호는 폴더 이름 끝(count_place)·시각은 앞 두 조각(review_batch.short_name)이라 둘 다 그대로다.
        root.mkdir(parents=True, exist_ok=True)
        for tail in ["", *"bcdefgh"]:
            self.dir = root / f"{stamp}{tail}_{place}_{scene.split()[0]}"
            try:
                self.dir.mkdir()
                break
            except FileExistsError:
                continue
        self.place, self.scene, self.every = place, scene, every
        self.meta = dict(meta)
        self.stages0 = dict(stages0 or {})   # 녹화 시작 때의 단계 수 — 이 녹화 몫만 남기려고
        self.n = 0
        self.next_at = 0.0
        self.started = time.time()

    def save(self, img) -> None:
        """🔴 cv2.imwrite 는 디스크가 차도 예외 없이 False 만 돌려준다 — 그대로 두면 화면의 장수만 오르고
        파일은 없다(여유 5.7G 에서 장소2 약 2~4G 를 찍는다). 실패하면 OSError 로 촬영을 멈춘다."""
        path = self.dir / f"f{self.n + 1:05d}.png"
        if not cv2.imwrite(str(path), img, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
            raise OSError(f"PNG 저장 실패 — 디스크 여유(df -h ~/data)를 확인하라: {path}")
        self.n += 1

    def maybe_save(self, img, now: float) -> bool:
        """간격이 됐으면 한 장 저장한다.

        🔴 시각은 저장 «전»에 잰 now 로 잡는다 — 저장 «뒤» 시각으로 잡으면 PNG 저장 시간(약 70ms)이
           간격에 더해져 0.2초가 0.27초가 됐다(2026-10-01 시운전 · 초당 5장 → 3.6장).
        격자(next_at += every)로 잡아 평균 간격이 every 가 되게 하고, 한 칸 넘게 밀리면 몰아서
        따라잡지 않고 그 시각부터 다시 센다.
        """
        if now < self.next_at:
            return False
        nxt = self.next_at + self.every
        self.next_at = nxt if nxt > now else now + self.every
        self.save(img)
        return True

    def close(self, stages: dict) -> None:
        self.meta.update({
            "place": self.place, "scene": self.scene, "every_sec": self.every,
            "frames": self.n, "seconds": round(time.time() - self.started, 1),
            # 🔑 이 녹화 동안만 — 도구를 켠 뒤 누적이면 녹화 68초에 수신 10,188 처럼 뜻이 어긋난다(2026-10-01)
            "stages": {k: v - self.stages0.get(k, 0) for k, v in stages.items()},
        })
        (self.dir / "session.json").write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")


def out_root(out: str, place: str) -> Path:
    """저장 뿌리 — 🔴 장소3(시험 전용)은 형제 폴더 `<out>_장소3` 에 따로 둔다.
    학습 묶음을 만들 때 장소 폴더 하나를 통째로 넘겨도 시험 사진이 섞이지 않게(설계 2026-09-16 §4)."""
    root = Path(os.path.abspath(os.path.expanduser(out)))   # abspath — `--out .` 도 이름이 생긴다
    return root.with_name(f"{root.name}_장소3") if place == "장소3" else root


def orient_meta(w0: int, h0: int, calib_path) -> dict:
    """촬영 조건 기록 — 장소1 사진을 찍은 bench_detector 의 manifest 와 **같은 이름·같은 뜻**.
    🔴 frame_size 는 센서 원본(회전 전) 크기다. 회전 뒤 크기를 적으면 같은 이름이 다른 뜻이 된다
       (2026-10-01 시운전에서 768x1024 로 기록돼 장소1 의 1024x768 과 어긋났다)."""
    return {"frame_size": f"{w0}x{h0}",
            "undistort": calib_path is not None,
            "calibration_file": os.path.basename(calib_path) if calib_path else None,
            "flip_mode": "v" if config.CAMERA_FLIP_VERTICAL else "none",
            "rotate_ccw90": bool(config.CAMERA_ROTATE_CCW90)}


@functools.lru_cache(maxsize=4)
def _font(size: int):
    from PIL import ImageFont
    return ImageFont.truetype(FONT_PATH, size)


def draw_banner(view, title: str, help_text: str) -> None:
    """미리보기 위쪽 BANNER_H 줄에 한글 안내 띠를 그린다(제자리 수정). 띠 높이만큼만 바꾼다 —
    한 장 전체를 Pillow 로 오가면 프레임마다 비용이 커서 띠만 그려 붙인다."""
    from PIL import Image, ImageDraw
    band = Image.new("RGB", (view.shape[1], BANNER_H), (0, 0, 0))
    d = ImageDraw.Draw(band)
    d.text((10, 4), title, font=_font(30), fill=(255, 230, 0))
    d.text((10, 40), help_text, font=_font(18), fill=(220, 220, 220))
    view[:BANNER_H] = cv2.cvtColor(np.asarray(band), cv2.COLOR_RGB2BGR)


# ───────────────────────────────────────────────────────────── 현장 장수 세기
def _health(path: str):
    """한 장의 거름 재료 — (버릴 사진인가, pHash). 기준은 묶음 도구(review_batch)와 같다."""
    import dedupe_raw
    import frame_health
    from review_batch import BLACK_MEAN
    try:
        seam, washed = frame_health.metrics(Path(path))
    except OSError:                  # 쓰다 만 파일(전원 차단·강제 종료) — 한 장 때문에 세기 전체가 죽지 않게
        return True, None
    img = cv2.imread(path)
    bad = seam > 0.02 or washed > 0.25 or img is None or float(img.mean()) < BLACK_MEAN
    return bad, (dedupe_raw.phash(img) if img is not None else None)


def count_place(root: Path, place: str, workers: int = 4) -> dict:
    """한 장소의 녹화를 묶음 도구와 같은 거름(깨짐·검은 화면 → 장소 전체 합쳐 pHash 중복)에
    넣어 장면별로 남는 장수를 센다. 🔑 촬영 직후 현장에서 돌린다 — 모자라면 장비를 걷기 전에 더 찍는다."""
    import dedupe_raw
    from review_batch import PHASH_THR
    dirs = sorted(d for d in Path(root).glob(f"*_{place}_*") if d.is_dir())
    items = [(d.name.rsplit("_", 1)[1], str(p)) for d in dirs for p in sorted(d.glob("f*.png"))]
    paths = [p for _, p in items]
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            res = pool.map(_health, paths, chunksize=16)
    else:
        res = [_health(p) for p in paths]
    ok = [i for i, (bad, _) in enumerate(res) if not bad]
    keep = dedupe_raw.dedupe([res[i][1] for i in ok], PHASH_THR)
    scenes: dict = {}
    for s, _ in items:
        scenes.setdefault(s, {"saved": 0, "unique": 0})["saved"] += 1
    for k in keep:
        scenes[items[ok[k]][0]]["unique"] += 1
    checks = []
    for key, need in MIN_KEEP.get(place, {}).items():
        have = sum(scenes.get(s, {}).get("unique", 0) for s in key.split("+"))
        checks.append({"scenes": key, "need": need, "have": have, "ok": have >= need})
    return {"sessions": len(dirs), "scenes": scenes, "checks": checks}


def run_count(args) -> int:
    root = out_root(args.out, args.place)
    print(f"[장수 세기] {root} · {args.place} — 깨짐·검은 화면·중복(장소 전체)을 거른다…")
    r = count_place(root, args.place)
    if r["sessions"] == 0:
        # 경로를 잘못 주면 「전부 모자람 — 더 찍는다」로 읽혀 다 찍은 장면을 다시 찍게 된다
        print(f"🔴 세션 없음 — {root} 에 *_{args.place}_* 폴더가 없다. --out·--place 를 확인하라.")
        return 2
    print(f"세션 {r['sessions']}개")
    names = {s.split()[0]: s for s in SCENES}
    print(f"\n{'장면':<10}{'저장':>8}{'남음':>8}")
    for s in sorted(r["scenes"]):
        v = r["scenes"][s]
        print(f"{names.get(s, s):<10}{v['saved']:>8}{v['unique']:>8}")
    for c in r["checks"]:
        mark = "✅" if c["ok"] else f"❌ {c['need'] - c['have']}장 모자람 — 그 장면을 더 찍는다"
        print(f"장면 {c['scenes']}: 남음 {c['have']} / 최소 {c['need']}  {mark}")
    return 0 if all(c["ok"] for c in r["checks"]) else 1


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
    umap, umap_ready, cond = None, False, {}
    place = args.place
    root = out_root(args.out, place)
    scene_i = 0
    sess = None
    stages = {"recv": 0, "decode": 0, "orient": 0, "saved": 0}
    print(f"[저장] {root} · {place}")
    print(HELP)

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
            umap, _, cpath = frame_orient.load_undistort(w0, h0)
            umap_ready, cond = True, orient_meta(w0, h0, cpath)
            # 🔑 해상도를 눈에 보이게 — VGA 보정 파일도 있어 펌웨어가 VGA 면 경고 없이 VGA 로 찍힌다
            print(f"[카메라] {w0}×{h0} · 보정 {cond['calibration_file']}  (장소1 = 1024×768)")
            if umap is None:
                print(f"🔴 [왜곡보정] {w0}×{h0} 용 맵 없음 — 런타임과 다른 그림이 된다.")
                if not args.force:
                    print("   --force 를 주면 그래도 진행한다. 지금은 멈춘다.")
                    sock.close()
                    return 1
        frame = frame_orient.apply_full(frame, umap)
        stages["orient"] += 1

        try:
            if sess is not None and sess.maybe_save(frame, time.time()):
                stages["saved"] += 1
        except OSError as e:
            print(f"🔴 [저장 실패] {e}")
            sess.close(stages)
            print(f"[녹화 정지] {sess.n}장 → {sess.dir}")
            sock.close()
            cv2.destroyAllWindows()
            return 1

        view = frame.copy()
        if sess:
            el = int(time.time() - sess.started)
            state = f"● 녹화 {el // 60:02d}:{el % 60:02d} · {sess.n}장"
        else:
            state = "대기"
        draw_banner(view, f"{place} · {SCENES[scene_i]} · {state}", HELP)
        cv2.imshow("capture_dataset", view)

        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord(" "):
            if sess is None:
                sess = Session(root, place, SCENES[scene_i], args.every,
                               {"host": host, **cond, "jpeg_quality": args.jpeg_quality},
                               stages0=stages)
                print(f"[녹화 시작] {sess.dir}")
            else:
                sess.close(stages)
                print(f"[녹화 정지] {sess.n}장 → {sess.dir}")
                sess = None
        # 🔑 장면은 녹화 중에 못 바꾼다 — 한 폴더에 두 조건이 섞이면 나중에 가를 수 없다.
        #    장소는 키로 바꾸지 않는다(--place) — 켜면 장소1 로 시작해 p 를 잊으면
        #    장소3 사진이 장소1 이름으로 학습 묶음에 섞일 수 있었다(2026-10-01).
        if k == ord("s") and sess is None:
            scene_i = (scene_i + 1) % len(SCENES)

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
    frame_size = "미확인"
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
            frame_size = f"{w0}x{h0}"
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
        # 🔴 조건은 **실측으로** 남긴다 — 2026-09-22 에 "VGA·q15" 가 하드코딩돼 있어
        #    SVGA·q10 회차가 VGA·q15 로 기록됐다. 조건이 거짓이면 수치도 못 쓴다.
        "frame_size": frame_size, "jpeg_quality": args.jpeg_quality,
        "undistort": bool(umap is not None),
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", choices=PLACES, default=None,
                    help="촬영 장소 — 촬영·--count 에 필수. 장소3 은 <out>_장소3 에 따로 저장한다")
    ap.add_argument("--count", action="store_true",
                    help="촬영 대신 그 장소의 녹화를 묶음 도구와 같은 거름에 넣어 장면별로 남는 장수를 센다")
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
    ap.add_argument("--jpeg-quality", type=int, default=None, metavar="N",
                    help="그때 펌웨어의 jpeg_quality. 기록용이며 도구가 바꾸지 않는다 "
                         "(0~63, 낮을수록 고화질). 안 주면 조건에 null 로 남는다")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if a.bench > 0:
        return run_bench(a)
    if a.place is None:
        ap.error("--place 장소2 처럼 촬영 장소를 정하라")
    return run_count(a) if a.count else run(a)


if __name__ == "__main__":
    sys.exit(main())
