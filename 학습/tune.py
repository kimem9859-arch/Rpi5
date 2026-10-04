"""탐색기 — Optuna TPE 로 학습 방식을 탐색한다(1-2단계 설계 §5). 데스크톱 ~/학습실험/venv 에서 독립 프로세스로 돈다.

시도 = 1단계 실행기 대기열의 작업 하나 · 목표 = 검증 몫 종류별 재현율 평균(요약 「검증목표」) · 기록 = 탐색/<이름>/시도.jsonl · study.db.
optuna 는 main() 안에서만 import 한다(파이 selftest 는 optuna 없이 순수 함수만 시험).
"""
import json
from pathlib import Path


def suggest(trial, space):
    out = {}
    for k, spec in space.items():
        if spec[0] == "log":
            out[k] = trial.suggest_float(k, spec[1], spec[2], log=True)
        elif spec[0] == "cat":
            out[k] = trial.suggest_categorical(k, spec[1])
        else:
            raise ValueError(f"모르는 범위 종류: {k} {spec[0]}")
    return out


def trial_id(group, study, n):
    return f"E8-{group}-{study}t{n:03d}"


def _fmt(v):
    return f"{v:.3g}" if isinstance(v, float) else str(v)


def job_for(template, study, n, params):
    job = json.loads(json.dumps(template, ensure_ascii=False))
    job["id"] = trial_id(job["group"], study, n)
    job["train_kwargs"].update(params)
    job["바꾼것"] = " · ".join(f"{k}={_fmt(v)}" for k, v in params.items())
    job["설정"]["id"] = job["id"]
    job["설정"].setdefault("train", {}).update(params)
    job["탐색"] = {"이름": study, "번호": n}
    return job


def finished(rd):
    """요약과 검증 채점이 모두 있어야 끝(이상 종료는 요약만으로 끝)."""
    rd = Path(rd)
    sp = rd / "요약.json"
    if not sp.exists():
        return None
    su = json.loads(sp.read_text(encoding="utf-8"))
    if su.get("이상"):
        return {"상태": "이상", "목표": None, "검증P": None}
    if not (rd / "채점_검증.json").exists():
        return None
    return {"상태": "끝", "목표": su["검증목표"], "검증P": su["검증P"]}


def pending(log_rows):
    """시도 기록에서 아직 안 끝난 시도 — 끊겼다 다시 뜬 탐색기가 마저 읽는다."""
    last = {}
    for r in log_rows:
        last[r["번호"]] = r
    return [r for _, r in sorted(last.items()) if r["상태"] == "걸음"]


def should_stop(rows, base_min, startup=10, max_bad=3):
    """중단 규칙(설계 §5.3) — 첫 startup 회 중 이상 종료 max_bad 회 이상 · 또는 끝난 목표값이 모두 기준 검증 최저 아래."""
    first = sorted(rows, key=lambda r: r["번호"])[:startup]
    if len(first) < startup:
        return None
    bad = sum(r["상태"] == "이상" for r in first)
    if bad >= max_bad:
        return f"첫 {startup}회 중 이상 종료 {bad}회 — 범위를 다시 정한다"
    done = [r["목표"] for r in first if r["상태"] == "끝"]
    if done and all(v < base_min for v in done):
        return f"첫 {startup}회 목표값이 모두 기준 검증 최저({base_min}) 아래 — 범위를 다시 정한다"
    return None


def pick_top(rows, k, p_floor):
    """상위 k 개 — 검증 정밀도가 기준 최저보다 낮은 시도는 뺀다(설계 §5.2)."""
    ok = [r for r in rows if r["상태"] == "끝" and r["검증P"] is not None and r["검증P"] >= p_floor]
    return sorted(ok, key=lambda r: -r["목표"])[:k]


def base_floor(root, base_ids):
    """기준(E0c 등)의 검증 목표·정밀도 최저 — 중단 규칙과 상위 거르기에 쓴다."""
    vals = [finished(Path(root) / "runs" / i) for i in base_ids]
    if any(v is None or v["상태"] != "끝" for v in vals):
        raise ValueError(f"기준의 검증 채점이 없다: {base_ids}")
    return min(v["목표"] for v in vals), min(v["검증P"] for v in vals)
