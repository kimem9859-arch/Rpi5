#!/usr/bin/env python3
"""학교 사전 점검 — 시연을 켜기 전에 한 번(약 30초). 항목마다 ✅ / ❌ 와, ❌ 면 대처표 번호 · 칠 명령을 보인다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §8.1(대처표 V1~V23) · §8.2
실행: python3 Demo/test/school_check.py           (학교 · 실물 · 10/12 측정용)
      python3 Demo/test/school_check.py --home    (집 · 가짜 장치 127.0.0.1 — 실물에만 맞는 항목은 「집 · 건너뜀」)
      python3 Demo/test/school_check.py --final   (🆕 최종 시연 — 인터넷 · 키 파일 · 출발 태그 · 측정 대본은 보지 않고
                                                   파이2 LLM 응답 · 코드 판을 본다 · 순서표 = 상위 docs/최종-시연-점검.md)
🔴 비밀값(와이파이 · API 키)은 열지 않는다 — 키 파일은 있는지만 본다(.claude/rules/비밀정보.md).
🔴 문제 프로세스를 자동으로 끄지 않는다 — 번호와 명령만 보인다(다른 작업을 끌 수 있다).
"""
import argparse
import glob
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

TEST = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(TEST)
RPI5 = os.path.dirname(DEMO)
sys.path.insert(0, DEMO)

import config   # noqa: E402

Check = namedtuple("Check", "group name ok detail fix")    # ok = True · False · None(건너뜀)
TAG = "학교1012-출발"
SCRIPTS = ("장소1_⑤음성.csv", "장소1_①정상.csv", "장소1_⑥근거.csv")
SWITCHES = ("SOP_",)


def _c(group, name, ok, detail="", fix=""):
    return Check(group, name, ok, detail, fix)


# ── 안경 ────────────────────────────────────────────────────────────────────
def ip_band(ip):
    ok = ip.startswith("192.168.1.")
    return _c("안경", "IP 대역", ok, f".camera_ip = {ip}",
              "" if ok else "V1 · 안경 전원을 껐다 켜고 → 안경을 USB 로 꽂고 bash arduino/update_ip.sh(메인 안경을 시리얼번호로 찾는다)")


def recv_probe(host, port=None, sec=5.0):
    """sec 동안 받아 받은 fps · 평균 장 크기 · 첫 장 풀림 — 연결 안 됨 V2 · 느림 V4."""
    port = port or config.CAMERA_TCP_PORT
    try:
        s = socket.create_connection((host, port), timeout=3)
    except OSError as e:
        return _c("안경", "연결 · 받기", False, f"{host}:{port} 연결 안 됨 — {e}",
                  "V2 · 안경을 USB 로 꽂고 bash arduino/update_ip.sh(바뀐 IP 를 읽어 .camera_ip 갱신) · 안경 전원")
    s.settimeout(3)
    n, size, first, t0 = 0, 0, None, time.monotonic()
    try:
        while time.monotonic() - t0 < sec:
            ln = struct.unpack("<I", _exact(s, 4))[0]
            data = _exact(s, ln)
            n += 1
            size += ln
            first = first if first is not None else data
    except (OSError, struct.error) as e:
        s.close()
        return _c("안경", "연결 · 받기", False, f"받다가 끊김 — {e} · {n}장", "V4 · 배터리 → 공유기 거리 → V1")
    s.close()
    fps = n / max(time.monotonic() - t0, 1e-6)
    ok_dec = False
    if first is not None:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(first, np.uint8), cv2.IMREAD_COLOR)
        ok_dec = img is not None
    detail = f"받은 {fps:.1f} fps · 장 평균 {size / max(n, 1) / 1000:.1f}KB · 풀림 {'✓' if ok_dec else '✗'}"
    ok = fps >= 15 and ok_dec
    return _c("안경", "연결 · 받기", ok, detail, "" if ok else "V4 · 볼 순서 = V1(IP 대역) → 배터리 → 공유기와의 거리")


def _exact(s, n):
    b = b""
    while len(b) < n:
        part = s.recv(n - len(b))
        if not part:
            raise OSError("끊김")
        b += part
    return b


