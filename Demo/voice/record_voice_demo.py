#!/usr/bin/env python3
"""음성비서 시연 촬영 — 콘솔 없이 카메라·공구·음성만으로 찍는다.

실행: python3 Demo/voice/record_voice_demo.py [--sec 90]
      🔴 시스템 python3 로 돈다(cv2 가 여기 있다). 음성비서만 ~/env/tts/.venv 로
         따로 띄운다 — sherpa-onnx 는 그쪽에만 있다.

무엇을 찍나 (2026-09-07 사용자 결정 — 콘솔·버튼·경고 시나리오는 안 쓴다):
  ① 1인칭 오버레이  ESP32 카메라 영상 + **공구 검출 박스**를 그려 넣은 것
  ② 3인칭          USB 웹캠 (ABKO APC900) 영상
                   🔑 `--preview` 면 **같은 ffmpeg 에서 미리보기 출력을 하나 더** 뽑아
                      창으로 띄운다 — v4l2 는 두 프로세스가 동시에 못 연다.
  ③ 소리           웹캠 마이크 — 3인칭 영상에 입히고, 끝난 뒤 **wav 로도 뽑아 둔다**
                   (🔴 ALSA 는 배타적이라 ffmpeg 둘이 동시에 마이크를 못 연다)

동시에 도는 것:
  · 공구 검출 워커(tool_worker) — GUI 없이 직접 띄운다
  · 음성비서 데몬(voice_assistant) — 「가디언」 → 띠링 → 공구 안내

🔴 **`--conf` 로 공구 임계를 낮출 수 있다** — 시연 촬영 한정이다(2026-09-07 결정).
   런타임 기본은 `config.TOOL_CONF`(0.65)이고 그건 **콘솔 버튼 5종 판정**을 위해
   고른 값이다. 이번 시연은 공구 3종만 보고 배경도 단순해 낮춰도 오검출이 적다.
   🔴 **낮춘 값은 `요약.json` 에 함께 적힌다** — 조건 없이 인용하지 않기 위해서다.

🔑 **보고서 시각자료용 계측을 함께 남긴다**(2026-09-07 사용자 요청):
     오디오/       🔑 마이크_전체.wav · 발화_NNN.wav+.txt(STT 결과) ·
                   재생_NNN_<키>.wav(스피커로 낸 TTS 원본)
     계측.jsonl   발화마다 한 줄 — 발화 길이·RMS·노이즈 바닥·STT 텍스트·
                  STT 소요·호출어/의도 판정·검출 공구·재생 소요
     요약.json    촬영 전체 — 프레임 수·FPS·공구별 검출 횟수·응답 지연 통계
   🔴 판단이 아니라 **관측**만 적는다. 해석(인식률·지연 분포)은 나중에 이 파일에서 뽑는다.

🔑 GUI(safety_console)를 안 쓴다. 이 촬영에는 FSM·인터록·버튼이 필요 없고,
   GUI 를 띄우면 콘솔이 없어 경고가 먼저 뜬다(2026-09-07 타워램프 사례).

🔴 공구 검출 결과는 GUI 와 같은 자리(/dev/shm/sop_tool)에 쓴다 — 음성비서가
   거기를 읽기 때문이다. GUI 를 같이 띄우면 서로 덮어쓰므로 **같이 쓰지 않는다.**
"""
import argparse
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
import config  # noqa: E402
import frame_orient  # noqa: E402

OUT_DIR   = os.path.join(_DEMO_DIR, "voice", "촬영본")
SHM_DIR   = config.TOOL_SHM_DIR
WEBCAM    = "/dev/video0"
MIC       = "plughw:2,0"          # ABKO APC900 웹캠 내장 마이크(카드 2)
FPS       = 15

# 색·이름 — GUI 와 같은 표를 쓴다(색표 정본 = config.TOOL_BOX_COLORS)
TOOL_KO = {"driver": "드라이버", "wrench": "렌치", "pliers": "플라이어"}

# 🔴 창 제목은 ASCII — 한글은 ?? 로 깨진다(2026-09-07 확인).
PREVIEW_WIN = "FPV overlay - tool check (press q to stop)"
WEBCAM_WIN  = "3rd person (webcam) - framing check"
WEB_PREV    = (480, 270)      # 미리보기 크기 — 작게 뽑아 CPU 를 아낀다

# 🔴 cv2.putText 는 한글을 못 그린다(전부 ? 로 나온다, 2026-09-07 확인).
#    Hershey 폰트에 한글 글리프가 없기 때문이다. Pillow + 나눔 폰트로 그린다.
_FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"
try:
    _FONT = ImageFont.truetype(_FONT_PATH, 22)
