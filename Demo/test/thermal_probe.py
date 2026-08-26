"""ESP32 연속 스트리밍 중 성능 추세 — 「발열이 성능을 깎는가」를 가른다.

왜 필요한가:
    2026-08-26 조사에서 ESP32 스트림 성능이 세션 중 무너지는 일이 반복됐다(처리량
    300 → 5 KB/s). 네 가지 가설(외장 가림 · 배터리 전압 · AP 재시작 · 장면 복잡도)이
    모두 기각됐고, 마지막으로 남은 유력 후보가 **카메라 모듈 발열**이다.

    🔑 이 가설은 앞선 반례를 설명한다 — **재부팅은 열을 식히지 못한다.** 전원을 껐다
    켠 직후(몇 초)에는 회복되지 않았고, 스위치를 끄고 수 분 둔 뒤에는 회복됐다.

무엇을 재는가:
    **한 연결을 유지한 채** 계속 받으면서 구간(기본 5분)마다 fps·프레임 크기·처리량·
    멈춤을 집계한다. 🔴 구간마다 새로 연결하면 그 사이 유휴 시간에 열이 식어
    **재려는 것 자체가 사라진다.**

어떻게 읽는가:
    - **단조 감소**(구간이 갈수록 처리량이 내려감) → 발열 가설 지지
    - 오르내림·평탄 → 발열은 원인이 아니다. 간섭·연결 재수립 쪽을 본다
    🔴 fps 만 보지 말 것 — 장면이 바뀌면 프레임 크기가 변해 fps 가 따라 움직인다.
       **처리량(KB/s)** 이 링크 지표다.

⚠️ 측정 중에는 ESP32 를 쓰는 다른 프로그램(GUI 데모)을 띄우지 말 것 —
   펌웨어가 클라이언트 소켓을 하나만 받으므로 서로 끊는다. USB 카메라 작업은 무방하다.

사용:
    python3 test/thermal_probe.py                 # 30분, 5분 구간
    python3 test/thermal_probe.py --minutes 45 --bucket 5
"""

import argparse
import json
import os
import re
import socket
import statistics
import struct
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.dirname(_HERE)
sys.path.insert(0, _DEMO)

import config  # noqa: E402
from pi_load import PiLoad  # noqa: E402

