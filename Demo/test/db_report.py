"""bench.db → 자립형 시각화 HTML 생성 (시험판).

- 정본 아님: 측정 수치 정본은 통합문서 §10. 이 HTML은 DB에서 언제든 재생성되는 열람용.
- 의존성 0 (표준 라이브러리만), 차트는 인라인 SVG — 오프라인/Artifact 양쪽에서 열린다.
- 사용: python3 test/db_report.py   →  test/bench_report.html
"""

import datetime
import os
import sqlite3
import statistics

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_TEST_DIR, "bench.db")
OUT_PATH = os.path.join(_TEST_DIR, "bench_report.html")
RAW_DIR = os.path.join(_TEST_DIR, "raw")

CLASSES = ["B1", "B2", "B3", "B4", "EMO"]
COND_ORDER = [
    ("baseline", "기준선 (각도·거리)"),
    ("specular", "정반사"),
    ("distance", "원거리·배경"),
    ("lowlight", "저조도"),
    ("holdout",  "홀드아웃 (학습 미사용)"),
]
# 순차 램프 (palette.md sequential blue 100→700)
RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
        "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]


def _png_count(session_id):
    d = os.path.join(RAW_DIR, session_id)
    if os.path.isdir(d):
        return sum(1 for n in os.listdir(d) if n.endswith(".png"))
    return None


def _ramp_color(pct):
    """0~100% → 램프 스텝. 0은 호출부에서 별도 처리."""
    i = min(len(RAMP) - 1, int(pct / 100 * len(RAMP)))
    return RAMP[i]


