"""공구 추론 게이트 — GUI 쪽에서 공구 검출을 부르는 **유일한 접점**.

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §3·§4.6

🔄 **`.hef` 전환 시 이 파일의 「안」만 갈아끼운다.**
   `start()`·`stop()`·`available`·`request()`·`poll()` 이라는 **바깥 인터페이스는
   그대로 두고**, 안을 Hailo 호출로 바꾸면 된다(그때 `tool_worker.py` 는 삭제).
   그러면 `camera_thread`·`safety_console` 은 한 줄도 안 고쳐도 된다 —
   이 파일을 둔 목적이 정확히 그것이다.

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

    # ------------------------------------------------------------------ 수명
    def start(self):
        """워커를 띄운다. 이미 떠 있으면 아무 일도 하지 않는다."""
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
            self._proc = subprocess.Popen(
                [self._python, _WORKER, self._dir, self._model, str(self._conf)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._log("[공구] 추론 워커를 띄웠습니다 — 모델 로딩에 몇 초 걸립니다.")
        except OSError as e:
            self._proc = None
            self._log(f"[공구] ⚠️ 비활성 — 워커를 띄우지 못했습니다({e}).")

    def stop(self):
        """워커를 내린다. 서브 작업이 끝나면 반드시 부른다(CPU 를 계속 먹는다)."""
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:                                    # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:                                # noqa: BLE001
                pass
        self._proc = None
        self._pending.clear()
        self._log("[공구] 추론 워커를 내렸습니다.")

    @property
    def available(self):
        """워커가 떠 있고 모델 로딩까지 끝났는가."""
        return self._proc is not None and os.path.exists(os.path.join(self._dir, "ready"))

    # ------------------------------------------------------------------ 요청
    def request(self, frame, fingertip):
        """프레임 하나를 추론에 넘긴다.

        🔑 **그 프레임의 손끝 좌표를 seq 와 함께 기억한다** — 추론이 약 0.5초
           걸려서, 결과가 돌아왔을 때의 손 위치는 이미 다르다. 지금 손 위치와
           1초 전 공구 박스를 섞으면 판정이 틀린다(§4.6).
        """
        if not self.available:
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
        if not self.available:
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
