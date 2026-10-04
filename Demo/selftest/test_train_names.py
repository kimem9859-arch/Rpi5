"""모델·실험 이름(학습/이름.py) — 버튼 B · 공구 T · 학습 방식 · 바꾼 것 · 시드 · 변환 방식.

실행: python3 Demo/selftest/test_train_names.py
정본 설계: 상위 docs/superpowers/specs/2026-10-05-모델이름-정리-design.md §2
"""
import json
import os
import re
import sys
from pathlib import Path

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import 이름 as N

RES = Path(_RPI5) / "학습" / "결과"
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


def test_대표():
    print("[n1] 옛 이름 → 새 이름 대표 대응(설계 §2.2)")
    cases = [("E0b-button-s0", 0.002, 0, "B-early-base-s0"), ("E0b-tool-s2", 0.002, 2, "T-early-base-s2"),
             ("E0-tool-s1", 0.005, 1, "T-early-base-old-s1"), ("E0c-tool-f120", 0, 0, "T-full-base-s0"),
             ("E0c-tool-f120s2", 0, 2, "T-full-base-s2"), ("E13-tool-base", 0, 0, "T-full-base-albu-s0"),
             ("E15-button-bases1", 0, 1, "B-full-base-s1"), ("E4c-tool-f120lr0005s1", 0, 1, "T-full-lr0005-s1"),
             ("E7c-tool-f120both", 0, 0, "T-full-in1024lr0005-s0"), ("E8-tool-T1t002", 0, 0, "T-full-S1t002-s0"),
             ("E10-tool-t002s1", 0, 1, "T-full-S1t002-s1"), ("E9-button-sat", 1.0, 0, "B-check-sat-s0"),
             ("E2-button-color", 0.002, 0, "B-early-color-s0"), ("B-full-color-s2", 0, 2, "B-full-color-s2")]
    for old, sat, seed, want in cases:
        got = N.new_name(old, sat, seed)
        check(got == want, f"{old} → {want} — {got}")
    check(raises(lambda: N.new_name("E0b-button-s1", 0.002, 0)), "이름의 시드 ≠ 실제 시드 → ValueError")
    check(raises(lambda: N.new_name("console_v2", 0, 0)), "이름 꼴이 아니면 → ValueError")


def test_전체():
    print("[n2] 지금 결과 폴더 전부 — 겹침 0 · B/T 뒤 숫자 없음 · 학습 방식 = 실제 멈춤 조건")
    names, wrong = {}, []
    for d in sorted(RES.iterdir()):
        if not (d / "설정.json").exists():
            continue
        c = json.loads((d / "설정.json").read_text(encoding="utf-8"))
        n = N.name_for(d.name, RES)
        names[d.name] = n
        if ("-full-" in n) != (c["train_kwargs"]["patience"] == 0):
            wrong.append(d.name)
    check(len(names) >= 95, f"결과 {len(names)}개")
    check(len(set(names.values())) == len(names), "새 이름 겹침 0")
    check(not [v for v in names.values() if re.match(r"^[BT]\d", v)], "B·T 바로 뒤 숫자 없음(버튼 종류 B1~B4 와 겹침 방지)")
    check(not wrong, f"학습 방식 ↔ 실제 patience 어긋남 0 — {wrong[:3]}")


def test_꼴():
    print("[n3] 새 꼴 · 옛 꼴 · 무리 · 학습 방식 · 시드")
    check(all(N.is_valid(x) for x in ["B-full-color-s0", "T-early-base-old-s1", "E0b-button-s0", "T-full-S1t002-s2"]), "새 꼴·옛 꼴 통과")
    bad = ["B1-full-color-s0", "B-fast-color-s0", "B-full-color", "X-full-color-s0", "B-full-color-s0\n", "B-full-color-OLD-s0"]
    check(not any(N.is_valid(x) for x in bad), "B 뒤 숫자 · 모르는 방식 · 시드 없음 · 모르는 접두 · 끝 줄바꿈 · 대문자 꼬리 거부")
    check(N.group_of("T-full-base-s0") == "tool" and N.group_of("E0b-button-s0") == "button" and N.group_of("x") is None, "무리")
    check(N.regime_of("B-check-sat-s0") == "check" and N.regime_of("E0b-button-s0") is None, "학습 방식(새 꼴만)")
    check(N.seed_of("B-full-color-s2") == 2 and N.seed_of("E0b-button-s2") is None, "시드(새 꼴만)")


def test_건너뛰기():
    print("[n4] 받기·장부에서 뺄 것 — 점검 · 속도 · 탐색 스모크(T0 = S0)")
    yes = ["E9-button-sat", "SPEED-640", "E8-tool-T0t000", "E8-button-T0t001", "B-check-sat-s0"]
    no = ["E8-tool-T1t002", "E0b-button-s0", "B-full-color-s0", "T-full-S1t002-s0", "E15-button-base"]
    check(all(N.skipped(x) for x in yes), "점검 · 속도 · 스모크 → 뺌")
    check(not any(N.skipped(x) for x in no), "탐색 본회차 · 실험 → 안 뺌")


def test_변환이름():
    print("[n5] 변환 모델 파일 = <학습 모델 새 이름>_<변환 방식>.hef")
    check(N.ours(2) == "ours-L2" and N.ours(1) == "ours-L1", "우리 스크립트 수준")
    check(N.hef_file("B-early-base-s0", "zoo") == "B-early-base-s0_zoo.hef", "Model Zoo")
    check(N.hef_file("T-full-base-s0", N.ours(2)) == "T-full-base-s0_ours-L2.hef", "우리 스크립트")
    check(raises(lambda: N.hef_file("B-early-base-s0", "MZ")), "모르는 방식(MZ) → ValueError")
    check(N.name_for("B-full-color-s0", RES) == "B-full-color-s0", "새 꼴은 결과 없이도 그대로")


if __name__ == "__main__":
    test_대표()
    test_전체()
    test_꼴()
    test_건너뛰기()
    test_변환이름()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 이름 규칙 검증 통과")
