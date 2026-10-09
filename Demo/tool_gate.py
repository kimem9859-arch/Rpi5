"""공구 추론 게이트 — GUI 쪽에서 공구 검출을 부르는 **유일한 접점**.

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §3·§4.6

🔄 **`.hef` 전환 시 이 파일의 「안」만 갈아끼운다.**
   `start()`·`stop()`·`available`·`request()`·`poll()` 이라는 **바깥 인터페이스는
   그대로 두고**, 안을 Hailo 호출로 바꾸면 된다(그때 `tool_worker.py` 는 삭제).
   그러면 `camera_thread`·`safety_console` 은 한 줄도 안 고쳐도 된다 —
   이 파일을 둔 목적이 정확히 그것이다.
   → 2026-10-07 NPU 갈래 `HailoToolGate` 를 더했다(시연 모델 설계 2026-10-07 §2.3). CPU 워커는 되돌리기로
     남기고(`config.TOOL_BACKEND="cpu"`) 삭제는 최종 모델 때 · 만드는 곳은 `create_tool_gate()` 하나.

지금은 왜 프로세스를 띄우나:
    🔴 GUI 는 시스템 파이썬(PyQt6+Hailo)이고 거기엔 ultralytics·torch 가 없다.
    상세 = `tool_worker.py` 머리 주석.

⚠️ 실패에 견딘다 — rfenv·모델이 없으면 `available` 이 False 로 남고 GUI 는
   종전대로 돈다(`hand_tracker` 와 같은 방침).
   🔴 단 **로그에 눈에 띄게 남긴다.** 이 경우 `wait_tool` 단계의 게이트가 영영
   안 열리므로, 조용히 넘어가면 원인을 못 찾는다.
"""

import json
import os
import shutil
import subprocess
import threading
import time

import cv2

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_worker.py")
_JPEG_QUALITY = 80


