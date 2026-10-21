"""안경 주소 자동 찾기 검증 — 실제 네트워크 · .camera_ip 를 건드리지 않는다(가짜 ping · 임시 파일).

실행: python3 Demo/selftest/test_glass_finder.py
정본 = 상위 docs/superpowers/plans/2026-10-21-관객소리TV.md Task 7b(10/14 카메라 미복구 원인 ① 주소 바뀜)
"""
import os
import sys
import tempfile

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import config               # noqa: E402
import glass_finder as GF   # noqa: E402

_fails = []
MAC = "68:EE:8F:4F:5D:38"
NEIGH = """192.168.1.13 dev eth0 lladdr 68:ee:8f:4f:5d:38 STALE
192.168.1.1 dev eth0 lladdr 58:86:94:e5:5e:8a REACHABLE
192.168.1.20 dev eth0 FAILED
192.168.1.14 dev eth0 lladdr 68:ee:8f:4f:5d:38 REACHABLE
10.147.16.188 dev wlan0 lladdr d2:44:5f:61:32:72 REACHABLE
"""


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _ipfile(val):
    p = os.path.join(tempfile.mkdtemp(), ".camera_ip")
    with open(p, "w") as f:
        f.write(val + "\n")
    return p


def test_neigh_parse():
    print("\n[찾기] 이웃 표에서 안경 고유 번호의 살아 있는 줄")
    check(GF.neigh_ip(MAC, NEIGH) == "192.168.1.14", "옛 주소(STALE .13)가 아니라 살아 있는 .14")
    check(GF.neigh_ip(MAC.lower(), NEIGH) == "192.168.1.14", "고유 번호 대소문자 무시")
    check(GF.neigh_ip(MAC, "192.168.1.13 dev eth0 lladdr 68:ee:8f:4f:5d:38 STALE\n") is None, "STALE 만 있으면 None")
    check(GF.neigh_ip("3C:0F:02:DD:5E:58", NEIGH) is None, "다른 보드(서브)는 None")
    check(GF.neigh_ip(MAC, "") is None, "빈 표 → None")
    check(GF.neigh_ip(MAC, "192.168.1.14 dev eth0 lladdr 68:ee:8f:4f:5d:38 DELAY\n") == "192.168.1.14", "DELAY 도 살아 있음")



def test_old_address_delay_not_chosen():
    print("\n[찾기] 🔴 검토 C1 — 옛 주소가 DELAY · 먼저 나와도 ping 에 답한 새 주소를 고른다")
    stale_first = ("192.168.1.13 dev eth0 lladdr 68:ee:8f:4f:5d:38 DELAY\n"
                   "192.168.1.14 dev eth0 lladdr 68:ee:8f:4f:5d:38 REACHABLE\n")
    check(GF.neigh_ip(MAC, stale_first, alive={"192.168.1.14"}) == "192.168.1.14", "답한 주소(.14)만")
    check(GF.neigh_ip(MAC, stale_first, alive={"192.168.1.13", "192.168.1.14"}) == "192.168.1.14",
          "둘 다 답했으면 REACHABLE 을 먼저")
    check(GF.neigh_ip(MAC, stale_first, alive=set()) is None, "아무도 답하지 않았으면 None")
    v6 = "fe80::1 dev eth0 lladdr 68:ee:8f:4f:5d:38 REACHABLE\n" + stale_first
    check(GF.neigh_ip(MAC, v6, alive={"192.168.1.14"}, prefix="192.168.1.") == "192.168.1.14",
          "IPv6 줄이 먼저 나와도 대역 안 주소(검토 Minor 6b)")


def test_sweep_returns_responders():
    print("\n[찾기] 훑기는 답한 주소를 돌려준다")
    got = GF.sweep("192.168.1.", ping=lambda ip: ip in ("192.168.1.1", "192.168.1.14"))
    check(got == {"192.168.1.1", "192.168.1.14"}, f"{got}")


def test_find_fast_path_when_current_ok():
    print("\n[찾기] 지금 주소가 맞으면 훑지 않는다(검토 Minor 6d — 켤 때 5초 줄임)")
    pinged = []
    def ping(ip):
        pinged.append(ip)
        return ip == "192.168.1.14"
    neigh = "192.168.1.14 dev eth0 lladdr 68:ee:8f:4f:5d:38 REACHABLE\n"
    ip = GF.find(MAC, "192.168.1.", current="192.168.1.14", ping=ping, neigh=lambda: neigh)
    check(ip == "192.168.1.14" and pinged == ["192.168.1.14"], f"한 번만 부름({len(pinged)}번)")
    pinged.clear()
    neigh2 = "192.168.1.15 dev eth0 lladdr 68:ee:8f:4f:5d:38 REACHABLE\n"
    ip = GF.find(MAC, "192.168.1.", current="192.168.1.14", ping=lambda ip: (pinged.append(ip), ip == "192.168.1.15")[1],
                 neigh=lambda: neigh2)
    check(ip == "192.168.1.15" and len(pinged) > 200, f"지금 주소가 아니면 훑어서 .15 ({ip} · {len(pinged)}번)")


