"""펌웨어 굽기 빌드 옵션 — 범위 검사(컴파일 전 · 보드에 아무것도 안 함) · --build-only · 옵션이 컴파일에 넘어가는지(학교 방문 준비 설계 §4.2 · Review Focus 5).

실행: python3 Demo/selftest/test_flash_options.py — 진짜 arduino-cli · esptool 을 부르지 않는다(기록만 하는 가짜로 바꿔 끼움).
"""
import os
import subprocess
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLASH = os.path.join(os.path.dirname(_DEMO_DIR), "arduino", "flash_esp32.sh")
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _run(*args):
    d = tempfile.mkdtemp()
    rec = os.path.join(d, "calls.txt")
    fake = os.path.join(d, "fake_cli.sh")
    with open(fake, "w") as f:
        f.write(f'#!/bin/bash\necho "$*" >> "{rec}"\nexit 0\n')
    os.chmod(fake, 0o755)
    env = dict(os.environ, ARDUINO_CLI_OVERRIDE=fake, ESPTOOL_OVERRIDE=fake, FLASH_BUILD_DIR=os.path.join(d, "build"))
    r = subprocess.run(["bash", FLASH, *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
                       timeout=60)
    calls = open(rec).read().splitlines() if os.path.exists(rec) else []
    return r, calls


def test_range():
    print("\n[옵션] 범위 밖 · 글자 → 컴파일 전에 「사용:」 · 종료 코드 2 · 아무것도 안 부름")
    for args in (("--jpeg-quality", "0"), ("--jpeg-quality", "70"), ("--jpeg-quality", "abc"),
                 ("--fb-count", "0"), ("--fb-count", "5"), ("--jpeg-quality",)):
        r, calls = _run("--build-only", *args)
        check(r.returncode == 2 and "사용:" in (r.stdout + r.stderr) and calls == [], f"{args} → 코드 {r.returncode} · 부름 {calls}")


def test_build_only():
    print("\n[옵션] --build-only — 컴파일만 · 옵션이 빌드 속성으로 · 포트 · 백업 · 업로드 없음")
    r, calls = _run("--build-only", "--jpeg-quality", "20", "--fb-count", "3")
    joined = " ".join(calls)
    check(r.returncode == 0, f"종료 코드 {r.returncode} · {r.stdout[-300:]} {r.stderr[-300:]}")
    check(len(calls) == 1 and calls[0].startswith("compile") and "--clean" in joined
          and "-DGLASS_JPEG_QUALITY=20 -DGLASS_FB_COUNT=3" in joined and "--build-property" in joined,
          f"컴파일 한 번 · 속성 → {calls}")
    check("upload" not in joined and "read-flash" not in joined and "-p " not in joined, "업로드 · 백업 · 포트 없음")
    r, calls = _run("--build-only")
    check(r.returncode == 0 and len(calls) == 1 and "--build-property" not in calls[0], f"옵션 없음 = 지금 펌웨어 그대로 → {calls}")
    r, calls = _run("--build-only", "main", "--fb-count", "3")
    check(r.returncode == 0 and "-DGLASS_JPEG_QUALITY=15 -DGLASS_FB_COUNT=3" in " ".join(calls),
          f"하나만 주면 다른 하나는 기본값(15) → {calls}")


def test_upload_no_second_clean():
    print("\n[옵션] 업로드 단계는 --clean 없이(3단계에서 같은 속성으로 이미 빌드 · 리뷰 Minor 7) — 문면 고정(보드 없이는 업로드를 못 돌린다)")
    src = open(FLASH, encoding="utf-8").read()
    up = [ln for ln in src.splitlines() if "compile --upload" in ln and not ln.lstrip().startswith("#")]
    check(len(up) == 1 and '"${EXTRA_UP[@]}"' in up[0], f"업로드 줄 {up}")
    defs = [ln for ln in src.splitlines() if ln.strip().startswith("EXTRA_UP=(") and "--build-property" in ln]
    check(len(defs) == 1 and "--clean" not in defs[0], f"EXTRA_UP 정의 {defs}")


if __name__ == "__main__":
    test_range()
    test_build_only()
    test_upload_no_second_clean()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 굽기 옵션 검증 통과")
