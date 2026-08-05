"""손 검출 network_group 감싸개 검증 — deprecated `activate()` 를 가로채는가.

실행: python3 Demo/selftest/test_hand_group.py

왜 필요한가:
    외부 blaze 소스(`~/hoi_probe/.../blazedetector.py` 등)가 **추론할 때마다**
    `network_group.activate()` 를 부른다. 우리는 ROUND_ROBIN 스케줄러를 쓰므로
    pyhailort 는 그 호출을 **무시하고 경고만** 낸다(pyhailort.py:581).
        WARNING:pyhailort:Calls to `activate()` when working with scheduler are deprecated!
    손 추론이 도는 프레임마다 나오므로 터미널이 이 한 줄로 덮인다.

    소스가 repo 밖에 있어 고쳐도 클론·sop-pi-2 에 안 따라간다. 그래서 우리가
    넘겨주는 network_group 을 감싸 **호출이 pyhailort 에 도달하지 않게** 한다.

⚠️ Hailo 장치 없이 돈다 — 감싸개는 순수 파이썬 위임이다.
"""

import os
import sys

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

from hand_tracker import _NoActivateGroup

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class _FakeGroup:
    """activate() 가 불리면 기록하는 가짜 network_group."""

    def __init__(self):
        self.activate_calls = 0
        self.name = "fake_ng"
        self._configured_network = object()

    def activate(self, params=None):
        self.activate_calls += 1
        raise AssertionError("activate() 가 실제 객체까지 도달했다")

    def create_params(self):
        return "params"

    def get_networks_names(self):
        return ["net0"]


print("\n[감싸개] deprecated activate() 차단")
ng = _FakeGroup()
w = _NoActivateGroup(ng)

with w.activate("params"):          # 예외가 나면 실패
    pass
check(ng.activate_calls == 0, "activate() 가 실제 network_group 에 도달하지 않는다")

with w.activate():                  # 인자 없이도 컨텍스트 매니저여야 한다
    pass
check(True, "인자 없는 activate() 도 컨텍스트 매니저를 돌려준다")

print("\n[감싸개] 나머지는 그대로 위임")
check(w.name == "fake_ng", "속성 위임 (name)")
check(w.create_params() == "params", "메서드 위임 (create_params)")
check(w.get_networks_names() == ["net0"], "메서드 위임 (get_networks_names)")
# 🔴 InferVStreams.__enter__ 가 이 비공개 속성을 직접 집는다(pyhailort.py:938).
#    위임되지 않으면 손 추론이 통째로 죽는다.
check(w._configured_network is ng._configured_network,
      "_configured_network 위임 — InferVStreams 가 직접 집는 속성")

print()
if _fails:
    print(f"❌ 실패 {len(_fails)}건")
    sys.exit(1)
print("✅ 전부 통과")
