"""발표용 차트 8종 생성 — 표준 라이브러리만 (인라인 SVG).

왜 이 방식인가:
    파이에 matplotlib 이 없고, `db_report.py` 가 이미 "표준 라이브러리 + 인라인 SVG"
    로 리포트를 만드는 선례가 있다. 같은 방식을 따른다.

만드는 것 (전부 로컬 데이터·추가 촬영 불필요):
    01 파랑스티커  ← test/raw/  ESP32 원본 프레임 2장 (§10.12)
    02 채점        ← test/logs/score_*_console_v2.csv (§10.20)
    03 HOI 구조    ← 작도 (§10.21)
    04 체류분포    ← test/hoi.db  palm_frames + presses
    05 버튼y       ← test/hoi.db  (판정 규칙은 `hoi_metrics.py` 단일 출처)
    06 오경보      ← §10.31 측정값을 1분 축에 옮긴 도식
    07 FPS         ← test/logs/20260810_*_fps-*_perf_log.csv (§10.34)
    08 tool_v3     ← ~/lab/tool-detect/tool_live_shots/ (§10.41·§10.42, repo 밖)

🔴 지표 이름을 섞지 않는다 — 각 차트의 부제에 **무엇을 잰 값인지·조건**을 박아 넣는다.
   특히 2)는 §10.23 의 57%/14% 와 **다른 모집단**(전체 눌림 407건, 22세션 통합)이므로
   그 수치의 재현이 아니다.

사용:
    python3 test/slide_charts.py [--out <디렉터리>]

PNG 로 굽기 (파이엔 rsvg/cairosvg 가 없어 헤드리스 크로미움을 쓴다):
    chromium --headless --disable-gpu --no-sandbox --hide-scrollbars \
             --force-device-scale-factor=2 --window-size=1616,916 \
             --screenshot=out.png file://$PWD/01_....svg
    # 그 뒤 가장자리 16px 를 잘라내면 정확히 3200x1800 이 된다.
    # 🔴 1600x900 으로 찍으면 body 기본 여백(8px) 때문에 **아래쪽 글이 잘린다** —
    #    여백만큼 키워 찍고 잘라내는 것이 유일하게 확실했다.
"""

import argparse
import base64
import csv
import glob
import os
import re
import statistics
import sys
import unicodedata

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _TEST_DIR)

import hoi_metrics as M  # noqa: E402

W, H = 1600, 900
FONT = "NanumGothic, 나눔고딕, sans-serif"
INK = "#1a1a1a"
MUTED = "#6b7280"
GRID = "#e5e7eb"
ACCENT = "#2563eb"
WARN = "#dc2626"
OK = "#059669"


# ──────────────────────────────────────────────────────────────── SVG 헬퍼
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def txt(x, y, s, size=20, fill=INK, anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">'
            f'{_esc(s)}</text>')


def rect(x, y, w, h, fill, rx=0, opacity=1.0):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" '
            f'height="{max(h, 0):.1f}" fill="{fill}" rx="{rx}" opacity="{opacity}"/>')