class ToolGate:
    """공구 추론 워커의 수명과 프레임 주고받기를 담당한다.

    쓰는 법 (camera_thread):
        gate.start()                       # 서브 작업 시작 시
        gate.request(frame, fingertip)     # 1초에 한 번
        got = gate.poll()                  # 매 프레임 — (dets, fingertip) 또는 None
        gate.stop()                        # 서브 작업 종료 시
    """

    def __init__(self, shm_dir=None, python=None, model=None, conf=None, log=None):
        # config 를 기본값으로 쓰되 인자로 덮을 수 있게 한다 — 테스트가 임시
        # 디렉터리를 쓸 수 있어야 한다.
        if shm_dir is None or python is None or model is None or conf is None:
            import config
            shm_dir = shm_dir if shm_dir is not None else config.TOOL_SHM_DIR
            python = python if python is not None else config.TOOL_WORKER_PYTHON
            model = model if model is not None else config.TOOL_MODEL_PATH
            conf = conf if conf is not None else config.TOOL_CONF

        self._dir = shm_dir
        self._python = python
        self._model = model
        self._conf = float(conf)
        self._log = log or (lambda m: None)

        self._proc = None
        self._seq = 0
        self._pending = {}        # seq → 그 요청을 보낼 때의 fingertip
        self._last_seq = 0        # 이미 소비한 응답의 seq
        # 🔴 GUI 스레드(start·stop)와 카메라 스레드(request·poll)가 함께 만진다 — 상태는 잠금
        #    안에서만(검토 C13). 없으면 stop() 의 `_pending.clear()` 가 poll() 의 검사와 pop 사이에
        #    끼어 KeyError·RuntimeError 가 났고, 그 예외가 카메라를 다시 붙게 했다.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 수명
    def start(self):
        """워커를 띄운다. 이미 떠 있으면 아무 일도 하지 않는다."""
        with self._lock:
            self._start_locked()

    def _start_locked(self):
        if self._proc is not None:
            return

        if not os.path.exists(self._python):
            self._log(f"[공구] ⚠️ 비활성 — 추론 환경이 없습니다({self._python}). "
                      "공구 지참 단계가 자동으로 넘어가지 않습니다.")
            return
        if not os.path.exists(self._model):
            self._log(f"[공구] ⚠️ 비활성 — 모델이 없습니다({self._model}). "
                      "공구 지참 단계가 자동으로 넘어가지 않습니다.")
            return

        # 지난 실행의 잔재를 지운다 — 옛 resp.json 을 새 응답으로 오인하면 안 된다.
        shutil.rmtree(self._dir, ignore_errors=True)
        os.makedirs(self._dir, exist_ok=True)
        self._seq = 0
        self._last_seq = 0
        self._pending.clear()

        try:
            # 🔑 오류 출력은 공유 폴더의 파일로 받는다 — 버리면 워커가 죽은 이유를 볼 수 없었다(C14)
            with open(os.path.join(self._dir, "worker.err"), "wb") as err:
                self._proc = subprocess.Popen(
                    [self._python, _WORKER, self._dir, self._model, str(self._conf)],
                    stdout=subprocess.DEVNULL, stderr=err,
                )
            self._log("[공구] 추론 워커를 띄웠습니다 — 모델 로딩에 몇 초 걸립니다.")
        except OSError as e:
            self._proc = None
            self._log(f"[공구] ⚠️ 비활성 — 워커를 띄우지 못했습니다({e}).")

    def stop(self):
        """워커를 내린다. 서브 작업이 끝나면 반드시 부른다(CPU 를 계속 먹는다).

        🔑 상태는 잠금 안에서 비우고, 종료는 **잠금 밖에서** 기다린다(C13) — 기다리는 동안
           카메라 스레드의 poll() 을 막지 않는다.
        """
        with self._lock:
            proc, self._proc = self._proc, None
            self._pending.clear()
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:                                    # noqa: BLE001
            try:
                proc.kill()
            except Exception:                                # noqa: BLE001
                pass
        self._log("[공구] 추론 워커를 내렸습니다.")

    @property
    def available(self):
        """워커가 떠 있고 모델 로딩까지 끝났는가."""
        with self._lock:
            return self._ready()

    def _ready(self):
        """(잠금 안에서) 워커가 **살아 있고** 모델 로딩까지 끝났는가.

        🔴 워커가 끝나 있으면(OOM 등) 한 번 로그를 남기고 내린 것으로 본다(검토 C14) — 종전에는
           `ready` 파일만 봐서 죽은 워커가 「사용 가능」으로 남았고, 요청 JPEG 만 쌓인 채 공구
           게이트가 로그 없이 영영 안 열렸다. 다음 서브 작업의 start() 가 다시 띄운다.
        """
        if self._proc is None:
            return False
        rc = self._proc.poll()
        if rc is not None:
            self._proc = None
            self._pending.clear()
            self._log(f"[공구] 🔴 추론 워커가 끝났습니다(종료 코드 {rc}) — 공구 지참 단계가 "
                      f"자동으로 넘어가지 않습니다.{self._err_tail()}")
            return False
        return os.path.exists(os.path.join(self._dir, "ready"))

    def _err_tail(self, n=5):
        """워커 오류 출력(worker.err)의 끝 n 줄 — 없으면 빈 문자열."""
        try:
            with open(os.path.join(self._dir, "worker.err"), encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip() for ln in f if ln.strip()]
        except OSError:
            return ""
        return "".join("\n    " + ln for ln in lines[-n:])

    # ------------------------------------------------------------------ 요청
    def request(self, frame, fingertip):
        """프레임 하나를 추론에 넘긴다.

        🔑 **그 프레임의 손끝 좌표를 seq 와 함께 기억한다** — 추론이 약 0.5초
           걸려서, 결과가 돌아왔을 때의 손 위치는 이미 다르다. 지금 손 위치와
           1초 전 공구 박스를 섞으면 판정이 틀린다(§4.6).
        """
        with self._lock:
            self._request_locked(frame, fingertip)

    def _request_locked(self, frame, fingertip):
        if not self._ready():
            return
        self._seq += 1
        seq = self._seq
        try:
            ok, buf = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
            if not ok:
                return
            tmp = os.path.join(self._dir, f"req_{seq}.jpg.tmp")
            with open(tmp, "wb") as f:
                f.write(buf.tobytes())
            os.replace(tmp, os.path.join(self._dir, f"req_{seq}.jpg"))
        except OSError as e:
            self._log(f"[공구] 요청 기록 실패: {e}")
            return
        self._pending[seq] = fingertip

    def poll(self):
        """새 결과가 있으면 `(dets, fingertip)`, 없으면 None.

        dets = [(클래스명, 점수, x1, y1, x2, y2), ...] — 워커가 이미 임계로 걸렀다.
        fingertip = **그 요청을 보낼 때**의 손끝 좌표(손이 없었으면 None).
        """
        with self._lock:
            return self._poll_locked()

    def _poll_locked(self):
        if not self._ready():
            return None
        path = os.path.join(self._dir, "resp.json")
        try:
            with open(path) as f:
                data = json.load(f)
            seq = int(data["seq"])
            raw = data["dets"]
        except (OSError, ValueError, KeyError, TypeError):
            return None          # 아직 없거나 반쯤 쓰인 것 — 다음 기회에

        if seq <= self._last_seq or seq not in self._pending:
            return None          # 이미 소비했거나 우리가 보낸 것이 아니다

        self._last_seq = seq
        fingertip = self._pending.pop(seq)
        # 이보다 오래된 요청은 응답을 못 받은 것이다 — 버린다.
        for old in [s for s in self._pending if s < seq]:
            self._pending.pop(old, None)

        dets = [(d[0], float(d[1]), float(d[2]), float(d[3]), float(d[4]), float(d[5]))
                for d in raw]
        return dets, fingertip


