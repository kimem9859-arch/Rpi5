#!/usr/bin/env python3
"""세기 보고 도구 — 측정 세션 폴더를 읽어 값을 내고 표로 쓴다(측정 도구 정합 1단계-나).

실행(Rpi5/Demo 에서): python3 test/measure_report.py <세션 폴더> [<세션 폴더> …] [--out <합계.md>] [--curve 0.80,0.90]
    · 세션 하나 = 그 폴더에 report.md · report.json · 여럿 = 합쳐 센 통합값(--out 에 · 없으면 화면만)
    · --curve 잡음,거름 = 체류 두 곡선의 참고 기준(정본 = 발표 설계 M8) — 주지 않으면 문턱별 표만
설계 = 상위 sop-project docs/superpowers/specs/2026-10-09-측정도구-정합-1단계-나-세기-design.md
측정 실행기(run_measure.sh)가 시연 프로그램을 닫으면 이것을 부른다(측정 설계 D10).
🔴 목표값은 통합문서 §4.1 표에서 읽는다(목표의 정본) — 못 읽으면 판정하지 않는다.
🔴 기준 값을 여기 따로 적지 않는다(설계 §3-b) — EMO = recipe.json · 마이크 표본률 = voice_assistant.RATE.
"""
import argparse
import ast
import csv
import io
import json
import os
import re
import statistics
import sys

_TEST = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.dirname(_TEST)
sys.path.insert(0, _DEMO)
sys.path.insert(0, _TEST)

import config               # noqa: E402 — EMO 폴백(fsm.py 와 같다)
import fps                  # noqa: E402
import measure_check        # noqa: E402 — 사건 읽기(잘린 마지막 줄 건너뜀) 재사용
import measure_count as MC  # noqa: E402

TARGETS_MD = os.path.join(os.path.dirname(os.path.dirname(_DEMO)), "docs", "통합문서.md")
RECIPE = os.path.join(_DEMO, "recipe.json")
VOICE_SRC = os.path.join(_DEMO, "voice_assistant.py")


# ── 읽기 ─────────────────────────────────────────────────────────────────
def _num(x):
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def _int(x):
    v = _num(x)
    return int(v) if v is not None else None


