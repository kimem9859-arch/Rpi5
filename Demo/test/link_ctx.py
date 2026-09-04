"""링크 측정의 **문맥**을 함께 남긴다 — 어느 보드·어느 망·어떤 TCP 상태였나.

왜 필요한가:
    🔴 **2026-09-04 에 실제로 물렸다.** 오후 라운드 도중 병행 세션이 `.camera_ip` 를
       서브 보드 → 메인 보드로 바꿨는데, `link_probe` 가 **대상 IP 를 기록하지 않아**
       어느 라운드가 어느 보드였는지 끝내 확정할 수 없었다. 「보드 개체 문제」 가설을
       가를 수 있었던 데이터가 그렇게 사라졌다.
    🔴 파이가 어느 AP·어느 채널에 붙어 있었는지도 남지 않았다. 폰 핫스팟은 채널을
       자동으로 옮긴다 — 2026-09-04 파이 로그에 `Eung Min` 이 ch6(2437) → ch11(2462)
       로 **1분 만에** 이동한 것이 잡혔다. ESP32 는 부팅 때 붙은 AP 를 유지하므로
       (§10.44-(2) 함정), 파이 쪽 채널과 ESP32 상태 줄의 `ch=` 가 어긋나면 그것만으로
       원인이 하나 확정된다.

무엇을 남기나:
    wlan()  — 파이 wlan0 의 SSID·주파수·신호세기·링크속도   (`iw dev wlan0 link`)
    tcp()   — ESP32→파이 TCP 연결의 RTT·수신량·재전송·수신윈도 (`ss -tin`)

🔴 **`ss` 의 `cwnd` 를 ESP32 의 송신 윈도로 읽지 말 것.** 그것은 *파이가 보내는 쪽*
   값이다. 보내는 쪽(ESP32) 윈도는 파이에서 직접 볼 수 없다 — 그것을 가르는 것은
   `link_probe --rcvbuf` 실험이고, 여기서 쓸 값은 `rcv_rtt`·`bytes_received` 다.

⚠️ 도구가 없거나(iw·ss 미설치) 연결이 없으면 **조용히 None 을 넣는다** — 문맥 수집
   실패로 측정 자체를 잃지 않는다(`pi_load` 와 같은 방침).
"""

import re
import statistics
import subprocess
import threading
import time


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# =============================================================================
# [파이 무선 상태]
# =============================================================================
_WLAN_PATTERNS = {
    "ssid":       (r"SSID:\s*(.+)", str),
    "freq_mhz":   (r"freq:\s*([\d.]+)", float),
    "signal_dbm": (r"signal:\s*(-?[\d.]+)", float),
    "rx_mbps":    (r"rx bitrate:\s*([\d.]+)", float),
    "tx_mbps":    (r"tx bitrate:\s*([\d.]+)", float),
}


def _channel(freq_mhz):
    """2.4GHz 주파수를 채널 번호로. ESP32 상태 줄의 `ch=` 와 바로 비교하기 위함."""
    if not freq_mhz:
        return None
    f = int(freq_mhz)
    if f == 2484:
        return 14
    if 2412 <= f <= 2472:
        return (f - 2407) // 5
    if 5000 <= f <= 5900:
        return (f - 5000) // 5
    return None


def route_iface(host):
    """대상까지 실제로 나가는 인터페이스. 커널의 라우팅 판단을 그대로 쓴다."""
    out = _run(["ip", "-o", "route", "get", str(host)])
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else None


def wlan(iface="wlan0"):
    if not iface:
        return None
    out = _run(["iw", "dev", iface, "link"])
    if "Connected to" not in out:
        return None
    d = {}
    for key, (pat, cast) in _WLAN_PATTERNS.items():
        m = re.search(pat, out)
        d[key] = cast(m.group(1).strip()) if m else None
    d["channel"] = _channel(d.get("freq_mhz"))
    return d


# =============================================================================
# [TCP 연결 상태]
# =============================================================================
_TCP_PATTERNS = {
    "rtt_ms":         r"\brtt:([\d.]+)/",
    "rtt_var_ms":     r"\brtt:[\d.]+/([\d.]+)",
    "rcv_rtt_ms":     r"\brcv_rtt:([\d.]+)",
    "mss":            r"\bmss:(\d+)",
    "cwnd":           r"\bcwnd:(\d+)",
    "rcv_space":      r"\brcv_space:(\d+)",
    "bytes_received": r"\bbytes_received:(\d+)",
    "retrans_total":  r"\bretrans:\d+/(\d+)",
}


