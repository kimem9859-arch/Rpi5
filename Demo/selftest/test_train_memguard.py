"""데스크톱 메모리 감시(학습/memguard.py)의 판단 부분을 고정한다 — 스왑으로 넘어가기 전에 변환을 멈춘다.

실행: python3 Demo/selftest/test_train_memguard.py
계기: 2026-10-05 01:04 U1 변환(수준 1 편향 보정 · 임시 6.5GB)에서 WSL 이 멈춰 데스크톱을 재부팅했다(사용자 「WSL 메모리 스왑 오버되지 않게 메모리 감시 붙여주고」).
"""
import os
import sys

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import memguard as M

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def mi(avail_mb, swap_total_mb=4096, swap_free_mb=4096):
    return (f"MemTotal:       16000000 kB\nMemAvailable:   {avail_mb * 1024} kB\n"
            f"SwapTotal:      {swap_total_mb * 1024} kB\nSwapFree:       {swap_free_mb * 1024} kB\n")


def test_판단():
    print("[1] 사용 가능 < 문턱 또는 스왑 사용 > 문턱 → 멈춤 · 그 밖은 계속")
    check(M.parse(mi(9000)) == {"avail_mb": 9000, "swap_used_mb": 0}, "meminfo 읽기")
    check(M.reason(M.parse(mi(9000)), 1500, 256) is None, "여유 → 계속")
    r = M.reason(M.parse(mi(1400)), 1500, 256)
    check(r is not None and "사용 가능" in r, f"사용 가능 1400 < 1500 → 멈춤 — {r}")
    r = M.reason(M.parse(mi(8000, swap_free_mb=3700)), 1500, 256)
    check(r is not None and "스왑" in r, f"스왑 396 > 256 → 멈춤 — {r}")
    check(M.reason(M.parse(mi(8000, swap_free_mb=4000)), 1500, 256) is None, "스왑 96 ≤ 256 → 계속")


def test_대상():
    print("[2] 멈출 대상 = 변환 프로세스만 · 감시 자신·학습·파일 보는 명령은 아님")
    yes = ["/home/u/hailo-venv/bin/python /home/u/학습실험/코드/abc/hef_convert.py hef /home/u/학습실험/변환/E0c-tool-f120",
           "/home/u/hailo-venv/bin/python /home/u/hailo-venv/bin/hailomz compile yolov8n --ckpt x.onnx",
           "/home/u/hailo-ul-venv/bin/python ul.py"]
    no = ["/usr/bin/python3 /home/u/학습실험/memguard.py",
          "/home/u/학습실험/venv/bin/python /home/u/학습실험/코드/abc/train_one.py job.json",
          "less /home/u/학습실험/코드/abc/hef_convert.py",
          "bash -c ~/학습실험/venv/bin/python ~/학습실험/코드/abc/hef_convert.py onnx ~/학습실험/변환/x > onnx.log"]
    check(all(M.is_target(c) for c in yes), "변환 3종(우리 · Model Zoo · ultralytics) → 대상")
    check(not any(M.is_target(c) for c in no), "감시 · 학습 · 파일 보기 · 띄우는 셸 → 대상 아님")


if __name__ == "__main__":
    test_판단()
    test_대상()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 메모리 감시 검증 통과")