def glass_ports(host):
    bad = []
    for p in (8889, 8890):
        try:
            socket.create_connection((host, p), timeout=2).close()
        except OSError:
            bad.append(str(p))
    return _c("음성", "안경 마이크 · 명령 포트", not bad, "8889 · 8890" + (f" — 안 됨 {'·'.join(bad)}" if bad else " 연결됨"),
              "" if not bad else "V2 · 안경 IP · 전원 확인(카메라 8888 은 되는데 이것만 안 되면 펌웨어가 glass_voice 인지)")


# ── Hailo ───────────────────────────────────────────────────────────────────
def hailo_scan():
    try:
        r = subprocess.run(["hailortcli", "scan"], capture_output=True, text=True, timeout=10)
        ok = r.returncode == 0 and "Device" in r.stdout
        return _c("Hailo", "장치", ok, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[:80],
                  "" if ok else "파이 재부팅 전 사용자 확인 · PCIe 연결")
    except (OSError, subprocess.TimeoutExpired) as e:
        return _c("Hailo", "장치", False, str(e), "hailortcli 가 없다 · 설치 확인")


def hailo_holders(proc_root="/proc"):
    """/dev/hailo0 을 연 프로세스 — 자동으로 끄지 않는다(V5)."""
    me = str(os.getpid())
    held = []
    for pid in os.listdir(proc_root) if os.path.isdir(proc_root) else ():
        if not pid.isdigit() or pid == me:
            continue
        fd = os.path.join(proc_root, pid, "fd")
        try:
            links = [os.readlink(os.path.join(fd, x)) for x in os.listdir(fd)]
        except OSError:
            continue
        if any(ln.startswith("/dev/hailo") for ln in links):
            try:
                with open(os.path.join(proc_root, pid, "cmdline"), "rb") as f:
                    cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            except OSError:
                cmd = "?"
            held.append((pid, cmd))
    if not held:
        return _c("Hailo", "장치를 쥔 프로세스", True, "없음")
    detail = " · ".join(f"{p} {c[:60]}" for p, c in held)
    return _c("Hailo", "장치를 쥔 프로세스", False, detail,
              "V5 · 앞 시연이 안 꺼졌다 — 화면이 있으면 ESC 로 닫고, 없으면 " + " · ".join(f"kill {p}" for p, _ in held))


# ── 파이 ────────────────────────────────────────────────────────────────────
def _vcgencmd(arg):
    try:
        return subprocess.run(["vcgencmd", arg], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def temp_c(limit=75.0):
    out = _vcgencmd("measure_temp")
    try:
        t = float(out.split("=")[1].split("'")[0])
    except (IndexError, ValueError):
        return _c("파이", "온도", None, f"읽지 못함 {out!r}")
    return _c("파이", "온도", t <= limit, f"{t:.1f}℃", "" if t <= limit else "V7 · 식힌 뒤 · 쿨러 확인")


def throttled():
    out = _vcgencmd("get_throttled")
    ok = out.endswith("=0x0")
    return _c("파이", "스로틀(전압 · 열)", ok if out else None, out or "읽지 못함",
              "" if ok or not out else "V7 · 전원 어댑터 · 열 확인(이 세션은 ⚠️)")


def free_space(path, min_gb=1.0):
    """남은 공간 — 문턱은 실행기 경고(1GB)와 같게 · 측정 세션 하나는 약 10MB(원본 녹화를 켜면 훨씬 크다)."""
    gb = shutil.disk_usage(path if os.path.isdir(path) else os.path.dirname(path)).free / 1e9
    ok = gb >= min_gb
    return _c("파이", "남은 공간", ok, f"{gb:.1f}GB",
              "" if ok else "V8 · 원본 녹화를 끄고 · 지난 녹화(Demo/recordings)는 사용자 확인 뒤 외장 저장소로(지우지 않음)")


def mem_avail(min_mb=500):
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            kb = next(int(ln.split()[1]) for ln in f if ln.startswith("MemAvailable"))
    except (OSError, StopIteration, ValueError):
        return _c("파이", "남은 메모리", None, "읽지 못함")
    ok = kb / 1024 >= min_mb
    return _c("파이", "남은 메모리", ok, f"{kb / 1024:.0f}MB", "" if ok else "다른 프로그램을 닫는다")


# ── 인터락 ──────────────────────────────────────────────────────────────────
def interlock_ack(port):
    if not port:
        return _c("인터락", "RUN 응답", False, "포트를 못 찾음", "V10 · USB 확인 → SOP_INTERLOCK_PORT=<경로> 로 지정")
    try:
        import serial
        with serial.Serial(port, config.INTERLOCK_BAUD, timeout=1.5) as ser:
            time.sleep(2.0)                       # 아두이노는 열 때 재시작한다
            ser.reset_input_buffer()
            ser.write(b"RUN\n")
            ack = ser.readline().decode("ascii", "replace").strip()
    except Exception as e:                          # noqa: BLE001
        return _c("인터락", "RUN 응답", False, f"{port} — {e}", "V10 · 시연이 켜져 있으면 끄고 · USB 확인")
    return _c("인터락", "RUN 응답", ack == "ACK", f"{port} → {ack!r}", "" if ack == "ACK" else "V10 · 배선 · 아두이노")


# ── 음성 ────────────────────────────────────────────────────────────────────
def internet():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2).close()
        return _c("음성", "인터넷", True, "연결됨")
    except OSError as e:
        return _c("음성", "인터넷", False, str(e), "V13 · ⑤음성 측정을 뒤로 · 와이파이 확인")


