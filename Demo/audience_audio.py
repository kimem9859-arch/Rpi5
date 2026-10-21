"""관객 소리(TV) 출력 장치 맞춤 — 시연을 켤 때마다 소리 출력을 TV 로 둔다(상위 specs/2026-10-21-관객소리TV-design.md 4장 10 · 11).

실행: python3 Demo/audience_audio.py --apply     (run_demo.sh 가 음성비서보다 먼저 부른다 · 실패해도 시연은 켜진다)
      python3 Demo/audience_audio.py --status    (지금 상태만 · school_check --final 의 「관객 소리(TV)」 줄과 같은 판정)

🔑 TV 와 제우스랩은 단자가 아니라 HDMI 카드의 ELD 이름(/proc/asound/card*/eld#0 의 monitor_name)으로 가른다 —
   화면 설정(/usr/share/dispsetup.sh)과 같은 방식 · 케이블을 바꿔 꽂아도 맞는다.
🔴 왜 매번인가(10/21 실측) — 기본 출력이 TV 인 것은 자동 선택일 뿐 기억된 값이 아니었고, TV 를 파이가 켜진 뒤 꽂자
   TV 카드가 「꺼짐」으로 남았으며, 저장된 TV 출력은 음소거였다. 소리 관리를 다시 시작해도 음소거는 안 풀렸다.
🔴 소리는 내지 않는다 — 설정만 바꾼다.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

ZEUS = "ZEUSLAP"          # 메인 터치 모니터 ELD 이름(화면 설정 스크립트와 같은 표지)
VOLUME = "0.40"           # 10/21 사용자가 TV 음량 10 과 함께 「괜찮다」 한 파이 쪽 출력 크기


def read_elds(root="/proc/asound"):
    """카드 번호 → ELD monitor_name(모니터가 꽂혀 소리 정보를 준 카드만)."""
    out = {}
    for d in sorted(glob.glob(os.path.join(root, "card*"))):
        m = re.fullmatch(r"card(\d+)", os.path.basename(d))
        if not m:
            continue
        for f in sorted(glob.glob(os.path.join(d, "eld#*"))):
            try:
                for ln in open(f, encoding="utf-8", errors="replace"):
                    if ln.startswith("monitor_name"):
                        parts = ln.split(None, 1)
                        name = parts[1].strip() if len(parts) > 1 else ""
                        if name:
                            out[int(m.group(1))] = name
            except OSError:
                pass
    return out


def pick(elds):
    """(TV 카드, 제우스랩 카드) — TV = 이름에 ZEUSLAP 이 없는 첫 카드 · 없으면 None."""
    tv = next((c for c, n in sorted(elds.items()) if ZEUS not in n.upper()), None)
    zeus = next((c for c, n in sorted(elds.items()) if ZEUS in n.upper()), None)
    return tv, zeus


def sinks(dump):
    """pw-dump JSON → {카드 번호: {"id", "name"}} — 출력(Audio/Sink) 노드만."""
    out = {}
    for o in dump or []:
        p = ((o or {}).get("info") or {}).get("props") or {}
        if p.get("media.class") != "Audio/Sink":
            continue
        card = p.get("alsa.card", p.get("api.alsa.card"))
        try:
            out[int(card)] = {"id": int(o["id"]), "name": p.get("node.name", "")}
        except (TypeError, ValueError, KeyError):
            pass
    return out


def _dump(run):
    try:
        r = run(["pw-dump"], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout or "[]")
    except Exception:                           # noqa: BLE001 — 소리 관리가 없으면 빈 목록
        return []


def _out(run, cmd):
    try:
        return run(cmd, capture_output=True, text=True, timeout=5).stdout or ""
    except Exception:                           # noqa: BLE001
        return ""


def apply(run=subprocess.run, log=print, elds=None, sleep=time.sleep):
    """TV 를 기본 출력 · 음소거 해제 · 40% · 제우스랩 음소거. 맞췄으면 True — 예외는 내지 않는다."""
    elds = read_elds() if elds is None else elds
    tv, zeus = pick(elds)
    if tv is None:
        log("관객 소리(TV): TV(HDMI)가 안 보인다 — 건너뜀(TV 케이블 · 전원)")
        return False
    s = sinks(_dump(run))
    if tv not in s:
        log(f"관객 소리(TV): TV 출력(카드 {tv})이 소리 관리에 없다 — 소리 관리를 다시 시작한다")
        try:
            run(["systemctl", "--user", "restart", "pipewire", "pipewire-pulse", "wireplumber"], timeout=15)
        except Exception as e:                  # noqa: BLE001
            log(f"관객 소리(TV): 다시 시작 실패 — {e}")
        for _ in range(12):
            sleep(0.5)
            s = sinks(_dump(run))
            if tv in s:
                break
        if tv not in s:
            log("관객 소리(TV): ❌ 다시 시작해도 TV 출력이 없다 — 안경 소리만")
            return False
    t = str(s[tv]["id"])
    try:
        for cmd in (["wpctl", "set-default", t], ["wpctl", "set-mute", t, "0"], ["wpctl", "set-volume", t, VOLUME]):
            run(cmd, timeout=5)
        if zeus in s:
            run(["wpctl", "set-mute", str(s[zeus]["id"]), "1"], timeout=5)
    except Exception as e:                      # noqa: BLE001
        log(f"관객 소리(TV): ❌ 설정 명령 실패 — {e}")
        return False
    log(f"관객 소리(TV): ✅ 기본 출력 = {elds[tv]}(카드 {tv}) · 음소거 해제 · {VOLUME} · 제우스랩 음소거")
    return True


def status(run=subprocess.run, elds=None):
    """(정상인가, 한 줄 설명) — 기본 출력이 TV 이고 음소거 아님 · 제우스랩은 음소거."""
    elds = read_elds() if elds is None else elds
    tv, zeus = pick(elds)
    if tv is None:
        return False, "TV(HDMI)가 안 보인다 — TV 케이블 · 전원"
    s = sinks(_dump(run))
    if tv not in s:
        return False, f"TV 출력(카드 {tv})이 소리 관리에 없다"
    m = re.match(r"\s*id (\d+)", _out(run, ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"]))
    if not m or int(m.group(1)) != s[tv]["id"]:
        return False, f"기본 출력이 TV 가 아니다(기본 id {m.group(1) if m else '없음'} · TV id {s[tv]['id']})"
    vol = _out(run, ["wpctl", "get-volume", str(s[tv]["id"])]).strip()
    if "MUTED" in vol:
        return False, f"TV 출력이 음소거다({vol})"
    if zeus in s and "MUTED" not in _out(run, ["wpctl", "get-volume", str(s[zeus]["id"])]):
        return False, "제우스랩 출력이 음소거가 아니다"
    return True, f"{elds[tv]} · {vol}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="관객 소리(TV) 출력 장치 맞춤")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="TV 를 기본 출력 · 음소거 해제 · 40% · 제우스랩 음소거")
    g.add_argument("--status", action="store_true", help="지금 상태만 본다")
    a = ap.parse_args(argv)
    stamp = time.strftime("%F %T")
    if a.apply:
        ok = apply(log=lambda m: print(f"[{stamp}] {m}", flush=True))
    else:
        ok, d = status()
        print(f"[{stamp}] 관객 소리(TV): {'✅' if ok else '❌'} {d}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
