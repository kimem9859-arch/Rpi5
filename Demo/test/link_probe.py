"""ESP32 링크 품질 한 라운드 측정 — 조건을 바꿔가며 대조하는 도구.

왜 필요한가:
    §10.42-(7) 의 「ESP32 무선 링크 불안정」이 **유휴 ping 요동**으로만 관측돼 있었다.
    2026-08-26 에 스트리밍 중에는 손실 0%·RTT 20ms 로 안정적이라는 것이 드러나
    (유휴 13.3%·85ms) **유휴 ping 은 운용 조건을 대표하지 않는다**는 것이 밝혀졌다.
    그래서 이 도구는 **스트리밍 중**을 주 지표로 삼고 유휴는 참고로만 잰다.

무엇을 재는가 (한 라운드):
    ① 순수 수신 FPS — 파이 추론·GUI 를 거치지 않는 **공급 상한**
       (GUI FPS 는 파이 부하가 섞여 링크 비교에 못 쓴다)
    ② 프레임 크기·처리량 — 🔴 **FPS 는 프레임 크기와 함께 봐야 한다.**
       §10.34 의 24fps 는 10.1KB 짜리 프레임이었고 2026-08-26 은 15.6KB 다.
       크기를 안 적은 FPS 는 재현되지 않는다.
    ③ 스트리밍 중 ping — 무선 품질 직접 지표
    ④ 유휴 ping — 옛 측정과 잇기 위한 참고값

🔴 조건을 바꿔 비교할 때는 **교차로 최소 2회씩** 재라.
   FPS 가 같은 조건에서도 15.4↔20.5 로 흔들린다(2026-08-26 실측). 한 번씩 재면
   그 변동을 조건 효과로 잘못 읽는다.

사용:
    python3 test/link_probe.py "프레임 안"
    python3 test/link_probe.py "프레임 밖"
    python3 test/link_probe.py --summary          # 지금까지 라운드 집계
    python3 test/link_probe.py --reset            # 기록 비우기

    # 🔑 송신 윈도 판별 실험 (아래 참조)
    python3 test/link_probe.py "윈도64K" 60 --rcvbuf 65536
    python3 test/link_probe.py "윈도4K"  60 --rcvbuf 4096

🔑 **`--rcvbuf` 는 왜 있나 — 「대역폭이냐 왕복지연이냐」를 가르는 실험이다.**
    2026-09-05 에 이 파일에 쌓인 18라운드를 회귀했더니 처리량이 전 구간에서
    `5744바이트 ÷ RTT` 선을 따라갔다(실측/상한 59~153%, 중앙 91%). 5744 는 맞춘 수가
    아니라 ESP32 툴체인의 `CONFIG_LWIP_TCP_SND_BUF_DEFAULT` 값이다. 사실이라면
    **FPS 는 대역폭이 아니라 왕복 지연에 매여 있다.**

    그런데 「무선 여유가 없어 처리량과 지연이 함께 나빠졌을 뿐」이라는 설명도 같은
    모양을 만든다. 둘을 가르는 방법 = **파이 쪽 수신 윈도를 좁혀 본다.**
      · 64KB → 8KB 로 줄여도 처리량이 그대로면 → 이미 **보내는 쪽이 상한**(윈도 가설 ✅)
      · 줄이는 대로 처리량이 같이 줄면 → 수신 윈도가 상한이었다(가설 기각·조건 재설정)
    🔴 실험 뒤에는 `--rcvbuf` 없이 다시 재서 평소 값으로 돌아오는지 확인하라.

결과는 `test/link_probe.json` 에 누적된다(gitignore 대상인 test/ 산출물).
"""

import json
import os
import re
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.dirname(_HERE)
sys.path.insert(0, _DEMO)

import config  # noqa: E402
import link_ctx  # noqa: E402
from pi_load import PiLoad  # noqa: E402

_STORE = os.path.join(_HERE, "link_probe.json")

