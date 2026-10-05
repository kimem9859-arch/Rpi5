"""모델·실험 이름 — 버튼 B · 공구 T · 학습 방식 · 바꾼 것 · 시드 · 변환 방식.

정본 설계 = 상위 docs/superpowers/specs/2026-10-05-모델이름-정리-design.md §2 · 설명·규칙 정본 = 통합문서 §6.4.
- 새 꼴 = <B|T>-<early|full|check>-<바꾼 것>[-<꼬리>]-s<시드> · 옛 꼴 = E<번호>[a-z]-<button|tool>-<이름>(기록만).
- 🔴 B·T 바로 뒤에 숫자를 붙이지 않는다 — B1~B4 는 버튼 종류 이름이다.
- 옛 이름은 바꾸지 않고 new_name 으로 새 이름을 얻는다(대조표 = 학습/이름대조표.md · `학습.py 이름표` 가 만든다).
- 변환 모델 파일 = <학습 모델 새 이름>_<변환 방식>.hef.
시스템 python3 로 돈다 — 표준 라이브러리만.
"""
import json
import re
from pathlib import Path

OLD_RE = re.compile(r"^E(\d+)([a-z]?)-(button|tool)-([A-Za-z0-9.]+)\Z")             # \Z — $ 는 끝 줄바꿈 하나를 허용한다
NEW_RE = re.compile(r"^([BT])-(early|full|check)-([A-Za-z0-9.]+)(?:-(old|albu))?-s(0|[1-9]\d*)\Z")   # 꼬리는 TAGS 의 둘뿐
ID_RE = re.compile(r"^(?:E\d+[a-z]?-(?:button|tool)-[A-Za-z0-9.]+|[BT]-(?:early|full|check)-[A-Za-z0-9.]+(?:-(?:old|albu))?-s(?:0|[1-9]\d*))\Z")  # 옛 꼴 | 새 꼴
GROUP = {"B": "button", "T": "tool"}
PREFIX = {v: k for k, v in GROUP.items()}
TAGS = {"E0": "old", "E13": "albu"}            # 같은 이름이 둘 생기는 기준만 — old = 옛 포화 문턱 · albu = 증강 라이브러리 설치 뒤
METHODS = ("ours-L2", "ours-L1", "zoo", "ultra")
_SMOKE = re.compile(r"^(?:E8-(?:button|tool)-T0t|[BT]-\w+-S0t)\d+")   # 탐색 스모크 = 회차 0(옛 T0 · 새 S0)


def is_valid(i):
    return bool(ID_RE.match(i))


def group_of(i):
    m = NEW_RE.match(i)
    if m:
        return GROUP[m.group(1)]
    m = OLD_RE.match(i)
    return m.group(3) if m else None


def regime_of(i):
    m = NEW_RE.match(i)
    return m.group(2) if m else None


def seed_of(i):
    m = NEW_RE.match(i)
    return int(m.group(5)) if m else None


def skipped(i):
    """받기·장부에서 뺀다 — 점검(E9 · check) · 속도 측정 · 탐색 스모크(T0 = 새 이름 S0)."""
    return i.startswith(("E9-", "SPEED-")) or bool(_SMOKE.match(i)) or regime_of(i) == "check"


def new_name(old, 포화_향상, seed):
    """옛 이름 → 새 이름. 학습 방식 = 멈춤 조건(포화_향상 0 → full · 아니면 early · E9 = check)."""
    if NEW_RE.match(old):
        return old
    m = OLD_RE.match(old)
    if not m:
        raise ValueError(f"이름 꼴이 아니다: {old!r}")
    num, sub, group, rest = m.groups()
    s = re.search(r"s(\d+)$", rest)
    if s:
        if int(s.group(1)) != int(seed):
            raise ValueError(f"{old}: 이름의 시드 {s.group(1)} ≠ 실제 시드 {seed}")
        rest = rest[:s.start()]
    regime = "check" if num == "9" else ("full" if float(포화_향상) == 0 else "early")
    rest = re.sub(r"^f120", "", rest)                       # 120 끝까지는 학습 방식(full)이 말한다
    rest = {"both": "in1024lr0005"}.get(rest, rest)
    rest = re.sub(r"^T(\d+)t", r"S\1t", rest)               # 탐색 회차 T<n> → S<n>(T 는 공구)
    rest = re.sub(r"^t(\d{3})$", r"S1t\1", rest)            # E10 = 탐색 1회차 시도의 시드 확인
    tag = TAGS.get(f"E{num}{sub}")
    return f"{PREFIX[group]}-{regime}-{rest or 'base'}" + (f"-{tag}" if tag else "") + f"-s{int(seed)}"


def name_for(i, results_dir):
    """id → 새 이름. 옛 꼴은 결과 설정.json 의 멈춤 조건·시드로 바꾼다(결과가 없으면 FileNotFoundError)."""
    if NEW_RE.match(i):
        return i
    c = json.loads((Path(results_dir) / i / "설정.json").read_text(encoding="utf-8"))
    return new_name(i, c["멈춤"]["포화_향상"], c["train_kwargs"]["seed"])


def ours(level):
    return f"ours-L{int(level)}"


def hef_file(model, method):
    if method not in METHODS:
        raise ValueError(f"모르는 변환 방식 {method!r} — {METHODS}")
    return f"{model}_{method}.hef"
