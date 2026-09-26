"""자가 테스트 일괄 러너(run_all.py) 검증 — 판정 규칙과 실제 실행을 가짜 시험 파일로 본다.

실행: python3 Demo/selftest/test_run_all.py

🔑 러너가 자기 자신(실제 selftest 전체)을 다시 부르지 않는다 — 임시 폴더의 가짜 시험만 돌린다.
판정 규칙의 근거 = 상위 docs/claude-code-작업로그.md 2026-09-22 블록(종료 코드 + 마지막 줄 · 세 갈래).
"""
import os
import shutil
import sys
import tempfile
import textwrap

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "selftest"))

import run_all

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_judge_pass_forms():
    """통과 형식 세 가지 — 「✅ … 통과」 · 「N/N passed」 · 「ALL OK」 — 는 종료 코드 0 일 때만 통과."""
    print("\n[판정] 통과 형식")
    for last in ("✅ 오버레이 스모크 통과", "✅ 결과 집계 검증 통과 (0.000s)", "39/39 passed", "ALL OK"):
        status, _ = run_all.judge(0, f"  ✅ 무엇\n\n{last}\n")
        check(status == "pass", f"{last!r} → pass (실제 {status})")


def test_judge_fail_forms():
    """실패 — 종료 코드가 0 이 아니면(✅ 를 찍었어도) · N/M 이 다르면 · 통과 줄이 없으면 · 시간 초과."""
    print("\n[판정] 실패 형식")
    cases = [
        ((139, "✅ 박스 색표 검증 통과\n"), "종료 코드 139 — 통과를 찍고 종료 중 크래시"),
        ((1, "  ❌ 틀림\n❌ 실패 1건\n"), "종료 코드 1"),
        ((0, "38/39 passed\n"), "N/M 이 다르다"),
        ((0, "done\n"), "통과 줄 없음"),
        ((0, ""), "출력 없음"),
    ]
    for (rc, out), what in cases:
        status, reason = run_all.judge(rc, out)
        check(status == "fail" and reason, f"{what} → fail (실제 {status} · {reason!r})")
    status, reason = run_all.judge(None, "✅ 통과\n", timed_out=True)
    check(status == "fail" and "시간" in reason, f"시간 초과 → fail (실제 {status} · {reason!r})")


def _write(d, name, body):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(body))


def test_run_suite_on_fake_tests():
    """가짜 시험 폴더를 실제로 돌린다 — 통과·실패·크래시·시간 초과·통과 줄 없음·건너뜀 · 시험이 아닌 파일은 안 돈다."""
    print("\n[실행] 가짜 시험 폴더")
    work = tempfile.mkdtemp(prefix="sop_runall_")
    tests = os.path.join(work, "selftest")
    os.makedirs(tests)
    _write(tests, "test_a_pass.py", f"""
        import os
        ok = os.getcwd() == {work!r} and os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        print("✅ 가짜 통과" if ok else "작업 폴더·화면 모드가 다르다")
        """)
    _write(tests, "test_b_fail.py", """
        import sys
        print("  ❌ 뭔가 틀림")
        print("❌ 실패 1건")
        sys.exit(1)
        """)
    _write(tests, "test_c_crash.py", """
        import os
        print("✅ 통과라고 찍고")
        os._exit(139)
        """)
    _write(tests, "test_d_timeout.py", """
        import time
        time.sleep(30)
        """)
    _write(tests, "test_e_noline.py", 'print("done")\n')
    _write(tests, "test_f_skip.py", 'print("✅ 여기까지 오면 안 된다")\n')
    _write(tests, "helper.py", 'raise SystemExit("시험이 아닌 파일이 실행됐다")\n')

    try:
        _run_fake_suite(work, tests)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_fake_suite(work, tests):
    lines = []
    counts, results, code = run_all.run_suite(
        tests, cwd=work, timeout=2,
        interpreters={"test_f_skip.py": os.path.join(work, "없는_파이썬")},
        out=lines.append)
    by = {r["name"]: r for r in results}
    check(set(by) == {"test_a_pass", "test_b_fail", "test_c_crash", "test_d_timeout",
                      "test_e_noline", "test_f_skip"}, f"시험 파일만 돈다 — {sorted(by)}")
    want = {"test_a_pass": "pass", "test_b_fail": "fail", "test_c_crash": "fail",
            "test_d_timeout": "fail", "test_e_noline": "fail", "test_f_skip": "skip"}
    for name, st in want.items():
        got = by.get(name, {}).get("status")
        check(got == st, f"{name} → {st} (실제 {got} · {by.get(name, {}).get('reason')!r})")
    check(counts == {"pass": 1, "fail": 4, "skip": 1}, f"세 갈래 개수 — {counts}")
    check(code == 1, f"실패가 있으면 종료 코드 1 (실제 {code})")
    text = "\n".join(lines)
    check("뭔가 틀림" in text, "실패한 파일은 ❌ 줄을 보여 준다")
    check(lines and lines[-1].startswith("SELFTEST 1 pass / 4 fail / 1 skip"), f"마지막 줄 — {lines[-1] if lines else None!r}")

    for name in list(os.listdir(tests)):
        if name != "test_a_pass.py":
            os.remove(os.path.join(tests, name))
    lines = []
    counts, _, code = run_all.run_suite(tests, cwd=work, timeout=5, interpreters={}, out=lines.append)
    check(counts == {"pass": 1, "fail": 0, "skip": 0} and code == 0,
          f"전부 통과면 종료 코드 0 — {counts} · {code}")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 일괄 러너 검증 통과")
