"""관객 소리(TV) 출력 장치 맞춤 검증 — 실제 PipeWire · 소리를 건드리지 않는다(가짜 명령 실행기 · 임시 ELD 파일).

실행: python3 Demo/selftest/test_audience_audio.py
정본 = 상위 docs/superpowers/specs/2026-10-21-관객소리TV-design.md 4장 10 · 11
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "test"))

import audience_audio as AA   # noqa: E402

_fails = []
# 10/21 실물 pw-dump 에서 출력 노드만 줄인 것(카드0 = TV · 카드1 = 제우스랩)
DUMP = [
    {"id": 54, "type": "PipeWire:Interface:Node", "info": {"props": {
        "media.class": "Audio/Sink", "node.name": "alsa_output.platform-107c701400.hdmi.hdmi-stereo",
        "alsa.card": 0, "alsa.card_name": "vc4-hdmi-0"}}},
    {"id": 46, "type": "PipeWire:Interface:Node", "info": {"props": {
        "media.class": "Audio/Sink", "node.name": "alsa_output.platform-107c706400.hdmi.hdmi-stereo",
        "alsa.card": 1, "alsa.card_name": "vc4-hdmi-1"}}},
    {"id": 31, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Source", "alsa.card": 2}}},
]


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


class FakeRun:
    """명령을 적고 정해 둔 출력을 돌려준다 — dumps = 차례로 돌려줄 pw-dump 목록."""

    def __init__(self, dumps=None, default=54, muted=()):
        self.cmds, self.dumps, self.default, self.muted = [], list(dumps or [DUMP]), default, set(muted)

    def __call__(self, cmd, **kw):
        self.cmds.append(list(cmd))
        out = ""
        if cmd[0] == "pw-dump":
            out = json.dumps(self.dumps.pop(0) if len(self.dumps) > 1 else self.dumps[0])
        elif cmd[:2] == ["wpctl", "inspect"]:
            out = f"id {self.default}, type PipeWire:Interface:Node\n"
        elif cmd[:2] == ["wpctl", "get-volume"]:
            out = "Volume: 0.40" + (" [MUTED]" if int(cmd[2]) in self.muted else "") + "\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")


def _eld_root(names):
    root = tempfile.mkdtemp()
    for card, name in names.items():
        d = os.path.join(root, f"card{card}")
        os.makedirs(d)
        with open(os.path.join(d, "eld#0"), "w") as f:
            f.write(f"monitor_name\t\t{name}\nconnection_type\t\tHDMI\n")
    return root


def test_pick_tv_by_eld():
    print("\n[맞춤] ELD 이름으로 TV · 제우스랩 가르기")
    check(AA.pick({0: "No Brand TV", 1: "ZEUSLAP-HDMI"}) == (0, 1), "카드0 TV · 카드1 제우스랩")
    check(AA.pick({0: "ZEUSLAP-HDMI", 1: "No Brand TV"}) == (1, 0), "반대로 꽂아도 이름으로")
    check(AA.pick({1: "ZEUSLAP-HDMI"}) == (None, 1), "TV 없음 → None")
    root = _eld_root({0: "No Brand TV", 1: "ZEUSLAP-HDMI"})
    check(AA.read_elds(root) == {0: "No Brand TV", 1: "ZEUSLAP-HDMI"}, f"ELD 파일 읽기 {AA.read_elds(root)}")


def test_sinks_from_dump():
    print("\n[맞춤] pw-dump 에서 카드별 출력 노드")
    s = AA.sinks(DUMP)
    check(s.get(0, {}).get("id") == 54 and s.get(1, {}).get("id") == 46 and 2 not in s, f"{s}")


def test_apply_commands():
    print("\n[맞춤] 기본 출력 = TV · 음소거 해제 · 40% · 제우스랩 음소거")
    r = FakeRun()
    ok = AA.apply(run=r, log=lambda m: None, elds={0: "No Brand TV", 1: "ZEUSLAP-HDMI"})
    w = [c for c in r.cmds if c[0] == "wpctl"]
    check(ok is True, "성공")
    check(w == [["wpctl", "set-default", "54"], ["wpctl", "set-mute", "54", "0"],
                ["wpctl", "set-volume", "54", "0.40"], ["wpctl", "set-mute", "46", "1"]], f"명령 순서 {w}")


def test_apply_restarts_when_tv_sink_missing():
    print("\n[맞춤] TV 는 꽂혔는데 출력 노드가 없으면 소리 관리를 다시 시작")
    r = FakeRun(dumps=[[DUMP[1]], DUMP])
    ok = AA.apply(run=r, log=lambda m: None, elds={0: "No Brand TV", 1: "ZEUSLAP-HDMI"}, sleep=lambda s: None)
    first_wpctl = next(i for i, c in enumerate(r.cmds) if c[0] == "wpctl")
    restart = next((i for i, c in enumerate(r.cmds) if c[:3] == ["systemctl", "--user", "restart"]), None)
    check(ok is True and restart is not None and restart < first_wpctl, f"다시 시작이 먼저 · {r.cmds[:3]}")
    r2 = FakeRun(dumps=[[DUMP[1]]])
    check(AA.apply(run=r2, log=lambda m: None, elds={0: "No Brand TV", 1: "ZEUSLAP-HDMI"},
                   sleep=lambda s: None) is False, "다시 시작해도 없으면 실패(False) · 예외 없음")
    check(AA.apply(run=FakeRun(), log=lambda m: None, elds={1: "ZEUSLAP-HDMI"}) is False, "TV 가 없으면 False")


def test_status_flags_muted_or_zeus_default():
    print("\n[점검] 기본 출력 TV · 음소거 아님 · 제우스랩 음소거")
    elds = {0: "No Brand TV", 1: "ZEUSLAP-HDMI"}
    ok, d = AA.status(run=FakeRun(muted={46}), elds=elds)
    check(ok is True, f"정상 → ✅ ({d})")
    ok, d = AA.status(run=FakeRun(muted={54, 46}), elds=elds)
    check(ok is False and "음소거" in d, f"TV 음소거 → ❌ ({d})")
    ok, d = AA.status(run=FakeRun(default=46, muted={46}), elds=elds)
    check(ok is False and "기본" in d, f"기본이 제우스랩 → ❌ ({d})")
    ok, d = AA.status(run=FakeRun(muted=()), elds=elds)
    check(ok is False and "제우스랩" in d, f"제우스랩 음소거 아님 → ❌ ({d})")
    ok, d = AA.status(run=FakeRun(), elds={1: "ZEUSLAP-HDMI"})
    check(ok is False and "TV" in d, f"TV 없음 → ❌ ({d})")


def test_school_check_has_audience_line():
    print("\n[점검] school_check --final 에 「관객 소리(TV)」 줄 · 집 모드는 건너뜀")
    import school_check as SC
    # 🔑 실물(안경 · 인터락 · 파이2)에 붙지 않게 test_school_check.test_run_final 과 같은 가짜를 끼운다
    keep = (SC.audience_check, SC.recv_probe, SC.glass_ports, SC.interlock_ack, SC._demo_running, SC.llm_check)
    SC.audience_check = lambda: SC._c("음성", "관객 소리(TV)", True, "시험 대역")
    SC.recv_probe = lambda host, port=None, sec=5.0: SC._c("안경", "연결 · 받기", True, "시험 대역")
    SC.glass_ports = lambda host: SC._c("음성", "안경 마이크 · 명령 포트", True, "시험 대역")
    SC.interlock_ack = lambda port: SC._c("인터락", "RUN 응답", True, "시험 대역")
    SC._demo_running = lambda: False
    SC.llm_check = lambda url=None, model=None: SC._c("음성", "파이2 LLM 응답", True, "시험 대역")
    try:
        names = [c.name for c in SC.run(final=True)]
        home = [c for c in SC.run(home=True, final=True) if c.name == "관객 소리(TV)"]
    finally:
        (SC.audience_check, SC.recv_probe, SC.glass_ports, SC.interlock_ack, SC._demo_running, SC.llm_check) = keep
    check("관객 소리(TV)" in names, "최종 점검에 줄이 있다")
    check(len(home) == 1 and home[0].ok is None, "집 모드는 건너뜀")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:      # noqa: BLE001
                check(False, f"{name} 예외 — {type(e).__name__}: {e}")
    print(f"\n{'❌ 실패 ' + str(len(_fails)) + '건' if _fails else '✅ 모두 통과'}")
    sys.exit(1 if _fails else 0)
