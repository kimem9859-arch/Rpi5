"""GUI 상태를 /dev/shm 으로 내보낸다 — 음성비서가 읽는다.

정본: ../docs/superpowers/specs/2026-09-07-음성비서-LLM-design.md §8

🔴 **GUI 는 이 파일 쓰기가 실패해도 계속 돌아야 한다.** 음성비서 때문에 콘솔이
   죽으면 본말전도다. 모든 예외를 삼키고 로그만 남긴다 — 이 모듈은 절대
   예외를 올리지 않는다.

🔑 tool_gate.py:133-136 과 같은 방식이다 — `.tmp` 에 쓰고 `os.replace` 로
   원자 교체한다. 읽는 쪽이 반쯤 쓰인 파일을 보는 일이 없다.

🔑 `pid` 를 함께 적는 이유 — GUI 가 죽어도 /dev/shm 파일은 재부팅까지 남는다.
   읽는 쪽이 그 pid 가 살아 있는지 보면 「유령 상태」를 걸러낼 수 있다.
"""
import json
import os
import time

STATE_FILE = "state.json"


class StatePublisher:
    """상태 한 벌을 원자적으로 쓴다. 쓰기 전용이고, 절대 예외를 올리지 않는다."""

    def __init__(self, shm_dir=None, log=None):
        if shm_dir is None:
            import config
            shm_dir = config.STATE_SHM_DIR
        self._path = os.path.join(shm_dir, STATE_FILE)
        self._log = log or (lambda m: None)
        self._ok = True
        try:
            os.makedirs(shm_dir, exist_ok=True)
        except OSError as e:
            self._ok = False
            self._log(f"[상태] 폴더를 만들 수 없다 — 상태 공개를 끈다: {e}")

    def publish(self, data):
        """`data` 에 pid·쓴시각을 얹어 기록한다. 성공하면 True."""
        if not self._ok:
            return False
        tmp = self._path + ".tmp"
        try:
            rec = dict(data)
            rec["pid"] = os.getpid()
            rec["쓴시각"] = time.time()
            body = json.dumps(rec, ensure_ascii=False)   # 🔴 직렬화를 먼저 — 실패해도 옛 파일이 남는다
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(body)
            os.replace(tmp, self._path)
            return True
        except (OSError, TypeError, ValueError) as e:
            self._log(f"[상태] 기록 실패: {e}")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def clear(self):
        """작업이 없는 상태로 되돌린다 — 파일을 지운다."""
        try:
            os.remove(self._path)
        except OSError:
            pass