_RTT_RE = re.compile(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/")
_LOSS_RE = re.compile(r"([\d.]+)% packet loss")


def quick_ping(host):
    """구간 끝에 짧게 — 스트림과 같은 구간이라 조건이 같다."""
    r = subprocess.run(["ping", "-c", "6", "-i", "0.3", "-W", "2", host],
                       capture_output=True, text=True)
    m, l = _RTT_RE.search(r.stdout), _LOSS_RE.search(r.stdout)
    return (float(m.group(2)) if m else None,
            float(l.group(1)) if l else None)


def summarize(rows):
    if not rows:
        print("구간 기록이 없다.")
        return
    print("\n" + "=" * 78)
    print("%-8s %-8s %-9s %-11s %-7s %-7s %-10s" %
          ("경과", "FPS", "프레임KB", "처리량KB/s", "멈춤", "끊김", "ping(손실)"))
    print("-" * 78)
    for r in rows:
        print("%-8s %-8.2f %-9.1f %-11.0f %-7d %-7d %-10s" %
              ("%d~%d분" % (r["from_min"], r["to_min"]), r["fps"], r["size_kb"],
               r["kbps"], r["stalls"], r["drops"],
               "%.0fms/%.0f%%" % (r["ping_avg"] or 0, r["ping_loss"] or 0)))
    print("=" * 78)

    kb = [r["kbps"] for r in rows]
    if len(kb) >= 3:
        first, last = kb[0], kb[-1]
        drop = (first - last) / first * 100 if first else 0
        # 단조 감소인가 — 뒤 구간이 앞 구간보다 낮은 비율
        desc = sum(1 for a, b in zip(kb, kb[1:]) if b < a)
        print("처리량 %.0f → %.0f KB/s (%+.1f%%) · 하강 전이 %d/%d 구간"
              % (first, last, -drop, desc, len(kb) - 1))
        if drop > 25 and desc >= len(kb) * 0.6:
            print("🔴 단조 감소 경향 — **발열 가설을 지지한다.** 식힌 뒤 재측정해 확인하라.")
        elif drop > 25:
            print("⚠️ 끝이 크게 낮지만 단조롭지 않다 — 발열보다 간헐 요인(간섭 등)이 의심된다.")
        else:
            print("✅ 뚜렷한 하강이 없다 — **발열 가설은 이 구간에서 지지되지 않는다.**")
        print("⚠️ 단일 세션 값이다. 결론으로 쓰려면 식힌 뒤 반복해 재현할 것.")


def main():
    ap = argparse.ArgumentParser(description="ESP32 연속 스트리밍 성능 추세(발열 검증)")
    ap.add_argument("--minutes", type=float, default=30.0, help="총 측정 분")
    ap.add_argument("--bucket", type=float, default=5.0, help="구간 길이(분)")
    args = ap.parse_args()

    host, port = config.CAMERA_TCP_HOST, config.CAMERA_TCP_PORT
    total, bucket = args.minutes * 60, args.bucket * 60
    print("ESP32 %s:%d — %.0f분 연속 수신, %.0f분 구간" % (host, port, args.minutes, args.bucket))
    print("⚠️ 측정 중 ESP32 를 쓰는 GUI 를 띄우지 말 것(소켓이 하나다).\n", flush=True)

    rows = []
    pi = PiLoad()
    t_start = time.time()
    sizes, gaps, last, drops = [], [], None, 0
    b_start = t_start
    sock = None

    def close():
        try:
            if sock:
                sock.close()
        except Exception:
            pass

    while time.time() - t_start < total:
        try:
            sock = socket.socket()
            sock.settimeout(10)
            sock.connect((host, port))

            def rx(n):
                b = b""
                while len(b) < n:
                    d = sock.recv(n - len(b))
                    if not d:
                        return None
                    b += d
                return b

            while time.time() - t_start < total:
                h = rx(4)
                if h is None:
                    break
                ln = struct.unpack("<I", h)[0]
                if rx(ln) is None:
                    break
                now = time.time()
                if last is not None:
                    gaps.append(now - last)
                last = now
                sizes.append(ln)

                if now - b_start >= bucket:
                    # 🔴 ping 보다 **먼저** 읽는다 — ping 이 도는 동안의 부하가 아니라
                    #    수신 구간의 부하를 알아야 한다.
                    load = pi.read()
                    pa, pl = quick_ping(host)
                    span = sum(gaps) or 1e-9
                    row = {
                        "from_min": round((b_start - t_start) / 60),
                        "to_min": round((now - t_start) / 60),
                        "fps": len(gaps) / span,
                        "size_kb": statistics.median(sizes) / 1024 if sizes else 0,
                        "kbps": sum(sizes) / span / 1024,
                        "stalls": sum(1 for g in gaps if g > 0.5),
                        "drops": drops,
                        "ping_avg": pa, "ping_loss": pl,
                        "cpu_max": load.get("cpu_max"),
                        "cpu_avg": load.get("cpu_avg"),
                        "temp": load.get("temp"),
                        "dirty": PiLoad.dirty(load),
                        "top": load.get("top"),
                    }
                    rows.append(row)
                    mark = " 🔴오염(%s)" % ", ".join(row["dirty"]) if row["dirty"] else ""
                    print("  [%d~%d분] FPS %.2f · %.1fKB · %.0f KB/s · 멈춤 %d · 끊김 %d · ping %s"
                          % (row["from_min"], row["to_min"], row["fps"], row["size_kb"],
                             row["kbps"], row["stalls"], row["drops"],
                             "%.0fms" % pa if pa else "—"), flush=True)
                    print("            %s%s" % (PiLoad.fmt(load), mark), flush=True)
                    sizes, gaps, drops = [], [], 0
                    last = None
                    pi.reset()
                    b_start = time.time()
        except (OSError, socket.timeout, struct.error):
            pass
        finally:
            close()
        if time.time() - t_start < total:
            drops += 1
            last = None
            time.sleep(1.0)

    summarize(rows)
    out = os.path.join(_HERE, "thermal_probe.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "minutes": args.minutes, "bucket": args.bucket,
                   "buckets": rows}, f, ensure_ascii=False, indent=1)
    print("기록: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