except OSError:
    _FONT = None


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def hex2bgr(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


class ToolWorker:
    """공구 검출 워커를 직접 띄운다 — GUI 가 하던 일을 대신한다."""

    def __init__(self, conf):
        os.makedirs(SHM_DIR, exist_ok=True)
        for f in os.listdir(SHM_DIR):          # 지난 실행 잔재를 지운다
            os.remove(os.path.join(SHM_DIR, f))
        self.p = subprocess.Popen(
            [config.TOOL_WORKER_PYTHON,
             os.path.join(_DEMO_DIR, "tool_worker.py"),
             SHM_DIR, config.TOOL_MODEL_PATH, str(conf)],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.seq = 0
        self.last = 0.0
        self.dets = []

    def ready(self, timeout=90):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if os.path.exists(os.path.join(SHM_DIR, "ready")):
                return True
            if self.p.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def maybe_request(self, frame):
        """1초에 한 번만 추론을 시킨다 — GUI 의 TOOL_SCAN_INTERVAL_SEC 과 같다."""
        now = time.time()
        if now - self.last < config.TOOL_SCAN_INTERVAL_SEC:
            return
        self.last = now
        self.seq += 1
        # 🔴 tool_gate.py:129~136 과 같은 방식이어야 한다 — 워커는 `req_<seq>.jpg`
        #    만 읽고, 반쯤 써진 파일을 집지 않도록 .tmp 로 쓴 뒤 원자적으로 옮긴다.
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return
        tmp = os.path.join(SHM_DIR, f"req_{self.seq}.jpg.tmp")
        with open(tmp, "wb") as f:
            f.write(buf.tobytes())
        os.replace(tmp, os.path.join(SHM_DIR, f"req_{self.seq}.jpg"))

    def poll(self):
        p = os.path.join(SHM_DIR, "resp.json")
        try:
            with open(p, encoding="utf-8") as f:
                self.dets = [tuple(d) for d in (json.load(f).get("dets") or [])]
        except (OSError, ValueError):
            pass
        return self.dets

    def stop(self):
        self.p.terminate()
        try:
            self.p.wait(3)
        except subprocess.TimeoutExpired:
            self.p.kill()


def draw(frame, dets):
    """검출 박스를 그린다 — 이게 촬영본의 「오버레이」다.

    🔴 라벨은 Pillow 로 그린다 — cv2.putText 는 한글을 ? 로 낸다(2026-09-07).
       박스는 cv2 로 그리는 편이 빠르므로 **박스는 cv2, 글자만 Pillow** 로 나눈다.
    """
    boxes = []
    for d in dets:
        name = str(d[0]).split("-in-hand")[0]
        score = float(d[1])
        x1, y1, x2, y2 = (int(float(v)) for v in d[2:6])
        color = hex2bgr(config.TOOL_BOX_COLORS.get(name, "#FFFFFF"))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        boxes.append((x1, y1, f"{TOOL_KO.get(name, name)} {score:.2f}", color))

    if not boxes or _FONT is None:
        for x1, y1, label, color in boxes:          # 폰트가 없으면 영문으로라도
            cv2.putText(frame, label.encode("ascii", "ignore").decode() or "?",
                        (x1 + 4, max(18, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        return frame

    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    dr = ImageDraw.Draw(img)
    for x1, y1, label, color in boxes:
        rgb = (color[2], color[1], color[0])        # BGR → RGB
        l, t, r, b = dr.textbbox((0, 0), label, font=_FONT)
        w, h = r - l, b - t
        ty = max(0, y1 - h - 8)
        dr.rectangle([x1, ty, x1 + w + 10, ty + h + 8], fill=rgb)
        dr.text((x1 + 5, ty + 2), label, font=_FONT, fill=(0, 0, 0))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sec", type=int, default=90, help="촬영 길이(초)")
    ap.add_argument("--no-voice", action="store_true", help="음성비서 데몬을 안 띄운다")
    ap.add_argument("--preview", action="store_true",
                    help="1인칭 오버레이를 화면에 띄운다 (공구가 잡히는지 눈으로 본다)")
    ap.add_argument("--no-record", action="store_true",
                    help="영상·소리를 저장하지 않는다 (확인 전용)")
    ap.add_argument("--check-webcam", type=int, default=0, metavar="초",
                    help="촬영 시작 전 3인칭 웹캠 구도를 그 초만큼 화면에 띄운다")
    ap.add_argument("--conf", type=float, default=config.TOOL_CONF,
                    help=f"공구 검출 임계 (기본 = config.TOOL_CONF = {config.TOOL_CONF})")
    a = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("🔴 ffmpeg 가 없다")
    if a.check_webcam:
        # 🔑 촬영 **전에** 본다 — 촬영 중에는 ffmpeg 이 장치를 독점한다.
        log(f"3인칭 웹캠 구도 확인 {a.check_webcam}초 …")
        subprocess.run(["ffplay", "-hide_banner", "-loglevel", "error",
                        "-autoexit", "-t", str(a.check_webcam),
                        "-f", "v4l2", "-input_format", "mjpeg",
                        "-video_size", "1920x1080", "-framerate", "15",
                        "-i", WEBCAM, "-vf", "scale=960:540",
                        "-window_title", "3rd person framing check"], check=False)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_DIR, stamp)
    os.makedirs(out, exist_ok=True)
    ip = open(os.path.join(_DEMO_DIR, ".camera_ip"), encoding="utf-8").read().strip()
    log(f"ESP32 = {ip} · 출력 = {out}")

    # ── ESP32 카메라 연결 (첫 프레임으로 크기를 안다) ──
    cam = socket.create_connection((ip, 8888), 10)
    cam.settimeout(10)

    # 🔴 GUI 와 **똑같은 프레임 처리**를 해야 한다 — 안 하면 화면이 GUI 와 다르게
    #    나오고(2026-09-07 확인), 공구 검출 결과도 달라진다.
    #    순서 = 반전 → 왜곡보정 → 회전. 이 순서는 frame_orient.py 머리말이 정본이다
    #    (왜곡보정 맵은 센서 원본 해상도 전용이라 회전을 먼저 하면 조용히 꺼진다).
    undist = {"map": None}

    def load_undistort(w, h):
        """왜곡보정 맵 — camera_thread._load_undistort_map 과 같은 계산.

        🔴 camera_thread 를 import 하지 않는다 — Qt·Hailo 를 끌어와 무겁고
           장치를 잡는다(frame_orient.py 머리말이 같은 이유로 갈라져 있다).
           대신 계산을 여기 옮겨 적는다. 🔴 alpha 는 config.CALIB_ALPHA 를 읽어
           복제하지 않는다(도구 기본값이 config 를 안 따라 4번 물렸다).
        """
        path = config.YOLO_CALIBRATION_PATH
        if not os.path.exists(path):
            return None, "missing"
        data = np.load(path)
        if "image_size" in data:
            iw, ih = int(data["image_size"][0]), int(data["image_size"][1])
            if (iw, ih) != (w, h):
                return None, "mismatch"
        cam_mat, dist = data["camera_matrix"], data["dist_coeffs"]
        new_mat, _ = cv2.getOptimalNewCameraMatrix(
            cam_mat, dist, (w, h), config.CALIB_ALPHA, (w, h))
        return cv2.initUndistortRectifyMap(
            cam_mat, dist, None, new_mat, (w, h), cv2.CV_16SC2), "ok"

    def process(frame):
        f = frame_orient.flip(frame)
        if undist["map"] is not None:
            f = cv2.remap(f, undist["map"][0], undist["map"][1], cv2.INTER_LINEAR)
        return frame_orient.rotate(f)

    def recv_frame():
        h = b""
        while len(h) < 4:
            c = cam.recv(4 - len(h))
            if not c:
                return None
            h += c
        n = struct.unpack("<I", h)[0]
        buf = b""
        while len(buf) < n:
            c = cam.recv(min(8192, n - len(buf)))
            if not c:
                return None
            buf += c
        return cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)

    raw0 = recv_frame()
    if raw0 is None:
        sys.exit("🔴 ESP32 첫 프레임을 못 받았다")
    rh, rw = raw0.shape[:2]
    maps, status = load_undistort(rw, rh)
    undist["map"] = maps
    log(f"왜곡보정: {status} (alpha={config.CALIB_ALPHA})")
    first = process(raw0)
    fh, fw = first.shape[:2]
    log(f"1인칭 원본 {rw}x{rh} → 처리 후 {fw}x{fh}")

    # ── 공구 워커 ──
    tw = ToolWorker(a.conf)
    if abs(a.conf - config.TOOL_CONF) > 1e-9:
        log(f"⚠️ 공구 임계를 {config.TOOL_CONF} → {a.conf} 로 낮춰 돈다 "
            f"(이번 촬영 한정 — 런타임 기본값은 안 바뀐다)")
    log("공구 워커 적재 중… (모델 로딩에 수십 초)")
    if not tw.ready():
        sys.exit("🔴 공구 워커가 안 떴다")
    log("공구 워커 준비됨")

    # ── ffmpeg 3벌: 1인칭(파이프) · 3인칭+소리 · 소리만 ──
    X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    p_fpv = p_cam = None
    if a.no_record:
        log("🔎 확인 모드 — 저장하지 않는다")
    else:
        p_fpv = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pixel_format", "bgr24",
         "-video_size", f"{fw}x{fh}", "-framerate", str(FPS), "-i", "-"]
        + X264 + [os.path.join(out, "1인칭_오버레이.mp4")], stdin=subprocess.PIPE)
        # 🔴 여기에 미리보기용 출력을 하나 더 붙이지 말 것 — 파이프가 막히면
        #   ffmpeg 이 mp4 를 마무리하지 못해 **영상이 통째로 깨진다**
        #   (2026-09-07: moov atom not found, 28.8MB 를 버렸다).
        #   3인칭 구도는 촬영 **전에** --check-webcam 으로 본다.
        cam_args = (
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "v4l2", "-input_format", "mjpeg",
             "-video_size", "1920x1080", "-framerate", str(FPS), "-i", WEBCAM,
             "-f", "alsa", "-ac", "1", "-ar", "48000", "-i", MIC,
             "-map", "0:v", "-map", "1:a", "-vf", "scale=1280:720"] + X264
            + ["-c:a", "aac", "-b:a", "128k",
               os.path.join(out, "3인칭_소리포함.mp4")])
        p_cam = subprocess.Popen(cam_args)
    # 🔴 마이크는 ffmpeg 하나만 열 수 있다(ALSA 는 배타적) — 둘이 물면
    #    「Input/output error」로 3인칭이 통째로 죽는다(2026-09-07 에 물렸다).
    #    그래서 소리는 3인칭에만 물리고, **끝난 뒤 그 mp4 에서 wav 를 뽑는다.**
        time.sleep(1.5)
        for name, p in (("1인칭", p_fpv), ("3인칭", p_cam)):
            if p.poll() is not None:
                log(f"🔴 {name} ffmpeg 이 즉시 죽었다 (코드 {p.returncode})")

    # ── 음성비서 데몬 ──
    voice = None
    if not a.no_voice:
        # 🔴 음성비서는 반드시 ~/env/tts/.venv 로 — sherpa-onnx 가 거기에만 있다.
        voice_py = os.path.expanduser("~/env/tts/.venv/bin/python")
        env = dict(os.environ,
                   SOP_VOICE_METRICS=os.path.join(out, "계측.jsonl"),
                   SOP_VOICE_AUDIO=os.path.join(out, "오디오"))
        voice = subprocess.Popen(
            [voice_py, os.path.join(_DEMO_DIR, "voice_assistant.py")],
            stdout=open(os.path.join(out, "음성비서.log"), "w"),
            stderr=subprocess.STDOUT, env=env)
        log("음성비서 데몬 시작 (로그 = 음성비서.log)")

    web = {"frame": None, "run": True}

    def web_reader_direct():
        """확인 모드(--no-record)에서만 웹캠을 직접 연다 — 그때는 ffmpeg 이 없다."""
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WEB_PREV[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, WEB_PREV[1])
        while web["run"]:
            ok, f = cap.read()
            if ok:
                web["frame"] = f
            else:
                time.sleep(0.1)
        cap.release()

    if a.preview:
        if a.no_record:            # 기록 중에는 ffmpeg 이 장치를 쥐고 있다
            threading.Thread(target=web_reader_direct, daemon=True).start()
        cv2.namedWindow(WEBCAM_WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WEBCAM_WIN, 640, 360)
        cv2.moveWindow(WEBCAM_WIN, 1040, 40)
        try:
            cv2.setWindowProperty(WEBCAM_WIN, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass

        # 🔴 창을 **항상 위**로 띄운다 — 2026-09-07 에 NoMachine 창 뒤에 가려
        #    「화면이 안 나온다」고 오인했다. 제목은 ASCII 로 둔다(한글이 ?? 로 깨진다).
        cv2.namedWindow(PREVIEW_WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(PREVIEW_WIN, 960, 720)
        cv2.moveWindow(PREVIEW_WIN, 40, 40)
        try:
            cv2.setWindowProperty(PREVIEW_WIN, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass
        log("📺 미리보기 창을 띄웠다 — 항상 위로 뜬다")

    log(f"🎬 촬영 시작 — {a.sec}초.  Ctrl-C 로 조기 종료")
    stop = {"v": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("v", True))

    # 🔴 벽시계에 맞춰 쓴다 — 안 그러면 재생 길이가 어긋난다.
    #    ESP32 는 10~28fps 로 흔들리는데 ffmpeg 에는 고정 FPS 로 알려주므로,
    #    그대로 밀면 **빠르거나 느린 영상**이 된다(2026-09-07: 10초 촬영이
    #    19.1초짜리 슬로모션으로 나왔다). 남으면 버리고, 모자라면 직전 프레임을
    #    한 번 더 쓴다.
    t0 = time.time()
    n = 0
    tool_hits = {}          # 공구별 검출 프레임 수 — 보고서 그림의 원자료
    period = 1.0 / FPS
    deadline = t0 + period
    latest = draw(first, [])
    try:
        while not stop["v"] and time.time() - t0 < a.sec:
            raw = recv_frame()
            if raw is None:
                log("🔴 ESP32 스트림 끊김")
                break
            f = process(raw)
            tw.maybe_request(f)
            dets = tw.poll()
            for d in dets:
                k = str(d[0]).split("-in-hand")[0]
                tool_hits[k] = tool_hits.get(k, 0) + 1
            latest = draw(f, dets)
            if a.preview:
                cv2.imshow(PREVIEW_WIN, latest)
                if web["frame"] is not None:
                    cv2.imshow(WEBCAM_WIN, web["frame"])
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
            now = time.time()
            while deadline <= now:                 # 늦었으면 그만큼 채운다
                if p_fpv:
                    p_fpv.stdin.write(latest.tobytes())
                n += 1
                deadline += period
    finally:
        el = time.time() - t0
        log(f"촬영 종료 — {n} 프레임 / {el:.0f}초 = {n/max(el,1):.1f} fps")
        web["run"] = False
        if a.preview:
            cv2.destroyAllWindows()
        if p_fpv:
            try:
                p_fpv.stdin.close()
            except OSError:
                pass
        if p_cam:
            p_cam.send_signal(signal.SIGINT)
        for p in (p_fpv, p_cam):
            if p is None:
                continue
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        if voice:
            voice.terminate()
        tw.stop()
        cam.close()
        # 소리만 따로 — 3인칭 mp4 에서 뽑는다(무손실 추출이라 다시 인코딩 안 한다)
        mp4 = os.path.join(out, "3인칭_소리포함.mp4")
        if os.path.exists(mp4) and os.path.getsize(mp4) > 0:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-i", mp4, "-vn", "-acodec", "pcm_s16le",
                            os.path.join(out, "소리만.wav")], check=False)
        # ── 보고서용 요약 ──
        summary = {
            "촬영시각": stamp,
            "길이초": round(el, 1),
            "1인칭": {"해상도": f"{fw}x{fh}", "프레임": n, "fps": round(n / max(el, 1), 1)},
            "3인칭": {"해상도": "1280x720", "장치": WEBCAM, "마이크": MIC},
            "공구검출_프레임수": tool_hits,
            "조건": {"ESP32": ip, "모델": os.path.basename(config.TOOL_MODEL_PATH),
                     "conf": a.conf,
                     "conf_런타임기본": config.TOOL_CONF,
                     "스캔주기초": config.TOOL_SCAN_INTERVAL_SEC},
        }
        mpath = os.path.join(out, "계측.jsonl")
        if os.path.exists(mpath):
            rows = [json.loads(x) for x in open(mpath, encoding="utf-8") if x.strip()]
            answered = [r for r in rows if r.get("답변")]
            summary["음성"] = {
                "발화수": len(rows),
                "호출어인식": sum(1 for r in rows if r.get("호출어")),
                "공구질문인식": sum(1 for r in rows if r.get("공구질문")),
                "답변수": len(answered),
                "답변분포": {k: sum(1 for r in answered if r["답변"] == k)
                            for k in {r["답변"] for r in answered}},
                "STT_ms_평균": round(sum(r["STT_ms"] for r in rows) / len(rows)) if rows else None,
                "재생_ms_평균": round(sum(r["재생_ms"] for r in answered) / len(answered))
                                if answered else None,
            }
        adir = os.path.join(out, "오디오")
        if os.path.isdir(adir):
            names = os.listdir(adir)
            summary["오디오파일"] = {
                "발화wav": sum(1 for x in names if x.startswith("발화_") and x.endswith(".wav")),
                "재생wav": sum(1 for x in names if x.startswith("재생_")),
                "마이크_전체": "마이크_전체.wav" in names,
            }
        with open(os.path.join(out, "요약.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        log("=== 산출물 ===")
        for f in sorted(os.listdir(out)):
            sz = os.path.getsize(os.path.join(out, f)) / 1024 / 1024
            log(f"  {f}  {sz:.1f} MB")


if __name__ == "__main__":
    main()
