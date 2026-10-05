"""학습 나눔 — 세션마다 프레임 순서로 학습 / 학습 중 검증 / 떼어 둔 20% 로 자르고, 몫이 바뀌는 경계에 빈 구간을 둔다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §5
- 떼어 둔 20% = tool_round.split_holdout 과 같은 규칙(세션마다 프레임 순서 마지막 20% · 올림) — 채점 목록은 반드시 그 안에 있다.
- 채점 목록에 없는 떼어 둔 사진(b001~b003)은 어느 몫에도 넣지 않는다(unused).
- 학습 중 검증 = 세션 전체 장수의 10%(올림)를 떼어 둔 20% 바로 앞에서 · 세션 사진이 20장 미만이면 떼지 않는다.
- 빈 구간 = 다음 몫의 첫 프레임 번호보다 GAP 이내로 앞선 사진을 앞 몫에서 뺀다(gap).
- 배경 줄이기 = 무리마다 학습 몫에서만(학습 중 검증·채점은 그대로).
- 나눔 파일은 덮어쓰지 않는다 — 사진이 늘면 새 판.
- 세션 보류 판(hold_session) = 한 세션을 버튼 학습·검증에서 통째로 빼 「처음 보는 세션」으로 채점(1-3단계 §4).
시스템 python3 로 돈다.
"""
import hashlib
import json
import math
import random
from pathlib import Path

HOLD_FRAC = 0.2
VAL_FRAC = 0.1
VAL_MIN_SESSION = 20
GAP = 36
BG_FRAC = 0.10
BG_SEED = 20261003
GROUPS = ("button", "tool")


def session_of(name):
    return name.split("__f")[0]


def frame_no(name):
    return int(name.split("__f")[1])


def three_way(names, test_names):
    """이름 → {"train", "val", "test", "gap", "unused"}(각각 정렬).
    채점 목록에 원본에 없는 이름이나 떼어 둔 20% 밖의 이름이 있으면 ValueError."""
    names, test_set = list(names), set(test_names)
    missing = sorted(test_set - set(names))
    if missing:
        raise ValueError(f"채점 목록에 원본에 없는 이름 {len(missing)}개: {missing[:3]}")
    by = {}
    for n in names:
        by.setdefault(session_of(n), []).append(n)
    out = {k: [] for k in ("train", "val", "test", "gap", "unused")}
    for s in sorted(by):
        xs = sorted(by[s], key=frame_no)
        cut = len(xs) - math.ceil(len(xs) * HOLD_FRAC)
        front, hold = xs[:cut], xs[cut:]
        k = min(math.ceil(len(xs) * VAL_FRAC), len(front)) if len(xs) >= VAL_MIN_SESSION else 0
        tr, va = front[:len(front) - k], front[len(front) - k:]
        b_hold = frame_no(hold[0]) if hold else None
        b_next = frame_no(va[0]) if va else b_hold
        for x in tr:
            out["gap" if b_next is not None and b_next - frame_no(x) <= GAP else "train"].append(x)
        for x in va:
            out["gap" if b_hold is not None and b_hold - frame_no(x) <= GAP else "val"].append(x)
        for x in hold:
            out["test" if x in test_set else "unused"].append(x)
    outside = sorted(test_set - set(out["test"]))
    if outside:
        raise ValueError(f"채점 목록 {len(outside)}장이 떼어 둔 20% 밖이다: {outside[:3]}")
    return {k: sorted(v) for k, v in out.items()}


def cap_background(train, is_bg, frac=BG_FRAC, seed=BG_SEED):
    """학습 몫의 배경(그 무리 물체가 없는 사진)을 전체의 frac 이 되게 줄인다(무작위 · 시드 고정).
    반환 = (남긴 목록, 뺀 배경 목록) — 둘 다 정렬. 배경이 이미 그보다 적으면 그대로."""
    bg = sorted(n for n in train if is_bg(n))
    pos = len(train) - len(bg)
    keep = set(random.Random(seed).sample(bg, min(round(pos * frac / (1 - frac)), len(bg))))
    dropped = sorted(set(bg) - keep)
    return sorted(set(train) - set(dropped)), dropped


def split_hash(d):
    body = {k: v for k, v in d.items() if k != "해시"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def make_split(name, names, test_names, labels_of):
    """labels_of(이름, 무리) → 그 무리 라벨 줄 목록(빈 목록 = 배경). 반환 = 나눔 사전(해시 포함)."""
    w = three_way(names, test_names)
    d = {"나눔": name,
         "규칙": {"HOLD_FRAC": HOLD_FRAC, "VAL_FRAC": VAL_FRAC, "VAL_MIN_SESSION": VAL_MIN_SESSION,
                 "GAP": GAP, "BG_FRAC": BG_FRAC, "BG_SEED": BG_SEED},
         "공통": {"val": w["val"], "test": w["test"], "gap": w["gap"], "unused": w["unused"]}}
    for g in GROUPS:
        kept, dropped = cap_background(w["train"], lambda n, g=g: not labels_of(n, g))
        d[g] = {"train": kept, "bg_dropped": dropped}
    d["해시"] = split_hash(d)
    return d


def save_split(d, path):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"나눔 판은 덮어쓰지 않는다 — 새 판 이름으로: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def load_split(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if split_hash(d) != d.get("해시"):
        raise ValueError(f"나눔 파일 해시가 다르다(손으로 고쳤나?): {path}")
    return d


def hold_session(d, session, all_names, name):
    """버튼 전용 새 판 — 세션 하나를 버튼 학습·공통 검증에서 빼고 「처음 보는 세션」 채점 몫으로(1-3단계 설계 §4).
    공구 몫·기존 채점은 그대로(공구는 이 판을 쓰지 않는다 — 걸기가 막는다). all_names = 세션 채점 몫을 고를 사진 목록 —
    1-3 호출은 바탕판의 사진만(names_of(바탕판) · 사용자 A — 원본 목록 전체를 주면 새 묶음 b010 이 섞인다).
    ⚠️ 배경 비율은 다시 맞추지 않는다 — 세션의 버튼 사진만 빠져 place1_v2b 버튼 학습 배경이 9.98% → 11.84%(1-3 최종 리뷰 I1)."""
    import copy
    h = copy.deepcopy(d)
    h["나눔"] = name
    h["규칙"] = {**d["규칙"], "세션보류": session, "바탕판": d["나눔"]}
    h["button"]["train"] = [n for n in d["button"]["train"] if session_of(n) != session]
    h["공통"]["val"] = [n for n in d["공통"]["val"] if session_of(n) != session]
    h["button"]["test_session"] = sorted(n for n in all_names if session_of(n) == session)
    h["해시"] = split_hash(h)
    return h


def names_of(d):
    """나눔 판에 나오는 이름 전부(몫 · 빈 구간 · 안 씀 · 뺀 배경 · 세션 채점) — 그 판의 사진 범위."""
    out = set()
    for k in ("val", "test", "gap", "unused"):
        out |= set(d["공통"][k])
    for g in GROUPS:
        for k in ("train", "bg_dropped", "test_session"):
            out |= set(d.get(g, {}).get(k, []))
    return sorted(out)


def session_test(d, group):
    """→ 세션 보류 채점 몫(없는 판 = 빈 목록)."""
    return list(d.get(group, {}).get("test_session", []))


def lists_for(d, group):
    """→ (학습, 학습 중 검증, 채점) — 한 무리의 몫."""
    return d[group]["train"], d["공통"]["val"], d["공통"]["test"]
