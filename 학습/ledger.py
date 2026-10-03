"""실험 장부 — 결과 폴더(학습/결과/<id>/요약.json · 채점.json)에서 장부.md 를 다시 만든다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §8 · §10
- 장부를 손으로 고치지 않는다 — 결과 폴더가 단일 출처.
- 판정 = 같은 무리 E0(시드 3개 · 정상 종료)의 지표별 최소~최대 범위 밖이면 ↑/↓, 안이면 =. E0 가 3개 미만이면 「기준 부족」.
- E9-(점검) · SPEED-(속도 측정)은 넣지 않는다.
"""
import json
from pathlib import Path

KEYS = {
    "button": [("P", lambda s: s["전체"]["precision"]), ("R", lambda s: s["전체"]["recall"])],
    "tool": [("dR", lambda s: s["클래스"]["driver"]["recall"]), ("wR", lambda s: s["클래스"]["wrench"]["recall"]),
             ("pR", lambda s: s["클래스"]["pliers"]["recall"]), ("P", lambda s: s["전체"]["precision"])],
}
SKIP = ("E9-", "SPEED-")


def load_results(root):
    out = []
    for d in sorted(Path(root).iterdir()) if Path(root).exists() else []:
        s, c = d / "요약.json", d / "채점.json"
        if d.is_dir() and s.exists() and not d.name.startswith(SKIP):
            out.append((json.loads(s.read_text(encoding="utf-8")),
                        json.loads(c.read_text(encoding="utf-8")) if c.exists() else None))
    return out


def baseline_ranges(results, group):
    base = [sc for su, sc in results if su["id"].startswith(f"E0-{group}-") and sc and not su.get("이상")]
    if len(base) < 3:
        return None
    return {name: (min(f(s) for s in base), max(f(s) for s in base)) for name, f in KEYS[group]}


def judge(score, ranges, group):
    if ranges is None:
        return "기준 부족"
    marks = []
    for name, f in KEYS[group]:
        v, (lo, hi) = f(score), ranges[name]
        marks.append(name + ("↑" if v > hi else "↓" if v < lo else "="))
    return " ".join(marks)


def metrics_text(sc, group):
    if group == "button":
        return f"P {sc['전체']['precision']:.3f} · R {sc['전체']['recall']:.3f} · 오분류 {sc['오분류']} · 오검출 {sc['오검출']}"
    c = sc["클래스"]
    return (f"R d {c['driver']['recall']:.3f} · w {c['wrench']['recall']:.3f} · p {c['pliers']['recall']:.3f}"
            f" · P {sc['전체']['precision']:.3f}")


def render(results):
    lines = ["# 실험 장부", "",
             "> 자동 생성 — `학습.py 받기` 가 결과 폴더에서 다시 만든다. 손으로 고치지 않는다.",
             "> 🔴 1단계 수치는 「장소1 참고값 · 같은 날 · 공구 채점 양성 한 세션 · 채점 라벨 = 형제 모델 초벌 흐름 · .pt(HEF 전)」 조건과 함께 인용한다(설계 §8).",
             "> 판정 = 같은 무리 E0 시드 3개의 최소~최대 범위 밖이면 ↑/↓, 안이면 =.", "",
             "| id | 무리 | 입력 | 바꾼 것 | 종료 | 에폭(best/끝) | 분 | 지표 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|"]
    ranges = {g: baseline_ranges(results, g) for g in KEYS}
    for su, sc in sorted(results, key=lambda r: r[0]["id"]):
        g = su["group"]
        ind = metrics_text(sc, g) if sc else "—"
        if su["id"].startswith("E0-"):
            jd = "기준"
        else:
            jd = judge(sc, ranges[g], g) if sc and not su.get("이상") else "—"
        end = su.get("종료이유", "?") + (" 🔴" if su.get("이상") else "")
        lines.append(f"| {su['id']} | {g} | {su.get('입력', '?')} | {su.get('바꾼것', '?')} | {end} | "
                     f"{su.get('best_epoch', '?')}/{su.get('에폭', '?')} | {su.get('분', 0):.0f} | {ind} | {jd} |")
    return "\n".join(lines) + "\n"


def rebuild(results_root, ledger_path):
    Path(ledger_path).write_text(render(load_results(results_root)), encoding="utf-8")
