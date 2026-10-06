"""두 안경 펌웨어의 카메라 설정이 같다 — `camera_stream_tcp`(카메라 전용) ↔ `glass_voice`(카메라+마이크+스피커).

실행: python3 Demo/selftest/test_firmware_camera_sync.py
계기: 2026-10-06 `glass_voice` 는 9/6 에 카메라 코드를 복사한 뒤 9/22~23 의 XGA·노출 상한 9ms 를 못 받아
      VGA·노출 기본값으로 남아 있었다(굽는 순간 카메라가 640×480 으로 내려간다). 복사본이 조용히 갈라지지 않게 대조한다.
      시리얼 진단 명령(`R:`·`W:`·`EXP:`)은 대조하지 않는다 — `glass_voice` 는 같은 시리얼로 음성 명령 R·W 를 받아 옮기지 않았다.
"""
import os
import re
import sys

_ARDUINO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "arduino")

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _src(name):
    with open(os.path.join(_ARDUINO, name, f"{name}.ino"), encoding="utf-8") as f:
        return f.read()


def _camera_config(src):
    """`config.<필드> = <값>;` 을 모은다 — 카메라 초기화 설정."""
    return dict(re.findall(r"config\.(\w+)\s*=\s*([^;]+);", src))


def test_카메라_설정():
    print("[c1] 카메라 초기화 설정(해상도·화질·버퍼·핀·클럭)이 두 펌웨어에서 같다")
    a, b = _camera_config(_src("camera_stream_tcp")), _camera_config(_src("glass_voice"))
    check(len(a) >= 20, f"camera_stream_tcp 설정 {len(a)}개를 읽었다")
    diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
    check(not diff, f"다른 설정 없음 — {diff}")
    check(a.get("frame_size") == "FRAMESIZE_XGA", f"기준 해상도 = XGA — {a.get('frame_size')}")


def test_노출_상한():
    print("[c2] 부팅 때 노출 상한 밴드 2(0x3A0E=2 → 최대 약 9ms)를 둘 다 건다 · 부팅 노출을 기록한다")
    pat = r"set_reg\(\s*\w+\s*,\s*0x3A0E\s*,\s*0xFF\s*,\s*0x02\s*\)"
    for name in ("camera_stream_tcp", "glass_voice"):
        s = _src(name)
        check(re.search(pat, s) is not None, f"{name} — 0x3A0E=2")
        check('printExposure("boot")' in s, f"{name} — 부팅 노출 기록")


def test_음성_명령과_안_겹침():
    print("[c3] glass_voice 는 시리얼 진단 명령(R:·W:·EXP:)을 받지 않는다 — 음성 명령 R·W 와 글자가 겹친다")
    s = _src("glass_voice")
    check('startsWith("R:")' not in s and 'startsWith("W:")' not in s and 'startsWith("EXP:")' not in s,
          "R:·W:·EXP: 처리 없음")


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
    print("✅ 두 펌웨어 카메라 설정 대조 통과")
