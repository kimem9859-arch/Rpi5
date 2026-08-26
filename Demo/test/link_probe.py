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

_STORE = os.path.join(_HERE, "link_probe.json")
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


def recv_stream(host, port, seconds, ping_result):
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


def run_round(label, seconds):
    host = config.CAMERA_TCP_HOST
    port = config.CAMERA_TCP_PORT
    print(f"[{label}] {host}:{port} — {seconds:.0f}초 측정…", flush=True)

    stream_ping = {}
    sizes, gaps, drops = recv_stream(host, port, seconds, stream_ping)
    if len(gaps) < 10:
        print("🔴 프레임을 거의 못 받았다 — 연결·전원을 확인하라.")
        return None

    print("  유휴 ping…", flush=True)
    time.sleep(2)                      # 스트림을 끊고 잠잠해지기를 기다린다
    idle_ping = ping(host, 30)

    r = {
        "label": label,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
    }
    print(f"  FPS {r['fps']:.2f} · 프레임 {r['size_med_kb']:.1f}KB · "
          f"처리량 {r['kbps']:.0f}KB/s · 멈춤(>0.5s) {r['stalls_500ms']}회 · "
          f"연결끊김 {r['drops']}회")
    print(f"  간격 중앙 {r['gap_med_ms']:.0f} / p90 {r['gap_p90_ms']:.0f} / "
          f"max {r['gap_max_ms']:.0f} ms")
    sp, ip_ = r["stream_ping"], r["idle_ping"]
    print(f"  ping 스트리밍중 손실{sp.get('loss')}% avg{sp.get('avg')} max{sp.get('max')} · "
          f"유휴 손실{ip_.get('loss')}% avg{ip_.get('avg')} max{ip_.get('max')}")
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
    print("%-12s %-4s %-8s %-9s %-10s %-7s %-7s %-8s" %
          ("조건", "n", "FPS", "프레임KB", "처리량KB/s", "멈춤", "끊김", "스트림ping"))
    print("-" * 74)
    for label, rs in by.items():
        f = statistics.median([r["fps"] for r in rs])
        k = statistics.median([r["size_med_kb"] for r in rs])
        b = statistics.median([r["kbps"] for r in rs])
        st = sum(r["stalls_500ms"] for r in rs)
        dr = sum(r.get("drops", 0) for r in rs)
        pl = [r["stream_ping"].get("avg") for r in rs if r["stream_ping"].get("avg")]
        p = statistics.median(pl) if pl else float("nan")
        print("%-12s %-4d %-8.2f %-9.1f %-10.0f %-7d %-7d %-8.1f" %
              (label, len(rs), f, k, b, st, dr, p))
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

    label = args[0]
    seconds = float(args[1]) if len(args) > 1 else 60.0
    r = run_round(label, seconds)
    if r is None:
        return 1
    rows = load()
    rows.append(r)
    save(rows)
    summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
