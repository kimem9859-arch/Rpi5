"""측정 세션 정보 — 폴더 이름 · session.json · 남은 공간(측정 도구 정합 §4.3 「세션 정보」·「용량」).

run_measure.sh 가 부른다: python3 measure_session.py --place 1 --kind 1 --hand 1 --person 2 [--light ...] [--script ...] --on 1
→ 세션 폴더(Demo/measure/<날짜_시각_장소_세션>/)를 만들고 session.json 을 쓴 뒤 경로를 한 줄 출력한다.
🔴 사람은 번호로만 — 이름을 적지 않는다(GitHub 제출 저장소 규칙).
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import time

import config

KINDS = {0: "시험", 1: "정상", 2: "위반", 3: "장갑", 4: "음성끔"}
HANDS = {1: "맨손", 2: "장갑"}
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "measure")
# 판정 규칙 · 모델·공구 경로 · 켜진 기능 — 세션 값을 나중에 같은 조건끼리 비교하려고 남긴다(설계 §4.3 session.json).
# 🔴 이름이 config 에 없으면 시험(test_session_json)이 잡는다 — config 이름을 바꾸면 여기도.
SETTINGS = ("FSM_DWELL_THRESHOLD_SEC", "FSM_GAP_FILL_SEC", "PRESS_CONFIRM_WINDOW_SEC", "PRESS_CONFIRM_GRACE_SEC",
            "PRESS_CONFIRM_FALLBACK_SEC", "TOOL_SCAN_INTERVAL_SEC", "TOOL_CONF", "YOLO_CONF_HIGH", "YOLO_CONF_LOW",
            "HAND_MIN_SCORE", "GPIO_BOUNCE_SEC",
            "INFERENCE_BACKEND", "HEF_MODEL_PATH", "HAND_ENABLED", "HAND_MODELS_DIR",
            "TOOL_ENABLED", "TOOL_BACKEND", "TOOL_HEF_PATH", "TOOL_NAMES", "TOOL_MODEL_PATH", "TOOL_WORKER_PYTHON",
            "INTERLOCK_ENABLED", "GPIO_INPUT_ENABLED", "VOICE_ALERTS", "LLM_ENABLED", "DEMO_CAPTURE")


def session_dir_name(place, kind, now=None):
    now = now or datetime.datetime.now()
    return f"{now:%Y%m%d_%H%M%S}_장소{place}_{KINDS[kind]}"


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def _git_head():
    try:
        return subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:                                # noqa: BLE001
        return None


def write_session(out_dir, answers, measure_on):
    rec = {
        "입력": answers,
        "시작_벽시계": datetime.datetime.now().isoformat(timespec="seconds"),
        "시작_단조_ms": round(time.monotonic() * 1000, 3),
        "코드": {"Rpi5": _git_head()},
        "설정": {k: getattr(config, k, None) for k in SETTINGS},
        "측정기록": bool(measure_on),
        "음성": os.environ.get("SOP_VOICE", "1") != "0",
    }
    # 🔑 파일에 쓴 그대로를 돌려준다 — 설정의 튜플(TOOL_NAMES)은 JSON 에서 리스트가 된다 ·
    #    JSON 으로 못 쓰는 설정값이 섞여도 세션 시작을 막지 않게 글자로(default=str)
    body = json.dumps(rec, ensure_ascii=False, indent=1, default=str)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "session.json"), "w", encoding="utf-8") as f:
        f.write(body)
    return json.loads(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--place", type=int, required=True, choices=(1, 2))
    ap.add_argument("--kind", type=int, required=True, choices=tuple(KINDS))
    ap.add_argument("--hand", type=int, required=True, choices=tuple(HANDS))
    ap.add_argument("--person", type=int, required=True)
    ap.add_argument("--light", default="")
    ap.add_argument("--script", default="")
    ap.add_argument("--firmware", default="glass_voice")      # 남길 펌웨어(실콘솔 plan Task 11 Step 1)
    ap.add_argument("--on", type=int, default=1, choices=(0, 1))
    a = ap.parse_args()
    os.makedirs(a.base, exist_ok=True)
    out = os.path.join(a.base, session_dir_name(a.place, a.kind))
    answers = {"장소": a.place, "세션": KINDS[a.kind], "손": HANDS[a.hand], "사람": a.person,
               "조명": a.light, "대본": os.path.basename(a.script) if a.script else "",
               "펌웨어": a.firmware or "glass_voice"}
    write_session(out, answers, a.on == 1)
    if a.script:
        # 대본 형식은 1단계-나에서 정한다 — 여기서는 원래 이름 그대로 복사만
        shutil.copy2(a.script, os.path.join(out, os.path.basename(a.script)))
    print(out)


if __name__ == "__main__":
    main()
