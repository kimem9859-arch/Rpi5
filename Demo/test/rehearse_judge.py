"""리허설 판정 규칙 · 세션 지표 · 결과표 — 집 값을 ❌ 이상 · ⚠️ 애매 · 🟡 임시 · ✅ 확정으로 가른다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §7.3(세 종류) · §7.4(판정 규칙)
🔴 순수 모듈 — 장치 · Qt 없음. ❌ · ⚠️ 는 학교에서 꼭 다시 잰다(사용자 「애매하거나 수치가 이상하다 싶으면 … 학교 하드웨어로 꼭」).
item = {"id", "title", "kind": 확정|임시|흐름, "finished", "errors", "warnings", "values": {이름: [1회, 2회]},
        "expect": {이름: (lo, hi)}, "samples": {이름: (n, 최소)}, "script": (대본 판 수, 실제 판 수) | None,
        "same": bool | None, "phys": [(설명, 참거짓)], "split": (이름A, 이름B) | None, "home": 집 조건 한 줄}
"""
import csv
import datetime
import os

TWICE_PCT = 10.0      # 두 번 잰 값의 차이가 이보다 크면 애매(작은 값 기준 %)
MUST = ("❌", "⚠️", "🟡")


def _csv(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def session_stats(d):
    """세션 폴더 → 장 수 · 처리 fps · 받은 fps · 판 수(run_start) — 기록이 모자라면 None."""
    fr = [r for r in _csv(os.path.join(d, "frames.csv")) if _f(r.get("t_recv_ms")) is not None]
    out = {"frames": len(fr), "proc_fps": None, "recv_fps": None, "runs": 0}
    if len(fr) >= 2:
        t0, t1 = _f(fr[0]["t_recv_ms"]), _f(fr[-1]["t_recv_ms"])
        sec = (t1 - t0) / 1000
        if sec > 0:
            out["proc_fps"] = (len(fr) - 1) / sec
            s0, s1 = _f(fr[0].get("recv_seq")), _f(fr[-1].get("recv_seq"))
            if s0 is not None and s1 is not None:
                out["recv_fps"] = (s1 - s0) / sec
    out["runs"] = sum(1 for r in _csv(os.path.join(d, "events.csv")) if r.get("kind") == "run_start")
    return out


def judge(it):
    """→ (표시, [이유]) — ❌ 가 하나라도 있으면 ❌(이유는 ⚠️ 것까지) · 그다음 ⚠️ · 아니면 종류대로."""
    bad, vague = [], []
    if not it.get("finished", True):
        bad.append("끝까지 못 돎")
    for e in it.get("errors") or ():
        bad.append(f"오류: {e}")
    if it.get("same") is False:
        bad.append("확정 비교에서 다름")
    sc = it.get("script")
    if sc and sc[0] != sc[1]:
        bad.append(f"판 수 — 대본 {sc[0]} · 실제 {sc[1]}")
    for desc, ok in it.get("phys") or ():
        if not ok:
            bad.append(f"물리적으로 안 되는 값 — {desc} 이(가) 아님")
    values = it.get("values") or {}
    for name, vals in values.items():
        if not vals or any(v is None or v <= 0 for v in vals):
            bad.append(f"{name} 값 없음 · 0 · 음수 {vals}")
            continue
        if len(vals) >= 2:
            a, b = vals[0], vals[1]
            pct = abs(a - b) / min(a, b) * 100
            if pct > TWICE_PCT:
                vague.append(f"{name} 두 번 차이 {pct:.0f}%")
        rng = (it.get("expect") or {}).get(name)
        if rng and any(not (rng[0] <= v <= rng[1]) for v in vals):
            vague.append(f"{name} 기대 범위 {rng[0]}~{rng[1]} 밖 {vals}")
    for name, (n, least) in (it.get("samples") or {}).items():
        if n < least:
            vague.append(f"표본 부족 — {name} {n} < {least}")
    for w in it.get("warnings") or ():
        vague.append(f"경고: {w}")
    sp = it.get("split")
    if sp and all(values.get(k) and None not in values[k] for k in sp):
        va, vb = values[sp[0]], values[sp[1]]
        diff = abs(sum(vb) / len(vb) - sum(va) / len(va))
        spread = max(max(va) - min(va), max(vb) - min(vb))
        if diff <= spread:
            vague.append(f"효과가 안 갈림 — {sp[0]} {va} · {sp[1]} {vb}(차이 {diff:.2f} ≤ 흩어짐 {spread:.2f})")
    if bad:
        return "❌", bad + vague
    if vague:
        return "⚠️", vague
    return ("🟡" if it.get("kind") == "임시" else "✅"), []


def _vals(it):
    parts = []
    for name, vals in (it.get("values") or {}).items():
        shown = " · ".join("—" if v is None else (f"{v:.1f}" if isinstance(v, float) else str(v)) for v in vals)
        parts.append(f"{name} {shown}")
    return " / ".join(parts) or "—"


def _rng(it):
    return " / ".join(f"{k} {lo}~{hi}" for k, (lo, hi) in (it.get("expect") or {}).items()) or "—"


def write_table(items, path, school_cmds=None, title=None):
    """결과표(마크다운) — 맨 위 「학교 필수」(❌ · ⚠️ · 🟡) · 아래 전 항목. → [(id, 표시, 이유)]."""
    school_cmds = school_cmds or {}
    judged = [(it, *judge(it)) for it in items]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    esc = lambda s: str(s).replace("|", "\\|")          # noqa: E731
    out = [f"# 리허설 결과 — {title or now}", "",
           "> 집 · 가짜 장치(카메라 · 안경 소리 · 인터락) 조건 — 집 값은 「예상」일 뿐, 학교 값이 본 값이다(설계 D16).",
           "> ❌ 이상 · ⚠️ 애매 = 학교에서 **꼭** 다시 잰다 · 🟡 임시 = 어차피 학교 값이 본 값 · ✅ 확정 = 학교에서는 선택.",
           "", "## 학교 필수", "", "| 항목 | 판정 | 이유 | 학교 짝 명령 |", "|---|---|---|---|"]
    for it, mark, why in judged:
        if mark in MUST:
            out.append(f"| {it['id']} {esc(it.get('title', ''))} | {mark} | {esc(' · '.join(why) or '임시 값')} "
                       f"| {esc(school_cmds.get(it['id'], '—'))} |")
    out += ["", "## 항목", "",
            "| 항목 | 이름 | 종류 | 집 값(두 번) | 기대 범위 | 판정 | 이유 | 학교 짝 명령 |", "|---|---|---|---|---|---|---|---|"]
    for it, mark, why in judged:
        out.append(f"| {it['id']} | {esc(it.get('title', ''))} | {it.get('kind', '')} | {esc(_vals(it))} | {esc(_rng(it))} "
                   f"| {mark} | {esc(' · '.join(why) or '—')} | {esc(school_cmds.get(it['id'], '—'))} |")
    notes = [f"- {it['id']}: {it['home']}" for it, _, _ in judged if it.get("home")]
    if notes:
        out += ["", "## 집 조건", ""] + notes
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return [(it["id"], mark, why) for it, mark, why in judged]