# ESP32(lwIP)의 TCP 송신 버퍼 — `CONFIG_LWIP_TCP_SND_BUF_DEFAULT`(= 4 × MSS 1436).
# 🔴 실행 중 못 바꾼다: 이 툴체인은 `CONFIG_LWIP_SO_SNDBUF` 가 꺼져 있어 펌웨어의
#    `setsockopt(SO_SNDBUF, 32768)` 이 무시된다(esp32s3-libs 3.3.10 sdkconfig 확인).
#    → 보내는 쪽이 한 왕복에 내보낼 수 있는 양의 상한이 이 값이다.
# ⚠️ 툴체인을 올리거나 커스텀 빌드로 바꾸면 이 상수도 같이 고칠 것.
ESP32_SND_WND = 5744
_PING_RE = re.compile(
    r"(\d+) packets transmitted, (\d+) received.*?([\d.]+)% packet loss", re.S)
_RTT_RE = re.compile(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)")


def ping(host, count, interval=0.5):
    r = subprocess.run(["ping", "-c", str(count), "-i", str(interval), "-W", "2", host],
                       capture_output=True, text=True)
    out = {"loss": None, "avg": None, "max": None, "mdev": None}
    m = _PING_RE.search(r.stdout)
    if m:
        out["loss"] = float(m.group(3))
    m = _RTT_RE.search(r.stdout)
    if m:
        out["avg"] = float(m.group(2))
        out["max"] = float(m.group(3))
        out["mdev"] = float(m.group(4))
    return out


def recv_stream(host, port, seconds, ping_result, rcvbuf=None):
    """순수 수신 — 4바이트 길이 헤더 + JPEG (camera_thread._recv_latest_frame 과 같은 규약).

    🔴 끊기면 죽지 않고 **재연결한다** — 런타임(`camera_thread`)도 그렇게 돌고,
       무엇보다 **끊김 횟수 자체가 측정하려는 지표**다. 예외로 라운드를 통째로
       잃으면 「가장 나쁜 조건」의 데이터만 사라진다.
    """
    # ping 은 수신과 **같은 구간에서** 재야 조건이 같다.
    t = threading.Thread(target=lambda: ping_result.update(ping(host, int(seconds / 0.5))))
    t.start()

    sizes, gaps, last, drops = [], [], None, 0
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            s = socket.socket()
            s.settimeout(10)
            if rcvbuf:
                # 🔴 반드시 connect() **전에** 걸어야 한다 — 3-way handshake 에서
                #    광고할 윈도가 이때 정해진다. 커널이 값을 2배로 부풀려 잡으므로
                #    실제 광고 윈도는 여기 넣은 값과 정확히 같지 않다(경향만 본다).
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, int(rcvbuf))
            s.connect((host, port))

            def rx(n):
                b = b""
                while len(b) < n:
                    d = s.recv(n - len(b))
                    if not d:
                        return None
                    b += d
                return b

            while time.time() - t0 < seconds:
                h = rx(4)
                if h is None:
                    break
                ln = struct.unpack("<I", h)[0]
                d = rx(ln)
                if d is None:
                    break
                now = time.time()
                if last is not None:
                    gaps.append(now - last)
                last = now
                sizes.append(ln)
        except (OSError, socket.timeout, struct.error):
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        if time.time() - t0 < seconds:
            drops += 1
            last = None          # 재연결 공백을 프레임 간격으로 세지 않는다
            time.sleep(1.0)
    t.join(timeout=30)
    return sizes, gaps, drops


def pct(vals, p):
    return sorted(vals)[min(len(vals) - 1, int(len(vals) * p))]


