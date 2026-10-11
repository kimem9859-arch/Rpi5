#!/usr/bin/env python3
"""카메라 → 파이 지연(램프) — 인터락 램프를 번갈아 켜고, 안경 영상에서 램프가 바뀐 첫 장까지의 시간을 잰다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §6 · 상위 처리흐름-판정기준 D12
실행(시연 끔 — 카메라 · 인터락을 이 도구가 쓴다):
  python3 Demo/test/lamp_latency.py [--n 24] [--out DIR]          램프(인터락 RUN ↔ WARN)
  python3 Demo/test/lamp_latency.py --screen [--n 24]             램프가 안 보이면 — 콘솔 화면 검정 ↔ 흰색(모니터 지연 섞임 · V11)
결과 = 지연 중앙값 · 90% · 최소 · 최대 + ACK(아두이노 응답) · lamp_latency.csv/json(--out)
🔴 상한 값이다 — 아두이노 처리 · 램프 켜짐 · 카메라 노출 · 압축 · 무선 · 받기가 모두 들어 있다(ACK 로 아두이노 몫을 뺄 수 있다).
"""
import argparse
import csv
import json
import os
import random
import socket
import struct
import sys
import threading
import time

TEST = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(TEST)
sys.path.insert(0, DEMO)

import cv2            # noqa: E402
import numpy as np    # noqa: E402

NOTE = "상한 값 — 아두이노 처리 · 램프 켜짐 · 카메라 노출 · 압축 · 무선 · 받기 포함(ACK 로 아두이노 몫을 뺄 수 있다)"
NOTE_SCREEN = "상한 값 — 모니터 표시 지연 섞임 · 카메라 노출 · 압축 · 무선 · 받기 포함"
SPOT_MIN = 15.0       # 켬 · 끔 평균 차이가 이보다 작으면 램프가 안 보이는 것
SPOT_R = 4            # 자리 반지름(1/4 크기 장 기준 화소)
LOOK = (0.4, 0.9)     # 자리 찾기 — 명령 뒤 「간격 × 이 비율」 구간 장들의 평균 · 다음 명령 전에 끝나게(간격 1.5초 = 0.6~1.35초)


def find_spot(on_imgs, off_imgs):
    """켬 평균 − 끔 평균의 절댓값을 흐린 뒤 가장 큰 자리 → (x, y, r) · 차이가 작으면 None."""
    if not on_imgs or not off_imgs:
        return None
    d = np.abs(np.mean([i.astype(np.float32) for i in on_imgs], axis=0)
               - np.mean([i.astype(np.float32) for i in off_imgs], axis=0))
    d = cv2.GaussianBlur(d, (9, 9), 0)
    _, mx, _, loc = cv2.minMaxLoc(d)
    return None if mx < SPOT_MIN else (loc[0], loc[1], SPOT_R)


def level(img, spot):
    x, y, r = spot
    return float(img[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].mean())


def first_cross(frames, t_cmd, mid, rising, until=None):
    """[(받은 시각, 수준)] 에서 t_cmd 뒤(until 전) 가운데 수준을 처음 넘는 장의 받은 시각 · 없으면 None."""
    for t, lv in frames:
        if t <= t_cmd:
            continue
        if until is not None and t >= until:
            return None
        if (lv > mid) if rising else (lv < mid):
            return t
    return None


def summarize(lat):
    v = sorted(x for x in lat if x is not None)
    if not v:
        return {"n": 0, "med": None, "p90": None, "min": None, "max": None}
    return {"n": len(v), "med": float(np.median(v)), "p90": float(np.percentile(v, 90)), "min": v[0], "max": v[-1]}


class Receiver:
    """안경 영상을 직접 받는다 — 장마다 받은 시각(ms) · 1/4 크기 회색."""

    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=5)
        self.frames = []
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _exact(self, n):
        b = b""
        while len(b) < n:
            part = self.s.recv(n - len(b))
            if not part:
                raise OSError("끊김")
            b += part
        return b

    def _loop(self):
        try:
            while not self._stop.is_set():
                n = struct.unpack("<I", self._exact(4))[0]
                data = self._exact(n)
                t = time.monotonic() * 1000
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_4)
                if img is not None:
                    self.frames.append((t, img))
        except (OSError, struct.error):
            pass

    def stop(self):
        self._stop.set()
        try:
            self.s.close()
        except OSError:
            pass


