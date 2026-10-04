"""실험 장부 — 결과 폴더(학습/결과/<id>/요약.json · 채점.json)에서 장부.md 를 다시 만든다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §8 · §10
- 장부를 손으로 고치지 않는다 — 결과 폴더가 단일 출처.
- 판정 = 같은 무리 · 같은 운용 조건(멈춤 규칙 · 나눔 해시 · conf · 판)의 E0(E0 · E0b … 시드 3개 · 정상 종료) 지표별
  최소~최대 범위 밖이면 ↑/↓ + 넘은 만큼, 안이면 =. 조건이 같은 E0 가 3개 미만이면 「기준 다름」(다른 조건의 E0 만 있음) · 「기준 부족」.
  조건 = 실험 변수(설정의 입력·학습 인자)가 아닌데 결과를 바꾸는 것 — E0 뒤 포화 문턱을 바꾼 경우를 막는다(최종 리뷰 C1).
- 이어 학습(요약 「이어서」)은 🔁 · 판정 「—」 · 기준에서 뺀다(patience 를 처음부터 다시 센다).
- E9-(점검) · SPEED-(속도 측정)은 넣지 않는다.
"""
import json
import re
from pathlib import Path

KEYS = {
    "button": [("P", lambda s: s["전체"]["precision"]), ("R", lambda s: s["전체"]["recall"])],
    "tool": [("dR", lambda s: s["클래스"]["driver"]["recall"]), ("wR", lambda s: s["클래스"]["wrench"]["recall"]),
             ("pR", lambda s: s["클래스"]["pliers"]["recall"]), ("P", lambda s: s["전체"]["precision"])],
}
SKIP = ("E9-", "SPEED-")
E0_RE = re.compile(r"^E0[a-z]?-")


def load_results(root):
    out = []
    for d in sorted(Path(root).iterdir()) if Path(root).exists() else []:
        s, c = d / "요약.json", d / "채점.json"
        if d.is_dir() and s.exists() and not d.name.startswith(SKIP):
            su = json.loads(s.read_text(encoding="utf-8"))
            cf = d / "설정.json"
            stop = json.loads(cf.read_text(encoding="utf-8")).get("멈춤") if cf.exists() else None
            su["조건"] = {"멈춤": stop, "나눔": (su.get("나눔") or {}).get("해시"), "conf": su.get("conf"), "판": su.get("판")}
            out.append((su, json.loads(c.read_text(encoding="utf-8")) if c.exists() else None))
    return out


def is_baseline(su):
    return bool(E0_RE.match(su["id"]))


def baseline_ranges(results, group, cond=None):
    """cond = 판정할 실험의 조건 — 같은 조건의 E0 만 기준으로 쓴다(None = 조건을 보지 않음)."""
    base = [sc for su, sc in results if is_baseline(su) and su["group"] == group and sc and not su.get("이상")
            and not su.get("이어서") and (cond is None or su.get("조건") == cond)]
    if len(base) < 3:
        return None
    return {name: (min(f(s) for s in base), max(f(s) for s in base)) for name, f in KEYS[group]}


def _gap(x):
    """넘은 만큼 — 아주 작게 넘어도 0 으로 보이지 않게(0.0001 미만은 다섯째 자리)."""
    return f"{x:.4f}" if x >= 0.0001 else f"{x:.5f}"


def judge(score, ranges, group, why="기준 부족"):
    if ranges is None:
        return why
    marks = []
    for name, f in KEYS[group]:
        v, (lo, hi) = f(score), ranges[name]
        marks.append(name + (f"↑+{_gap(v - hi)}" if v > hi else f"↓-{_gap(lo - v)}" if v < lo else "="))
    return " ".join(marks)


def adopt(cands, bases, group):
    """채택 판정 규칙(1-2단계 설계 §3 · 1단계 §15) — 지표마다 위로/아래로 갈림·겹침 · 채택 = 위로 갈림 하나 이상 · 아래로 갈림 없음."""
    if len(cands) < 3 or len(bases) < 3:
        raise ValueError("채택 판정은 후보·기준 각 3회 이상")
    out = {}
    for name, f in KEYS[group]:
        c, b = [f(s) for s in cands], [f(s) for s in bases]
        out[name] = "위로 갈림" if min(c) > max(b) else "아래로 갈림" if max(c) < min(b) else "겹침"
    return out, any(v == "위로 갈림" for v in out.values()) and "아래로 갈림" not in out.values()


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
             "> 판정 = 같은 무리 · 같은 운용 조건(멈춤 규칙 · 나눔 · conf · 판)의 E0 시드 3개 최소~최대 범위 밖이면 ↑/↓(+넘은 만큼), 안이면 =."
             " 조건이 같은 E0 가 3개 미만이면 「기준 다름」·「기준 부족」.",
             "> ⚠️ ↑/↓ 는 후보 표시이지 효과 판정이 아니다 — 시드 3개 범위라 효과가 없어도 지표마다 최대 약 절반이 범위 밖으로 나온다."
             " 채택 전에 시드를 더 돌려 범위가 겹치지 않는지 본다.",
             "> ⚠️ 학습률 감소·close_mosaic 일정은 epochs(최대 200)에 묶여 있다 — 일찍 멈춤·포화로 끝난 학습은 학습률이 거의 줄지 않고"
             " 모자이크도 끄지 않은 채 끝난다(설계 §3.2 함정⑤). 에폭을 정해 일정을 끝까지 도는 최종 학습에 그대로 옮겨진다는 보장이 없다.",
             "> 🔁 = 끊긴 뒤 이어 학습한 실험 — 일찍 멈춤 카운트를 처음부터 다시 세어 기준과 견줄 수 없으므로 판정하지 않고 기준에서도 뺀다(새 id 로 다시 돌린다).", "",
             "| id | 무리 | 입력 | 바꾼 것 | 종료 | 에폭(best/끝) | 분 | 지표 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for su, sc in sorted(results, key=lambda r: r[0]["id"]):
        g = su["group"]
        ind = metrics_text(sc, g) if sc else "—"
        if su.get("이어서"):                    # 이어 학습은 patience 를 처음부터 다시 세어 기준과 견줄 수 없다
            jd = "—"
        elif is_baseline(su):
            jd = "기준"
        elif sc and not su.get("이상"):
            other = any(is_baseline(b) and b["group"] == g and not b.get("이어서") for b, _ in results)
            jd = judge(sc, baseline_ranges(results, g, su.get("조건")), g, "기준 다름" if other else "기준 부족")
        else:
            jd = "—"
        end = su.get("종료이유", "?") + (" 🔴" if su.get("이상") else "") + (" 🔁이어서" if su.get("이어서") else "")
        lines.append(f"| {su['id']} | {g} | {su.get('입력', '?')} | {su.get('바꾼것', '?')} | {end} | "
                     f"{su.get('best_epoch', '?')}/{su.get('에폭', '?')} | {su.get('분', 0):.0f} | {ind} | {jd} |")
    return "\n".join(lines) + "\n"


def rebuild(results_root, ledger_path):
    Path(ledger_path).write_text(render(load_results(results_root)), encoding="utf-8")
