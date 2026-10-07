"""측정 기록 — 측정할 때만 시연 프로그램·음성 데몬이 프레임·박스·사건을 CSV 로 적는다.

설계 = 상위 docs/superpowers/specs/2026-09-27-측정도구-정합-design.md §4.3(적기 · D9~D15)
켜는 법 = 환경변수 SOP_MEASURE_DIR(측정 실행기 run_measure.sh 가 넣는다) — 없으면 NullLog(아무것도 안 함).
🔴 쓰기는 전용 스레드 하나 — 호출부(카메라·화면·음성)는 큐에 넣고 바로 돌아간다. 큐가 차면 버리고 센다.
🔴 기록 쪽 오류는 시연을 멈추지 않는다 — 로그 한 줄.
🔴 시각 = time.monotonic() 의 ms — 리눅스 CLOCK_MONOTONIC 은 프로세스끼리 같은 시계라 음성 데몬과 맞는다.
🔴 표준 라이브러리만 쓴다 — 음성 데몬(tts venv)도 이 모듈을 쓴다.
"""
import csv
import json
import os
import queue
import threading
import time

HEADERS = {
    "frames": ["frame", "t_recv_ms", "recv_seq", "t_start_ms", "t_done_ms", "decode_ms", "orient_ms",
               "detect_ms", "track_ms", "hand_ms", "tool_ms", "zone_ms", "tip_x", "tip_y", "tip_score", "roi", "level"],
    "boxes": ["frame", "t_recv_ms", "kind", "cls_name", "score", "x1", "y1", "x2", "y2", "confirmed"],
    "fsm": ["t_recv_ms", "t_gui_ms", "fsm_roi", "fsm_level", "state", "expected"],
    "env": ["frame", "t_recv_ms", "brightness", "contrast", "clip_pct", "saturation", "lab_a", "lab_b"],
    "events": ["t_ms", "kind", "data"],
    "voice_events": ["t_ms", "kind", "data"],
}
_STOP = object()


def now_ms(t=None):
    """단조 시계 ms(소수 셋째 자리). t = 단조 시각(초)을 주면 그것을 ms 로."""
    return round((time.monotonic() if t is None else t) * 1000, 3)


class NullLog:
    """측정을 켜지 않았을 때 — 모든 호출이 아무것도 하지 않는다(지금과 같은 시연)."""
    enabled = False
    dropped = 0
    failed = False

    def row(self, name, values):
        pass

    def event(self, kind, t=None, **data):
        pass

    def close(self, timeout=5.0):
        pass


class MeasureLog:
    enabled = True

    def __init__(self, out_dir, names, event_file="events", log=print, qmax=20000, flush_sec=0.5):
        os.makedirs(out_dir, exist_ok=True)
        self._log = log
        self._event_file = event_file
        self._flush_sec = flush_sec
        self._q = queue.Queue(maxsize=qmax)
        self._pause = threading.Event()          # 시험용 문 — 쓰기 스레드를 잠깐 멈춘다
        self._drop_lock = threading.Lock()       # 버린 수 — 여러 스레드(카메라·화면·GPIO·인터락)가 센다
        self.dropped = 0
        self.failed = False
        self._files = {}
        for n in names:
            # 🔴 이어 쓰기 — 음성 데몬은 run_voice.sh --forever 가 다시 띄운다. "w" 면 앞 기록이 지워진다.
            f = open(os.path.join(out_dir, f"{n}.csv"), "a", encoding="utf-8", newline="")
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(HEADERS[n])
                f.flush()
            self._files[n] = (f, w)
        self._th = threading.Thread(target=self._run, name="measure-writer", daemon=True)
        self._th.start()

    def _drop(self):
        with self._drop_lock:
            self.dropped += 1

    def row(self, name, values):
        try:
            self._q.put_nowait((name, list(values)))
        except queue.Full:
            self._drop()

    def event(self, kind, t=None, **data):
        # 🔴 부르는 쪽(Qt 슬롯 포함)에서 예외를 내지 않는다 — 슬롯 예외는 PyQt6 가 앱 전체를 끈다.
        #    JSON 으로 못 쓰는 값은 글자로(default=str) · 그래도 실패하면 버린 수로 센다(리뷰 M-2)
        try:
            body = json.dumps(data, ensure_ascii=False, default=str)
            self.row(self._event_file, [now_ms(t), kind, body])
        except Exception:                        # noqa: BLE001
            self._drop()

    def _write(self, name, values):
        if self.failed:
            return
        try:
            self._files[name][1].writerow(values)
        except Exception as e:                   # noqa: BLE001 — 기록 오류로 시연을 멈추지 않는다
            self.failed = True
            self._log(f"[측정] 측정 기록 쓰기 실패 — 이후 기록을 버린다: {e}")

    def _flush(self):
        for f, _w in self._files.values():
            try:
                f.flush()
            except Exception:                    # noqa: BLE001
                pass

    def _run(self):
        last = time.monotonic()
        while True:
            while self._pause.is_set():
                time.sleep(0.01)
            try:
                item = self._q.get(timeout=self._flush_sec)
            except queue.Empty:
                item = None
            if item is _STOP:
                break
            if item is not None:
                self._write(*item)
                if self._q.empty():
                    # 🔑 밀린 것이 없으면 곧바로 디스크로 — 드문 사건(음성)이 비우기 주기를 기다리다 강제 종료에
                    #    사라지지 않게(리뷰 I-1) · 바쁜 흐름(프레임)은 큐에 쌓인 만큼 묶어 쓴다
                    self._flush()
                    last = time.monotonic()
            if time.monotonic() - last >= self._flush_sec:
                self._flush()
                last = time.monotonic()
        self._flush()

    def close(self, timeout=5.0):
        """남은 것을 쓰고 끝 사건(버린 수)을 남긴 뒤 닫는다."""
        self._pause.clear()
        end = [now_ms(), "measure_end", json.dumps({"dropped": self.dropped, "failed": self.failed})]
        try:
            self._q.put((self._event_file, end), timeout=timeout)
            self._q.put(_STOP, timeout=timeout)
        except queue.Full:
            pass
        self._th.join(timeout=timeout)
        for f, _w in self._files.values():
            try:
                f.close()
            except Exception:                    # noqa: BLE001
                pass


def open_from_env(names, event_file="events", log=print):
    """SOP_MEASURE_DIR 가 있으면 그 폴더에 MeasureLog · 없으면 NullLog."""
    d = os.environ.get("SOP_MEASURE_DIR")
    if not d:
        return NullLog()
    try:
        return MeasureLog(d, names, event_file=event_file, log=log)
    except Exception as e:                       # noqa: BLE001 — 기록을 못 열어도 시연은 돈다
        log(f"[측정] 측정 기록을 열 수 없다 — 기록 없이 계속: {e}")
        return NullLog()