def run_round(label, seconds, rcvbuf=None):
    host = config.CAMERA_TCP_HOST
    port = config.CAMERA_TCP_PORT
    print(f"[{label}] {host}:{port} — {seconds:.0f}초 측정…", flush=True)
    if rcvbuf:
        print(f"  🔬 수신 윈도 실험: SO_RCVBUF={rcvbuf}B", flush=True)

    pi = PiLoad()
    ctx = link_ctx.Sampler(host, port).start()
    stream_ping = {}
    sizes, gaps, drops = recv_stream(host, port, seconds, stream_ping, rcvbuf)
    # 🔴 수신이 끝나자마자 읽는다 — 유휴 ping 구간의 부하가 섞이면 안 된다.
    pi_snap = pi.read()
    ctx_snap = ctx.stop()
    if len(gaps) < 10:
        print("🔴 프레임을 거의 못 받았다 — 연결·전원을 확인하라.")
        return None

    print("  유휴 ping…", flush=True)
    time.sleep(2)                      # 스트림을 끊고 잠잠해지기를 기다린다
    idle_ping = ping(host, 30)

    r = {
        "label": label,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        # 🔴 대상 IP 를 반드시 남긴다 — 2026-09-04 에 라운드 도중 병행 세션이
        #    `.camera_ip` 를 바꿔, 어느 라운드가 어느 보드였는지 못 가렸다.
        "host": host,
        "rcvbuf": rcvbuf,
        "ctx": ctx_snap,
        "frames": len(sizes),
        "fps": len(gaps) / sum(gaps),
        "gap_med_ms": statistics.median(gaps) * 1000,
        "gap_p90_ms": pct(gaps, 0.9) * 1000,
        "gap_max_ms": max(gaps) * 1000,
        "stalls_500ms": sum(1 for g in gaps if g > 0.5),
        "drops": drops,
        "size_med_kb": statistics.median(sizes) / 1024,
        "kbps": sum(sizes) / sum(gaps) / 1024,
        "stream_ping": stream_ping,
        "idle_ping": idle_ping,
        "cpu_max": pi_snap.get("cpu_max"),
        "cpu_avg": pi_snap.get("cpu_avg"),
        "temp": pi_snap.get("temp"),
        "dirty": PiLoad.dirty(pi_snap),
        "top": pi_snap.get("top"),
    }
    print(f"  FPS {r['fps']:.2f} · 프레임 {r['size_med_kb']:.1f}KB · "
          f"처리량 {r['kbps']:.0f}KB/s · 멈춤(>0.5s) {r['stalls_500ms']}회 · "
          f"연결끊김 {r['drops']}회")
    print(f"  간격 중앙 {r['gap_med_ms']:.0f} / p90 {r['gap_p90_ms']:.0f} / "
          f"max {r['gap_max_ms']:.0f} ms")
    sp, ip_ = r["stream_ping"], r["idle_ping"]
    print(f"  ping 스트리밍중 손실{sp.get('loss')}% avg{sp.get('avg')} max{sp.get('max')} · "
          f"유휴 손실{ip_.get('loss')}% avg{ip_.get('avg')} max{ip_.get('max')}")
    print("  " + PiLoad.fmt(pi_snap))
    print("  " + link_ctx.fmt(ctx_snap))
    # 🔑 「대역폭이냐 왕복지연이냐」를 그 자리에서 보여준다 — 이 상한을 넘지 못하면
    #    조명·구도·모델과 무관하게 그 지연에서는 더 나올 수가 없다는 뜻이다.
    rtt = (r["stream_ping"] or {}).get("avg")
    if rtt:
        cap = ESP32_SND_WND / (rtt / 1000.0) / 1024        # KB/s
        ratio = 100 * r["kbps"] / cap
        pct_s = f"{ratio:.0f}%" if ratio >= 10 else f"{ratio:.1f}%"
        print(f"  윈도상한 {cap:.0f}KB/s (= {ESP32_SND_WND}B ÷ RTT {rtt:.2f}ms) · "
              f"실측 {r['kbps']:.0f}KB/s = 상한의 {pct_s}")
        # 🔑 읽는 법 — 상한에 붙어 있으면(대략 60% 이상) 그 지연에서는 **더 나올 수가
        #    없다**는 뜻이라 조명·구도·모델을 손봐야 소용없다. 한참 아래면 병목이
        #    다른 데 있다(파이 부하·카메라·프레임 크기).
        if ratio < 40:
            print("  ⚠️ 상한에서 멀다 — 이 라운드의 병목은 무선 왕복지연이 아닐 수 있다")
    if r["dirty"]:
        # 🔴 파이가 바빴으면 이 라운드의 「멈춤」은 ESP32 가 아니라 파이 탓일 수 있다.
        print("  🔴 파이 부하로 오염 가능: %s — 이 값을 링크 판정에 쓰지 말 것"
              % ", ".join(r["dirty"]))
    return r


