"""애니메이션 ON/OFF FPS 전후 비교 (G6) — 같은 조건에서 UI_ANIMATION 만 바꿔 잰다.

왜 필요한가:
    2026-08-16 UI 애니메이션 작업은 계측 수단(`fps.py`)만 넣고 **측정은 카메라 부재로
    미뤘다**(design §4). 남은 것이 ⏸ G6 이며, 판정 규칙은 그 design §5 에 이미 있다 —
    **하락 10% 초과면 `UI_ANIMATION` 기본값을 False 로 돌리고 원인을 재분석한다.**

무엇을 재는가:
    런타임이 10초마다 로그에 남기는 `[FPS] 21.5 (애니메이션 on)` 줄을 모은다.
    그 값은 **프레임 도착 간격의 중앙값**에서 나온 것이다(`fps.py`).

동일 조건을 어떻게 만드는가:
    🔴 애니메이션은 **상태가 바뀔 때만** 발생한다 — 가만히 두면 ON/OFF 차이가 안 난다.
    그래서 카메라 앞을 비워 둔 채(정지 장면) SOP 4단계를 실제로 굴린다.
    **손이 화면에 들어가지 않으므로** 추론 부하가 일정하고 애니메이션만 변수로 남는다.

    이 도구는 GUI 를 띄우고 **사람이 키보드로 진행하기를 기다린다.**
    🔴 자동 키 주입(xdotool)은 2026-08-26 에 폐기했다 — 「▶ 작업 시작」이 화면 정중앙
    **GUI 버튼**이라 키보드 우회에 대응 키가 없고, 창 활성화도 불안정해 키가 통째로
    안 들어간 런이 나왔다. 사람이 누르는 편이 확실하고 조건도 흐려지지 않는다.

    측정 구간은 **로그에서 `작업 시작` ~ 마지막 버튼 눌림**을 잘라 쓴다.
    🔴 기동 후 고정 시간으로 자르지 않는다 — Hailo 로드·카메라 재연결이 런마다 달라
    워밍업 구간이 섞이면 그것을 애니메이션 효과로 잘못 읽는다.

    ON/OFF 를 **교차**로 돌린다(ON,OFF,ON,OFF,...). 같은 조건을 연달아 돌리면
    파이 발열·무선 드리프트가 한쪽에만 실린다.

🔴 이 값의 인용 제약:
    **ON/OFF 전후 비교 전용이다.** 손 없는 정지 장면·단일 조건이므로 절대 FPS 를
    성능 지표로 쓰지 않는다(2026-08-14-공구입력-A2-design §G6 과 같은 규율).

전제:
    ① 카메라 — 기본은 **USB 웹캠**(`--camera usb`). 🔴 ESP32 로는 재지 않는다:
       무선·배터리 전압·장면 복잡도(프레임 크기 12~48KB)가 함께 흔들려 FPS 가
       3~25 로 요동하므로, 애니메이션 효과(수 %)를 분리할 수 없다(2026-08-26 실측).
    ② EMO 복귀(GPIO26 LOW) — 열려 있으면 BLOCK 에 갇혀 단계가 진행되지 않는다
    ③ 카메라 앞을 비워 둘 것 — 손이 들어가면 추론 부하가 달라져 비교가 깨진다

사용:
    python3 test/anim_fps_bench.py                  # 기본 3쌍(ON/OFF 각 3런)
    python3 test/anim_fps_bench.py --pairs 2
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEMO = os.path.dirname(_HERE)
sys.path.insert(0, _DEMO)

import config  # noqa: E402  (Demo 를 경로에 넣은 뒤에 읽어야 한다)

_TS = r"\[(\d\d):(\d\d):(\d\d)\]"
_FPS_RE = re.compile(_TS + r"\s+\[FPS\]\s+([\d.]+)\s+\(애니메이션\s+(on|off)\)")
_START_RE = re.compile(_TS + r"\s+\[FSM\] 작업 시작")
_PRESS_RE = re.compile(_TS + r"\s+\[버튼\] (B\d) 눌림")


def load_steps():
    """recipe.json 에서 단계를 읽는다 — 🔴 하드코딩하면 레시피가 바뀔 때 도구가
    조용히 딴 것을 재게 된다(도구 기본값이 config 를 안 따라 네 번 물린 함정)."""
    with open(os.path.join(_DEMO, "recipe.json"), encoding="utf-8") as f:
        recipe = json.load(f)
    steps = []
    for st in sorted(recipe["steps"], key=lambda s: s["order"]):
        sub = st.get("sub") or {}
        steps.append({
            "button": st["button"],
            "key": st["button"][-1],            # "B1" → "1"
            "name": st["name"],
            "wait": float(sub.get("sec", 0)),
            "needs_tool": sub.get("type") == "wait_tool",
        })
    return recipe["process_name"], steps


def newest_log(after):
    """`after`(epoch) 이후에 만들어진 가장 최근 로그 파일."""
    best, best_m = None, after
    for name in os.listdir(config.LOG_SAVE_DIR):
        if not name.endswith("_log.txt"):
            continue
        path = os.path.join(config.LOG_SAVE_DIR, name)
        m = os.path.getmtime(path)
        if m >= best_m:
            best, best_m = path, m
    return best


def _hms(m, base=0):
    return (int(m.group(base + 1)), int(m.group(base + 2)), int(m.group(base + 3)))


def measure_window(text):
    """측정 구간 = `작업 시작` ~ 마지막 버튼 눌림. 못 찾으면 (None, None)."""
    start = _START_RE.search(text)
    presses = list(_PRESS_RE.finditer(text))
    if not start or not presses:
        return None, None
    return _hms(start), _hms(presses[-1])


def parse_fps(text, window):
    """구간 안의 [FPS] 값과 애니메이션 표기."""
    lo, hi = window
    vals, anim_seen = [], set()
    for m in _FPS_RE.finditer(text):
        anim_seen.add(m.group(5))
        if lo <= _hms(m) <= hi:
            vals.append(float(m.group(4)))
    return vals, sorted(anim_seen)


def check_quality(vals, min_fps):
    """🔴 이 런이 **판정에 쓸 만한 상태에서 났는가**.

    2026-08-26 에 두 번 물렸다 — 카메라 공급이 무너져 1~5fps 로 찍힌 데이터를 도구가
    그대로 집계해 「✅ 문턱 이내」를 출력했다. **애니메이션 효과(수 %)를 재는 자리에서
    공급이 절반 이하로 흔들리면 그 값은 애니메이션과 무관한 것을 재고 있다.**
    """
    problems = []
    if len(vals) < 3:
        problems.append("표본 %d개(3개 미만)" % len(vals))
    if vals and statistics.median(vals) < min_fps:
        problems.append("중앙값 %.1f fps < 최소 %.0f" % (statistics.median(vals), min_fps))
    if len(vals) >= 3 and min(vals) * 2 < max(vals):
        problems.append("런 안에서 %.1f~%.1f 로 2배 넘게 흔들림" % (min(vals), max(vals)))
    return problems


def check_run(text, steps):
    """런이 쓸 만한가. 문제 목록을 돌려준다(비면 정상).

    사람이 진행하므로 **덜 눌림·순서 이탈**이 실제로 일어난다. 조용히 집계하면
    구간이 짧거나 딴 장면을 잰 값이 섞인다.
    """
    problems = []
    if not _START_RE.search(text):
        problems.append("「작업 시작」을 누르지 않았다")
    pressed = [m.group(4) for m in _PRESS_RE.finditer(text)]
    for st in steps:
        if st["button"] not in pressed:
            problems.append("%s(%s) 미눌림" % (st["button"], st["name"]))
    if "BLOCK 해제 거부" in text:
        problems.append("EMO 미복귀로 BLOCK")
    if "[FSM] 작업 초기화" in text:
        problems.append("작업 초기화가 섞였다")
    return problems


def run_once(anim_on, timeout, min_fps, camera):
    """GUI 를 띄우고 사람이 진행·종료(ESC)하기를 기다린 뒤 로그를 수집한다."""
    env = dict(os.environ)
    env["SOP_UI_ANIM"] = "1" if anim_on else "0"
    env["SOP_CAMERA"] = camera
    env.setdefault("DISPLAY", ":0")

    started = time.time() - 1
    proc = subprocess.Popen([sys.executable, "main.py"], cwd=_DEMO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        return {"error": "시간 초과(%.0f초) — GUI 를 강제 종료했다" % timeout}

    time.sleep(1.0)
    log = newest_log(started)
    if log is None:
        return {"error": "로그 파일을 찾지 못했다"}
    with open(log, encoding="utf-8", errors="replace") as f:
        text = f.read()

    problems = check_run(text, load_steps()[1])
    lo, hi = measure_window(text)
    if lo is None:
        problems.append("측정 구간을 잡지 못했다")
        return {"log": os.path.basename(log), "path": log, "problems": problems}
    vals, anim_seen = parse_fps(text, (lo, hi))
    if not vals:
        problems.append("구간 안에 [FPS] 표본이 없다(구간이 너무 짧다)")
    problems += check_quality(vals, min_fps)
    return {
        "log": os.path.basename(log),
        "path": log,
        "fps": vals,
        "anim_seen": anim_seen,
        "problems": problems,
        "span": "%02d:%02d:%02d~%02d:%02d:%02d" % (lo + hi),
    }


def main():
    ap = argparse.ArgumentParser(description="애니메이션 ON/OFF FPS 전후 비교 (G6)")
    ap.add_argument("--pairs", type=int, default=3,
                    help="ON/OFF 교차 쌍 수 (기본 3 → 총 6런)")
    ap.add_argument("--timeout", type=float, default=600,
                    help="한 런을 기다리는 최대 초")
    ap.add_argument("--camera", default="usb", choices=("usb", "esp32"),
                    help="측정에 쓸 카메라. 기본 usb — ESP32 는 무선·전원·장면이 함께 "
                         "흔들려 애니메이션 효과를 분리할 수 없다(2026-08-26)")
    ap.add_argument("--min-fps", type=float, default=10.0, dest="min_fps",
                    help="런을 인정할 최소 FPS 중앙값 — 카메라 공급이 무너진 런을 거른다")
    args = ap.parse_args()

    process_name, steps = load_steps()
    runs = args.pairs * 2
    order = []
    for st in steps:
        order.append(st["key"])
        if st["needs_tool"]:
            order.append("t")

    print("=" * 60)
    print(f"애니메이션 ON/OFF FPS 전후 비교 (G6) — {runs}런 · 카메라 {args.camera}")
    print(f"레시피: {process_name} — {len(steps)}단계")
    print()
    print("각 런에서 할 일:")
    print("  ① 화면 정중앙 「▶ 작업 시작」을 누른다 (키보드에 없는 유일한 조작)")
    print(f"  ② 키보드로 {' → '.join(order)} 순서로 진행")
    print("     (각 단계 뒤 대기가 끝나야 다음이 먹는다 — 화면 표시를 보고 누른다)")
    print("  ③ 마지막 단계까지 끝나면 ESC 로 닫는다 → 다음 런이 자동으로 뜬다")
    print()
    print("🔴 카메라 앞은 비워 둔다 — 손이 들어가면 비교가 깨진다.")
    print("🔴 ON/OFF 는 도구가 정한다. 화면으로 구별하려 하지 말 것.")
    print("=" * 60)
    print()

    results = {True: [], False: []}
    for i in range(runs):
        anim_on = (i % 2 == 0)          # 교차: ON, OFF, ON, OFF, ...
        # 🔴 버린 런은 **같은 조건으로 다시** 돌린다 — 그냥 넘기면 ON/OFF 개수가
        #    어긋나 교차 배치의 의미(드리프트 상쇄)가 사라진다.
        while True:
            print(f"[{i+1}/{runs}] 기동 중… GUI 가 뜨면 진행하세요.", flush=True)
            r = run_once(anim_on, args.timeout, args.min_fps, args.camera)
            if r.get("error"):
                print(f"   🔴 {r['error']}")
                return 1
            if r["problems"]:
                print(f"   ⚠️ 이 런은 버린다: {', '.join(r['problems'])} — {r['log']} 폐기")
                os.remove(r["path"])        # 무효 산출물은 남기지 않는다
                print("   → 같은 조건으로 다시 돌립니다.")
                continue
            expect = "on" if anim_on else "off"
            if r["anim_seen"] != [expect]:
                print(f"   🔴 로그의 애니메이션 표기가 {r['anim_seen']} — 기대 {expect}. 중단한다.")
                return 1
            print(f"   {r['log']} [{r['span']}]: 표본 {len(r['fps'])}개 {r['fps']}")
            results[anim_on].extend(r["fps"])
            break

    on, off = results[True], results[False]
    if not on or not off:
        print("\n🔴 한쪽 조건의 표본이 없다 — 판정할 수 없다.")
        return 1

    # 🔴 평균이 아니라 중앙값 — 재연결 구간의 큰 간격 하나가 평균을 무너뜨린다(fps.py 와 같은 이유).
    m_on, m_off = statistics.median(on), statistics.median(off)
    drop = (m_off - m_on) / m_off * 100

    # 🔴 판정 자체가 성립하는가 — 성립 안 하면 「판정 불가」를 명시한다.
    #    조용히 통과시키면 근거 없는 통과 선언이 문서에 남는다(2026-08-26 에 실제로 났다).
    blockers = []
    if len(on) < 6 or len(off) < 6:
        blockers.append("표본 부족(ON %d · OFF %d, 각 6개 필요)" % (len(on), len(off)))
    if abs(drop) > 30:
        blockers.append("차이 %+.1f%% 가 너무 크다 — 애니메이션이 아니라 다른 변수가 "
                        "지배하고 있다" % drop)

    print("\n" + "=" * 60)
    print(f"애니메이션 ON  중앙값 {m_on:5.2f} fps  (표본 {len(on)}개, "
          f"{min(on):.1f}~{max(on):.1f})")
    print(f"애니메이션 OFF 중앙값 {m_off:5.2f} fps  (표본 {len(off)}개, "
          f"{min(off):.1f}~{max(off):.1f})")
    print(f"하락률 {drop:+.1f}%   (판정 문턱: 10% 초과 시 기본 OFF)")
    print("=" * 60)
    if blockers:
        print("🔴 판정 불가 — " + " · ".join(blockers))
        print("   조건을 통제한 뒤 다시 재라. 이 값을 결론으로 쓰지 않는다.")
    elif drop > 10:
        print("🔴 판정: 문턱 초과 — UI_ANIMATION 기본값을 False 로 돌리고 원인을 재분석한다.")
    else:
        print("✅ 판정: 문턱 이내 — UI_ANIMATION 기본 True 를 유지한다.")
    print("⚠️ 이 값은 ON/OFF 전후 비교 전용이다. 손 없는 정지 장면·단일 조건이므로"
          " 절대 FPS 성능 지표로 인용하지 않는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