class SerialSender:
    """인터락에 RUN · WARN 한 줄 → (보낸 시각, ACK 시각|None) ms."""

    def __init__(self, port, settle_s=2.0):
        import serial
        import config
        self.ser = serial.Serial(port, config.INTERLOCK_BAUD, timeout=1.0)
        time.sleep(settle_s)                      # 아두이노는 열 때 재시작한다
        self.ser.reset_input_buffer()

    def send(self, cmd):
        self.ser.reset_input_buffer()
        t = time.monotonic() * 1000
        self.ser.write((cmd + "\n").encode("ascii"))
        self.ser.flush()
        ack = self.ser.readline().decode("ascii", "replace").strip()
        return t, (time.monotonic() * 1000 if ack == "ACK" else None)

    def wait(self, sec):
        time.sleep(sec)

    def close(self):
        try:
            self.send("RUN")                      # 끝나면 정상 램프로
        finally:
            self.ser.close()


class ScreenSender:
    """램프 대신 콘솔 화면 전체를 검정(RUN) ↔ 흰색(WARN) — 칠한 뒤 시각(V11)."""

    def __init__(self):
        from PyQt6.QtWidgets import QApplication, QWidget
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.w = QWidget()
        self.w.setStyleSheet("background:black")
        self.w.showFullScreen()
        self.wait(1.0)

    def send(self, cmd):
        self.w.setStyleSheet("background:white" if cmd == "WARN" else "background:black")
        self.w.repaint()
        self.app.processEvents()
        return time.monotonic() * 1000, None

    def wait(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def close(self):
        self.w.close()


def run(host, port, serial_port=None, n_find=6, n_meas=24, interval=1.5, out=None, screen=False, settle_s=2.0):
    """→ {"n", "med", "p90", "min", "max", "ack_med", "spot", "note", "rows"} 또는 {"error": …}."""
    try:
        rx = Receiver(host, port)
    except OSError as e:
        return {"error": f"카메라 {host}:{port} 연결 안 됨 — {e} (V2 · 시연이 켜져 있으면 끈다)"}
    try:
        tx = ScreenSender() if screen else SerialSender(serial_port, settle_s)
    except Exception as e:                        # noqa: BLE001
        rx.stop()
        return {"error": f"인터락 {serial_port} 을 열지 못함 — {e} (V10 · 시연이 켜져 있으면 끈다)"}
    rows = []
    try:
        t0 = time.monotonic()
        while not rx.frames and time.monotonic() - t0 < 5:
            time.sleep(0.05)
        if not rx.frames:
            return {"error": "영상이 안 온다(V2 · V4)"}
        tx.send("RUN")
        tx.wait(1.0)
        for i in range(n_find + n_meas):
            cmd = "WARN" if i % 2 == 0 else "RUN"
            t_send, t_ack = tx.send(cmd)
            rows.append({"i": i, "cmd": cmd, "t_send": t_send, "t_ack": t_ack, "find": i < n_find})
            tx.wait(interval + random.uniform(0.0, 0.3))
    finally:
        tx.close()
        rx.stop()
    frames = list(rx.frames)
    on, off = [], []
    for r in rows[:n_find]:
        lo, hi = r["t_send"] + LOOK[0] * interval * 1000, r["t_send"] + LOOK[1] * interval * 1000
        grp = [img for t, img in frames if lo <= t <= hi]
        (on if r["cmd"] == "WARN" else off).extend(grp)
    spot = find_spot(on, off)
    if spot is None:
        return {"error": "램프 자리를 못 찾음 — 램프가 안경 화면에 안 보인다 → --screen 으로 다시(V11)", "rows": rows}
    lv = [(t, level(img, spot)) for t, img in frames]
    on_lv = float(np.mean([level(i, spot) for i in on]))
    off_lv = float(np.mean([level(i, spot) for i in off]))
    mid, up = (on_lv + off_lv) / 2, on_lv > off_lv
    # 🔴 헛자리 막기 — 장면만 움직여도 「가장 많이 바뀐 자리」는 나온다(리허설이 찾음 · 엉터리 23ms).
    #    자리 찾기 판마다 켬 · 끔이 늘 같은 쪽으로 갈리고, 차이가 판 안 흔들림의 3배를 넘을 때만 잰다.
    cyc = []
    for r in rows[:n_find]:
        lo, hi = r["t_send"] + LOOK[0] * interval * 1000, r["t_send"] + LOOK[1] * interval * 1000
        vals = [level(img, spot) for t, img in frames if lo <= t <= hi]
        if vals:
            cyc.append((r["cmd"], float(np.mean(vals)), float(np.std(vals))))
    same_side = all((m > mid) == (up if cmd == "WARN" else not up) for cmd, m, _ in cyc)
    noise = max([sd for _, _, sd in cyc] + [1.0])
    if len(cyc) < n_find or not same_side or abs(on_lv - off_lv) < 3 * noise:
        return {"error": "램프 자리가 흔들린다 — 켬 · 끔이 판마다 같은 쪽으로 갈리지 않는다(장면이 움직였거나 램프가 안 보인다)"
                         " → 안경을 거치대에 고정하고 다시 · 그래도 안 되면 --screen(V11)", "rows": rows, "spot": spot}
    lat = []
    meas = rows[n_find:]
    for k, r in enumerate(meas):
        nxt = meas[k + 1]["t_send"] if k + 1 < len(meas) else None
        t = first_cross(lv, r["t_send"], mid, up if r["cmd"] == "WARN" else not up, until=nxt)
        r["t_first"] = t
        r["lat"] = (t - r["t_send"]) if t is not None else None
        lat.append(r["lat"])
    acks = [r["t_ack"] - r["t_send"] for r in rows if r["t_ack"] is not None]
    res = dict(summarize(lat), ack_med=float(np.median(acks)) if acks else None, spot=spot, on=on_lv, off=off_lv,
               missed=sum(1 for x in lat if x is None), note=NOTE_SCREEN if screen else NOTE, rows=rows)
    if res["missed"] > len(lat) / 4:
        res["warning"] = f"바뀐 장을 못 찾은 명령 {res['missed']}/{len(lat)} — 값이 애매하다(학교 필수 · 다시)"
    if out:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "lamp_latency.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["i", "cmd", "t_send_ms", "t_ack_ms", "t_first_ms", "lat_ms", "find"])
            for r in rows:
                w.writerow([r["i"], r["cmd"], r["t_send"], r["t_ack"], r.get("t_first"), r.get("lat"), int(r["find"])])
        with open(os.path.join(out, "lamp_latency.json"), "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in res.items() if k != "rows"}, f, ensure_ascii=False, indent=1)
    return res


def main(argv=None):
    import config
    ap = argparse.ArgumentParser(description="카메라 → 파이 지연(램프 · 학교 방문 준비 설계 §6)")
    ap.add_argument("--screen", action="store_true", help="램프 대신 콘솔 화면을 번쩍인다(V11)")
    ap.add_argument("--n", type=int, default=24, help="잴 횟수(자리 찾기 6번은 따로)")
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--port", default="", help="인터락 포트(엔터 = 자동으로 찾기)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    port = a.port or (None if a.screen else config.find_interlock_port()[0])
    if not a.screen and not port:
        print("❌ 인터락 포트를 못 찾음 — V10 · --port 로 지정하거나 --screen")
        return 1
    r = run(config.CAMERA_TCP_HOST, config.CAMERA_TCP_PORT, port, n_meas=a.n, interval=a.interval,
            out=a.out or None, screen=a.screen)
    if "error" in r:
        print(f"❌ {r['error']}")
        return 1
    f = lambda v: "—" if v is None else f"{v:.0f}"     # noqa: E731
    print(f"> {r['note']}")
    print(f"지연 ms — 중앙 {f(r['med'])} · 90% {f(r['p90'])} · 최소 {f(r['min'])} · 최대 {f(r['max'])} · n {r['n']}"
          f" · 못 찾음 {r['missed']} · ACK 중앙 {f(r['ack_med'])}")
    if r.get("warning"):
        print(f"⚠️ {r['warning']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
