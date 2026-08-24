"""발표용 차트 3종 생성 — 표준 라이브러리만 (인라인 SVG).

왜 이 방식인가:
    파이에 matplotlib 이 없고, `db_report.py` 가 이미 "표준 라이브러리 + 인라인 SVG"
    로 리포트를 만드는 선례가 있다. 같은 방식을 따른다.

만드는 것 (전부 로컬 데이터·추가 촬영 불필요):
    1) 02_채점.svg      ← test/logs/score_*_console_v2.csv  (§10.20)
    2) 04_체류분포.svg  ← test/hoi.db  palm_frames + presses
    3) 05_버튼y.svg     ← test/hoi.db  (판정 규칙은 `hoi_metrics.py` 단일 출처)

🔴 지표 이름을 섞지 않는다 — 각 차트의 부제에 **무엇을 잰 값인지·조건**을 박아 넣는다.
   특히 2)는 §10.23 의 57%/14% 와 **다른 모집단**(전체 눌림 407건, 22세션 통합)이므로
   그 수치의 재현이 아니다.

사용:
    python3 test/slide_charts.py [--out <디렉터리>]
"""

import argparse
import csv
import glob
import os
import statistics
import sys

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


def svg_page(title, subtitle, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">'
            + rect(0, 0, W, H, "#ffffff")
            + txt(70, 78, title, 40, INK, weight="bold")
            + txt(70, 116, subtitle, 20, MUTED)
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
    b.append(txt(70, 175, "클래스별 AP50", 24, INK, weight="bold"))
    for i in range(6):
        gy = y0 - hmax * i / 5
        b.append(line(x0 - 20, gy, x0 + 5 * (bw + gap), gy))
        b.append(txt(x0 - 32, gy + 7, f"{i / 5:.1f}", 16, MUTED, anchor="end"))
    for i, cls in enumerate(["B1", "B2", "B3", "B4", "EMO"]):
        v = ap.get(cls, 0.0)
        x = x0 + i * (bw + gap)
        color = ACCENT if cls != "B4" else OK
        b.append(rect(x, y0 - hmax * v, bw, hmax * v, color, rx=4))
        b.append(txt(x + bw / 2, y0 - hmax * v - 14, f"{v:.3f}", 22, color,
                     anchor="middle", weight="bold"))
        b.append(txt(x + bw / 2, y0 + 32, cls, 22, INK, anchor="middle"))
    b.append(txt(x0, y0 + 80,
                 f"mAP50 {meta.get('mAP50', '?')} · test {meta.get('images', '?')}장 "
                 f"· 운용 임계 conf 0.65", 20, MUTED))
    b.append(txt(x0, y0 + 112,
                 "🔵 B4 = 파랑 스티커 적용본. v1 은 같은 클래스를 실추론에서 0회 검출"
                 "(검출 횟수 — AP 와 다른 지표)", 18, OK))

    # 혼동행렬
    cx, cy, cell = 1010, 210, 74
    labels = ["B1", "B2", "B3", "B4", "EMO"]
    cols = labels + ["미검출"]
    b.append(txt(cx, 175, "혼동행렬 (정답 → 예측)", 24, INK, weight="bold"))
    for j, c in enumerate(cols):
        b.append(txt(cx + 110 + j * cell + cell / 2, cy - 10, c, 15, MUTED,
                     anchor="middle"))
    for i, r in enumerate(labels):
        yy = cy + i * cell
        b.append(txt(cx + 100, yy + cell / 2 + 6, r, 18, INK, anchor="end"))
        for j, c in enumerate(cols):
            n = conf.get(f"{r}->{c}", 0)
            xx = cx + 110 + j * cell
            diag = (r == c)
            fill = "#dbeafe" if diag and n else ("#fee2e2" if n else "#fafafa")
            b.append(rect(xx, yy, cell - 4, cell - 4, fill, rx=4))
            if n:
                b.append(txt(xx + (cell - 4) / 2, yy + cell / 2 + 7, n, 20,
                             INK if diag else WARN, anchor="middle",
                             weight="bold" if not diag else "normal"))
    b.append(txt(cx, cy + 5 * cell + 46,
                 "클래스 오분류 1건(EMO→B4) · 배경 오검출 0건", 20, INK))

    return write(out_dir, "02_console_v2_채점.svg", svg_page(
        "console_v2 정량 채점 — B4 AP50 0.997",
        "모조 콘솔 · 클린룸 형광등 · test 113장 전량 수동 라벨 · 누출 0 "
        "(통합문서 §10.20). 실콘솔 2차 test 미실시.", "".join(b)))


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
        b.append(txt(x0 - 16, gy + 7, int(peak * i / 4), 16, MUTED, anchor="end"))
    for i, cnt in enumerate(bins):
        x = x0 + i * bw
        lo = i * step
        color = MUTED if lo < 0.3 else ACCENT
        b.append(rect(x + 4, y0 - hmax * cnt / peak, bw - 8, hmax * cnt / peak,
                      color, rx=3))
        if i % 2 == 0:
            lab = f"{lo:.1f}" if i < nbin else f"{nbin * step:.1f}+"
            b.append(txt(x, y0 + 30, lab, 17, MUTED, anchor="middle"))
    b.append(txt(x0 + plotw / 2, y0 + 68, "눌림 직전 같은 버튼 구역에 연속으로 머문 시간 (초)",
                 19, MUTED, anchor="middle"))
    b.append(txt(x0 - 16, y0 - hmax - 24, "눌림 건수", 17, MUTED, anchor="start"))

    for thr, color, note in ((0.3, OK, "채택 0.3초"), (0.5, WARN, "구 정본 0.5초")):
        x = x0 + (thr / step) * bw
        pct = 100 * sum(1 for d in dw if d >= thr) / n
        b.append(line(x, y0 - hmax - 10, x, y0, color, 3, dash="8 6"))
        b.append(txt(x + 10, y0 - hmax + 10, note, 20, color, weight="bold"))
        b.append(txt(x + 10, y0 - hmax + 40, f"이 이상 = {pct:.1f}%", 20, color))

    med = statistics.median(dw)
    b.append(txt(x0, y0 + 116,
                 f"표본 {n}건 · 22세션 통합 · 중앙값 {med:.2f}초 · 팜 임계 0.5 고정",
                 20, INK))
    b.append(txt(x0, y0 + 150,
                 "🔴 §10.23 의 57%/14% 와 모집단이 다르다 — 그 수치의 재현이 아니라 "
                 "같은 방향을 보이는 별개 집계다.", 18, WARN))

    return write(out_dir, "04_체류시간_분포.svg", svg_page(
        "체류 임계 0.5초 → 0.3초",
        "hoi.db 22세션 전체 눌림 기준 · 판정 규칙은 `hoi_metrics.py` 단일 출처",
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
    b.append(txt(x0 + bw * 2, y0 - hmax - 44, "권장 운용 구간  y 120~280", 21, OK,
                 anchor="middle", weight="bold"))
    for i in range(5):
        gy = y0 - hmax * i / 4
        b.append(line(x0, gy, x0 + plotw, gy))
        b.append(txt(x0 - 16, gy + 7, f"{25 * i}%", 16, MUTED, anchor="end"))
    for i, (lo, hi, cnt, rate) in enumerate(stats):
        x = x0 + i * bw
        color = OK if rate >= 90 else (WARN if rate < 60 else ACCENT)
        b.append(rect(x + 18, y0 - hmax * rate / 100, bw - 36, hmax * rate / 100,
                      color, rx=5))
        b.append(txt(x + bw / 2, y0 - hmax * rate / 100 - 14, f"{rate:.1f}%", 24,
                     color, anchor="middle", weight="bold"))
        lab = f"{lo}~{hi}" if hi < 10 ** 5 else f"{lo}+"
        b.append(txt(x + bw / 2, y0 + 32, lab, 20, INK, anchor="middle"))
        b.append(txt(x + bw / 2, y0 + 58, f"n={cnt}", 17, MUTED, anchor="middle"))

    cliff_x = x0 + bw * 4
    b.append(line(cliff_x, y0 - hmax - 30, cliff_x, y0, WARN, 3, dash="8 6"))
    b.append(txt(cliff_x + 12, y0 - hmax + 4, f"절벽 y={M.CLIFF_Y}", 20, WARN,
                 weight="bold"))
    b.append(txt(cliff_x + 12, y0 - hmax + 32, "아래는 임계·창으로 못 고친다", 18, WARN))

    tot = len(rows)
    b.append(txt(x0, y0 + 112, "가로축 = 버튼이 화면 안에서 잡히는 세로 위치(픽셀). "
                               "위쪽일수록 값이 작다.", 20, MUTED))
    b.append(txt(x0, y0 + 146,
                 f"세로축 = 사전 감지율(눌림 1건 단위, 창 5프레임) · 표본 {tot}건 "
                 f"· 22세션 통합 · 팜 임계 0.5 고정", 20, INK))

    return write(out_dir, "05_버튼y_사전감지율.svg", svg_page(
        "감지 성능을 가르는 변수는 자세가 아니라 버튼의 화면 속 높이",
        "사전 감지율 = (감지 성공 눌림 ÷ 전체 눌림). 프레임 단위 손 검출률이 아니다.",
        "".join(b)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_TEST_DIR, "slides"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    chart_score(args.out)
    chart_dwell(args.out)
    chart_button_y(args.out)


if __name__ == "__main__":
    main()
