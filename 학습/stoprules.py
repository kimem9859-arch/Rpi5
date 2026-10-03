"""학습 멈춤 규칙 — 순수 함수(학습 콜백 · 실행기 · 속도 측정이 같이 쓴다).

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §7
- ultralytics 일찍 멈춤은 최고점이 조금이라도 오르면 카운트가 처음으로 돌아간다(8.4.171 EarlyStopping · 최소 향상폭 없음) → 포화로 막는다.
- fitness = mAP50-95 하나(8.4.171 metrics.py w=[0,0,0,1]) — 가장 좋은 에폭도 그 열로 고른다.
표준 라이브러리만 쓴다.
"""
FIT = "metrics/mAP50-95(B)"


def saturated(best_hist, window, min_gain):
    """best_hist[i] = (i+1) 에폭까지의 최고 fitness. 최근 window 에폭 동안 최고점이 min_gain 미만으로만 올랐으면 True."""
    if len(best_hist) <= window:
        return False
    return best_hist[-1] - best_hist[-1 - window] < min_gain


def zero_score(epoch, map50, at_epoch, thr):
    """at_epoch 에폭(1부터)을 마쳤는데 학습 중 검증 mAP50 이 thr 미만이면 True — 학습이 안 되는 중."""
    return epoch == at_epoch and map50 < thr


def csv_rows(text):
    """ultralytics results.csv 내용 → 에폭마다 {열 이름: 값(float)} (빈 줄 무시)."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        r = {}
        for h, v in zip(head, line.split(",")):
            try:
                r[h] = float(v)
            except ValueError:
                pass
        rows.append(r)
    return rows


def best_epoch(rows):
    """fitness 가 가장 높은 에폭(1부터 · 같으면 앞) — 없으면 None."""
    vals = [r.get(FIT, float("-inf")) for r in rows]
    return vals.index(max(vals)) + 1 if vals else None


def fitness_history(rows):
    out, best = [], float("-inf")
    for r in rows:
        best = max(best, r.get(FIT, float("-inf")))
        out.append(best)
    return out


def stalled(last_progress, now, minutes):
    return now - last_progress > minutes * 60


def time_limit_s(sec_per_epoch, max_epochs, factor):
    return sec_per_epoch * max_epochs * factor


def over_time(started, now, limit_s):
    return limit_s is not None and now - started > limit_s
