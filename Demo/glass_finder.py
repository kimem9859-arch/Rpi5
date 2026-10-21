"""안경 주소 자동 찾기 — 시연을 켤 때 메인 안경을 고유 번호(MAC)로 찾아 `Demo/.camera_ip` 를 맞춘다.

실행: python3 Demo/glass_finder.py --apply   (run_demo.sh 가 음성비서 · 시연보다 먼저 부른다 · 실패해도 시연은 켜진다)
      python3 Demo/glass_finder.py --find    (찾기만 · 파일은 그대로)

🔑 왜(10/14 학과 발표) — 공유기를 껐다 켜자 안경 주소가 .9 → .13 으로 바뀌었는데, 시연은 켤 때 읽은 옛 주소로만 붙어
   카메라가 끝까지 돌아오지 않았다. 공유기 관리자 비밀번호가 없어 주소 예약을 못 하고(10/21), 안경 펌웨어 고정 주소는
   설치 날 다시 굽기 · 열린 망에서 충돌(ESP32 는 충돌을 확인하지 않는다) 때문에 쓰지 않는다 — 파이가 찾아 따라간다.
🔑 찾는 법 = 지금 주소가 답하고 그 MAC 이 안경이면 그대로(빠름) · 아니면 공유기 대역 1~254 에 ping 한 번씩(sudo 없음) →
   `ip -4 neigh` 에서 그 MAC 의 주소 가운데 **ping 에 실제로 답한 것**(옛 주소 줄은 DELAY 로 살아 보여도 답이 없다 · 검토 C1).
🔑 끄기 = SOP_GLASS_FINDER=0(서브 보드로 시연할 때 — 메인 안경이 켜져 있으면 그쪽 주소로 바꾼다) · 가짜 카메라(SOP_CAMERA_HOST)도 건너뜀.
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
_DEAD = ("FAILED", "INCOMPLETE")


def _ping(ip):
    """한 번 불러 답했으면 True."""
    try:
        return subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except Exception:                           # noqa: BLE001
        return False


def sweep(prefix, ping=_ping, workers=64):
    """대역 1~254 에 한 번씩 부른다 → 답한 주소 집합(답한 기기는 이웃 표에 살아 있는 줄로 올라온다)."""
    ips = [f"{prefix}{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        ok = list(ex.map(ping, ips))
    return {ip for ip, r in zip(ips, ok) if r}


def neigh_ip(mac, text, alive=None, prefix=None):
    """`ip neigh` 출력에서 그 MAC 의 주소 — 없으면 None.

    🔴 `alive`(ping 에 답한 주소 집합)가 있으면 그 안에서만 고른다(검토 C1) — 리눅스는 STALE 줄로 보낸 패킷 때문에
       옛 주소 줄을 DELAY · PROBE 로 바꾸므로, 상태만 보면 바뀌기 전 옛 주소를 고를 수 있었다(10/14 사고 모양).
       `alive` 가 없으면 살아 있는 상태(REACHABLE · DELAY · PROBE)만. 어느 쪽이든 REACHABLE 을 먼저 · `prefix` 대역만.
    """
    want, found = mac.lower(), []
    for ln in (text or "").splitlines():
        parts = ln.split()
        if "lladdr" not in parts:
            continue
        i, ip, state = parts.index("lladdr"), parts[0], parts[-1]
        if i + 1 >= len(parts) or parts[i + 1].lower() != want or (prefix and not ip.startswith(prefix)):
            continue
        if alive is not None:
            if ip in alive and state not in _DEAD:
                found.append((state != "REACHABLE", ip))
        elif state in _ALIVE:
            found.append((state != "REACHABLE", ip))
    return min(found)[1] if found else None


def _neigh_text():
    try:
        return subprocess.run(["ip", "-4", "neigh"], capture_output=True, text=True, timeout=5).stdout
    except Exception:                           # noqa: BLE001
        return ""


def find(mac, prefix, current=None, ping=_ping, neigh=_neigh_text):
    """안경 주소 — 지금 주소가 답하고 그 주소의 MAC 이 안경이면 그대로(훑기 생략) · 아니면 대역을 훑어 답한 주소 가운데서."""
    if current and current.startswith(prefix) and ping(current):
        if neigh_ip(mac, neigh(), alive={current}, prefix=prefix) == current:
            return current
    return neigh_ip(mac, neigh(), alive=sweep(prefix, ping=ping), prefix=prefix)


def apply(path=None, mac=None, prefix=None, log=print, finder=None):
    """찾은 주소가 파일과 다르면 고친다(옛 값 = <path>.prev). 찾았으면 True — 못 찾으면 그대로 두고 False."""
    path = path or config._CAMERA_IP_FILE
    mac, prefix = mac or config.GLASS_MAC, prefix or config.GLASS_SUBNET
    try:
        old = open(path, encoding="utf-8").read().strip()
    except OSError:
        old = ""
    finder = finder or (lambda m, p: find(m, p, current=old))
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
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(ip + "\n")
        os.replace(path + ".tmp", path)          # 🔑 쓰다 끊겨도 반쪽 주소가 남지 않게(검토 Minor 6a)
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
    try:
        cur = open(config._CAMERA_IP_FILE, encoding="utf-8").read().strip()
    except OSError:
        cur = None
    ip = find(config.GLASS_MAC, config.GLASS_SUBNET, current=cur)
    say(f"안경 주소: {ip or '못 찾음'}")
    return 0 if ip else 1


if __name__ == "__main__":
    sys.exit(main())