def _cell_ink(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 140 else "#0b0b0b"


# =============================================================================
# 데이터 수집
# =============================================================================
def collect(con):
    d = {}
    d["n_sessions"] = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    d["n_rawdet"] = con.execute("SELECT COUNT(*) FROM rawdet").fetchone()[0]
    d["n_frames"] = con.execute("SELECT COUNT(*) FROM perf").fetchone()[0]
    d["n_replays"] = con.execute("SELECT COUNT(*) FROM replay_runs").fetchone()[0]

    # 조건 → 세션 id (§10.13 5세션)
    cond_sid = {}
    for cond, _ in COND_ORDER:
        row = con.execute("SELECT id FROM sessions WHERE condition=?", (cond,)).fetchone()
        if row:
            cond_sid[cond] = row[0]
    d["cond_sid"] = cond_sid

    # ── 히트맵: 조건 × 클래스, v1 라이브 rawdet 검출 프레임율
    heat = {}
    for cond, sid in cond_sid.items():
        total = con.execute("SELECT COUNT(*) FROM perf WHERE session_id=?", (sid,)).fetchone()[0]
        row = {}
        for c in CLASSES:
            hitf = con.execute(
                "SELECT COUNT(DISTINCT frame) FROM rawdet WHERE session_id=? AND cls_name=?",
                (sid, c)).fetchone()[0]
            row[c] = 100.0 * hitf / total if total else 0.0
        heat[cond] = (row, total)
    d["heat"] = heat

    # ── v2 replay: 조건별 최신 run의 클래스별 (검출 프레임율, score 리스트)
    replay = {}
    for cond, sid in cond_sid.items():
        run = con.execute(
            "SELECT id, hef, run_ts FROM replay_runs WHERE session_id=? AND degrade='원본'"
            " ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
        if not run:
            continue
        run_id, hef, run_ts = run
        total = _png_count(sid) or con.execute(
            "SELECT MAX(frame) FROM replay_dets WHERE run_id=?", (run_id,)).fetchone()[0]
        per_cls = {}
        for c in CLASSES:
            scores = [r[0] for r in con.execute(
                "SELECT score FROM replay_dets WHERE run_id=? AND cls_name=?", (run_id, c))]
            hitf = con.execute(
                "SELECT COUNT(DISTINCT frame) FROM replay_dets WHERE run_id=? AND cls_name=?",
                (run_id, c)).fetchone()[0]
            per_cls[c] = {"rate": 100.0 * hitf / total if total else 0.0, "scores": scores}
        replay[cond] = {"hef": hef, "run_ts": run_ts, "total": total, "cls": per_cls}
    d["replay"] = replay

    # ── FPS: 세션별 median·p10 (전 세션)
    fps = []
    for sid, src in con.execute("SELECT id, source FROM sessions ORDER BY id"):
        vals = sorted(r[0] for r in con.execute(
            "SELECT fps FROM perf WHERE session_id=? AND fps > 0", (sid,)))
        if not vals:
            continue
        fps.append({"sid": sid, "src": src,
                    "median": statistics.median(vals),
                    "p10": vals[int(len(vals) * 0.10)]})
    d["fps"] = fps
    return d


# =============================================================================
# SVG 조각
# =============================================================================
def svg_heatmap(heat):
    cw, ch, lx, ty = 108, 44, 150, 30
    w = lx + cw * len(CLASSES) + 10
    h = ty + ch * len(COND_ORDER) + 6
    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="조건별 v1 검출 프레임율 히트맵">']
    for j, c in enumerate(CLASSES):
        p.append(f'<text x="{lx + cw * j + cw / 2}" y="{ty - 10}" text-anchor="middle" class="ax">{c}</text>')
    for i, (cond, label) in enumerate(COND_ORDER):
        if cond not in heat:
            continue
        row, total = heat[cond]
        y = ty + ch * i
        p.append(f'<text x="{lx - 8}" y="{y + ch / 2 + 4}" text-anchor="end" class="ax">{label}</text>')
        for j, c in enumerate(CLASSES):
            v = row[c]
            x = lx + cw * j
            if v == 0:
                p.append(f'<g><rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="4" '
                         f'class="cell0"/><text x="{x + cw / 2}" y="{y + ch / 2 + 4}" '
                         f'text-anchor="middle" class="mut">0%</text>'
                         f'<title>{label} · {c}: 검출 0 / {total}프레임</title></g>')
            else:
                fill = _ramp_color(v)
                vtxt = "<0.1%" if v < 0.1 else f"{v:.1f}%"
                p.append(f'<g><rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="4" '
                         f'fill="{fill}"/><text x="{x + cw / 2}" y="{y + ch / 2 + 4}" '
                         f'text-anchor="middle" fill="{_cell_ink(fill)}" class="cellv">{vtxt}</text>'
                         f'<title>{label} · {c}: {v:.2f}% ({total}프레임 중)</title></g>')
    p.append("</svg>")
    return "".join(p)


def svg_grouped_bar(v1, v2, total1, total2):
    """홀드아웃: 클래스별 v1(라이브) vs v2(replay) 검출 프레임율."""
    bw, gap, grp, lx, ty, ph = 22, 2, 96, 46, 26, 170
    w = lx + grp * len(CLASSES) + 10
    h = ty + ph + 34
    base = ty + ph

    def bar(x, pct, cls_attr, tip):
        bh = ph * pct / 100
        return (f'<g><path d="M{x},{base} v{-max(bh - 4, 0)} q0,-4 4,-4 h{bw - 8} q4,0 4,4 '
                f'v{max(bh - 4, 0)} z" class="{cls_attr}"/>'
                f'<rect x="{x}" y="{base - ph}" width="{bw}" height="{ph}" fill="transparent"/>'
                f'<title>{tip}</title></g>')

    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="홀드아웃 v1 대 v2 검출 프레임율">']
    for gy in (0, 50, 100):
        yy = base - ph * gy / 100
        p.append(f'<line x1="{lx}" y1="{yy}" x2="{w - 10}" y2="{yy}" class="grid"/>'
                 f'<text x="{lx - 6}" y="{yy + 4}" text-anchor="end" class="ax">{gy}</text>')
    for i, c in enumerate(CLASSES):
        gx = lx + grp * i + 14
        p.append(bar(gx, v1[c], "s1", f"v1 라이브 · {c}: {v1[c]:.1f}% ({total1}프레임)"))
        p.append(bar(gx + bw + gap, v2[c], "s2", f"v2 replay · {c}: {v2[c]:.1f}% ({total2}프레임)"))
        p.append(f'<text x="{gx + bw + gap / 2}" y="{base + 18}" text-anchor="middle" class="ax">{c}</text>')
        if c == "B4":  # 이야기의 중심만 직접 라벨
            p.append(f'<text x="{gx + bw / 2}" y="{base - ph * v1[c] / 100 - 5}" '
                     f'text-anchor="middle" class="vl">{v1[c]:.0f}</text>')
            p.append(f'<text x="{gx + bw + gap + bw / 2}" y="{base - ph * v2[c] / 100 - 5}" '
                     f'text-anchor="middle" class="vl">{v2[c]:.0f}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_score_range(replay):
    """조건별 v2 B4 score: min–median–max 범위 도트. 저조도 강조."""
    lx, rx_pad, rh, ty = 190, 20, 40, 24
    w = 640
    h = ty + rh * len(COND_ORDER) + 34
    pw = w - lx - rx_pad
    lo, hi = 0.5, 1.0

    def X(v):
        return lx + pw * (v - lo) / (hi - lo)

    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="조건별 v2 B4 score 분포">']
    for gv in (0.5, 0.65, 0.8, 1.0):
        p.append(f'<line x1="{X(gv)}" y1="{ty}" x2="{X(gv)}" y2="{ty + rh * len(COND_ORDER)}" class="grid"/>'
                 f'<text x="{X(gv)}" y="{ty + rh * len(COND_ORDER) + 16}" text-anchor="middle" class="ax">{gv}</text>')
    p.append(f'<text x="{X(0.65)}" y="{ty - 8}" text-anchor="middle" class="mut">conf_high 0.65</text>')
    for i, (cond, label) in enumerate(COND_ORDER):
        y = ty + rh * i + rh / 2
        p.append(f'<text x="{lx - 10}" y="{y + 4}" text-anchor="end" class="ax">{label}</text>')
        info = replay.get(cond)
        s = info["cls"]["B4"]["scores"] if info else []
        if not s:
            p.append(f'<text x="{lx + 4}" y="{y + 4}" class="mut">replay 데이터 없음</text>')
            continue
        med, mn, mx = statistics.median(s), min(s), max(s)
        emph = cond == "lowlight"
        cls_line = "s1l" if emph else "gline"
        cls_dot = "s1" if emph else "gdot"
        p.append(f'<g><line x1="{X(mn)}" y1="{y}" x2="{X(mx)}" y2="{y}" class="{cls_line}"/>'
                 f'<circle cx="{X(med)}" cy="{y}" r="6" class="{cls_dot} ring"/>'
                 f'<rect x="{X(mn) - 8}" y="{y - 14}" width="{X(mx) - X(mn) + 16}" height="28" fill="transparent"/>'
                 f'<title>{label} · B4 median {med:.3f} (범위 {mn:.3f}–{mx:.3f}, n={len(s)})</title></g>')
        if emph:
            p.append(f'<text x="{X(med)}" y="{y - 12}" text-anchor="middle" class="vl">median {med:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_fps(fps):
    lx, ty, rh = 208, 26, 22
    w = 640
    h = ty + rh * len(fps) + 36
    pw = w - lx - 20
    hi = max(16.0, max(f["median"] for f in fps) * 1.08)

    def X(v):
        return lx + pw * v / hi

    p = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="세션별 FPS median">']
    for gv in range(0, int(hi) + 1, 5):
        p.append(f'<line x1="{X(gv)}" y1="{ty}" x2="{X(gv)}" y2="{ty + rh * len(fps)}" class="grid"/>'
                 f'<text x="{X(gv)}" y="{ty + rh * len(fps) + 16}" text-anchor="middle" class="ax">{gv}</text>')
    for i, f in enumerate(fps):
        y = ty + rh * i
        bw_ = X(f["median"]) - lx
        cls = "s1" if f["src"] == "esp32" else "s2"
        label = f["sid"].replace("2026", "").rsplit("_", 1)[0]  # '0713_180016' (카메라는 색+범례)
        p.append(f'<text x="{lx - 8}" y="{y + rh / 2 + 4}" text-anchor="end" class="axs">{label}</text>')
        p.append(f'<g><path d="M{lx},{y + 3} h{max(bw_ - 4, 0)} q4,0 4,4 v{rh - 14} q0,4 -4,4 '
                 f'h{-max(bw_ - 4, 0)} z" class="{cls}"/>'
                 f'<rect x="{lx}" y="{y}" width="{pw}" height="{rh}" fill="transparent"/>'
                 f'<title>{f["sid"]} ({f["src"]}) · median {f["median"]:.1f} FPS · p10 {f["p10"]:.1f}</title></g>')
    yb = ty + rh * len(fps)
    p.append(f'<line x1="{X(15)}" y1="{ty - 6}" x2="{X(15)}" y2="{yb}" class="ref"/>'
             f'<text x="{X(15) + 4}" y="{ty - 10}" class="mut">NFR-1 = 15 FPS</text>')
    p.append("</svg>")
    return "".join(p)


# =============================================================================
# HTML 조립
# =============================================================================
def table(headers, rows):
    th = "".join(f"<th>{h}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<details><summary>표로 보기</summary><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></details>'


def build_html(d):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    heat, replay = d["heat"], d["replay"]

    heat_rows = []
    for cond, label in COND_ORDER:
        if cond in heat:
            row, total = heat[cond]
            heat_rows.append([label, f"{total:,}"] + [f"{row[c]:.1f}%" for c in CLASSES])

    hold_v1 = {c: heat["holdout"][0][c] for c in CLASSES} if "holdout" in heat else {}
    hold_v2 = {c: replay["holdout"]["cls"][c]["rate"] for c in CLASSES} if "holdout" in replay else {}
    t1 = heat["holdout"][1] if "holdout" in heat else 0
    t2 = replay["holdout"]["total"] if "holdout" in replay else 0

    score_rows = []
    for cond, label in COND_ORDER:
        info = replay.get(cond)
        s = info["cls"]["B4"]["scores"] if info else []
        if s:
            score_rows.append([label, f'{info["cls"]["B4"]["rate"]:.1f}%',
                               f"{statistics.median(s):.3f}", f"{min(s):.3f}", f"{max(s):.3f}", len(s)])

    fps_rows = [[f["sid"], f["src"], f'{f["median"]:.1f}', f'{f["p10"]:.1f}'] for f in d["fps"]]

    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SOP 벤치 로그 리포트 (시험판)</title>
<style>
.viz-root {{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --mut:#898781;
  --grid:#e1e0d9; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#008300; --gray:#c3c2b7;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .viz-root {{
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --mut:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#008300; --gray:#52514e;
  }}
}}
:root[data-theme="dark"] .viz-root {{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --mut:#898781;
  --grid:#2c2c2a; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#008300; --gray:#52514e;
}}
.viz-root {{ background:var(--page); color:var(--ink); min-height:100vh; box-sizing:border-box;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; margin:0; padding:24px 16px 48px; }}
.wrap {{ max-width:880px; margin:0 auto; }}
.banner {{ font-size:13px; color:var(--ink2); border:1px solid var(--border);
  background:var(--surface); border-radius:8px; padding:8px 14px; margin-bottom:20px; }}
.banner b {{ color:var(--ink); }}
h1 {{ font-size:22px; margin:0 0 6px; }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:18px 20px 14px; margin-bottom:22px; overflow-x:auto; }}
.card h2 {{ font-size:15px; margin:0 0 4px; }}
.card p.note {{ font-size:12.5px; color:var(--ink2); margin:2px 0 12px; }}
svg {{ max-width:100%; height:auto; display:block; }}
.kpi {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:22px; }}
.tile {{ flex:1 1 140px; background:var(--surface); border:1px solid var(--border);
  border-radius:12px; padding:12px 16px; }}
.tile .l {{ font-size:12px; color:var(--ink2); }}
.tile .v {{ font-size:26px; font-weight:600; margin-top:2px; }}
.legend {{ display:flex; gap:16px; font-size:12.5px; color:var(--ink2); margin:0 0 10px; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:5px; }}
.ax {{ font-size:11.5px; fill:var(--mut); }}
.axs {{ font-size:10.5px; fill:var(--mut); }}
.mut {{ font-size:11px; fill:var(--mut); }}
.vl {{ font-size:11px; font-weight:600; fill:var(--ink); }}
.cellv {{ font-size:12px; font-weight:600; }}
.cell0 {{ fill:var(--surface); stroke:var(--grid); }}
.grid {{ stroke:var(--grid); stroke-width:1; }}
.ref  {{ stroke:var(--mut); stroke-width:1; }}
.s1 {{ fill:var(--s1); }} .s2 {{ fill:var(--s2); }}
.s1l {{ stroke:var(--s1); stroke-width:2; stroke-linecap:round; }}
.gline {{ stroke:var(--gray); stroke-width:2; stroke-linecap:round; }}
.gdot {{ fill:var(--gray); }}
.ring {{ stroke:var(--surface); stroke-width:2; }}
details {{ margin-top:10px; font-size:13px; }}
summary {{ color:var(--ink2); cursor:pointer; }}
table {{ border-collapse:collapse; margin-top:8px; font-size:12.5px; }}
th,td {{ padding:4px 12px 4px 0; text-align:left; border-bottom:1px solid var(--grid);
  font-variant-numeric:tabular-nums; }}
th {{ color:var(--ink2); font-weight:600; }}
</style>
<div class="viz-root"><div class="wrap">
<h1>SOP 벤치 로그 리포트</h1>
<div class="banner">🧪 <b>시험판</b> — 정본 아님. 측정 수치 정본 = 통합문서 §10.
bench.db에서 재생성되는 열람용 파생물 · 생성 {now}</div>

<div class="kpi">
<div class="tile"><div class="l">세션</div><div class="v">{d["n_sessions"]}</div></div>
<div class="tile"><div class="l">raw 검출 행</div><div class="v">{d["n_rawdet"]:,}</div></div>
<div class="tile"><div class="l">처리 프레임</div><div class="v">{d["n_frames"]:,}</div></div>
<div class="tile"><div class="l">v2 replay 실행</div><div class="v">{d["n_replays"]}</div></div>
</div>

<div class="card">
<h2>조건별 검출 프레임율 — console_v1 라이브 (2026-07-13 촬영)</h2>
<p class="note">rawdet(트래킹 이전, ≥conf_low) 기준. 저조도에서 B3·B4가 비는 것이 v2 재학습의 출발점(§10.13).</p>
{svg_heatmap(heat)}
{table(["조건", "프레임", *CLASSES], heat_rows)}
</div>

<div class="card">
<h2>홀드아웃 세션 — v1 라이브 vs v2 replay</h2>
<p class="note">같은 장면(학습 미사용 53프레임)에 대한 검출 프레임율. v1은 파랑 스티커가 학습 분포 밖이라 B4 0%는 예정된 결과(§10.12) — v2 상승분 자체는 증거가 아니며, 판정 기준은 §10.16.</p>
<div class="legend"><span><i style="background:var(--s1)"></i>console_v1 (라이브)</span>
<span><i style="background:var(--s2)"></i>console_v2 (replay)</span></div>
{svg_grouped_bar(hold_v1, hold_v2, t1, t2) if hold_v1 and hold_v2 else '<p class="note">replay 데이터 없음</p>'}
{table(["클래스", "v1 %", "v2 %"], [[c, f"{hold_v1.get(c, 0):.1f}", f"{hold_v2.get(c, 0):.1f}"] for c in CLASSES])}
</div>

<div class="card">
<h2>조건별 B4 confidence — console_v2 replay</h2>
<p class="note">선 = min–max 범위, 점 = median. 저조도(강조)가 마진 최저인지 확인(§10.17의 ⚠️ 신호).</p>
{svg_score_range(replay)}
{table(["조건", "검출율", "median", "min", "max", "n"], score_rows)}
</div>

<div class="card">
<h2>세션별 FPS (median)</h2>
<p class="note">perf 로그 기준, 세로선 = NFR-1 하한 15 FPS. ESP32 세션은 TCP 수신이 상한(§10.11).</p>
<div class="legend"><span><i style="background:var(--s1)"></i>ESP32</span>
<span><i style="background:var(--s2)"></i>USB</span></div>
{svg_fps(d["fps"])}
{table(["세션", "카메라", "median FPS", "p10"], fps_rows)}
</div>

<p style="font-size:12px;color:var(--mut)">원천: Rpi5/Demo/test/bench.db (db_import.py로 재구축) · 이 파일: db_report.py 산출물 · 미커밋 시험판</p>
</div></div>
"""


def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"bench.db 없음 — 먼저 실행: python3 test/db_import.py")
    con = sqlite3.connect(DB_PATH)
    d = collect(con)
    con.close()
    html = build_html(d)
    with open(OUT_PATH, "w") as f:
        f.write(html)
    print(f"[report] {OUT_PATH}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