def key_file(path=os.path.join(RPI5, ".env")):
    ok = os.path.exists(path)                     # 🔴 있는지만 — 열지 않는다
    return _c("음성", "키 파일", ok, ".env 있음" if ok else ".env 없음", "" if ok else "V13 · 키 파일 위치 확인(값은 말하지 않는다)")


def answer_wavs():
    n = len(glob.glob(os.path.join(DEMO, "voice", "wav", "*.wav")))
    return _c("음성", "답 · 안내 소리 파일", n > 0, f"{n}개", "" if n else "voice/make_answers.py 로 만든다")


def llm_check(url=None, model=None, timeout=3.0):
    """파이2 ollama 가 닿고 시연 모델이 있는가 — 음성비서가 실제로 기대는 곳(인터넷 · 키는 쓰지 않는다).
    🔴 ollama 는 파이2 유선 주소 192.168.1.12 에만 열려 있다(파이2 OLLAMA_HOST) — 그런데 파이1 · 파이2 유선은 둘 다
       공유기가 주는 자동 주소다(2026-10-15 확인). 공유기가 파이2 에 .12 를 주지 않으면 LLM 이 통째로 안 된다."""
    url, model = url or config.LLM_URL, model or config.LLM_MODEL
    u = urllib.parse.urlsplit(url)
    tags = f"{u.scheme}://{u.netloc}/api/tags"
    fix_net = ("파이2 를 켠 지 1분 안이면 기다렸다 다시 · 파이2 전원 · 파이1 · 파이2 랜선이 공유기에 꽂혔나 · "
               "파이1 유선 주소가 192.168.1.x 인가(ip -4 addr show eth0) · "
               "파이2 가 공유기에서 꼭 192.168.1.12 를 받았나(ollama 는 그 주소에서만 받는다 · 공유기 주소 예약)")
    fix_srv = "파이2 에는 닿았는데 ollama 가 오류를 냈다 — 파이2 에서 systemctl status ollama · ollama list"
    import json
    try:
        with urllib.request.urlopen(tags, timeout=timeout) as r:
            names = [m.get("name", "") for m in json.load(r).get("models", [])]
    except urllib.error.HTTPError as e:            # 서버에 닿았다(랜선 · 주소 문제 아님)
        return _c("음성", "파이2 LLM 응답", False, f"{u.netloc} — HTTP {e.code}", fix_srv)
    except (ValueError, TypeError, AttributeError) as e:   # 답은 왔는데 모양이 다르다
        return _c("음성", "파이2 LLM 응답", False, f"{u.netloc} — 답 모양이 다름 {e}", fix_srv)
    except Exception as e:                          # noqa: BLE001
        return _c("음성", "파이2 LLM 응답", False, f"{u.netloc} — {e}", fix_net)
    ok = model in names
    return _c("음성", "파이2 LLM 응답", ok, f"{u.netloc} · {model}" + ("" if ok else f" 없음(있는 것 {' · '.join(names) or '없음'})"),
              "" if ok else "파이2 에서 ollama list 로 모델 확인 — 음성비서는 고정 문장으로만 답한다")