def load():
    if os.path.exists(_STORE):
        with open(_STORE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save(rows):
    with open(_STORE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


def summary(rows):
    if not rows:
        print("기록이 없다.")
        return
    by = {}
    for r in rows:
        by.setdefault(r["label"], []).append(r)

    print("\n" + "=" * 74)
    print("%-12s %-4s %-8s %-9s %-10s %-7s %-7s %-9s %-8s" %
          ("조건", "n", "FPS", "프레임KB", "처리량KB/s", "멈춤", "끊김", "스트림ping", "CPU최대"))
    print("-" * 74)
    for label, rs in by.items():
        f = statistics.median([r["fps"] for r in rs])
        k = statistics.median([r["size_med_kb"] for r in rs])
        b = statistics.median([r["kbps"] for r in rs])
        st = sum(r["stalls_500ms"] for r in rs)
        dr = sum(r.get("drops", 0) for r in rs)
        pl = [r["stream_ping"].get("avg") for r in rs if r["stream_ping"].get("avg")]
        p = statistics.median(pl) if pl else float("nan")
        cm = [r.get("cpu_max") for r in rs if r.get("cpu_max") is not None]
        c = max(cm) if cm else float("nan")
        print("%-12s %-4d %-8.2f %-9.1f %-10.0f %-7d %-7d %-9.1f %-8.0f" %
              (label, len(rs), f, k, b, st, dr, p, c))
        # 🔴 조건이 섞였으면 위 중앙값을 조건 효과로 읽지 말 것 —
        #    2026-09-04 에 라운드 도중 대상 보드가 바뀐 채로 하나의 추세로 읽었다.
        hosts = {r.get("host") for r in rs if r.get("host")}
        chans = {(r.get("ctx") or {}).get("channel") for r in rs
                 if (r.get("ctx") or {}).get("channel")}
        note = []
        if len(hosts) > 1:
            note.append("🔴 대상 보드가 섞였다: " + ", ".join(sorted(hosts)))
        elif hosts:
            note.append("대상 " + next(iter(hosts)))
        if len(chans) > 1:
            note.append("🔴 채널이 섞였다: " + ", ".join(str(c) for c in sorted(chans)))
        elif chans:
            note.append("ch%s" % next(iter(chans)))
        rb = {r.get("rcvbuf") for r in rs}
        if rb - {None}:
            note.append("rcvbuf " + ", ".join(str(x) for x in sorted(rb - {None})))
        if note:
            print("             └ " + " · ".join(note))
    print("=" * 74)
    if len(by) == 2:
        (la, ra), (lb, rb) = list(by.items())
        fa = statistics.median([r["fps"] for r in ra])
        fb = statistics.median([r["fps"] for r in rb])
        # 🔴 라운드마다 프레임 크기가 다르면 FPS 만으로 비교할 수 없다 — 처리량도 함께 본다.
        ba = statistics.median([r["kbps"] for r in ra])
        bb = statistics.median([r["kbps"] for r in rb])
        print(f"FPS  {la} {fa:.2f}  vs  {lb} {fb:.2f}   → 차이 {(fb-fa)/fa*100:+.1f}%")
        print(f"처리량 {la} {ba:.0f}  vs  {lb} {bb:.0f} KB/s → 차이 {(bb-ba)/ba*100:+.1f}%")
        if min(len(ra), len(rb)) < 2:
            print("⚠️ 각 조건 2회 미만이다 — FPS 는 같은 조건에서도 흔들린다. 더 재라.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--reset":
        if os.path.exists(_STORE):
            os.remove(_STORE)
        print("기록을 비웠다.")
        return 0
    if args[0] == "--summary":
        summary(load())
        return 0

    rcvbuf = None
    if "--rcvbuf" in args:
        i = args.index("--rcvbuf")
        try:
            rcvbuf = int(args[i + 1])
        except (IndexError, ValueError):
            print("--rcvbuf 뒤에 바이트 수를 적어라. 예: --rcvbuf 8192")
            return 1
        args = args[:i] + args[i + 2:]

    label = args[0]
    seconds = float(args[1]) if len(args) > 1 else 60.0
    r = run_round(label, seconds, rcvbuf)
    if r is None:
        return 1
    rows = load()
    rows.append(r)
    save(rows)
    summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
