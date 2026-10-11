#!/usr/bin/env python3
"""가짜 안경 카메라 — 녹화된 원본을 안경과 같은 형식(포트 8888 · 4바이트 길이(<I) + JPEG)으로 보낸다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §7.1 · §6(램프 흉내)
실행: python3 Demo/test/fake_camera.py <폴더(f*.jpg) | 영상.mp4> [--fps 19.5] [--port 8888] [--seconds 0]
시험: from fake_camera import FakeCamera — port 0 이면 빈 포트를 고른다.

🔴 답하는 것 = 받기 · 풀기 · 처리 흐름이 끝까지 도는지 · 처리 fps(임시 값 — 장면 · JPEG 크기 · 무선이 실물과 다르다).
   답하지 않는 것 = 실제 안경의 송출 속도 · 지연 · 화질(학교 값이 본 값 · 설계 D16).
"""
import argparse
import glob
import os
import socket
import struct
import threading
import time

import cv2
import numpy as np

LAMP_BOX = (40, 40, 120, 120)   # 램프 흉내 — 밝게 칠할 자리(x1, y1, x2, y2 · 보내는 장 좌표)


def unorient(img):
    """화면 방향(시연이 반전 → 회전한 뒤) 장을 안경 원본 방향으로 — 시계 방향 90° → 상하 반전(frame_orient 의 거꾸로).
    🔑 녹화 영상은 보정(왜곡 펴기)까지 된 장이라 완전한 원본은 아니다 — 처리 흐름 · fps 를 돌려 보는 데만 쓴다."""
    import config
    if config.CAMERA_ROTATE_CCW90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if config.CAMERA_FLIP_VERTICAL:
        img = cv2.flip(img, 0)
    return img


def load_frames(src, limit=0, unorient_video=False):
    """폴더(f*.jpg — 안경이 보낸 바이트 그대로) 또는 영상(mp4 — 장마다 JPEG 로 다시 압축) → [JPEG 바이트].
    unorient_video = 영상이 화면 방향(측정 녹화)이면 안경 원본 방향으로 되돌린다."""
    if os.path.isdir(src):
        out = []
        for p in sorted(glob.glob(os.path.join(src, "f*.jpg"))):
            with open(p, "rb") as f:
                out.append(f.read())
    else:
        cap = cv2.VideoCapture(src)
        out = []
        while not limit or len(out) < limit:
            ok, img = cap.read()
            if not ok:
                break
            if unorient_video:
                img = unorient(img)
            out.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes())
        cap.release()
    out = out[:limit] if limit else out
    if not out:
        raise SystemExit(f"보낼 장이 없다: {src}")
    return out


class FakeCamera:
    """손님 하나에게 장을 정한 속도로 되풀이해 보낸다 — 끊으면 다음 손님을 기다린다(안경처럼 손님 하나)."""

    def __init__(self, frames, port=8888, fps=19.5, host="127.0.0.1", mimic=False):
        self.frames, self.fps, self.mimic = frames, fps, mimic
        self.sent = 0
        self._lamp_next = None        # (바뀔 시각 monotonic, 켬?)
        self._lamp_on = False
        self._stop = threading.Event()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(1)
        self._srv.settimeout(0.5)
        self.port = self._srv.getsockname()[1]

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass

    def lamp(self, on, delay_s):
        """램프 흉내 — delay_s 뒤부터 보내는 장의 램프 자리를 밝게(on) · 어둡게(off) 칠한다(mimic=True 일 때)."""
        self._lamp_next = (time.monotonic() + delay_s, bool(on))

    def _frame(self, i):
        data = self.frames[i % len(self.frames)]
        if not self.mimic:
            return data
        nxt = self._lamp_next
        if nxt is not None and time.monotonic() >= nxt[0]:
            self._lamp_on, self._lamp_next = nxt[1], None
        # 🔑 켜든 끄든 매 장 풀고 다시 압축한다 — 램프 흉내 중 장마다 걸리는 시간이 같게
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        x1, y1, x2, y2 = LAMP_BOX
        img[y1:y2, x1:x2] = 255 if self._lamp_on else 0
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()

    def _loop(self):
        period = 1.0 / self.fps
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            i, t_next = 0, time.monotonic()
            try:
                while not self._stop.is_set():
                    data = self._frame(i)
                    c.sendall(struct.pack("<I", len(data)) + data)
                    self.sent += 1
                    i += 1
                    t_next += period
                    time.sleep(max(0.0, t_next - time.monotonic()))
            except OSError:
                pass                                   # 손님이 끊음 — 다음 손님을 기다린다
            finally:
                c.close()


def main():
    ap = argparse.ArgumentParser(description="가짜 안경 카메라(학교 방문 준비 설계 §7.1)")
    ap.add_argument("src", help="f*.jpg 폴더 또는 mp4")
    ap.add_argument("--fps", type=float, default=19.5)
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--limit", type=int, default=0, help="앞에서 이만큼만(0 = 전부)")
    ap.add_argument("--seconds", type=float, default=0.0, help="이만큼 뒤 끝(0 = Ctrl+C 까지)")
    ap.add_argument("--unorient", action="store_true", help="영상이 화면 방향(측정 녹화)이면 안경 원본 방향으로 되돌린다")
    a = ap.parse_args()
    cam = FakeCamera(load_frames(a.src, a.limit, a.unorient), port=a.port, fps=a.fps).start()
    print(f"가짜 카메라 127.0.0.1:{cam.port} · {len(cam.frames)}장 · {a.fps}장/초", flush=True)
    t_end = time.monotonic() + a.seconds if a.seconds > 0 else None
    try:
        while t_end is None or time.monotonic() < t_end:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    cam.stop()
    print(f"보낸 장 {cam.sent}")


if __name__ == "__main__":
    main()