def tcp(host, port):
    out = _run(["ss", "-tin", "dst", str(host)])
    if f":{port}" not in out:
        return None
    d = {}
    for key, pat in _TCP_PATTERNS.items():
        m = re.search(pat, out)
        d[key] = float(m.group(1)) if m else None
    return d


# =============================================================================
# [샘플러] — 측정 구간 **내내** 훑는다
# =============================================================================
class Sampler:
    """측정이 도는 동안 문맥을 주기적으로 훑어 대표값을 낸다.

    🔑 한 번만 찍으면 안 되는 이유 — 어제 요동 구간에서 RTT 가 26ms↔1100ms 사이를
       오갔다. 시작·끝의 한 점은 그 라운드를 대표하지 못한다.
    """

    def __init__(self, host, port, interval=2.0, iface=None):
        # 🔴 인터페이스를 고정하지 않는다 — 대상까지 실제로 쓰는 길을 커널에 묻는다.
        #    2026-09-04 에 물렸다: 대상이 유선(eth0) 너머에 있는데 wlan0 상태를
        #    기록해, 라운드 문맥에 **무관한 AP 이름과 신호세기**가 찍혔다.
        #    유선이면 무선 항목은 아예 비워야 「이 값을 링크 판정에 쓰지 말라」가
        #    저절로 드러난다.
        self._host, self._port = host, port
        self._iface = iface or route_iface(host)
        self._interval = interval
        self._wlan, self._tcp = [], []
        self._stop = threading.Event()
        self._t = None

    def start(self):
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            w = wlan(self._iface)
            if w:
                self._wlan.append(w)
            c = tcp(self._host, self._port)
            if c:
                self._tcp.append(c)
            self._stop.wait(self._interval)

    def stop(self):
        self._stop.set()
        if self._t:
            self._t.join(timeout=5)
        return self.result()

    @staticmethod
    def _agg(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            return None
        return {"med": statistics.median(vals), "min": min(vals), "max": max(vals)}

    def result(self):
        out = {"samples": max(len(self._wlan), len(self._tcp)), "iface": self._iface}
        if self._wlan:
            last = self._wlan[-1]
            out["ssid"] = last.get("ssid")
            out["channel"] = last.get("channel")
            out["freq_mhz"] = last.get("freq_mhz")
            # 🔴 라운드 도중 AP·채널이 바뀌었으면 그 라운드는 조건이 하나가 아니다.
            out["channel_changed"] = len({w.get("channel") for w in self._wlan}) > 1
            out["ssid_changed"] = len({w.get("ssid") for w in self._wlan}) > 1
            for k in ("signal_dbm", "rx_mbps", "tx_mbps"):
                out[k] = self._agg(self._wlan, k)
        if self._tcp:
            for k in ("rtt_ms", "rcv_rtt_ms", "rcv_space", "cwnd"):
                out[k] = self._agg(self._tcp, k)
            last = self._tcp[-1]
            out["mss"] = last.get("mss")
            out["retrans_total"] = last.get("retrans_total")
        return out


# =============================================================================
# [사람이 읽는 한 줄]
# =============================================================================
def fmt(ctx):
    if not ctx or not ctx.get("samples"):
        return "문맥: (수집 실패 — iw/ss 확인)"
    parts = ["경로 %s" % ctx.get("iface")]
    if ctx.get("ssid"):
        parts.append("AP %s ch%s" % (ctx["ssid"], ctx.get("channel")))
    else:
        parts.append("무선구간 없음(유선)")
    sig = ctx.get("signal_dbm")
    if sig:
        parts.append("파이신호 %.0f~%.0fdBm" % (sig["min"], sig["max"]))
    rx = ctx.get("rx_mbps")
    if rx:
        parts.append("링크속도 %.0f~%.0fMb/s" % (rx["min"], rx["max"]))
    # 🔴 `rcv_rtt` 를 쓰지 않는다 — 그것은 수신 버퍼 자동조절용으로 「한 윈도를 다
    #    받는 데 걸린 시간」이라 네트워크 RTT 가 아니다(실측에서 168ms 로 찍혔는데
    #    같은 순간 실제 RTT 는 3ms 였다). 네트워크 RTT 는 `rtt_ms` 다.
    rt = ctx.get("rtt_ms")
    if rt:
        parts.append("TCP rtt %.1f~%.1fms" % (rt["min"], rt["max"]))
    line = "문맥: " + " · ".join(parts)
    if ctx.get("channel_changed") or ctx.get("ssid_changed"):
        line += "\n  🔴 라운드 도중 AP/채널이 바뀌었다 — 이 라운드는 조건이 하나가 아니다"
    return line