# ── 코드 ────────────────────────────────────────────────────────────────────
def git_clean(repo=RPI5, final=False, lines_for_test=None):
    if lines_for_test is None:
        r = subprocess.run(["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True)
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    else:
        lines = lines_for_test
    # 🔴 최종 모드에는 출발 태그가 없다 — 「학교1012-출발」은 10/12 판이라 되돌리면 그 뒤 개선이 모두 사라진다(리뷰 Important 1)
    fix = ("무엇인지 Claude 가 보고 정한다 — 함부로 되돌리지 않는다" if final
           else "V9 · 무엇인지 Claude 가 보고 정한다(출발 태그로 되돌리기 가능)")
    return _c("코드", "커밋 안 된 변경", not lines, f"{len(lines)}개" + (f" — {lines[0]}" if lines else ""),
              "" if not lines else fix)


def git_head(repo=RPI5):
    """지금 도는 코드 판 — 어느 판으로 시연했는지 남긴다(판정 없음 · 늘 ✅)."""
    def git(*a):
        return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True).stdout.strip()
    head = git("log", "-1", "--format=%h %ad", "--date=format:%m-%d %H:%M") or "읽지 못함"
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    # 인터넷 없이 — 마지막으로 받아 온 origin/main 과 비교만(판정 없음)
    ahead_behind = git("rev-list", "--left-right", "--count", "HEAD...origin/main").split()
    if len(ahead_behind) == 2:
        a, b = ahead_behind
        rel = "origin/main 과 같음" if a == b == "0" else f"origin/main 보다 {a}개 앞 · {b}개 뒤(마지막으로 받아 온 기준)"
    else:
        rel = "origin/main 없음"
    return _c("코드", "코드 판", True, f"{branch} · {head} · {rel}")


def at_tag(repo=RPI5, tag=TAG):
    t = subprocess.run(["git", "-C", repo, "rev-parse", "-q", "--verify", tag + "^{commit}"], capture_output=True, text=True)
    if t.returncode != 0:
        return _c("코드", f"출발 태그 {tag}", None, "태그 없음(출발 전)")
    h = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    ok = h == t.stdout.strip()
    return _c("코드", f"출발 태그 {tag}", ok, "같음" if ok else f"HEAD {h[:7]} ≠ 태그 {t.stdout.strip()[:7]}",
              "" if ok else f"V9 · Claude 가 차이를 본다(git -C {repo} log --oneline {tag}..HEAD)")


def stray_env(env=None):
    env = os.environ if env is None else env
    names = sorted(k for k in env if k.startswith(SWITCHES))
    return _c("코드", "셸에 남은 SOP_* 변수", not names, " · ".join(names) or "없음",
              "" if not names else "V9 · 새 터미널을 연다(실행기가 처리 스위치는 지우지만 주소 · 포트 변수는 남는다)")


# ── 파일 ────────────────────────────────────────────────────────────────────
def files(scripts=SCRIPTS):
    need = [os.path.join(DEMO, "measure", "시나리오", n) for n in scripts]
    need += [config.HEF_MODEL_PATH, config.TOOL_HEF_PATH,
             os.path.join(config.HAND_MODELS_DIR, "palm_detection_lite.hef"),
             os.path.join(config.HAND_MODELS_DIR, "hand_landmark_lite.hef"),
             os.path.join(DEMO, "camera_calibration_1024x768.npz")]
    miss = [p for p in need if not os.path.exists(p)]
    bins = sorted(glob.glob(os.path.expanduser("~/lab/esp32-link/main_5D38_full_*.bin")))
    if not bins or not os.path.exists(bins[-1] + ".md5"):
        miss.append("안경 펌웨어 백업 main_5D38_full_*.bin(.md5)")
    detail = "다 있음" if not miss else " · ".join(os.path.basename(m) for m in miss)
    if bins:
        detail += f" · 최근 백업 {os.path.basename(bins[-1])}"
    name = ("대본 · " if scripts else "") + "모델 · 보정 · 펌웨어 백업"
    return _c("파일", name, not miss, detail, "" if not miss else "Claude 가 경로를 찾는다")


def _demo_running():
    r = subprocess.run(["pgrep", "-f", "python3 main.py"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def run(home=False, final=False):
    host = "127.0.0.1" if home else config.CAMERA_TCP_HOST
    skip = lambda g, n, why="집 · 건너뜀": _c(g, n, None, why)     # noqa: E731
    # 🔴 시연이 켜져 있으면 안경 · 인터락 · Hailo 를 건드리지 않는다 — 안경은 손님 하나라 새 연결이 시연 연결을 끊고,
    #    Hailo 를 쥔 프로세스는 시연 자신이다(끄라고 안내하면 안 된다 · 최종 리뷰 Minor 2)
    busy = (not home) and _demo_running()
    why_busy = "시연이 켜져 있다 — 시연을 닫고 다시(측정 연결을 끊지 않게 건너뜀)"
    out = [skip("안경", "IP 대역") if home else ip_band(host)]
    if busy:
        out += [skip("안경", "연결 · 받기", why_busy), skip("음성", "안경 마이크 · 명령 포트", why_busy),
                hailo_scan(), skip("Hailo", "장치를 쥔 프로세스", "시연이 쥐고 있다(정상) — 시연을 닫고 다시")]
    else:
        out += [recv_probe(host, sec=5.0 if not home else 2.0), glass_ports(host), hailo_scan(), hailo_holders()]
    out += [temp_c(), throttled(), free_space(os.path.join(DEMO, "measure")), mem_avail()]
    if home:
        out.append(skip("인터락", "RUN 응답"))
    elif busy:
        out.append(skip("인터락", "RUN 응답", why_busy))
    else:
        out.append(interlock_ack(config.find_interlock_port()[0]))
    env = {k: v for k, v in os.environ.items() if not (home and k in ("SOP_CAMERA_HOST", "SOP_INTERLOCK_PORT"))}
    if final:       # 🆕 최종 시연 — 음성비서는 인터넷 · 키를 쓰지 않는다(우리 공유기가 인터넷에 물려 있지 않으면 헛 ❌) · 측정 대본 · 출발 태그 없음
        out += [answer_wavs(), skip("음성", "파이2 LLM 응답") if home else llm_check(),
                git_head(), git_clean(final=True), stray_env(env), files(scripts=())]
        order = {}
        for c in out:                       # 같은 묶음은 한 머리 아래로(처음 나온 순서 · 순서표 4장 표와 같게)
            order.setdefault(c.group, len(order))
        return sorted(out, key=lambda c: order[c.group])
    out += [internet(), key_file(), answer_wavs(),
            git_clean(), skip("코드", f"출발 태그 {TAG}") if home else at_tag(),
            stray_env(env), files()]
    return out


def report(res):
    mark = {True: "✅", False: "❌", None: "⏭"}
    group = None
    for c in res:
        if c.group != group:
            group = c.group
            print(f"[{group}]")
        print(f"  {mark[c.ok]} {c.name} — {c.detail}" + (f"\n      → 대처 {c.fix}" if c.ok is False and c.fix else ""))
    bad = [c for c in res if c.ok is False]
    print(f"\n{'✅ 점검 통과' if not bad else f'❌ {len(bad)}건 — 위 「대처」를 따르고 다시 돌린다'}")
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="학교 사전 점검(학교 방문 준비 설계 §8.2) · 최종 시연 점검(--final)")
    ap.add_argument("--home", action="store_true", help="집 · 가짜 장치(127.0.0.1)")
    ap.add_argument("--final", action="store_true", help="최종 시연 — 파이2 LLM · 코드 판 · 인터넷/키/대본/출발 태그 빼고")
    a = ap.parse_args(argv)
    return report(run(home=a.home, final=a.final))


if __name__ == "__main__":
    sys.exit(main())