def test_apply_atomic_write():
    print("\n[맞춤] 파일은 임시 파일에 쓴 뒤 바꿔 끼운다(검토 Minor 6a)")
    import inspect
    check("os.replace(" in inspect.getsource(GF.apply), "os.replace 로 바꿔 끼움")

def test_apply_updates_file():
    print("\n[맞춤] 바뀐 주소면 .camera_ip 를 고치고 옛 값을 .prev 로")
    p = _ipfile("192.168.1.13")
    logs = []
    ok = GF.apply(path=p, log=logs.append, finder=lambda mac, prefix: "192.168.1.14")
    check(ok is True and open(p).read().strip() == "192.168.1.14", f"새 주소 .14 ({open(p).read().strip()})")
    check(open(p + ".prev").read().strip() == "192.168.1.13", "옛 값 .13 은 .prev")
    check(any(".13" in m and ".14" in m for m in logs), f"로그에 바뀐 내용 {logs}")


def test_apply_same_no_write():
    print("\n[맞춤] 같으면 그대로")
    p = _ipfile("192.168.1.14")
    t0 = os.path.getmtime(p)
    ok = GF.apply(path=p, log=lambda m: None, finder=lambda mac, prefix: "192.168.1.14")
    check(ok is True and os.path.getmtime(p) == t0 and not os.path.exists(p + ".prev"), "파일을 다시 쓰지 않음")


def test_apply_not_found_keeps():
    print("\n[맞춤] 못 찾으면 그대로 두고 안내")
    p = _ipfile("192.168.1.13")
    logs = []
    ok = GF.apply(path=p, log=logs.append, finder=lambda mac, prefix: None)
    check(ok is False and open(p).read().strip() == "192.168.1.13", "주소 그대로 · False")
    check(any("전원" in m for m in logs), f"안경 전원 안내 {logs}")


def test_sweep_pings_subnet():
    print("\n[찾기] 공유기 대역 1~254 를 한 번씩 부른다(이웃 표 새로 채우기)")
    got = []
    GF.sweep("192.168.1.", ping=lambda ip: got.append(ip) or False)
    check(sorted(got, key=lambda s: int(s.rsplit(".", 1)[1])) == [f"192.168.1.{i}" for i in range(1, 255)],
          f"{len(got)}개")


def test_config_values():
    print("\n[설정] 메인 안경 고유 번호 · 공유기 대역")
    check(config.GLASS_MAC == MAC and config.GLASS_SUBNET == "192.168.1.", f"{config.GLASS_MAC} · {config.GLASS_SUBNET}")


def test_run_demo_finds_glass_before_main():
    print("\n[런처] 시연 · 음성비서보다 먼저 찾는다 · 가짜 카메라(SOP_CAMERA_HOST)면 건너뜀")
    src = open(os.path.join(_DEMO, "run_demo.sh"), encoding="utf-8").read()
    i = src.find("glass_finder.py --apply")
    check(i >= 0, "런처가 glass_finder.py --apply 를 부른다")
    check(i < src.find("./run_voice.sh") and i < src.find("python3 main.py"), "음성비서 · main.py 보다 앞")
    check("SOP_CAMERA_HOST" in src[max(0, i - 400):i], "SOP_CAMERA_HOST 가 있으면 건너뛰는 조건")
    check("SOP_GLASS_FINDER" in src[max(0, i - 400):i], "SOP_GLASS_FINDER=0 이면 건너뛰는 조건(서브 보드 · 검토 Minor 6c)")


def test_prev_file_ignored_by_git():
    print("\n[저장소] 옛 주소 파일(.camera_ip.prev)은 git 무시 — 생겨도 점검 도구 「커밋 안 된 변경」 ❌ 가 안 나게")
    import subprocess
    r = subprocess.run(["git", "check-ignore", "-q", os.path.join(_DEMO, ".camera_ip.prev")], cwd=_DEMO)
    check(r.returncode == 0, f"git check-ignore → {r.returncode}(0 = 무시)")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:      # noqa: BLE001
                check(False, f"{name} 예외 — {type(e).__name__}: {e}")
    print(f"\n{'❌ 실패 ' + str(len(_fails)) + '건' if _fails else '✅ 모두 통과'}")
    sys.exit(1 if _fails else 0)
