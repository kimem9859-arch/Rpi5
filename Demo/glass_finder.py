"""안경 주소 자동 찾기 — 시연을 켤 때 메인 안경을 고유 번호(MAC)로 찾아 `Demo/.camera_ip` 를 맞춘다.

실행: python3 Demo/glass_finder.py --apply   (run_demo.sh 가 음성비서 · 시연보다 먼저 부른다 · 실패해도 시연은 켜진다)
      python3 Demo/glass_finder.py --find    (찾기만 · 파일은 그대로)

🔑 왜(10/14 학과 발표) — 공유기를 껐다 켜자 안경 주소가 .9 → .13 으로 바뀌었는데, 시연은 켤 때 읽은 옛 주소로만 붙어
   카메라가 끝까지 돌아오지 않았다. 공유기 관리자 비밀번호가 없어 주소 예약을 못 하고(10/21), 안경 펌웨어 고정 주소는
   설치 날 다시 굽기 · 열린 망에서 충돌(ESP32 는 충돌을 확인하지 않는다) 때문에 쓰지 않는다 — 파이가 찾아 따라간다.
🔑 찾는 법 = 공유기 대역 1~254 에 ping 한 번씩(이웃 표를 새로 채운다 · sudo 없음) → `ip neigh` 에서 그 MAC 의 살아 있는 줄.
   STALE 은 버린다 — 바뀌기 전 옛 주소가 STALE 로 남아 있었다.
🔴 핫스팟 대역은 찾지 않는다 — 안경이 핫스팟에 붙으면 fps 만 떨어지는 조용한 고장이라, 따라가지 말고 안경을 껐다 켜야 한다.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import config

_ALIVE = ("REACHABLE", "DELAY", "PROBE")


def _ping(ip):
    try:
        subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=3)
    except Exception:                           # noqa: BLE001
        pass


def sweep(prefix, ping=_ping, workers=64):
    """대역 1~254 에 한 번씩 부른다 — 답한 기기가 이웃 표에 살아 있는 줄로 올라온다."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(ping, [f"{prefix}{i}" for i in range(1, 255)]))


def neigh_ip(mac, text):
    """`ip neigh` 출력에서 그 MAC 의 살아 있는(REACHABLE · DELAY · PROBE) 줄 주소 — 없으면 None."""
    want = mac.lower()
    for ln in (text or "").splitlines():
        parts = ln.split()
        if "lladdr" not in parts or not parts:
            continue
        i = parts.index("lladdr")
        if i + 1 < len(parts) and parts[i + 1].lower() == want and parts[-1] in _ALIVE:
            return parts[0]
    return None


def find(mac, prefix):
    """안경 주소 — 대역을 한 번 훑은 뒤 이웃 표에서 찾는다. 못 찾으면 None."""
    sweep(prefix)
    try:
        text = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=5).stdout
    except Exception:                           # noqa: BLE001
        return None
    ip = neigh_ip(mac, text)
    return ip if ip and ip.startswith(prefix) else None


def apply(path=None, mac=None, prefix=None, log=print, finder=find):
    """찾은 주소가 파일과 다르면 고친다(옛 값 = <path>.prev). 찾았으면 True — 못 찾으면 그대로 두고 False."""
    path = path or config._CAMERA_IP_FILE
    mac, prefix = mac or config.GLASS_MAC, prefix or config.GLASS_SUBNET
    try:
        old = open(path, encoding="utf-8").read().strip()
    except OSError:
        old = ""
    try:
        ip = finder(mac, prefix)
    except Exception as e:                      # noqa: BLE001
        ip = None
        log(f"안경 주소: 찾다가 오류 — {type(e).__name__}: {e}")
    if not ip:
        log(f"안경 주소: ⚠️ 공유기 대역에서 안경({mac})을 못 찾음 — 옛 주소 {old or '(없음)'} 그대로 · "
            "안경 전원 · 배터리를 보고, 켜져 있으면 핫스팟에 붙었을 수 있으니 안경을 껐다 켠 뒤 시연을 다시 켠다")
        return False
    if ip == old:
        log(f"안경 주소: ✅ {ip} 그대로")
        return True
    try:
        if old:
            with open(path + ".prev", "w", encoding="utf-8") as f:
                f.write(old + "\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(ip + "\n")
    except OSError as e:
        log(f"안경 주소: ❌ {path} 를 못 고쳤다 — {e}")
        return False
    log(f"안경 주소: ✅ 바뀜 {old or '(없음)'} → {ip}(옛 값 = {os.path.basename(path)}.prev)")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="안경 주소 자동 찾기(메인 안경 MAC)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="찾아서 .camera_ip 를 맞춘다")
    g.add_argument("--find", action="store_true", help="찾기만 한다")
    a = ap.parse_args(argv)
    stamp = time.strftime("%F %T")
    say = lambda m: print(f"[{stamp}] {m}", flush=True)       # noqa: E731
    if a.apply:
        return 0 if apply(log=say) else 1
    ip = find(config.GLASS_MAC, config.GLASS_SUBNET)
    say(f"안경 주소: {ip or '못 찾음'}")
    return 0 if ip else 1


if __name__ == "__main__":
    sys.exit(main())
