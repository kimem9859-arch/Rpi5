"""파이 자원 사용률 스냅샷 — 측정 결과가 **파이 부하에 오염됐는지** 가른다.

왜 필요한가:
    🔴 2026-08-26 에 실제로 물렸다. ESP32 링크 요동을 쫓아 여섯 번 측정하는 동안
    **파이 CPU 를 한 번도 보지 않았다.** 나중에 보니 2차 발열 측정의 전반부 저하가
    내가 파이에서 `arduino-cli compile` 을 돌리던 구간과 정확히 겹쳤다.

    수신·집계가 파이에서 도는 파이썬 루프라, **CPU 가 바쁘면 루프가 밀려
    「프레임 멈춤」으로 집계된다.** ESP32 가 멀쩡해도 그렇게 보인다.

    CLAUDE.md §5 = *"자원 사용률을 먼저 확인한다."* FPS 병목을 TCP 전송으로 오진해
    두 달을 버린 전례(§10.34)와 같은 계열의 실패였다.

무엇을 보나:
    🔑 **평균이 아니라 `cpu_max`(가장 바쁜 코어)** 가 핵심이다 — 수신 루프는 단일
    스레드라 한 코어만 쓴다. 4코어 평균이 25% 여도 그 코어가 100% 면 루프는 밀린다.

사용:
    from pi_load import PiLoad
    load = PiLoad()          # 기준점 잡기
    ...                      # 측정 구간
    snap = load.read()       # 구간 평균 + 현재 온도·스로틀
"""

import os
import subprocess
import time

try:
    import psutil
except ImportError:                      # 없으면 조용히 비활성 — 측정 자체는 계속된다
    psutil = None

# 이 값을 넘은 구간은 「파이 부하로 오염 가능」으로 표시한다.
# 🔴 근거 있는 경계가 아니라 **판단을 멈추게 하는 문턱**이다 — 넘으면 결론을 내지 말고
#    부하를 없앤 뒤 다시 재라는 뜻이다.
CPU_MAX_WARN = 70.0


def _vcgencmd(arg):
    try:
        out = subprocess.run(["vcgencmd", arg], capture_output=True, text=True,
                             timeout=5).stdout.strip()
        return out.split("=", 1)[1] if "=" in out else out
    except Exception:
        return None


class PiLoad:
    """구간 평균 CPU 를 재려면 구간 시작에 기준점을 잡아야 한다."""

    def __init__(self):
        self.proc = psutil.Process() if psutil else None
        self.reset()

    def reset(self):
        """여기부터 다음 read() 까지를 한 구간으로 본다."""
        if psutil:
            psutil.cpu_percent(percpu=True)      # 기준점 — 반환값은 버린다
            if self.proc:
                self.proc.cpu_percent()
            # 🔴 프로세스별 cpu_percent 도 **첫 호출은 0** 이다. 여기서 기준점을 잡지
            #    않으면 read() 의 「상위 프로세스」가 엉뚱한 것을 가리킨다(실제로 그랬다).
            try:
                for p in psutil.process_iter(["cpu_percent"]):
                    pass
            except Exception:
                pass

    def read(self, top_n=2):
        """구간 평균 CPU + 현재 온도·스로틀. read() 가 다음 구간의 기준점도 된다."""
        out = {"cpu_avg": None, "cpu_max": None, "self_cpu": None,
               "load1": None, "temp": None, "throttled": None, "top": []}
        try:
            out["load1"] = os.getloadavg()[0]
        except OSError:
            pass
        out["temp"] = _vcgencmd("measure_temp")
        thr = _vcgencmd("get_throttled")
        out["throttled"] = thr
        if psutil:
            per = psutil.cpu_percent(percpu=True)
            if per:
                out["cpu_avg"] = sum(per) / len(per)
                out["cpu_max"] = max(per)
            if self.proc:
                out["self_cpu"] = self.proc.cpu_percent()
            # 부하의 주범을 남긴다 — 나중에 「그때 무엇이 돌았나」를 되짚을 유일한 단서다.
            # ⚠️ 이것만은 **구간 평균이 아니라 지금 순간**이다. 구간 중간에 새로 뜬
            #    프로세스는 기준점이 없어 구간 평균으로는 0 으로 잡힌다(실제로 그랬다).
            #    그래서 여기서 기준점을 새로 잡고 짧게 재측정한다.
            try:
                for pr in psutil.process_iter(["cpu_percent"]):
                    pass
                time.sleep(0.15)
                procs = [(pr.info["cpu_percent"], pr.info["name"])
                         for pr in psutil.process_iter(["name", "cpu_percent"])
                         if pr.info["cpu_percent"]]
                procs.sort(reverse=True)
                out["top"] = procs[:top_n]
            except Exception:
                pass
        return out

    @staticmethod
    def dirty(snap):
        """이 구간이 파이 부하에 오염됐을 수 있는가."""
        reasons = []
        if snap.get("cpu_max") is not None and snap["cpu_max"] >= CPU_MAX_WARN:
            reasons.append("코어 최대 %.0f%%" % snap["cpu_max"])
        thr = snap.get("throttled")
        if thr and thr not in ("0x0",):
            reasons.append("스로틀 %s" % thr)
        return reasons

    @staticmethod
    def fmt(snap):
        """한 줄 요약."""
        if snap.get("cpu_max") is None:
            return "CPU —(psutil 없음) · %s" % (snap.get("temp") or "?")
        s = "CPU 평균 %.0f%% 최대 %.0f%%" % (snap["cpu_avg"], snap["cpu_max"])
        if snap.get("self_cpu") is not None:
            s += " (자신 %.0f%%)" % snap["self_cpu"]
        s += " · %s" % (snap.get("temp") or "?")
        if snap.get("top"):
            s += " · 상위 " + ", ".join("%s %.0f%%" % (n, c) for c, n in snap["top"])
        return s