class HailoToolGate:
    """공구 추론 — NPU(HEF) 갈래. 바깥 인터페이스는 `ToolGate` 와 같다(start·stop·available·request·poll).

    정본: 상위 docs/superpowers/specs/2026-10-07-시연모델-재학습HEF-design.md §2.3

    - 생성 때(프로그램 시작 · 카메라 스레드가 돌기 전) 한 번 적재한다 — 버튼·손과 같은 공유 장치.
      start() 는 화면 스레드에서 불리므로 거기서 장치를 구성하면 카메라 추론과 겹친다.
    - request() 는 카메라 스레드에서 **그 자리에서** 추론한다(재압축 없음 · 640 늘리기 = 학습·채점과 같은 입력).
      결과는 그 프레임의 손끝과 함께 보관하고 poll() 이 한 번 돌려준다.
    - 🔴 적재 실패(파일 없음·장치 오류)면 available False + 로그 — **CPU 로 저절로 바꾸지 않는다**
      (다른 모델이 조용히 돌면 시연 기준이 흐려진다).
    - 🔑 검사마다 결과를 **음성비서 공유 파일**(`<TOOL_SHM_DIR>/resp.json` · CPU 워커와 같은 자리·모양)에도 쓴다 —
      음성비서(`voice_lib.read_tool_dets`)가 「보이는 공구」를 거기서 읽는다. 10/7 NPU 로 바꾼 뒤 이 파일을 아무도
      안 써 음성비서가 공구를 몰랐다(공구 구간 설계 D2). 끄거나 닫으면 지운다.
    - 🔴 생성 때 낸 로그는 화면 로그에 안 붙는다(CameraThread.__init__ 시점 — 손 검출과 같은 함정) →
      `loaded`·`reason` 을 두어 시연 화면이 시작 로그에 다시 적고, start() 도 실패면 다시 알린다(리뷰 I-1).
    """

    _ERR_LOG_SEC = 5.0               # 추론 오류가 이어져도 로그는 이 간격에 한 번(camera_thread C12 와 같은 값)

    def __init__(self, hef=None, names=None, conf=None, log=None, detector_factory=None, shm_dir=None):
        import config
        self._hef = hef if hef is not None else config.TOOL_HEF_PATH
        self._shm = shm_dir if shm_dir is not None else config.TOOL_SHM_DIR   # 음성비서 공유 파일 자리(D2)
        self._seq = 0
        self._share_err_at = None
        self._names = tuple(names if names is not None else config.TOOL_NAMES)
        self._conf = float(conf if conf is not None else config.TOOL_CONF)
        self._log = log or (lambda m: None)
        self._lock = threading.Lock()
        self._on = False
        self._gen = 0                # start·stop 마다 올린다 — 추론 도중 꺼졌다 켜져도 옛 결과가 새지 않게(리뷰 m3)
        self._result = None          # (dets, fingertip) — poll() 이 한 번 돌려준다
        self._err_at = None
        self._det = None
        self.loaded = False
        self.reason = ""
        try:
            if not os.path.exists(self._hef):
                raise FileNotFoundError(self._hef)
            if detector_factory is None:
                from detector import HailoDetector
                detector_factory = lambda: HailoDetector(hef_path=self._hef,          # noqa: E731
                                                         names=dict(enumerate(self._names)))
            self._det = detector_factory()
            self.loaded = True
            self.reason = f"NPU 적재 — {os.path.basename(self._hef)} · 문턱 {self._conf}"
            self._log(f"[공구] {self.reason} · {', '.join(self._names)}")
        except Exception as e:                                # noqa: BLE001
            self._det = None
            self.reason = f"NPU 공구 모델을 올리지 못했습니다({e})"
            self._log(f"[공구] ⚠️ 비활성 — {self.reason}. 공구 지참 단계가 자동으로 넘어가지 않습니다.")
        # 🔴 검출기(HailoDetector.detect)가 먼저 YOLO_CONF_LOW(버튼 설정)로 거른다 — 그보다 낮은 공구 문턱은 안 먹는다(리뷰 m5)
        low = getattr(config, "YOLO_CONF_LOW", 0.0)
        if self._conf < low:
            warn = f"⚠️ 공구 문턱 {self._conf} 이 검출기 하한 YOLO_CONF_LOW {low} 보다 낮다 — 실제 문턱은 {low}"
            self.reason += f" · {warn}"          # 생성 때 로그는 화면에 안 붙는다 — 시작 줄이 reason 으로 다시 적는다
            self._log(f"[공구] {warn}")

    def start(self):
        with self._lock:
            self._on = True
            self._gen += 1
            self._result = None
            det = self._det
        if det is None:
            self._log(f"[공구] ⚠️ 비활성 — {self.reason}. 공구 지참 단계가 자동으로 넘어가지 않습니다.")

    def stop(self):
        with self._lock:
            self._on = False
            self._gen += 1
            self._result = None       # 서브 작업이 끝난 뒤 늦게 남은 결과를 내지 않는다
            self._unshare()           # 같은 잠금 안 — request 가 그 뒤에 다시 쓰지 못한다

    @property
    def available(self):
        with self._lock:
            return self._on and self._det is not None

    def request(self, frame, fingertip):
        with self._lock:
            if not (self._on and self._det is not None):
                return
            det, gen = self._det, self._gen
        try:
            raw = det.detect(frame)
        except Exception as e:                                # noqa: BLE001 — 그 요청만 버린다(카메라는 계속)
            now = time.monotonic()
            if self._err_at is None or now - self._err_at >= self._ERR_LOG_SEC:
                self._err_at = now
                self._log(f"[공구] NPU 추론 오류 — 그 요청만 버린다: {e!r}")
            return
        dets = [(det.class_name(c), float(s), float(x1), float(y1), float(x2), float(y2))
                for c, s, x1, y1, x2, y2 in raw if s >= self._conf]
        with self._lock:
            if not (self._on and self._gen == gen):
                return
            self._result = (dets, fingertip)
            # 🔑 잠금 안에서 쓴다 — 밖에서 쓰면 화면 스레드의 stop()·close() 가 지운 **뒤에** 다시 써 낡은 파일이
            #    남을 수 있었다(최종 리뷰 Minor 1 · tmpfs 라 µs 수준).
            self._share(dets)

    def _share(self, dets):
        """음성비서가 읽는 공구 검출 파일 — CPU 워커(`tool_worker.py`)와 같은 자리·모양 `{"seq", "dets"}`(D2).

        임시 파일에 쓰고 이름을 바꿔 한 번에 바꾼다(반쯤 쓰인 파일을 읽지 않게).
        🔴 실패해도 판정은 계속한다 — 음성 안내만 빠진다. 로그는 _ERR_LOG_SEC 간격에 한 번.
        """
        try:
            os.makedirs(self._shm, exist_ok=True)
            self._seq += 1
            path = os.path.join(self._shm, "resp.json")
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"seq": self._seq, "dets": [list(d) for d in dets]}, f)
            os.replace(tmp, path)
        except OSError as e:
            now = time.monotonic()
            if self._share_err_at is None or now - self._share_err_at >= self._ERR_LOG_SEC:
                self._share_err_at = now
                self._log(f"[공구] 음성비서 공유 파일을 못 썼다(판정은 계속): {e!r}")

    def _unshare(self):
        """공유 파일을 지운다 — 꺼진 뒤 낡은 검출을 음성비서가 읽지 않게(신선도 3초 전이라도)."""
        try:
            os.remove(os.path.join(self._shm, "resp.json"))
        except OSError:
            pass

    def poll(self):
        with self._lock:
            got, self._result = self._result, None
            return got

    def close(self):
        with self._lock:
            det, self._det = self._det, None
            self._on = False
            self._result = None
            self.loaded = False
            self.reason = "닫힘"
            self._unshare()
        if det is not None:
            try:
                det.close()
            except Exception:                                 # noqa: BLE001
                pass


