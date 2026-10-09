"""연출 시험본 2단계 — 원본 1인칭 영상 + 검출(dets.json) + 실제 시스템 로그 사건 → 1920×1080 30fps 합성 영상.

python3 render.py <원본.mp4> <dets.json> <출력.mp4>

원칙: 연출은 보여 주는 방식만 바꾼다. 박스·손 점 = 같은 모델 재검출 그대로(위치 보간 없음),
      단계·누름 시각 = 실제 시스템 로그(1초 단위)를 영상 시각에 맞춘 것.
"""
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEMO = "/home/pi/sop-project/Rpi5/Demo"
sys.path.insert(0, DEMO)
import config  # noqa: E402
import frame_orient  # noqa: E402
import roi_zones  # noqa: E402

SRC, DETS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
W, H, FPS = 1920, 1080, 30
T_START, T_END = 7.5, 42.0          # 원본 영상 구간(초)
SRC_FPS = 15.0
VS = H / 1024.0                     # 원본 768×1024 → 810×1080
VW = int(round(768 * VS))
VX = (W - VW) // 2
RING = frame_orient.ring_px(768, 1024)

# ── 실제 시스템 로그(Demo/logs/20261006_212649_log.txt · 녹화 시작 21:26:53 = 0초) ──
#    1초 단위 기록이라 누름은 손끝이 박스 안에 든 구간(재검출) 안으로 맞췄다.
EV_START = 7.0                                     # 21:27:00 작업 시작 — 1단계
PRESSES = [(17.2, "B1"), (29.4, "B2")]             # 21:27:10 · 21:27:22 눌림
SUBS = [(17.2, 10.0, "플라즈마 클린"), (29.4, 10.0, "N2 퍼지")]   # [서브] 10초
ADVANCES = [(27.2, 2), (39.4, 3)]                  # 21:27:20 · 21:27:32 단계 진행
TOOL_WIN = (29.4, 39.4)                            # 공구 추론 워커 띄움 ~ 단계 진행
TOOL_GRIP = 38.4                                   # 21:27:31 찾기 → 쥠 (wrench)
STEPS = [("클린·가스차단", "B1"), ("펌프/퍼지", "B2"), ("전극 냉각", "B3"), ("챔버 벤트", "B4")]

# ── 색 (theme.py dark · config 박스 색) ──
def hex_bgr(h):
    h = h.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))


def hex_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


C = {k: v for k, v in dict(text="#e6e8ea", label="#c3c9cf", done="#7dffa8", current="#ffd75c",
                           warn="#ff8f2e", info="#5aa8ff", dim="#8a939c", todo="#c3c9cf").items()}
BOX = dict(config.DETECT_BOX_COLORS)
TOOL = dict(config.TOOL_BOX_COLORS)
KO_TOOL = {"wrench": "렌치", "driver": "드라이버", "pliers": "펜치"}

FD = "/home/pi/.local/share/fonts/Pretendard/Pretendard-"
_fonts, _texts = {}, {}


def font(size, weight="SemiBold"):
    k = (size, weight)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype(f"{FD}{weight}.otf", size)
    return _fonts[k]


def text_img(s, size, color, weight="SemiBold", shadow=True):
    """글자 → RGBA(numpy · BGRA 순). 그림자 3겹 대신 흐린 검은 후광 하나."""
    k = (s, size, color, weight, shadow)
    if k in _texts:
        return _texts[k]
    f = font(size, weight)
    l, t, r, b = f.getbbox(s)
    pad = 8 if shadow else 2
    w, h = r - l + pad * 2, b - t + pad * 2
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((pad - l, pad - t), s, font=f, fill=(0, 0, 0, 230))
        a = np.array(sh)
        a[..., 3] = cv2.GaussianBlur(a[..., 3], (0, 0), 3)
        img = Image.fromarray(a)
    ImageDraw.Draw(img).text((pad - l, pad - t), s, font=f, fill=hex_rgb(color) + (255,))
    arr = np.array(img)[..., [2, 1, 0, 3]].astype(np.float32)
    _texts[k] = (arr, pad)
    return _texts[k]


