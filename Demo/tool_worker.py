"""공구 추론 워커 — rfenv 파이썬으로 도는 **별도 프로세스**.

정본: ../docs/superpowers/specs/2026-08-14-공구입력-A2-design.md §3

🗑️ **`.hef` 전환 시 이 파일은 통째로 삭제된다.**
   Hailo 로 공구를 돌릴 수 있게 되면 별도 프로세스가 필요 없어진다 —
   `tool_gate.py` 안이 Hailo 호출로 바뀌고 이 파일은 사라진다.

왜 별도 프로세스인가:
    🔴 GUI 는 **시스템 파이썬**(PyQt6 + hailo_platform)으로 도는데 거기엔
    `ultralytics` 도 `torch` 도 없다. 둘은 `~/env/rfenv` 안에만 있다. 두 파이썬이
    서로 남이므로 같은 프로세스에서 `tool_v3.pt` 를 못 돌린다.

    시스템 파이썬에 torch 를 설치하는 방법도 있으나(약 2GB), Hailo·PyQt6 가
    도는 환경을 건드리는 위험이 얻는 것보다 크다고 판단했다.

사용법:
    <rfenv python> tool_worker.py <shm_dir> <model_path> <conf>

    예) ~/env/rfenv/bin/python tool_worker.py /dev/shm/sop_tool models/tool_v3.pt 0.65

    ⚠️ config 를 import 하지 않고 **인자로 받는다** — rfenv 에서 config import 가
       되기는 하지만, 인자로 받으면 이 워커를 단독으로 시험할 수 있다.

주고받는 규약 (설계 §3):
    ready              — 모델 로딩 완료 표시(이것이 없으면 gate 가 비활성으로 본다)
    req_<seq>.jpg      — GUI 가 쓴 요청 프레임
    resp.json          — {"seq": N, "dets": [[cls, score, x1, y1, x2, y2], ...]}

    · 원자적 쓰기 = tmp 에 쓰고 os.replace()
    · 🔑 req 가 여러 개 밀려 있으면 **가장 큰 seq 만 처리하고 나머지는 지운다**.
      늦은 결과는 쓸모가 없다(설계 §4.6 — 지금 손 위치와 옛 공구 박스를 섞지 않는다).
"""

import json
import os
import re
import sys
import time

_REQ_RE = re.compile(r"^req_(\d+)\.jpg$")
_IDLE_SLEEP = 0.05


def _write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, path)


def _latest_request(shm_dir):
    """가장 큰 seq 의 요청을 고르고 나머지는 지운다. 없으면 (None, None)."""
    found = []
    try:
        names = os.listdir(shm_dir)
    except OSError:
        return None, None

    for name in names:
        m = _REQ_RE.match(name)
        if m:
            found.append((int(m.group(1)), name))
    if not found:
        return None, None

    found.sort()
    seq, name = found[-1]
    for _s, old in found[:-1]:                     # 밀린 것은 버린다
        try:
            os.remove(os.path.join(shm_dir, old))
        except OSError:
            pass
    return seq, os.path.join(shm_dir, name)


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2

    shm_dir, model_path, conf = sys.argv[1], sys.argv[2], float(sys.argv[3])
    os.makedirs(shm_dir, exist_ok=True)

    ready_path = os.path.join(shm_dir, "ready")
    resp_path = os.path.join(shm_dir, "resp.json")

    # 모델 로딩에 수 초 걸린다 — 그동안 gate 는 ready 가 없으므로 비활성으로 본다.
    from ultralytics import YOLO
    model = YOLO(model_path)
    _write_atomic(ready_path, str(os.getpid()))
    print(f"[tool_worker] 준비 완료 — {model_path} conf={conf}", flush=True)

    while True:
        # 부모(GUI)가 죽으면 같이 끝난다 — 고아로 남아 CPU 를 먹지 않게.
        if os.getppid() == 1:
            print("[tool_worker] 부모가 사라져 종료한다", flush=True)
            break

        seq, req_path = _latest_request(shm_dir)
        if seq is None:
            time.sleep(_IDLE_SLEEP)
            continue

        dets = []
        try:
            res = model.predict(req_path, conf=conf, verbose=False)[0]
            for b in res.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                dets.append([res.names[int(b.cls[0])], float(b.conf[0]),
                             x1, y1, x2, y2])
        except Exception as e:                     # noqa: BLE001
            # 🔴 한 프레임의 실패로 워커가 죽으면 안 된다 — 건너뛰고 계속 돈다.
            print(f"[tool_worker] seq={seq} 추론 실패: {e}", flush=True)

        try:
            os.remove(req_path)
        except OSError:
            pass

        _write_atomic(resp_path, json.dumps({"seq": seq, "dets": dets}))

    return 0


if __name__ == "__main__":
    sys.exit(main())
