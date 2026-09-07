"""GUI 상태 내보내기 검증 — 원자적 교체와 「절대 안 죽는다」를 본다.

실행: python3 Demo/selftest/test_state_publisher.py

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §8
"""
import json
import os
import shutil
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from state_publisher import STATE_FILE, StatePublisher

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="sop_state_test_")
    try:
        print("── 기본 기록")
        p = StatePublisher(shm_dir=tmp)
        ok = p.publish({"세션": True, "현재단계": 2, "현재단계명": "펌프/퍼지"})
        check(ok, "publish 가 True 를 돌려준다")
        path = os.path.join(tmp, STATE_FILE)
        check(os.path.exists(path), "state.json 이 생긴다")
        d = json.load(open(path, encoding="utf-8"))
        check(d["현재단계명"] == "펌프/퍼지", "한글이 안 깨진다")
        check(d.get("pid") == os.getpid(), "pid 가 함께 적힌다")
        check(isinstance(d.get("쓴시각"), float), "쓴시각이 함께 적힌다")

        print("── .tmp 가 남지 않는다(원자적 교체)")
        check(not os.path.exists(path + ".tmp"), "임시 파일이 안 남는다")

        print("── 지우기")
        p.clear()
        check(not os.path.exists(path), "clear 로 사라진다")
        p.clear()
        check(True, "없는 파일을 또 지워도 예외가 안 난다")

        print("── 🔴 절대 예외를 올리지 않는다")
        bad = StatePublisher(shm_dir="/proc/못쓰는곳")
        check(bad.publish({"a": 1}) is False, "쓸 수 없는 경로면 False 만 돌려준다")
        p2 = StatePublisher(shm_dir=tmp)
        p2.publish({"현재단계": 3})
        check(p2.publish({"안됨": object()}) is False, "직렬화 못 하는 값이면 False")
        d2 = json.load(open(path, encoding="utf-8"))
        check(d2["현재단계"] == 3,
              "🔴 직렬화 실패가 **옛 파일을 깨뜨리지 않는다** — 읽는 쪽이 반쪽 상태를 못 본다")
        check(not os.path.exists(path + ".tmp"), "실패해도 .tmp 가 안 남는다")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print("   -", m)
        sys.exit(1)
    print("✅ 전부 통과")


if __name__ == "__main__":
    main()