def paste(cv, s, x, y, size, color, alpha=1.0, weight="SemiBold", anchor="lt", shadow=True):
    if alpha <= 0.01:
        return 0
    arr, pad = text_img(s, size, color, weight, shadow)
    h, w = arr.shape[:2]
    if anchor == "ct":
        x -= w // 2 - pad
    elif anchor == "rt":
        x -= w - pad
    x0, y0 = int(x) - pad, int(y) - pad
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if xa >= xb or ya >= yb:
        return w - 2 * pad
    sub = arr[ya - y0:yb - y0, xa - x0:xb - x0]
    a = sub[..., 3:4] / 255.0 * alpha
    roi = cv[ya:yb, xa:xb]
    roi[:] = roi * (1 - a) + sub[..., :3] * a
    return w - 2 * pad


def text_w(s, size, weight="SemiBold"):
    l, _, r, _ = font(size, weight).getbbox(s)
    return r - l


def blend(cv, x0, y0, x1, y1, alpha, fn, blur=0):
    """ROI 복사본에 그린 뒤 alpha 로 섞는다. blur>0 이면 그린 것만 번지게(빛남)."""
    x0, y0, x1, y1 = max(int(x0), 0), max(int(y0), 0), min(int(x1), W), min(int(y1), H)
    if alpha <= 0.01 or x0 >= x1 or y0 >= y1:
        return
    roi = cv[y0:y1, x0:x1]
    if blur:
        layer = np.zeros_like(roi)
        fn(layer, x0, y0)
        layer = cv2.GaussianBlur(layer, (0, 0), blur)
        roi[:] = np.minimum(roi + layer * alpha, 255)
        return
    tmp = roi.copy()
    fn(tmp, x0, y0)
    roi[:] = roi * (1 - alpha) + tmp * alpha


def rrect(img, x0, y0, x1, y1, r, color, thick=-1):
    x0, y0, x1, y1, r = int(x0), int(y0), int(x1), int(y1), int(r)
    if thick < 0:
        cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), color, -1, cv2.LINE_AA)
        cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), color, -1, cv2.LINE_AA)
        for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
            cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA)
    else:
        for (a, b) in (((x0 + r, y0), (x1 - r, y0)), ((x0 + r, y1), (x1 - r, y1)),
                       ((x0, y0 + r), (x0, y1 - r)), ((x1, y0 + r), (x1, y1 - r))):
            cv2.line(img, a, b, color, thick, cv2.LINE_AA)
        for cx, cy, ang in ((x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270), (x0 + r, y1 - r, 90), (x1 - r, y1 - r, 0)):
            cv2.ellipse(img, (cx, cy), (r, r), ang, 0, 90, color, thick, cv2.LINE_AA)


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def eo(t):            # ease-out cubic
    t = clamp(t)
    return 1 - (1 - t) ** 3


def eob(t):           # ease-out back (살짝 튀어나왔다 자리 잡기)
    t = clamp(t)
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def fade(now, t_in, d_in, t_out=None, d_out=0.3):
    a = eo((now - t_in) / d_in) if d_in > 0 else float(now >= t_in)
    if t_out is not None:
        a *= 1 - eo((now - t_out) / d_out)
    return a


def V(x, y):          # 원본 좌표 → 화면
    return VX + x * VS, y * VS


# ── 배경 ──
BG = np.zeros((H, W, 3), np.float32)
g = np.linspace(0, 1, H)[:, None]
BG[:] = (np.array(hex_bgr("#0a0d12")) * (1 - g) + np.array(hex_bgr("#121821")) * g)[:, None, :][:, 0, :][:, None, :]
for x in range(0, W, 40):
    BG[:, x] += 6
for y in range(0, H, 40):
    BG[y, :] += 6

HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
              (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]
DEPTH = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 1, 6: 2, 7: 3, 8: 4, 9: 1, 10: 2, 11: 3, 12: 4, 13: 1, 14: 2, 15: 3,
         16: 4, 17: 1, 18: 2, 19: 3, 20: 4}

