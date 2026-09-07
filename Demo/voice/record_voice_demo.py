#!/usr/bin/env python3
"""음성비서 시연 촬영 — 콘솔 없이 카메라·공구·음성만으로 찍는다.

실행: python3 Demo/voice/record_voice_demo.py [--sec 90]
      🔴 시스템 python3 로 돈다(cv2 가 여기 있다). 음성비서만 ~/env/tts/.venv 로
         따로 띄운다 — sherpa-onnx 는 그쪽에만 있다.

무엇을 찍나 (2026-09-07 사용자 결정 — 콘솔·버튼·경고 시나리오는 안 쓴다):
  ① 1인칭 오버레이  ESP32 카메라 영상 + **공구 검출 박스**를 그려 넣은 것
  ② 3인칭          USB 웹캠 (ABKO APC900) 영상
  ③ 소리           웹캠 마이크 — 3인칭 영상에 입히고, 끝난 뒤 **wav 로도 뽑아 둔다**
                   (🔴 ALSA 는 배타적이라 ffmpeg 둘이 동시에 마이크를 못 연다)

동시에 도는 것:
  · 공구 검출 워커(tool_worker) — GUI 없이 직접 띄운다
  · 음성비서 데몬(voice_assistant) — 「가디언」 → 띠링 → 공구 안내

🔑 **보고서 시각자료용 계측을 함께 남긴다**(2026-09-07 사용자 요청):
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
import time

import cv2
import numpy as np

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)
import config  # noqa: E402

OUT_DIR   = os.path.join(_DEMO_DIR, "voice", "촬영본")
SHM_DIR   = config.TOOL_SHM_DIR
WEBCAM    = "/dev/video0"
MIC       = "plughw:2,0"          # ABKO APC900 웹캠 내장 마이크(카드 2)
FPS       = 15

# 색·이름 — GUI 와 같은 표를 쓴다(색표 정본 = config.TOOL_BOX_COLORS)
TOOL_KO = {"driver": "드라이버", "wrench": "렌치", "pliers": "플라이어"}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def hex2bgr(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


class ToolWorker:
    """공구 검출 워커를 직접 띄운다 — GUI 가 하던 일을 대신한다."""

    def __init__(self):
        os.makedirs(SHM_DIR, exist_ok=True)
        for f in os.listdir(SHM_DIR):          # 지난 실행 잔재를 지운다
            os.remove(os.path.join(SHM_DIR, f))
        self.p = subprocess.Popen(
            [config.TOOL_WORKER_PYTHON,
             os.path.join(_DEMO_DIR, "tool_worker.py"),
             SHM_DIR, config.TOOL_MODEL_PATH, str(config.TOOL_CONF)],
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
    """검출 박스를 그린다 — 이게 촬영본의 「오버레이」다."""
    for d in dets:
        name = str(d[0]).split("-in-hand")[0]
        score = float(d[1])
        x1, y1, x2, y2 = (int(float(v)) for v in d[2:6])
        color = hex2bgr(config.TOOL_BOX_COLORS.get(name, "#FFFFFF"))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        label = f"{TOOL_KO.get(name, name)} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
        cv2.putText(frame, label, (x1 + 4, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return frame


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sec", type=int, default=90, help="촬영 길이(초)")
    ap.add_argument("--no-voice", action="store_true", help="음성비서 데몬을 안 띄운다")
    a = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("🔴 ffmpeg 가 없다")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_DIR, stamp)
    os.makedirs(out, exist_ok=True)
    ip = open(os.path.join(_DEMO_DIR, ".camera_ip"), encoding="utf-8").read().strip()
    log(f"ESP32 = {ip} · 출력 = {out}")

    # ── ESP32 카메라 연결 (첫 프레임으로 크기를 안다) ──
    cam = socket.create_connection((ip, 8888), 10)
    cam.settimeout(10)

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

    first = recv_frame()
    if first is None:
        sys.exit("🔴 ESP32 첫 프레임을 못 받았다")
    fh, fw = first.shape[:2]
    log(f"1인칭 {fw}x{fh}")

    # ── 공구 워커 ──
    tw = ToolWorker()
    log("공구 워커 적재 중… (모델 로딩에 수십 초)")
    if not tw.ready():
        sys.exit("🔴 공구 워커가 안 떴다")
    log("공구 워커 준비됨")

    # ── ffmpeg 3벌: 1인칭(파이프) · 3인칭+소리 · 소리만 ──
    X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    p_fpv = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pixel_format", "bgr24",
         "-video_size", f"{fw}x{fh}", "-framerate", str(FPS), "-i", "-"]
        + X264 + [os.path.join(out, "1인칭_오버레이.mp4")], stdin=subprocess.PIPE)
    p_cam = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "v4l2", "-input_format", "mjpeg",
         "-video_size", "1920x1080", "-framerate", str(FPS), "-i", WEBCAM,
         "-f", "alsa", "-ac", "1", "-ar", "48000", "-i", MIC,
         "-vf", "scale=1280:720"] + X264
        + ["-c:a", "aac", "-b:a", "128k",
           os.path.join(out, "3인칭_소리포함.mp4")])
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
        env = dict(os.environ, SOP_VOICE_METRICS=os.path.join(out, "계측.jsonl"))
        voice = subprocess.Popen(
            [voice_py, os.path.join(_DEMO_DIR, "voice_assistant.py")],
            stdout=open(os.path.join(out, "음성비서.log"), "w"),
            stderr=subprocess.STDOUT, env=env)
        log("음성비서 데몬 시작 (로그 = 음성비서.log)")

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
            f = recv_frame()
            if f is None:
                log("🔴 ESP32 스트림 끊김")
                break
            tw.maybe_request(f)
            dets = tw.poll()
            for d in dets:
                k = str(d[0]).split("-in-hand")[0]
                tool_hits[k] = tool_hits.get(k, 0) + 1
            latest = draw(f, dets)
            now = time.time()
            while deadline <= now:                 # 늦었으면 그만큼 채운다
                p_fpv.stdin.write(latest.tobytes())
                n += 1
                deadline += period
    finally:
        el = time.time() - t0
        log(f"촬영 종료 — {n} 프레임 / {el:.0f}초 = {n/max(el,1):.1f} fps")
        try:
            p_fpv.stdin.close()
        except OSError:
            pass
        p_cam.send_signal(signal.SIGINT)
        for p in (p_fpv, p_cam):
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
                     "conf": config.TOOL_CONF,
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
        with open(os.path.join(out, "요약.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        log("=== 산출물 ===")
        for f in sorted(os.listdir(out)):
            sz = os.path.getsize(os.path.join(out, f)) / 1024 / 1024
            log(f"  {f}  {sz:.1f} MB")


if __name__ == "__main__":
    main()