class DisabledToolGate:
    """꺼진 공구 갈래 — 같은 바깥 인터페이스로 아무것도 하지 않고, 꺼진 사유를 시작 로그·start() 에 남긴다."""

    loaded = False

    def __init__(self, reason, log=None):
        self.reason = reason
        self._log = log or (lambda m: None)
        self._log(f"[공구] ⚠️ 비활성 — {reason}")

    def start(self):
        self._log(f"[공구] ⚠️ 비활성 — {self.reason}. 공구 지참 단계가 자동으로 넘어가지 않습니다.")

    def stop(self):
        pass

    @property
    def available(self):
        return False

    def request(self, frame, fingertip):
        pass

    def poll(self):
        return None

    def close(self):
        pass


def create_tool_gate(log=None):
    """설정(`config.TOOL_BACKEND`)대로 공구 추론 갈래를 만든다 — "cpu" = 종전 워커 · "hailo" = NPU.
    모르는 값은 꺼진 갈래(DisabledToolGate) — 오타가 조용히 어느 한쪽으로 가지 않고, 사유가 시작 로그에 남는다(리뷰 m7·후속 m2)."""
    import config
    backend = getattr(config, "TOOL_BACKEND", "cpu")
    if backend == "cpu":
        return ToolGate(log=log)
    if backend == "hailo":
        return HailoToolGate(log=log)
    return DisabledToolGate(f"알 수 없는 TOOL_BACKEND {backend!r}(\"hailo\" 또는 \"cpu\")", log=log)