def line(x1, y1, x2, y2, stroke=GRID, width=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>')


def image(path, x, y, w, h, fit="slice"):
    """PNG 을 base64 로 박아 넣는다 — SVG 를 자립형으로 유지(외부 파일 의존 금지).

    🔴 `fit="slice"` 는 넘치는 쪽을 잘라낸다 — **잘리면 안 되는 증거 사진은 "meet"**.
    (검정 B4 가 프레임 아래쪽에 있어 slice 로는 화면 밖으로 나갔다.)
    """
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (f'<image x="{x}" y="{y}" width="{w}" height="{h}" '
            f'preserveAspectRatio="xMidYMid {fit}" '
            f'href="data:image/png;base64,{b64}"/>')


def svg_page(title, subtitle, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">'
            + rect(0, 0, W, H, "#ffffff")
            + txt(70, 78, title, 40, INK, weight="bold")
            + txt(70, 118, subtitle, 22, MUTED)
            + body + "</svg>")


def write(out_dir, name, content):
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("wrote", path)
    return path


# ─────────────────────────────────────────────────── 1) console_v2 정량 채점
def chart_score(out_dir):
    src = sorted(glob.glob(os.path.join(_TEST_DIR, "logs", "score_*_console_v2.csv")))
    if not src:
        raise SystemExit("score_*.csv 없음")
    ap, conf, meta = {}, {}, {}
    with open(src[-1], encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m, c, v = row["metric"], row["class"], row["value"]
            if m == "AP50" and c:
                ap[c] = float(v)
            elif m == "confusion":
                conf[c] = int(v)
            elif not c:
                meta[m] = v

    b = []
    x0, y0, bw, gap, hmax = 120, 620, 130, 60, 380
    b.append(txt(70, 168, "클래스별 AP50", 28, INK, weight="bold"))
    for i in range(6):
        gy = y0 - hmax * i / 5
        b.append(line(x0 - 20, gy, x0 + 5 * (bw + gap), gy))
        b.append(txt(x0 - 32, gy + 7, f"{i / 5:.1f}", 16, MUTED, anchor="end"))
    for i, cls in enumerate(["B1", "B2", "B3", "B4", "EMO"]):
        v = ap.get(cls, 0.0)
        x = x0 + i * (bw + gap)
        color = ACCENT if cls != "B4" else OK
        b.append(rect(x, y0 - hmax * v, bw, hmax * v, color, rx=4))
        b.append(txt(x + bw / 2, y0 - hmax * v - 14, f"{v:.3f}", 26, color,
                     anchor="middle", weight="bold"))
        b.append(txt(x + bw / 2, y0 + 36, cls, 26, INK, anchor="middle"))
    b.append(txt(x0, y0 + 92,
                 f"mAP50 {meta.get('mAP50', '?')} · test {meta.get('images', '?')}장 "
                 f"· conf 0.65", 24, MUTED))
    b.append(txt(x0, y0 + 132, "🔵 B4 = v1 이 실추론에서 0회 잡던 클래스", 24, OK))

    # 혼동행렬
    cx, cy, cell = 1010, 210, 74
    labels = ["B1", "B2", "B3", "B4", "EMO"]
    cols = labels + ["미검출"]
    b.append(txt(cx, 168, "혼동행렬 (정답 → 예측)", 28, INK, weight="bold"))
    for j, c in enumerate(cols):
        b.append(txt(cx + 110 + j * cell + cell / 2, cy - 12, c, 18, MUTED,
                     anchor="middle"))
    for i, r in enumerate(labels):
        yy = cy + i * cell
        b.append(txt(cx + 100, yy + cell / 2 + 7, r, 21, INK, anchor="end"))
        for j, c in enumerate(cols):
            n = conf.get(f"{r}->{c}", 0)
            xx = cx + 110 + j * cell
            diag = (r == c)
            fill = "#dbeafe" if diag and n else ("#fee2e2" if n else "#fafafa")
            b.append(rect(xx, yy, cell - 4, cell - 4, fill, rx=4))
            if n:
                b.append(txt(xx + (cell - 4) / 2, yy + cell / 2 + 8, n, 23,
                             INK if diag else WARN, anchor="middle",
                             weight="bold" if not diag else "normal"))
    b.append(txt(cx, cy + 5 * cell + 52,
                 "오분류 1건 · 배경 오검출 0건", 24, INK))

    return write(out_dir, "02_console_v2_채점.svg", svg_page(
        "console_v2 정량 채점 — B4 AP50 0.997",
        "모조 콘솔·클린룸 형광등 · test 113장 전량 수동 라벨 · 누출 0 (§10.20)",
        "".join(b)))


# ─────────────────────────────────────────────── 2) 눌림 직전 체류 시간 분포
def _dwell_samples(con):
    out = []
    for sid in M.session_ids(con):
        series = M.load_series(con, sid)
        if not series:
            continue
        ts = {r["frame"]: r["ts"] for r in con.execute(
            "SELECT frame, ts FROM palm_frames WHERE session_id=? AND palm_thresh=?",
            (sid, M.PALM_THRESH))}
        for p in M.load_presses(con, sid):
            f, run = p["frame"], []
            while series.get(f) == p["button"] and f in ts:
                run.append(f)
                f -= 1
            if run:
                out.append(ts[run[0]] - ts[run[-1]] if len(run) > 1 else 0.0)
    return out


def chart_dwell(out_dir):
    con = M.connect()
    dw = _dwell_samples(con)
    n = len(dw)
    step, nbin = 0.1, 12
    bins = [0] * (nbin + 1)
    for d in dw:
        bins[min(int(d / step), nbin)] += 1
    peak = max(bins)

    b = []
    x0, y0, plotw, hmax = 120, 640, 1080, 400
    bw = plotw / (nbin + 1)
    for i in range(5):
        gy = y0 - hmax * i / 4
        b.append(line(x0, gy, x0 + plotw, gy))
        b.append(txt(x0 - 16, gy + 7, int(peak * i / 4), 19, MUTED, anchor="end"))
    for i, cnt in enumerate(bins):
        x = x0 + i * bw
        lo = i * step
        color = MUTED if lo < 0.3 else ACCENT
        b.append(rect(x + 4, y0 - hmax * cnt / peak, bw - 8, hmax * cnt / peak,
                      color, rx=3))
        if i % 2 == 0:
            lab = f"{lo:.1f}" if i < nbin else f"{nbin * step:.1f}+"
            b.append(txt(x, y0 + 34, lab, 20, MUTED, anchor="middle"))
    b.append(txt(x0 + plotw / 2, y0 + 76, "눌림 직전 체류 시간 (초)", 24, MUTED,
                 anchor="middle"))
    b.append(txt(x0 - 16, y0 - hmax - 26, "눌림 건수", 20, MUTED, anchor="start"))

    for thr, color, note in ((0.3, OK, "채택 0.3초"), (0.5, WARN, "구 정본 0.5초")):
        x = x0 + (thr / step) * bw
        pct = 100 * sum(1 for d in dw if d >= thr) / n
        b.append(line(x, y0 - hmax - 10, x, y0, color, 3, dash="8 6"))
        b.append(txt(x + 12, y0 - hmax + 12, note, 25, color, weight="bold"))
        b.append(txt(x + 12, y0 - hmax + 48, f"{pct:.1f}% 포착", 25, color))

    med = statistics.median(dw)
    b.append(txt(x0, y0 + 124,
                 f"눌림 {n}건 · 22세션 통합 · 중앙값 {med:.2f}초", 24, INK))
    b.append(txt(x0, y0 + 160, "🔴 §10.23 과 모집단이 다른 별개 집계", 22, WARN))

    return write(out_dir, "04_체류시간_분포.svg", svg_page(
        "체류 임계 0.5초 → 0.3초",
        "hoi.db 22세션 전체 눌림 · 팜 임계 0.5 고정",
        "".join(b)))


# ───────────────────────────────────────── 3) 버튼 화면 y × 사전 감지 성공률
def chart_button_y(out_dir):
    con = M.connect()
    rows = []
    for sid in M.session_ids(con):
        series = M.load_series(con, sid)
        if not series:
            continue
        for p in M.load_presses(con, sid):
            if p["button_y"] is None:
                continue
            rows.append((p["button_y"],
                         M.capability_hit(series, p["frame"], p["button"])))

    edges = [(0, 120), (120, 200), (200, 280), (280, M.CLIFF_Y),
             (M.CLIFF_Y, 420), (420, 10 ** 6)]
    stats = []
    for lo, hi in edges:
        sub = [h for y, h in rows if lo <= y < hi]
        stats.append((lo, hi, len(sub),
                      100 * sum(sub) / len(sub) if sub else 0.0))

    b = []
    x0, y0, plotw, hmax = 130, 640, 1350, 400
    bw = plotw / len(stats)
    # 최적 띠 음영 (y 120~280 = 2·3번째 구간)
    b.append(rect(x0 + bw, y0 - hmax - 30, bw * 2, hmax + 30, OK, rx=6, opacity=0.08))
    b.append(txt(x0 + bw * 2, y0 - hmax - 46, "권장 운용 구간  y 120~280", 26, OK,
                 anchor="middle", weight="bold"))
    for i in range(5):
        gy = y0 - hmax * i / 4
        b.append(line(x0, gy, x0 + plotw, gy))
        b.append(txt(x0 - 16, gy + 7, f"{25 * i}%", 19, MUTED, anchor="end"))
    for i, (lo, hi, cnt, rate) in enumerate(stats):
        x = x0 + i * bw
        color = OK if rate >= 90 else (WARN if rate < 60 else ACCENT)
        b.append(rect(x + 18, y0 - hmax * rate / 100, bw - 36, hmax * rate / 100,
                      color, rx=5))
        b.append(txt(x + bw / 2, y0 - hmax * rate / 100 - 16, f"{rate:.1f}%", 30,
                     color, anchor="middle", weight="bold"))
        lab = f"{lo}~{hi}" if hi < 10 ** 5 else f"{lo}+"
        b.append(txt(x + bw / 2, y0 + 36, lab, 24, INK, anchor="middle"))
        b.append(txt(x + bw / 2, y0 + 66, f"n={cnt}", 20, MUTED, anchor="middle"))

    cliff_x = x0 + bw * 4
    b.append(line(cliff_x, y0 - hmax - 30, cliff_x, y0, WARN, 3, dash="8 6"))
    b.append(txt(cliff_x + 14, y0 - hmax + 6, f"절벽 y={M.CLIFF_Y}", 26, WARN,
                 weight="bold"))
    b.append(txt(cliff_x + 14, y0 - hmax + 42, "아래는 못 고친다", 23, WARN))

    tot = len(rows)
    b.append(txt(x0, y0 + 124, "가로축 = 버튼의 화면 속 세로 위치(px) — 작을수록 위쪽",
                 24, MUTED))
    b.append(txt(x0, y0 + 160,
                 f"세로축 = 사전 감지율 · 눌림 {tot}건 · 22세션 통합", 24, INK))

    return write(out_dir, "05_버튼y_사전감지율.svg", svg_page(
        "감지 성능을 가르는 변수는 자세가 아니라 버튼의 화면 속 높이",
        "사전 감지율 = 감지 성공 눌림 ÷ 전체 눌림 (프레임 검출률 아님)",
        "".join(b)))


# ───────────────────────────────────────────────── 4) B4 파랑 스티커 Before/After
_RAW = os.path.join(_TEST_DIR, "raw")
STICKER_BEFORE = os.path.join(_RAW, "20260710_173555_esp32", "f00050.png")
STICKER_AFTER = os.path.join(_RAW, "20260713_174153_esp32", "f00051.png")


def chart_sticker(out_dir):
    b = []
    iw, ih, iy = 560, 372, 192
    for i, (path, cap, sub, color) in enumerate((
            (STICKER_BEFORE, "BEFORE — 검정 B4", "07-10", WARN),
            (STICKER_AFTER, "AFTER — 🔵 파랑 스티커", "07-13 · 같은 콘솔", OK))):
        x = 130 + i * (iw + 220)
        b.append(rect(x - 6, iy - 6, iw + 12, ih + 12, color, rx=8))
        b.append(image(path, x, iy, iw, ih, fit="meet"))
        b.append(txt(x, iy - 26, cap, 30, color, weight="bold"))
        b.append(txt(x, iy + ih + 34, sub, 21, MUTED))

    y = iy + ih + 84
    b.append(txt(130, y, "B4 버튼만 바뀌었다 — 모델도 카메라도 그대로", 30, INK,
                 weight="bold"))

    # 채도 대비 막대
    by, bh, bx, bmax = y + 42, 36, 300, 860
    for i, (lab, v, color) in enumerate((("검정 B4", 9.1, WARN), ("파랑 B4", 98.0, OK))):
        yy = by + i * (bh + 22)
        b.append(txt(280, yy + bh - 10, lab, 24, INK, anchor="end"))
        b.append(rect(bx, yy, bmax * v / 100, bh, color, rx=5))
        b.append(txt(bx + bmax * v / 100 + 16, yy + bh - 10, f"ΔS {v}", 28, color,
                     weight="bold"))
    b.append(txt(130, by - 12, "채도 대비 10.8배", 22, MUTED))
    b.append(txt(bx, by + 2 * (bh + 22) + 30,
                 "블러·압축·축소·3중 복합 — 전부 ΔS 98 유지", 24, INK))

    return write(out_dir, "01_파랑스티커_전후.svg", svg_page(
        "B4 미검출 — 재학습이 아니라 스티커로 풀었다",
        "ESP32 원본 프레임 · §10.12 · 검정 버튼은 패널과 대비 15/255", "".join(b)))


# ─────────────────────────────────────────────────────────── 5) HOI 통합 구조
def chart_hoi(out_dir):
    b = []
    cy = 205
    for side, (title, color) in enumerate((("BEFORE", WARN), ("AFTER", OK))):
        x0 = 90 + side * 800
        b.append(txt(x0, cy - 38, title, 32, color, weight="bold"))
        b.append(rect(x0, cy, 660, 380, "#fafafa", rx=10))
        for i, name in enumerate(("버튼 검출 모델", "손 검출 모델")):
            bx = x0 + 40 + i * 300
            b.append(rect(bx, cy + 40, 260, 90, "#e8eefc", rx=8))
            b.append(txt(bx + 130, cy + 94, name, 24, INK, anchor="middle"))
            if side == 0:
                b.append(rect(bx, cy + 170, 260, 70, "#fde8e8", rx=8))
                b.append(txt(bx + 130, cy + 214, "자체 VDevice", 23, WARN,
                             anchor="middle"))
                b.append(line(bx + 130, cy + 130, bx + 130, cy + 170, MUTED, 3))
        if side == 0:
            b.append(rect(x0 + 40, cy + 290, 560, 70, "#fde8e8", rx=8))
            b.append(txt(x0 + 320, cy + 334, "NPU 를 다퉈 동시 실행 불가",
                         25, WARN, anchor="middle"))
        else:
            for i in range(2):
                b.append(line(x0 + 170 + i * 300, cy + 130, x0 + 330, cy + 200,
                              MUTED, 3))
            b.append(rect(x0 + 40, cy + 200, 560, 80, "#dcfce7", rx=8))
            b.append(txt(x0 + 320, cy + 250, "공유 스케줄러 (ROUND_ROBIN)", 25, OK,
                         anchor="middle"))
            b.append(rect(x0 + 40, cy + 310, 560, 70, "#dcfce7", rx=8))
            b.append(txt(x0 + 320, cy + 354, "버튼 + 손 동시 추론", 25, OK,
                         anchor="middle"))
    b.append(txt(770, cy + 230, "→", 60, MUTED, anchor="middle"))

    y = cy + 470
    b.append(txt(90, y, "합쳤더니 코드가 줄었다", 30, INK, weight="bold"))
    for i, (lab, val, color) in enumerate((("삭제", "− 81줄", OK), ("추가", "+ 15줄", MUTED))):
        b.append(txt(90 + i * 280, y + 56, f"{lab}  {val}", 34, color, weight="bold"))
    b.append(txt(740, y + 56, "MediaPipe 블록 4곳 → hand_tracker.py", 23, MUTED))
    b.append(txt(90, y + 106, "🔑 이 시점에 「감지」가 성립 — 이후는 성능 문제",
                 26, ACCENT))

    return write(out_dir, "03_HOI_통합구조.svg", svg_page(
        "HOI 통합 — 버튼과 손을 한 장치에서",
        "§10.21 · Rpi5 d9b5077 · 0953294",
        "".join(b)))


# ────────────────────────────────────────────────── 6) E2E 오경보 (부정 결과)
FALSE_ALARM_PER_MIN = 15.46   # §10.31 — 창 ON. 대조군(창 OFF) 15.32


def chart_false_alarm(out_dir):
    b = []
    x0, y0, w = 110, 400, 1380
    b.append(txt(x0, y0 - 140, f"{FALSE_ALARM_PER_MIN}", 110, WARN, weight="bold"))
    b.append(txt(x0 + 300, y0 - 152, "회 / 분", 44, WARN, weight="bold"))
    b.append(txt(x0 + 300, y0 - 104, "정상 작업 중 오경보", 28, MUTED))

    b.append(line(x0, y0, x0 + w, y0, MUTED, 3))
    n = int(round(FALSE_ALARM_PER_MIN))
    for i in range(n):
        x = x0 + w * (i + 0.5) / n
        b.append(line(x, y0 - 60, x, y0, WARN, 5))
        b.append(f'<circle cx="{x:.1f}" cy="{y0 - 66}" r="9" fill="{WARN}"/>')
    for s in range(0, 61, 10):
        x = x0 + w * s / 60
        b.append(line(x, y0, x, y0 + 12, MUTED, 2))
        b.append(txt(x, y0 + 44, f"{s}초", 21, MUTED, anchor="middle"))
    b.append(txt(x0, y0 + 108, "= 약 4초에 한 번 차단", 40, INK, weight="bold"))

    y = y0 + 170
    for i, (head, body_txt, color) in enumerate((
            ("층1 · 경고", "알리기만 한다 — 작업은 이어진다", OK),
            ("층2 · 물리 차단", "전기를 끊는다 — 오경보마다 라인이 멈춘다", WARN))):
        yy = y + i * 96
        b.append(rect(x0, yy, 1380, 78, "#dcfce7" if color == OK else "#fee2e2", rx=8))
        b.append(txt(x0 + 28, yy + 50, head, 28, color, weight="bold"))
        b.append(txt(x0 + 300, yy + 50, body_txt, 25, INK))
    b.append(txt(x0, y + 236, "🔴 층2는 현재 성립 불가 — 선행 조건은 오경보 저감",
                 28, WARN, weight="bold"))

    return write(out_dir, "06_E2E_오경보.svg", svg_page(
        "차단을 설계하기 전에 오경보를 재지 않았다",
        "§10.31 · 시뮬레이션 정책 4종 적용값 · 아래 눈금은 1분 축 도식",
        "".join(b)))


# ──────────────────────────────────────────────────────── 7) FPS 병목 해소
FPS_BEFORE = os.path.join(_TEST_DIR, "logs",
                          "20260810_141413_esp32_fps-eungmin-hoi_console_v2_perf_log.csv")
FPS_AFTER = os.path.join(_TEST_DIR, "logs",
                         "20260810_143036_esp32_fps-after-fbcount2-hoi_console_v2_perf_log.csv")


def _fps(path):
    return [float(r["fps"]) for r in csv.DictReader(open(path, encoding="utf-8"))][1:]


def chart_fps(out_dir):
    before, after = _fps(FPS_BEFORE), _fps(FPS_AFTER)
    b = []
    x0, y0, plotw, hmax, ymax = 130, 530, 1000, 360, 35.0
    for v in range(0, int(ymax) + 1, 5):
        gy = y0 - hmax * v / ymax
        b.append(line(x0, gy, x0 + plotw, gy))
        b.append(txt(x0 - 16, gy + 7, v, 19, MUTED, anchor="end"))
    gy15 = y0 - hmax * 15 / ymax
    b.append(line(x0, gy15, x0 + plotw, gy15, "#111827", 3, dash="10 6"))

    for series, color in ((before, WARN), (after, OK)):
        pts = " ".join(f"{x0 + plotw * i / (len(series) - 1):.1f},"
                       f"{y0 - hmax * min(v, ymax) / ymax:.1f}"
                       for i, v in enumerate(series))
        b.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                 f'stroke-width="2.5" opacity="0.9"/>')
    b.append(rect(x0 + 6, gy15 - 40, 206, 34, "#ffffff", rx=4, opacity=0.9))
    b.append(txt(x0 + 14, gy15 - 15, "NFR-1  15 fps", 24, INK, weight="bold"))
    b.append(txt(x0, y0 + 38, "각 300프레임 · 같은 장면·같은 코드", 23, MUTED))

    px = x0 + plotw + 60
    for i, (lab, series, color) in enumerate((("BEFORE  fb_count=1", before, WARN),
                                              ("AFTER  fb_count=2", after, OK))):
        yy = 190 + i * 200
        b.append(txt(px, yy, lab, 27, color, weight="bold"))
        b.append(txt(px, yy + 60, f"{statistics.mean(series):.2f} fps", 52, color,
                     weight="bold"))
        b.append(txt(px, yy + 104,
                     f"15fps 미만 "
                     f"{100 * sum(1 for v in series if v < 15) / len(series):.0f}%",
                     25, INK))
        b.append(txt(px, yy + 140, f"최저 {min(series):.1f} fps", 23, MUTED))

    y = y0 + 90
    b.append(txt(x0, y, "바꾼 것은 펌웨어 3줄", 30, INK, weight="bold"))
    b.append(rect(x0, y + 22, 900, 116, "#f4f4f5", rx=8))
    for i, ln in enumerate(("config.fb_count = 2;",
                            "config.grab_mode = CAMERA_GRAB_LATEST;",
                            "WiFi.setSleep(false);")):
        b.append(txt(x0 + 24, y + 58 + i * 34, ln, 23, INK))
    b.append(txt(x0 + 960, y + 30, "🔴 두 달간의 진단 = 「전송·하드웨어 한계」", 25,
                 WARN, weight="bold"))
    b.append(txt(x0 + 960, y + 76, "대역폭은 1.2%만 쓰고 있었다", 24, INK))
    b.append(txt(x0 + 960, y + 116, "진짜 병목 = 내부 프레임 버퍼 1장", 24, INK))

    return write(out_dir, "07_FPS_병목해소.svg", svg_page(
        "FPS 10 → 24 — 원인을 두 달간 잘못 짚었다",
        "2026-08-10 · ESP32 · 손 검출 포함 · §10.34 · 🔴 정지 장면·단일 조건",
        "".join(b)))


# ─────────────────────────────────────────────────────── 8) tool_v3 공구 검출
_SHOTS = os.path.expanduser("~/lab/tool-detect/tool_live_shots")
TOOL_SHOTS = (("드라이버", "tool_v3_driver-0.75_161444.png"),
              ("렌치", "tool_v3_wrench-0.79_161344.png"),
              ("플라이어", "tool_v3_pliers-0.80_161453.png"))


def chart_tool(out_dir):
    b = []
    iw, ih, iy = 440, 300, 195
    for i, (name, fn) in enumerate(TOOL_SHOTS):
        path = os.path.join(_SHOTS, fn)
        if not os.path.exists(path):
            continue
        x = 90 + i * (iw + 40)
        b.append(rect(x - 5, iy - 5, iw + 10, ih + 10, OK, rx=8))
        b.append(image(path, x, iy, iw, ih))
        b.append(txt(x, iy - 22, name, 28, INK, weight="bold"))
        conf = fn.split("-")[1].split("_")[0]
        b.append(txt(x + iw, iy - 22, f"conf {conf}", 24, OK, anchor="end"))

    y = iy + ih + 62
    b.append(txt(90, y, "바꾼 변수는 데이터 하나", 30, INK, weight="bold"))
    for i, (lab, val, note, color) in enumerate((
            ("tool_v1 · ARCAD", "사용 불가", "렌치를 오분류", WARN),
            ("tool_v3 · 병합", "29,809장", "누출 0건", OK))):
        yy = y + 44 + i * 96
        b.append(rect(90, yy, 1420, 78, "#fee2e2" if color == WARN else "#dcfce7", rx=8))
        b.append(txt(120, yy + 50, lab, 26, INK))
        b.append(txt(560, yy + 50, val, 30, color, weight="bold"))
        b.append(txt(880, yy + 50, note, 24, MUTED))
    b.append(txt(90, y + 252, "🔴 배경 오검출 잔존 — 키보드를 렌치로 0.79", 26, WARN))

    return write(out_dir, "08_tool_v3_공구검출.svg", svg_page(
        "공구 검출 — 실패 원인은 데이터 양이 아니라 다양성",
        "tool_live.py 실시간 캡처 · 뷰어 임계 0.60(운용 0.65 아님) · §10.41·§10.42",
        "".join(b)))


# ─────────────────────────────────────────────────────── 겹침 검사 (--check)
_TEXT_RE = re.compile(
    r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*?font-size="([\d.]+)"[^>]*?'
    r'text-anchor="(\w+)"[^>]*?>(.*?)</text>', re.S)


def _text_box(x, y, size, anchor, s):
    """글자 폭을 어림한다 — 한글 1.0em · 영숫자 0.56em · 그 외 0.38em."""
    def w(ch):
        if ch == " ":
            return size * 0.30
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            return size * 1.00
        return size * (0.56 if ch.isalnum() else 0.38)
    total = sum(w(c) for c in s)
    if anchor == "middle":
        x -= total / 2
    elif anchor == "end":
        x -= total
    return x, y - size * 0.86, x + total, y + size * 0.26


def check(out_dir):
    """글자끼리 겹치거나 화면 밖으로 나간 것을 보고한다. 눈으로는 놓친다."""
    bad = 0
    for path in sorted(glob.glob(os.path.join(out_dir, "*.svg"))):
        with open(path, encoding="utf-8") as f:
            src = f.read()
        boxes = [(_text_box(float(a), float(b), float(c), d, e), e)
                 for a, b, c, d, e in _TEXT_RE.findall(src)]
        msgs = []
        for (bx, t) in boxes:
            if bx[0] < 8 or bx[2] > W - 8 or bx[1] < 4 or bx[3] > H - 6:
                msgs.append(f"화면 밖: {t[:40]}")
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i][0], boxes[j][0]
                ix = min(a[2], b[2]) - max(a[0], b[0])
                iy = min(a[3], b[3]) - max(a[1], b[1])
                if ix > -2 and iy > -2:      # 2px 까지는 스침으로 본다
                    msgs.append(f"겹침 {ix:.0f}x{iy:.0f}px: "
                                f"{boxes[i][1][:28]} / {boxes[j][1][:28]}")
        name = os.path.basename(path)
        print(("🔴 " if msgs else "✅ ") + name)
        for m in msgs:
            print("    ", m)
        bad += len(msgs)
    print("총", bad, "건")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_TEST_DIR, "slides"))
    ap.add_argument("--check", action="store_true", help="겹침·화면밖 검사만")
    args = ap.parse_args()
    if args.check:
        raise SystemExit(1 if check(args.out) else 0)
    os.makedirs(args.out, exist_ok=True)
    chart_sticker(args.out)
    chart_score(args.out)
    chart_hoi(args.out)
    chart_dwell(args.out)
    chart_button_y(args.out)
    chart_false_alarm(args.out)
    chart_fps(args.out)
    chart_tool(args.out)


if __name__ == "__main__":
    main()