def _rows(path):
    """CSV → 줄 사전 목록. 도중에 꺼져 잘린 마지막 줄(줄바꿈 없음)은 버린다 — 잘린 숫자가 틀린 값이 되지 않게."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    if text and not text.endswith("\n"):
        text = text[: text.rfind("\n") + 1]
    return list(csv.DictReader(io.StringIO(text)))


def emo_button(recipe=RECIPE):
    """recipe.json emo_button — 없으면 config.FSM_EMO_BUTTON(fsm.py 폴백과 같다)."""
    try:
        with open(recipe, encoding="utf-8") as f:
            v = json.load(f).get("emo_button")
    except (OSError, ValueError):
        v = None
    return v if v is not None else config.FSM_EMO_BUTTON


def recipe_buttons(recipe=None):
    """recipe.json 단계 버튼(순서대로) — 대본 위반·머묾 대상 검사 · 18 기대 누름 수."""
    try:
        with open(recipe or RECIPE, encoding="utf-8") as f:
            return [s_.get("button") for s_ in json.load(f).get("steps", []) if s_.get("button")]
    except (OSError, ValueError):
        return []


def mic_rate(src=None):
    """voice_assistant.RATE — 모듈을 불러오지 않고 파일에서 상수만 읽는다(음성 전용 파이썬 없이)."""
    src = src or VOICE_SRC
    with open(src, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "RATE" for t in node.targets):
            return int(ast.literal_eval(node.value))
    raise ValueError(f"RATE 상수가 없다: {src}")


def load_script(path, buttons=None):
    """대본 CSV(설계 §5) — 빈 줄·BOM 은 받는다 · 행동 철자·판 숫자·위반/머묾 대상(레시피 버튼) 오류는 줄 번호와 함께 멈춘다."""
    name, rows = os.path.basename(path), []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        for r in rd:
            n = rd.line_num                         # 빈 줄이 있어도 파일의 실제 줄 번호
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not any(r.values()):
                continue
            if r.get("행동") not in MC.ACTIONS:
                raise ValueError(f"대본 {name} {n}행 — 행동 「{r.get('행동')}」 은(는) {'·'.join(MC.ACTIONS)} 가운데 하나여야 한다")
            try:
                r["판"] = int(r.get("판", ""))
            except ValueError:
                raise ValueError(f"대본 {name} {n}행 — 판 「{r.get('판')}」 은(는) 1부터의 숫자여야 한다") from None
            for k in ("대상", "기대", "메모"):
                r.setdefault(k, "")
            if buttons and r["행동"] in ("위반", "머묾") and r["대상"] not in buttons:
                raise ValueError(f"대본 {name} {n}행 — {r['행동']} 대상 「{r['대상']}」 은(는) 레시피 버튼({'·'.join(buttons)}) 가운데 하나여야 한다")
            rows.append(r)
    return rows


def load_session(d):
    """세션 폴더 → S(measure_count 머리말의 꼴)."""
    d = d.rstrip("/")
    with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
        info = json.load(f)
    frames = []
    for r in _rows(os.path.join(d, "frames.csv")):
        f_, t = _int(r.get("frame")), _num(r.get("t_recv_ms"))
        if f_ is None or t is None:
            continue
        row = {"frame": f_, "t": t, "seq": _int(r.get("recv_seq")), "t_start": _num(r.get("t_start_ms")),
               "t_done": _num(r.get("t_done_ms")), "roi": r.get("roi") or None, "level": _int(r.get("level"))}
        for s in MC.STAGES:
            row[s] = _num(r.get(s))
        frames.append(row)
    frames.sort(key=lambda x: x["t"])
    fsm = []
    for r in _rows(os.path.join(d, "fsm.csv")):
        t, tg = _num(r.get("t_recv_ms")), _num(r.get("t_gui_ms"))
        if t is None or tg is None:
            continue
        fsm.append({"t": t, "t_gui": tg, "roi": r.get("fsm_roi") or None, "level": _int(r.get("fsm_level")),
                    "state": r.get("state") or None, "expected": r.get("expected") or None})
    fsm.sort(key=lambda x: x["t"])
    inp = info.get("입력") or {}
    steps = recipe_buttons()
    script = load_script(os.path.join(d, inp["대본"]), buttons=steps) if inp.get("대본") else None
    try:
        rate = mic_rate()
    except (OSError, ValueError, SyntaxError):
        rate = None                                   # V9 하나만 못 낸다 — 보고 전체를 멈추지 않는다
    return {"dir": d, "name": os.path.basename(d), "info": info, "kind": inp.get("세션"),
            "settings": info.get("설정") or {}, "frames": frames, "fsm": fsm,
            "events": sorted(measure_check.load_events(os.path.join(d, "events.csv")), key=lambda e: e[0]),
            "voice": sorted(measure_check.load_events(os.path.join(d, "voice_events.csv")), key=lambda e: e[0]),
            "script": script, "emo": emo_button(), "rate": rate, "steps": steps}


def warnings(S):
    """표 머리에 다는 경고 — 끊긴 기록 · 뺀 것 · 시험 세션."""
    w = []
    if not S["info"].get("측정기록", True):
        w.append("측정 기록 끔 회차 — 셀 기록이 없다")
    ends = [d for _, k, d in S["events"] if k == "measure_end"]
    if S["info"].get("측정기록", True) and not ends:
        w.append("events.csv 에 끝 사건(measure_end)이 없다 — 도중에 꺼졌거나 쓰기 실패(시연 로그 「[측정] 측정 기록 쓰기 실패」 확인)")
    dropped = sum(d.get("dropped") or 0 for d in ends)
    if dropped:
        w.append(f"버린 사건 {dropped}건(큐 넘침) — 그 세션 값이 모자랄 수 있다")
    if MC.recording(S):
        w.append("녹화를 켠 세션 — 속도 값(12 · 13 · 26 · 27)에서 뺐다")
    ps = MC.pair_presses(S["events"])
    kb = sum(1 for p in ps if p["how"] == "키보드")
    cb = sum(1 for p in ps if p["how"] == "콜백")
    nb = sum(1 for p in ps if p["how"] == "처리")
    if kb:
        w.append(f"키보드 누름 {kb}건 — 위반·구역 값에서 뺐다")
    if cb:
        w.append(f"엣지 시각 대신 콜백 시각이 적힌 누름 {cb}건 — 콜백 시각을 썼다")
    if nb:
        w.append(f"GPIO 엣지 기록이 없는 누름 {nb}건 — 화면 처리 시각으로 대신했다")
    if S["script"]:
        n_runs = len(MC.split_runs(S["events"]))
        over = sorted({int(r["판"]) for r in S["script"] if int(r["판"]) > n_runs})
        if over:
            w.append(f"대본 판 {'·'.join(map(str, over))} 이 기록에 없다(기록된 판 {n_runs}개) — 그 줄은 세지 않았다")
    vends = [d for _, k, d in S["voice"] if k == "measure_end"]
    if S["info"].get("음성", True) and S["info"].get("측정기록", True) and not S["voice"]:
        w.append("음성 켬 세션인데 음성 기록이 없다(voice_events.csv) — 음성 값(V1~V9)이 비어 있다")
    vdrop = sum(d.get("dropped") or 0 for d in vends)
    if vdrop:
        w.append(f"버린 음성 사건 {vdrop}건(큐 넘침) — 음성 값이 모자랄 수 있다")
    if not S.get("rate"):
        w.append("마이크 표본률(voice_assistant.RATE)을 못 읽어 V9 를 내지 않았다")
    if any(k == "tool_sim" for _, k, _ in S["events"]):
        w.append("키보드 공구(tool_sim)가 있다 — 그 판은 공구 값에서 뺐다")
    if S["kind"] == "시험":
        w.append("시험 세션 — 도구 확인 전용 · 인용·목표 판정 금지")
    return w


# ── 목표(통합문서 §4.1) ───────────────────────────────────────────────────
def parse_target(text):
    """목표값 칸 → {op, value, unit, stat(median|max|None), min_n, text} · 못 읽으면 None."""
    v = text.replace("**", "").strip()
    m = re.search(r"([≥≤])\s*([0-9.]+)\s*(%|초|fps|ms)?", v)
    if m:
        op, num, unit = m.group(1), float(m.group(2)), m.group(3) or ""
    elif re.match(r"0\s*건", v):
        op, num, unit = "≤", 0.0, "건"
    else:
        return None
    stat = "median" if "중앙값" in v else ("max" if "모든 건" in v else None)
    n = re.search(r"\([^)]*?(\d+)\s*(?:회|판)", v)
    return {"op": op, "value": num, "unit": unit, "stat": stat, "min_n": int(n.group(1)) if n else None, "text": v}


def load_targets(path=TARGETS_MD):
    """통합문서 §4.1 목표 표(머리 「| ID | 측정 # | 목표 | 목표값 |」) → {측정 #: 목표} · 못 읽으면 None."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"^\| ID \| 측정 # \| 목표 \| 목표값 \|[^\n]*\n\|[-| ]+\|\n((?:\|[^\n]*\n)+)", text, re.M)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        t = parse_target(cells[3]) or {"text": cells[3].replace("**", "").strip(), "unreadable": True}
        t["name"] = cells[2]
        out[cells[1]] = t
    return out or None


def fps_floor(targets):
    """13 의 기준 = NFR-1(측정 # 12) 목표값 — 못 읽었으면 None."""
    t = (targets or {}).get("12")
    return t["value"] if t and not t.get("unreadable") else None


def target_value(mid, M, t=None):
    """목표 측정 # → {raw(값 또는 목록), n(표본), note(덧붙임), why(값이 없는 까닭 — 있으면 판정 대신)}.
    놓친 것(ACK 없는 명령 · 재생 없는 알림)은 ∞ 로 넣는다 — 빼면 판정이 좋은 쪽으로 치우친다."""
    g = lambda k: M.get(k, {})                      # noqa: E731
    if mid == "1":
        n, k = g("1").get("n", 0), g("1").get("k", 0)
        return {"raw": 100 * k / n if n else None, "n": n, "why": "",
                "note": f"처리 늦음 후보 {g('1').get('late', 0)} · 체류 미달 후보 {g('1').get('short', 0)}"}
    if mid == "4":
        v = g("4").get("leads", [])
        return {"raw": v, "n": len(v), "note": f"0 이하 {sum(1 for x in v if x <= 0)}(누름이 경고보다 먼저)", "why": ""}
    if mid == "16":
        n, k = g("16").get("n", 0), g("16").get("k", 0)
        return {"raw": 100 * k / n if n else None, "n": n, "why": "",
                "note": f"실패 — 경고·차단 {g('16').get('f_alarm', 0)} · 초기화 {g('16').get('f_reset', 0)}"
                        f" · 위반 {g('16').get('f_viol', 0)} · 열린 판 {g('16').get('open', 0)}(뺌)"}
    if mid == "17ⓐ":
        if not g("17a").get("script"):
            return {"raw": None, "n": 0, "note": "", "why": "대본 없음"}
        return {"raw": g("17a").get("k", 0), "n": g("17a").get("n", 0),
                "note": f"틀린 공구 알아챔 {g('17a').get('det', 0)} · 건너뜀 {g('17a').get('skip', 0)}", "why": ""}
    if mid == "12":
        iv = g("12").get("iv", [])
        return {"raw": fps.fps_from_intervals(iv), "n": len(iv), "note": "화면이 받은 간격", "why": ""}
    if mid == "14":
        v, un, to = g("14").get("total", []), g("14").get("unsent", 0), g("14").get("timeout", 0)
        lim = t["value"] if t and not t.get("unreadable") else None
        over = f"{lim:g} 넘음 {sum(1 for x in v if x > lim)} · " if lim is not None else ""
        return {"raw": v + [float("inf")] * (un + to), "n": g("14").get("n", 0), "why": "",
                "note": f"{over}시간 초과 {to} · 미연결 {un} · 짝 요청 없음 {g('14').get('noreq', 0)}"}
    if mid == "V1":
        v, miss = g("V1").get("delays", []), g("V1").get("missing", 0)
        return {"raw": v + [float("inf")] * miss, "n": len(v) + miss, "note": f"재생 없음 {miss}(∞ 로 넣음)", "why": ""}
    if mid == "9":
        return {"raw": None, "n": 0, "note": "", "why": "세기 밖 — 모델 채점(비전 모델 재정립 ③)"}
    return {"raw": None, "n": 0, "note": "", "why": "세는 법 없음"}


def apply_stat(t, raw):
    """목록이면 목표의 통계로 — 중앙값 · 모든 건(최댓값) · 표시 없음 = 모든 건으로."""
    if not isinstance(raw, list):
        return raw, ""
    if not raw:
        return None, ""
    if t["stat"] == "median":
        return statistics.median(raw), "중앙값"
    if t["stat"] == "max":
        return max(raw), "최댓값"
    if t["op"] == "≥":                               # 표시 없음 = 모든 건 — 부호에 따라 엄격한 쪽(≥ 는 최솟값)
        return min(raw), "최솟값 — 목표에 통계 표시가 없어 모든 건으로"
    return max(raw), "최댓값 — 목표에 통계 표시가 없어 모든 건으로"


def judge(t, v, n):
    if v is None:
        return "값 없음"
    if t["min_n"] and n < t["min_n"]:
        return f"⏸ 표본 부족({n} < {t['min_n']})"
    ok = v >= t["value"] if t["op"] == "≥" else v <= t["value"]
    return "✅ 충족" if ok else "❌ 미달"


# ── 표 ───────────────────────────────────────────────────────────────────
def _med(v):
    return statistics.median(v) if v else None


def _pq(v, q):
    s = sorted(v)
    return s[int(round(q * (len(s) - 1)))] if s else None


def _min(v):
    return min(v) if v else None


def _max(v):
    return max(v) if v else None


def _f(x, nd=3, unit=""):
    if x is None:
        return "—"
    return "∞" if x == float("inf") else f"{x:.{nd}f}{unit}"


def _pct(k, n):
    return f"{100 * k / n:.1f}% ({k}/{n})" if n else "—"


def _ft(x, unit):
    if x is None:
        return "—"
    if x == float("inf"):
        return "∞"
    return {"%": f"{x:.1f}%", "초": f"{x:.3f}초", "fps": f"{x:.1f} fps", "ms": f"{x:.1f} ms", "건": f"{int(x)}건"}.get(unit, f"{x:.3f}")


def render(sessions, per, M, targets, curve=None):
    L = ["# 세기 결과 — " + " · ".join(S["name"] for S in sessions), ""]
    if len(sessions) == 1:
        L.append("> ⚠️ **단일 세션 — 인용 금지**(`rules/수치인용.md` — 통합값으로 인용한다)")
    for S in sessions:
        for w in warnings(S):
            L.append(f"> ⚠️ {S['name']} — {w}")
    L += ["", "## ① 목표(통합문서 §4.1)", ""]
    if not targets:
        L.append("❌ **목표 읽기 실패 — 판정 없음**(통합문서 §4.1 목표 표를 찾지 못했다)")
    else:
        trial = any(S["kind"] == "시험" for S in sessions)       # 설계 §3 — 시험 세션 = 인용·목표 판정 금지
        voiced = [p for S, p in zip(sessions, per) if S["info"].get("음성", True)]
        Mt = dict(M, **{"12": MC.merge([p.get("12", {}) for p in voiced])})   # NFR-1 = 모든 기능을 켠 시연 상태(§4.1)
        muted = len(sessions) - len(voiced)
        L += ["| # | 목표 | 목표값 | 값 | 표본 | 판정 | 덧붙임 |", "|---|---|---|---|---|---|---|"]
        for mid, t in targets.items():
            if t.get("unreadable"):
                L.append(f"| {mid} | {t['name']} | {t['text']} | — | — | 목표값 못 읽음 |  |")
                continue
            tv = target_value(mid, Mt, t)
            v, how = apply_stat(t, tv["raw"])
            verdict = tv["why"] or ("판정 안 함 — 시험 세션" if trial else judge(t, v, tv["n"]))
            val = _ft(v, t["unit"]) + (f" ({how})" if how else "")
            note = tv["note"] + (f" · 음성 끔 세션 {muted} 뺌" if mid == "12" and muted else "")
            L.append(f"| {mid} | {t['name']} | {t['text']} | {val} | {tv['n']} | {verdict} | {note} |")
        if len(sessions) > 1:
            # 설계 §3 「세션별 값도 함께」 — 합친 값만 보면 한 세션이 튄 것을 놓친다(rules/수치인용 「세션 간 편차가 크다」)
            L += ["", "### 세션별 값(편차 확인 · 값(표본))", "",
                  "| 세션 | " + " | ".join(targets) + " |", "|---|" + "---|" * len(targets)]
            for S, p in zip(sessions, per):
                cells = []
                for mid, t in targets.items():
                    if t.get("unreadable"):
                        cells.append("—")
                        continue
                    tv = target_value(mid, p, t)
                    cells.append("—" if tv["why"] else f"{_ft(apply_stat(t, tv['raw'])[0], t['unit'])} ({tv['n']})")
                L.append(f"| {S['name']} | " + " | ".join(cells) + " |")
    g = lambda k: M.get(k, {})                      # noqa: E731
    a16, z, s23, st, gaps = g("16").get("alarms", []), g("5"), g("23"), g("26"), g("28").get("gaps", [])
    fills = sorted({str(S["settings"].get("FSM_GAP_FILL_SEC")) for S in sessions})
    v2, f12, i18 = g("V2"), g("12"), g("18")
    L += ["", "## ② 목표를 두지 않는 값(수치만 · 통합문서 §4.1 「목표를 두지 않는 측정 값」)", "",
          f"- 2 헛경고 — 정상 판 하나당 {_f(sum(a16) / len(a16) if a16 else None, 2)}회(판 {len(a16)})",
          f"- 3 위반 판별 정밀도 — {_pct(g('3').get('k', 0), g('3').get('n', 0)) if g('3').get('script') else '대본 없음'}",
          f"- 5 사전 감지율 — {_pct(z.get('k5', 0), z.get('n', 0))} · 창 능력 상한 {_pct(z.get('kwin', 0), z.get('n', 0))}"
          f" · 구역 선행시간 중앙값 {_f(_med(z.get('leads', [])), 3, '초')} · 프레임 기록 없는 누름 {z.get('noframe', 0)}(뺌)",
          f"- 7 ROI 오분류 — {z.get('k7', 0)}건 / 눌림 {z.get('n', 0)}",
          f"- 13 FPS 끊김 — 최근 {fps.FPS_WINDOW}간격 FPS 최저 {_f(_min(f12.get('roll_min', [])), 1)}"
          f" · 목표(NFR-1) 미만 진입 {f12.get('low_n', 0)}회 · 이어진 최장 {_f(_max(f12.get('low_longest', [])), 2, '초')}"
          f" · 끊김({fps.STALE_SEC:g}초 이상) {len(f12.get('stalls', []))}회 · 합 {_f(sum(f12.get('stalls', [])), 1, '초')}"
          f" · 최장 {_f(_max(f12.get('stalls', [])), 1, '초')} · 시연이 10초마다 적은 FPS 중앙값 {_f(_med(f12.get('fps_ev', [])), 1)}",
          f"- 17ⓑ 공구 확인 소요 — 중앙값 {_f(_med(g('17b').get('times', [])), 2, '초')}(판 {len(g('17b').get('times', []))})"
          " · 쥠 확정 = 연속 확인 포함(④ 조건 「쥠 연속」)",
          f"- 18 입력 누락(표본만 · 판정은 다음 판) — 완주한 정상 판 {i18.get('runs', 0)} · 기대 누름 {i18.get('expect', 0)}"
          f" · 기록된 누름 {i18.get('got', 0)}",
          f"- 21 누름 카메라 확인 — {_pct(g('21').get('k', 0), g('21').get('n', 0))} · 누르기 전 중앙값"
          f" {_f(_med(g('21').get('before', [])), 0, 'ms')} · 경로 {g('21').get('why', {})} · 가짜 미확인 {g('21').get('fake', 0)}",
          f"- 23 스침 통과율 — {_pct(s23.get('pass_k', 0), s23.get('pass_n', 0))} · 대본 머묾 가운데 경고 {_pct(s23.get('stay_warned', 0), s23.get('stay_n', 0))}",
          f"- 25 경고 효과 — {_pct(g('25').get('k', 0), g('25').get('n', 0))}(경고 뒤 누름 없음 {g('25').get('none', 0)})",
          "- 26 단계별 시간(ms 중앙값/95%) — " + " · ".join(
              f"{s[:-3]} {_f(_med(st.get(s, [])), 1)}/{_f(_pq(st.get(s, []), 0.95), 1)}" for s in MC.STAGES + ("total_ms",)),
          f"- 27 받기↔처리 — 받은 {st.get('recv_n', 0)} · 처리 {st.get('proc_n', 0)}({_pct(st.get('proc_n', 0), st.get('recv_n', 0))})"
          f" · 처리한 프레임의 받은 간격 중앙값 {_f(_med(st.get('recv_iv', [])), 1, 'ms')} · 처리 끝 간격 중앙값 {_f(_med(st.get('done_iv', [])), 1, 'ms')}",
          f"- 28 손 놓침 공백 — 중앙값 {_f(_med(gaps), 3, '초')} · 90% {_f(_pq(gaps, 0.9), 3, '초')}"
          f" · 갭메우기({'·'.join(fills)}초 — 세션마다 그 세션 값) 이하 {_pct(g('28').get('le_fill', 0), len(gaps))}"
          f" · {MC.GAP_MAX_SEC:g}초 넘는 공백 {g('28').get('long', 0)}개는 뺐다(손을 떼고 돌아옴)",
          f"- 30 자원 — CPU 평균 중앙값 {_f(_med(g('30').get('cpu_avg', [])), 1, '%')} · CPU 최대 {_f(_max(g('30').get('cpu_max', [])), 1, '%')}"
          f" · 온도 최대 {_f(_max(g('30').get('temp', [])), 1, '℃')}",
          ("- V2 알림 정확도 — 음성 기록 없음" if v2.get("off") and not v2.get("trans") else
           f"- V2 알림 정확도 — 경고·차단 전이 {v2.get('trans', 0)} 가운데 알림 한 번 {v2.get('one', 0)} · 없음 {v2.get('zero', 0)}"
           f" · 여러 번 {v2.get('multi', 0)} · 정상 판 헛알림 {v2.get('normal', 0)}"),
          f"- V3 알림 끊기 — 중앙값 {_f(_med(g('V3').get('delays', [])), 3, '초')}(멈춤 없음 {g('V3').get('missing', 0)})",
          f"- V4 알림 길이 — 중앙값 {_f(_med(g('V4').get('lens', [])), 2, '초')}(알림 {len(g('V4').get('lens', []))}"
          f" · 중단된 재생 {g('V4').get('cut', 0)}은 뺌)",
          f"- V9 마이크 손실 — 받은/기대 바이트 중앙값 {_f(_med(g('V9').get('ratios', [])), 3)}"
          f" · 최저 {_f(_min(g('V9').get('ratios', [])), 3)}(10초 칸 {len(g('V9').get('ratios', []))})"
          + (" · 표본률을 못 읽은 세션 있음" if g("V9").get("norate") else "")]
    pd_, pdur = s23.get("press_dwell", []), s23.get("pass_dur", [])
    cv = MC.curve(pd_, pdur)
    L += ["", "## ③ 체류 두 곡선(발표 「판정 기준 근거」 · 23)", "",
          f"누름 구간 {len(pd_)} · 지나감 구간 {len(pdur)} · ⚠️ 경고는 안쪽 상자에서만 나지만(C1) 곡선은 링 포함 구간으로 잰다", "",
          "| 문턱(초) | 누르려던 손을 잡은 비율 | 스친 손을 거른 비율 |", "|---|---|---|"]
    L += [f"| {t:.2f} | {_f(a * 100 if a is not None else None, 1, '%')} | {_f(b * 100 if b is not None else None, 1, '%')} |"
          for t, a, b in cv]
    if curve:
        rng = MC.fit_range(cv, curve[0], curve[1])
        L.append(f"\n참고 기준 잡음 ≥ {curve[0]:.0%} · 거름 ≥ {curve[1]:.0%} → "
                 + (f"{rng[0]:.2f}~{rng[1]:.2f}초" if rng else "만족하는 문턱 없음") + "(기준의 정본 = 발표 설계 M8)")
    L.append("\n🔴 이 곡선으로 체류 임계를 고르면 그 세션은 판정용으로 쓰지 않는다(측정 설계 §4.2 사전 고정 — 조정용·판정용 분리)")
    L += ["", "## ④ 조건", ""]
    for S in sessions:
        i, s = S["info"].get("입력") or {}, S["settings"]
        L.append(f"- {S['name']} — 장소 {i.get('장소')} · {i.get('세션')} · {i.get('손')} · 사람 {i.get('사람')}"
                 f" · 조명 {i.get('조명') or '—'} · 대본 {i.get('대본') or '없음'} · 체류 {s.get('FSM_DWELL_THRESHOLD_SEC')}초"
                 f" · 갭메우기 {s.get('FSM_GAP_FILL_SEC')}초 · 버튼 모델 {os.path.basename(str(s.get('HEF_MODEL_PATH') or '—'))}"
                 f" · 공구 {s.get('TOOL_BACKEND')} {os.path.basename(str(s.get('TOOL_HEF_PATH') or ''))}"
                 f" · 쥠 연속 {s.get('TOOL_GRASP_CONFIRM_SCANS') or '—'}번 · 안경 {i.get('안경전원') or '—'}"
                 f" · 음성 {'켬' if S['info'].get('음성', True) else '끔'} · EMO {S['emo']}"
                 f" · 코드 {(S['info'].get('코드') or {}).get('Rpi5')}")
    return "\n".join(L) + "\n"


def _save(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="세기 — 측정 세션 폴더의 값을 낸다(측정 도구 정합 1단계-나)")
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--out", default="", help="여러 세션 통합값을 쓸 .md(같은 이름 .json 도)")
    ap.add_argument("--curve", default="", help="잡음,거름 — 예: 0.80,0.90(정본 = 발표 설계 M8)")
    a = ap.parse_args(argv)
    try:
        curve = tuple(float(x) for x in a.curve.split(",")) if a.curve else None
        if curve is not None and len(curve) != 2:
            raise ValueError
    except ValueError:
        ap.error("--curve 는 「잡음,거름」 꼴의 두 수다(예: 0.80,0.90)")
    targets = load_targets()
    below = fps_floor(targets)
    sessions, per = [], []
    for d in a.dirs:
        try:
            S = load_session(d)
        except (OSError, ValueError, KeyError) as e:
            print(f"❌ {d} — {e}")
            return 1
        sessions.append(S)
        per.append(MC.count_all(S, below))
    M = MC.merge(per)
    md = render(sessions, per, M, targets, curve)
    js = json.dumps({"targets": targets, "merged": M, "sessions": {S["name"]: p for S, p in zip(sessions, per)}},
                    ensure_ascii=False, indent=1, default=str)
    print(md)
    if len(sessions) == 1:
        _save(os.path.join(sessions[0]["dir"], "report.md"), md)
        _save(os.path.join(sessions[0]["dir"], "report.json"), js)
    if a.out:
        _save(a.out, md)
        _save(os.path.splitext(a.out)[0] + ".json", js)
    return 0


if __name__ == "__main__":
    sys.exit(main())