rows = {r["f"]: r for r in json.load(open(DETS))["rows"]}
cap = cv2.VideoCapture(SRC)
f_first = int(T_START * SRC_FPS)
cap.set(cv2.CAP_PROP_POS_FRAMES, f_first)
cur_f, cur_img = f_first - 1, None

ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                       "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                       "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)

# 상태(연출 타이밍) — 클래스가 0.7초 넘게 안 보이다 다시 나오면 다시 그려지는 연출
appear, last_seen = {}, {}
hand_appear, hand_last = None, -9
INTRO_END, SCAN0, SCAN1, UI_IN = 2.5, 2.5, 3.7, 3.0     # 구간 기준 시각(c)

n_out = int((T_END - T_START) * FPS)
STILLS = {int(x) for x in os.environ.get("STILLS", "").split(",") if x}
for i in range(n_out):
    c = i / FPS                       # 구간 시각
    t = T_START + c                   # 원본 영상 시각(로그 시각과 같은 축)
    f = f_first + int(c * SRC_FPS)
    while cur_f < f:
        ok, img = cap.read()
        if not ok:
            break
        cur_f, cur_img = cur_f + 1, img
    row = rows.get(f, {"btn": [], "tool": [], "hand": None})

    cv = BG * fade(c, INTRO_END, 1.0)
    vid = cv2.resize(cur_img, (VW, H), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    cv[:, VX:VX + VW] = vid
    ui = fade(c, UI_IN, 0.9)

    # 영상 가장자리 선
    if ui > 0:
        blend(cv, VX - 2, 0, VX + VW + 2, H, 0.35 * ui,
              lambda im, ox, oy: (cv2.line(im, (VX - ox - 1, 0), (VX - ox - 1, H), (255, 255, 255), 1),
                                  cv2.line(im, (VX + VW - ox, 0), (VX + VW - ox, H), (255, 255, 255), 1)))

    # 현재 단계 · 진행 중 작업
    step = 0 if t < EV_START else 1
    t_step = EV_START
    for ta, s in ADVANCES:
        if t >= ta:
            step, t_step = s, ta
    want = STEPS[step - 1][1] if step else None
    sub = next(((ts, d, n) for ts, d, n in SUBS if ts <= t < ts + d), None)

    # 손끝 → 구역(런타임 규칙 roi_zones 그대로)
    btn_boxes = [(b[0], *b[2:6]) for b in row["btn"]]
    hand = row["hand"]
    zone = (None, None)
    if hand is not None:
        zone = roi_zones.zone_at_point(hand[8][0], hand[8][1], btn_boxes, RING)

    # ── 스캔 선 + 박스 ──
    scan_y = H * eo((c - SCAN0) / (SCAN1 - SCAN0)) if c >= SCAN0 else -1
    for kind, dets in (("btn", row["btn"]), ("tool", row["tool"] if TOOL_WIN[0] <= t < TOOL_WIN[1] else [])):
        for name, score, x1, y1, x2, y2 in dets:
            key = (kind, name)
            X1, Y1 = V(x1, y1)
            X2, Y2 = V(x2, y2)
            if c < SCAN0 or (c < SCAN1 and Y1 > scan_y):
                continue
            if key not in appear or t - last_seen.get(key, -9) > 0.7:
                appear[key] = t
            last_seen[key] = t
            k = eo((t - appear[key]) / 0.35)
            col = hex_bgr(TOOL[name] if kind == "tool" else BOX[name])
            bw, bh = X2 - X1, Y2 - Y1
            L = min(bw, bh) * 0.32 * k
            z_lv = zone[1] if zone[0] == name and kind == "btn" else 0
            is_want = kind == "btn" and name == want and sub is None
            if is_want and k >= 1:          # 다음 누를 버튼 — 숨 쉬듯 빛남
                br = 0.55 + 0.35 * math.sin(t * 2 * math.pi / 1.4)
                blend(cv, X1 - 40, Y1 - 40, X2 + 40, Y2 + 40, br,
                      lambda im, ox, oy: cv2.rectangle(im, (int(X1 - ox), int(Y1 - oy)), (int(X2 - ox), int(Y2 - oy)), col, 6, cv2.LINE_AA),
                      blur=9)
            if z_lv == 2:                   # 손끝이 박스 안
                blend(cv, X1, Y1, X2, Y2, 0.22,
                      lambda im, ox, oy: cv2.rectangle(im, (int(X1 - ox), int(Y1 - oy)), (int(X2 - ox), int(Y2 - oy)), col, -1))
            frame_a = (0.9 if z_lv else 0.38) * k
            blend(cv, X1 - 4, Y1 - 4, X2 + 5, Y2 + 5, frame_a,
                  lambda im, ox, oy: cv2.rectangle(im, (int(X1 - ox), int(Y1 - oy)), (int(X2 - ox), int(Y2 - oy)), col, 2 if z_lv else 1, cv2.LINE_AA))

            def corners(im, ox, oy):
                for cx, cy, sx, sy in ((X1, Y1, 1, 1), (X2, Y1, -1, 1), (X1, Y2, 1, -1), (X2, Y2, -1, -1)):
                    p = (int(cx - ox), int(cy - oy))
                    cv2.line(im, p, (int(cx - ox + sx * L), int(cy - oy)), col, 4, cv2.LINE_AA)
                    cv2.line(im, p, (int(cx - ox), int(cy - oy + sy * L)), col, 4, cv2.LINE_AA)
            blend(cv, X1 - 6, Y1 - 6, X2 + 7, Y2 + 7, 1.0, corners)
            la = eo((t - appear[key] - 0.25) / 0.25)
            label = (KO_TOOL.get(name, name) if kind == "tool" else name) + f"  {score:.2f}"
            lw = text_w(label, 19)
            ly = Y1 - 34 if Y1 > 40 else Y2 + 8
            blend(cv, X1, ly, X1 + lw + 20, ly + 28, 0.78 * la,
                  lambda im, ox, oy: rrect(im, X1 - ox, ly - oy, X1 + lw + 19 - ox, ly + 27 - oy, 8, (16, 12, 10)))
            paste(cv, label, X1 + 10, ly + 4, 19, TOOL[name] if kind == "tool" else BOX[name], la, "Bold", shadow=False)

    if SCAN0 <= c < SCAN1 + 0.15:           # 스캔 선(빛남 + 지나간 자리 옅은 격자)
        sa = 1 - eo((c - SCAN1) / 0.15) if c > SCAN1 else 1.0
        sy = int(min(scan_y, H - 2))
        blend(cv, VX, 0, VX + VW, sy, 0.10 * sa,
              lambda im, ox, oy: [cv2.line(im, (x - ox, 0), (x - ox, sy), (255, 220, 120), 1) for x in range(VX, VX + VW, 36)] and None)
        blend(cv, VX, sy - 40, VX + VW, sy + 40, 1.0 * sa,
              lambda im, ox, oy: cv2.line(im, (0, sy - oy), (VW, sy - oy), (255, 220, 120), 4), blur=10)
        blend(cv, VX, sy - 2, VX + VW, sy + 3, 0.95 * sa,
              lambda im, ox, oy: cv2.line(im, (0, sy - oy), (VW, sy - oy), (255, 245, 210), 2, cv2.LINE_AA))

    # ── 손 21점(나타날 때 손목부터 뼈대가 뻗어 나감) ──
    if hand is not None and c >= UI_IN:
        if t - hand_last > 0.5:
            hand_appear = t
        hand_last = t
        k = clamp((t - hand_appear) / 0.4)
        P = [V(x, y) for x, y in hand]

        def bones(im, ox, oy):
            for a, b in HAND_EDGES:
                d = DEPTH[b]
                kk = clamp(k * 4 - (d - 1))
                if kk <= 0:
                    continue
                pa, pb = P[a], P[b]
                e = (pa[0] + (pb[0] - pa[0]) * kk, pa[1] + (pb[1] - pa[1]) * kk)
                cv2.line(im, (int(pa[0] - ox), int(pa[1] - oy)), (int(e[0] - ox), int(e[1] - oy)), (255, 255, 255), 2, cv2.LINE_AA)
        xs, ys = [p[0] for p in P], [p[1] for p in P]
        bx0, by0, bx1, by1 = min(xs) - 30, min(ys) - 30, max(xs) + 30, max(ys) + 30
        blend(cv, bx0, by0, bx1, by1, 0.8, bones)

        def joints(im, ox, oy):
            for j, (x, y) in enumerate(P):
                kk = eob(k * 4 - (DEPTH[j] - 1)) if k < 1 else 1.0
                r = max(0, 5 * kk)
                if r > 0.5:
                    cv2.circle(im, (int(x - ox), int(y - oy)), int(round(r)), hex_bgr(C["info"]), -1, cv2.LINE_AA)
        blend(cv, bx0, by0, bx1, by1, 1.0, joints)
        tx, ty = P[8]
        pr = 13 + 3 * math.sin(t * 2 * math.pi / 0.9)
        blend(cv, tx - 30, ty - 30, tx + 30, ty + 30, k,
              lambda im, ox, oy: cv2.circle(im, (int(tx - ox), int(ty - oy)), int(pr), hex_bgr(C["current"]), 3, cv2.LINE_AA))

    # ── 누름 파동 ──
    for tp, name in PRESSES:
        dt = t - tp
        if 0 <= dt < 1.0:
            box = next((b for b in rows.get(int(tp * SRC_FPS), row)["btn"] if b[0] == name), None)
            if box:
                cx, cy = V((box[2] + box[4]) / 2, (box[3] + box[5]) / 2)
                col = hex_bgr(BOX[name])
                for lag in (0.0, 0.18):
                    q = clamp((dt - lag) / 0.7)
                    if 0 < q < 1:
                        r = 25 + 140 * eo(q)
                        blend(cv, cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, 1 - q,
                              lambda im, ox, oy: cv2.circle(im, (int(cx - ox), int(cy - oy)), int(r), col, 4, cv2.LINE_AA))

    # ── 왼쪽 패널: 작업 순서 ──
    if ui > 0:
        dx = -70 * (1 - eo((c - UI_IN) / 0.8))
        px0, py0, pw = 48 + dx, 170, 460
        blend(cv, px0, py0, px0 + pw, py0 + 480, 0.85 * ui,
              lambda im, ox, oy: rrect(im, px0 - ox, py0 - oy, px0 + pw - ox, py0 + 480 - oy, 18, (24, 19, 15)))
        blend(cv, px0, py0, px0 + pw + 1, py0 + 481, 0.25 * ui,
              lambda im, ox, oy: rrect(im, px0 - ox, py0 - oy, px0 + pw - ox, py0 + 480 - oy, 18, (255, 255, 255), 1))
        paste(cv, "작업 순서", px0 + 28, py0 + 26, 18, C["label"], ui, "Medium")
        paste(cv, "PECVD 정비(PM)", px0 + 28, py0 + 54, 30, C["text"], ui, "Bold")
        RY0, RH = py0 + 120, 86
        # 현재 단계 막대 — 단계가 바뀌면 미끄러져 내려간다
        if step:
            prev = step - 1 if step > 1 else 1
            yb = RY0 + RH * ((prev - 1) + (step - prev) * eo((t - t_step) / 0.45))
            blend(cv, px0 + 14, yb + 4, px0 + pw - 14, yb + RH - 4, 0.9 * ui,
                  lambda im, ox, oy: rrect(im, px0 + 14 - ox, yb + 4 - oy, px0 + pw - 14 - ox, yb + RH - 4 - oy, 12, (40, 54, 66)))
            blend(cv, px0 + 14, yb + 4, px0 + 20, yb + RH - 4, ui,
                  lambda im, ox, oy: cv2.rectangle(im, (0, 6), (5, RH - 14), hex_bgr(C["current"]), -1))
        for j, (nm, bn) in enumerate(STEPS):
            sj = j + 1
            ra = ui * eo((c - UI_IN - 0.15 - 0.08 * j) / 0.5)
            rdx = -30 * (1 - ra)
            ry = RY0 + RH * j
            state = "done" if step > sj else ("current" if step == sj else "todo")
            col = C[state]
            cx, cy = px0 + 52 + rdx, ry + RH / 2
            # 완료 순간 초록 번쩍
            t_done = next((ta for ta, s in ADVANCES if s == sj + 1), None)
            if t_done is not None and 0 <= t - t_done < 0.8:
                blend(cv, px0 + 14, ry + 4, px0 + pw - 14, ry + RH - 4, 0.45 * (1 - (t - t_done) / 0.8),
                      lambda im, ox, oy: rrect(im, px0 + 14 - ox, ry + 4 - oy, px0 + pw - 14 - ox, ry + RH - 4 - oy, 12, hex_bgr(C["done"])))
            if state == "done":
                blend(cv, cx - 18, cy - 18, cx + 18, cy + 18, ra,
                      lambda im, ox, oy: (cv2.circle(im, (int(cx - ox), int(cy - oy)), 15, hex_bgr(C["done"]), -1, cv2.LINE_AA),
                                          cv2.polylines(im, [np.array([[cx - ox - 7, cy - oy], [cx - ox - 2, cy - oy + 6], [cx - ox + 8, cy - oy - 6]], np.int32)],
                                                        False, (20, 30, 20), 3, cv2.LINE_AA)))
            else:
                rr = 15 + (2 * math.sin(t * 2 * math.pi / 1.4) if state == "current" else 0)
                blend(cv, cx - 20, cy - 20, cx + 20, cy + 20, ra,
                      lambda im, ox, oy: cv2.circle(im, (int(cx - ox), int(cy - oy)), int(rr), hex_bgr(col), 3, cv2.LINE_AA))
            paste(cv, f"{sj}단계", px0 + 84 + rdx, ry + 18, 17, C["label"] if state != "current" else C["current"], ra, "Medium")
            paste(cv, nm, px0 + 84 + rdx, ry + 41, 25, C["text"] if state != "todo" else C["dim"], ra, "Bold")
            chip_x = px0 + pw - 80 + rdx
            blend(cv, chip_x, ry + 26, chip_x + 54, ry + 60, 0.95 * ra,
                  lambda im, ox, oy: rrect(im, chip_x - ox, ry + 26 - oy, chip_x + 54 - ox, ry + 60 - oy, 9, hex_bgr(BOX[bn])))
            paste(cv, bn, chip_x + 27, ry + 33, 18, "#111418", ra, "Bold", anchor="ct", shadow=False)

        # 상단 머리글
        paste(cv, "SOP 가디언", 48 + dx, 52, 34, C["text"], ui, "ExtraBold")
        paste(cv, "Vision AI 순서 위반 감지 · 1인칭 시연", 48 + dx, 98, 18, C["label"], ui, "Medium")
        # 합성 표기(정직성 문구)
        paste(cv, "※ 박스·손 점·화면 표시는 촬영 뒤 같은 AI 모델로 다시 그린 합성입니다.", 48 + dx, 990, 16, C["label"], ui, "Regular")
        paste(cv, "   단계·버튼 누름 시각은 실제 시스템 기록(1초 단위)을 따릅니다.", 48 + dx, 1016, 16, C["label"], ui, "Regular")

    # ── 오른쪽 패널: 상태 카드 ──
    if ui > 0:
        dx = 70 * (1 - eo((c - UI_IN - 0.1) / 0.8))
        qx0, qw = W - 48 - 460 + dx, 460
        paste(cv, "AI 화면 합성 연출 · 시험본", W - 48 + dx, 60, 18, C["label"], ui, "Medium", anchor="rt")

        def card(y0, h, title, k_in):
            a = ui * eo((c - UI_IN - 0.2 - k_in) / 0.5)
            blend(cv, qx0, y0, qx0 + qw, y0 + h, 0.85 * a,
                  lambda im, ox, oy: rrect(im, qx0 - ox, y0 - oy, qx0 + qw - ox, y0 + h - oy, 16, (24, 19, 15)))
            blend(cv, qx0, y0, qx0 + qw + 1, y0 + h + 1, 0.22 * a,
                  lambda im, ox, oy: rrect(im, qx0 - ox, y0 - oy, qx0 + qw - ox, y0 + h - oy, 16, (255, 255, 255), 1))
            paste(cv, title, qx0 + 24, y0 + 18, 17, C["label"], a, "Medium")
            return a

        a = card(170, 96, "시스템 상태", 0.0)
        live = t >= EV_START
        dot = hex_bgr(C["done"] if live else C["dim"])
        pul = 0.6 + 0.4 * math.sin(t * 2 * math.pi / 1.2) if live else 1
        blend(cv, qx0 + 24, 218, qx0 + 46, 240, a * pul,
              lambda im, ox, oy: cv2.circle(im, (int(qx0 + 34 - ox), int(229 - oy)), 8, dot, -1, cv2.LINE_AA))
        paste(cv, "감시 중" if live else "작업 대기", qx0 + 54, 214, 26, C["done"] if live else C["text"], a, "Bold")

        a = card(282, 96, "손 위치", 0.08)
        if hand is None:
            hv, hc = "보이지 않음", C["dim"]
        elif zone[1] == 2:
            hv, hc = f"{zone[0]} 위 (박스 안)", C["current"]
        elif zone[1] == 1:
            hv, hc = f"{zone[0]} 근처", C["info"]
        else:
            hv, hc = "보임 · 버튼 밖", C["text"]
        paste(cv, hv, qx0 + 24, 326, 26, hc, a, "Bold")

        a = card(394, 130, "진행 중 작업", 0.16)
        if sub:
            ts, d, nm = sub
            q = clamp((t - ts) / d)
            ka = eo((t - ts) / 0.4)
            paste(cv, nm, qx0 + 24, 438, 26, C["text"], a * ka, "Bold")
            paste(cv, f"{min(t - ts, d):.1f} / {d:.0f}초", qx0 + qw - 24, 442, 20, C["current"], a * ka, "SemiBold", anchor="rt")
            gx0, gy0, gx1 = qx0 + 24, 486, qx0 + qw - 24
            blend(cv, gx0, gy0, gx1, gy0 + 14, a * ka, lambda im, ox, oy: rrect(im, 0, 0, gx1 - gx0 - 1, 13, 7, (10, 8, 6)))
            gw = (gx1 - gx0) * q
            if gw > 14:
                def gauge(im, ox, oy):
                    ramp = np.linspace(0, 1, int(gw))[None, :, None]
                    col = np.array(hex_bgr("#e8a000"), np.float32) * (1 - ramp) + np.array(hex_bgr("#ffd75c"), np.float32) * ramp
                    m = np.zeros((14, int(gw), 3), np.float32)
                    rrect(m, 0, 0, int(gw) - 1, 13, 7, (1, 1, 1))
                    im[0:14, 0:int(gw)] = im[0:14, 0:int(gw)] * (1 - m) + col * m
                blend(cv, gx0, gy0, gx1, gy0 + 14, a * ka, gauge)
        else:
            paste(cv, "—", qx0 + 24, 438, 26, C["dim"], a, "Bold")

        a = card(540, 96, "공구 확인", 0.24)
        if TOOL_WIN[0] <= t < TOOL_WIN[1]:
            ka = eo((t - TOOL_WIN[0]) / 0.4)
            if t < TOOL_GRIP:
                dots = "." * (1 + int(t * 3) % 3)
                paste(cv, "렌치 찾는 중" + dots, qx0 + 24, 584, 26, C["info"], a * ka, "Bold")
            else:
                if t - TOOL_GRIP < 0.7:
                    blend(cv, qx0, 540, qx0 + qw, 636, 0.35 * (1 - (t - TOOL_GRIP) / 0.7),
                          lambda im, ox, oy: rrect(im, qx0 - ox, 540 - oy, qx0 + qw - ox, 636 - oy, 16, hex_bgr(C["done"])))
                paste(cv, "렌치 쥠 · 확인", qx0 + 24, 584, 26, C["done"], a * eob((t - TOOL_GRIP) / 0.4), "Bold")
        else:
            paste(cv, "이 단계엔 없음" if step != 2 else "—", qx0 + 24, 584, 26, C["dim"], a, "Bold")

        a = card(652, 96, "AI 인식 (이 화면)", 0.32)
        nb, nt = len(row["btn"]), len(row["tool"]) if TOOL_WIN[0] <= t < TOOL_WIN[1] else 0
        paste(cv, f"버튼 {nb}  ·  공구 {nt}  ·  손 {'21점' if hand else '없음'}", qx0 + 24, 696, 24, C["text"], a, "Bold")

        paste(cv, "1인칭 안경 카메라", VX + 20, 22, 18, C["text"], ui, "SemiBold")

    # ── 알림(아래에서 올라옴) ──
    toasts = [(EV_START, "작업 시작 · 1단계 클린·가스차단", C["info"])]
    toasts += [(tp, f"{n} 눌림 · 순서 맞음", C["done"]) for tp, n in PRESSES]
    toasts += [(ta, f"{s}단계 시작 · {STEPS[s - 1][0]}", C["current"]) for ta, s in ADVANCES]
    toasts += [(TOOL_GRIP, "공구 확인 · 렌치를 쥐었습니다", C["done"])]
    for tt, msg, col in toasts:
        dt = t - tt
        if 0 <= dt < 2.4:
            a = eo(dt / 0.3) * (1 - eo((dt - 2.0) / 0.4))
            yy = 930 + 30 * (1 - eo(dt / 0.35))
            tw = text_w(msg, 24, "Bold")
            bx0, bx1 = W // 2 - tw // 2 - 44, W // 2 + tw // 2 + 26
            blend(cv, bx0, yy, bx1, yy + 54, 0.85 * a,
                  lambda im, ox, oy: rrect(im, bx0 - ox, yy - oy, bx1 - ox, yy + 53 - oy, 27, (20, 16, 12)))
            blend(cv, bx0, yy, bx1 + 1, yy + 55, 0.7 * a,
                  lambda im, ox, oy: rrect(im, bx0 - ox, yy - oy, bx1 - ox, yy + 53 - oy, 27, hex_bgr(col), 2))
            blend(cv, bx0 + 16, yy + 18, bx0 + 36, yy + 38, a,
                  lambda im, ox, oy: cv2.circle(im, (int(bx0 + 26 - ox), int(yy + 27 - oy)), 7, hex_bgr(col), -1, cv2.LINE_AA))
            paste(cv, msg, bx0 + 44, yy + 13, 24, C["text"], a, "Bold", shadow=False)

    # ── 여는 제목 · 끝 어둡게 ──
    ta = fade(c, 0.3, 0.6, 2.0, 0.5)
    if ta > 0:
        blend(cv, VX, 420, VX + VW, 640, 0.55 * ta, lambda im, ox, oy: cv2.rectangle(im, (0, 0), (VW, 220), (0, 0, 0), -1))
        paste(cv, "SOP 가디언", W // 2, 455, 64, "#ffffff", ta, "ExtraBold", anchor="ct")
        paste(cv, "AI 화면 합성 연출 시험", W // 2, 555, 26, C["label"], ta, "Medium", anchor="ct")
    end = T_END - T_START
    if c > end - 0.8:
        cv *= 1 - eo((c - (end - 0.8)) / 0.8)

    out8 = np.clip(cv, 0, 255).astype(np.uint8)
    if i in STILLS:
        cv2.imwrite(os.path.join(os.path.dirname(OUT), f"still_{i:04d}.jpg"), out8, [cv2.IMWRITE_JPEG_QUALITY, 88])
    ff.stdin.write(out8.tobytes())
    if i % 150 == 0:
        print(i, "/", n_out, flush=True)

ff.stdin.close()
ff.wait()
print("done", OUT, os.path.getsize(OUT))
