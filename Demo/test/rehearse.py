#!/usr/bin/env python3
"""집 리허설 — 학교 절차를 가짜 장치로 사용자 조작 없이 끝까지 돌리고 결과표를 쓴다(학교 방문 준비 설계 §7).

실행: python3 Demo/test/rehearse.py [--only R1,R3] [--twice] [--out DIR]
      결과 = ~/lab/리허설/<시각>/결과.md(학교 필수 · 항목 · 학교 짝 명령) · 세션 = …/measure · 로그 = …/logs
🔑 집과 학교의 차이는 입력 장치 주소뿐 — 실행기 · 시연 · 진행 도우미 · 세기는 학교와 같은 파일 · 같은 답으로 돈다.
🔴 실제 측정 폴더(Demo/measure)와 .camera_ip 는 건드리지 않는다(SOP_MEASURE_BASE · SOP_CAMERA_HOST).
🔴 집 값은 「예상」이다 — 결과표의 ❌ · ⚠️ 는 학교에서 꼭 다시 잰다(설계 D16).
"""
import argparse
import datetime
import glob
import json
import os
import pty
import signal
import subprocess
import sys
import threading
import time

TEST = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(TEST)
sys.path.insert(0, DEMO)
sys.path.insert(0, TEST)

import config                      # noqa: E402
import measure_prompt              # noqa: E402
import measure_script as MS        # noqa: E402
import rehearse_judge as RJ        # noqa: E402
from fake_camera import FakeCamera, load_frames      # noqa: E402
from fake_interlock import FakeInterlock             # noqa: E402
from rehearse_glass import LiveGlass, make_clips, watch_say   # noqa: E402

SCEN = os.path.join(DEMO, "measure", "시나리오")
SRC_STILL = os.path.expanduser("~/lab/화면검사/20261011_②B_전")              # 안경 원본 바이트(손 없음)
SRC_HANDS = os.path.join(DEMO, "recordings", "20261006_201449_camera.mp4")    # 손 · 버튼이 있는 녹화(화면 방향)
VOICE_SCRIPT = os.path.join(SCEN, "장소1_⑤음성.csv")
BASIS_SCRIPT = os.path.join(SCEN, "장소1_⑥근거.csv")
PROC = {"2": "종전", "1": "1단계", "3": "1단계+화면 덜 그리기", "4": "1단계+2a", "5": "1단계+2a+2b"}
PROC_ORDER = ["2", "1", "3", "4", "5"]
EXPECT_1 = (14.5, 17.0)            # 1단계 기대(상위 설계 근거 · 설계 근거용) — 범위 밖이면 ⚠️(학교 필수)


class Devices:
    """가짜 카메라 · 말하는 가짜 안경 · 가짜 인터락 — with 로 띄우고 내린다."""

    def __init__(self, src=SRC_STILL, unorient=False, clips=None, limit=600, fps=19.5):
        self.src, self.unorient, self.clips, self.limit, self.fps = src, unorient, clips or {}, limit, fps

    def __enter__(self):
        self.cam = FakeCamera(load_frames(self.src, self.limit, self.unorient), port=config.CAMERA_TCP_PORT,
                              fps=self.fps).start()
        self.glass = LiveGlass(quiet=True).start()
        self.fi = FakeInterlock().start()
        self._stop = threading.Event()
        threading.Thread(target=watch_say, args=(self.glass, self.clips, self._stop), daemon=True).start()
        return self

    def env(self):
        return {"SOP_CAMERA_HOST": "127.0.0.1", "SOP_INTERLOCK_PORT": self.fi.port}

    def __exit__(self, *exc):
        self._stop.set()
        for d in (self.cam, self.glass, self.fi):
            try:
                d.stop()
            except Exception:                       # noqa: BLE001
                pass
        time.sleep(0.5)                             # 포트가 풀리게


def _clean_shm():
    measure_prompt.clear()
    try:
        os.remove(os.path.join(config.CUE_SHM_DIR, "rehearse_say.json"))
    except OSError:
        pass


def _start_guide(env, log_path):
    """진행 도우미를 가상 단말(pty)에서 — 키 입력이 단말을 요구한다. 출력은 로그 파일로 비운다."""
    m, s = pty.openpty()
    p = subprocess.Popen([sys.executable, "measure_guide.py"], cwd=DEMO, env=env, stdin=s, stdout=s, stderr=s,
                         start_new_session=True)
    os.close(s)

    def drain():
        with open(log_path, "ab") as f:
            while True:
                try:
                    b = os.read(m, 4096)
                except OSError:
                    return
                if not b:
                    return
                f.write(b)
    threading.Thread(target=drain, daemon=True).start()
    return p, m


def _stop_guide(g):
    p, m = g
    try:
        os.write(m, b"q")
    except OSError:
        pass
    try:
        p.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGTERM)
        p.wait(5)
    try:
        os.close(m)
    except OSError:
        pass


def answers(script="", from_run="", processing=""):
    """실행기 질문 차례 = 장소 · 세션 · 손 · 사람 · 조명 · 대본 · 몇 판부터 · 펌웨어 · 안경 전원 · 처리 설정 · 측정 기록 · 음성 알림."""
    return ["1", "0", "1", "9", "리허설", script, from_run, "", "", processing, "1", "", "", ""]


def run_session(out, name, script="", processing="", extra=None, guide=False, timeout=600, devices=None):
    """실행기를 표준입력 답으로 한 번 → {"dir", "finished", "errors", "warnings", "log", "sec"}."""
    logs = os.path.join(out, "logs")
    os.makedirs(logs, exist_ok=True)
    log = os.path.join(logs, f"{name}.log")
    # 🔴 SOP_AUDIENCE_SPEAKER=0 — 가짜 안경도 「[재생]」을 돌려줘 진짜 TV 로 알림 없이 소리가 났다(2026-10-21 최종 리뷰 I2)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", SOP_FULLSCREEN="0", SOP_REHEARSE_WORKER="1", SOP_REHEARSAL="1",
               SOP_AUDIENCE_SPEAKER="0",
               SOP_MEASURE_BASE=os.path.join(out, "measure"), **(devices.env() if devices else {}), **(extra or {}))
    for k in ("SOP_ORIENT_ONE_REMAP", "SOP_DISPLAY_PAINT", "SOP_DISPLAY_EVERY", "SOP_INFER_MODEL", "SOP_PIPELINE2"):
        env.pop(k, None)
    _clean_shm()
    g = _start_guide(env, os.path.join(logs, f"{name}_guide.log")) if guide else None
    t0 = time.monotonic()
    finished = True
    with open(log, "wb") as f:
        p = subprocess.Popen(["bash", "run_measure.sh"], cwd=DEMO, env=env, stdin=subprocess.PIPE, stdout=f,
                             stderr=subprocess.STDOUT, start_new_session=True)
        try:
            p.communicate("\n".join(answers(script, "", processing)).encode() + b"\n", timeout=timeout)
        except subprocess.TimeoutExpired:
            finished = False
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
    if g:
        _stop_guide(g)
    _clean_shm()
    text = open(log, encoding="utf-8", errors="replace").read()
    d = next((ln.split("세션 폴더:", 1)[1].strip() for ln in text.splitlines() if "세션 폴더:" in ln), None)
    errors = [ln.strip() for ln in text.splitlines() if "Traceback" in ln or "세기 실패" in ln
              or "세션 정보를 만들지 못했다" in ln]
    if p.returncode not in (0, None) and finished:
        errors.append(f"실행기 종료 코드 {p.returncode}")
    warnings = [ln.strip() for ln in text.splitlines() if "[config] ⚠️" in ln]
    import re
    for code in re.findall(r"=== 종료 \(exit code: (-?\d+)\)", text):
        if code != "0":
            errors.append(f"시연 종료 코드 {code}")      # 🔑 오류 Enter 대기를 답 끝 빈 줄이 채워 조용히 넘어가지 않게(리뷰 Minor 6)
    if not finished:
        errors.append(f"시간 상한 {timeout}초 넘김")
    return {"dir": d, "finished": finished and d is not None, "errors": errors, "warnings": warnings,
            "log": log, "sec": round(time.monotonic() - t0)}


def _script_runs(path, from_run=1):
    rows = MS.load_script(path)
    return len({r["판"] for r in rows if r["판"] >= from_run})


def _questions(path):
    return sorted({r["대상"] for r in MS.load_script(path) if r["행동"] in ("질문", "비상질문") and r["대상"]})


def _voice_counts(d):
    import csv
    n = {"wake": 0, "stt": 0, "answer": 0}
    try:
        with open(os.path.join(d, "voice_events.csv"), encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("kind") in n:
                    n[r["kind"]] += 1
    except OSError:
        pass
    return n


def _base(iid, title, kind, home, **kw):
    it = {"id": iid, "title": title, "kind": kind, "finished": True, "errors": [], "warnings": [], "values": {},
          "expect": {}, "samples": {}, "script": None, "same": None, "phys": [], "split": None, "home": home}
    it.update(kw)
    return it


def _merge(it, r):
    it["finished"] = it["finished"] and r["finished"]
    it["errors"] += r["errors"]
    it["warnings"] += r["warnings"]


# ── 항목 ────────────────────────────────────────────────────────────────────
def items_R1(out, twice):
    """⑤음성 측정 — 대본 전부 · 흐름 + 음성 사건 수(임시)."""
    clips = make_clips(_questions(VOICE_SCRIPT), os.path.join(out, "clips"))
    flow = _base("R1", "⑤음성 측정(대본 전부)", "흐름", "가짜 카메라(정지 장면) · TTS 질문 소리 · 가상 작업자")
    voice = _base("R1-음성", "호출 · 받아쓰기 · 답 사건 수", "임시", "TTS 소리 — 실물 마이크 · 소음 아님")
    want = _script_runs(VOICE_SCRIPT)
    for k in range(2 if twice else 1):
        with Devices(clips=clips) as dev:
            r = run_session(out, f"R1_{k + 1}", VOICE_SCRIPT, guide=True, timeout=1800, devices=dev)
        _merge(flow, r)
        if r["dir"]:
            st = RJ.session_stats(r["dir"])
            flow["script"] = (want, st["runs"])
            vc = _voice_counts(r["dir"])
            for key, label in (("wake", "호출"), ("answer", "답")):
                voice["values"].setdefault(label, []).append(float(vc[key]))
    return [flow, voice]


def items_R2(out, twice):
    it = _base("R2", "3판 판 1 재확인", "흐름", "가짜 카메라 · 가상 작업자")
    clips = make_clips(_questions(VOICE_SCRIPT), os.path.join(out, "clips"))
    for k in range(2 if twice else 1):
        with Devices(clips=clips) as dev:
            r = run_session(out, f"R2_{k + 1}", VOICE_SCRIPT, extra={"SOP_REHEARSE_RUNS": "1"}, guide=True,
                            timeout=600, devices=dev)
        _merge(it, r)
        if r["dir"]:
            it["script"] = (1, RJ.session_stats(r["dir"])["runs"])
    return [it]


def items_R3(out, twice, order=None):
    """처리 비교 — 처리 설정마다 60초(대본 없음 · 작업 시작 뒤 그대로) · 번갈아 두 번."""
    order = order or PROC_ORDER
    its = {n: _base(f"R3-{n}", f"처리 비교 · {PROC[n]}", "임시", "가짜 카메라 19.5장/초(손 있는 녹화 · 방향 되돌림) · 화면 offscreen",
                    phys=[]) for n in order}
    for k in range(2 if twice else 1):
        for n in order:
            with Devices(src=SRC_HANDS, unorient=True) as dev:
                r = run_session(out, f"R3_{n}_{k + 1}", processing=n, extra={"SOP_REHEARSE_SECONDS": "60"},
                                timeout=300, devices=dev)
            it = its[n]
            _merge(it, r)
            st = RJ.session_stats(r["dir"]) if r["dir"] else {"proc_fps": None, "recv_fps": None, "frames": 0}
            it["values"].setdefault("처리 fps", []).append(st["proc_fps"])
            it["values"].setdefault("받은 fps", []).append(st["recv_fps"])
            it["samples"]["처리 장"] = (min(it["samples"].get("처리 장", (10 ** 9, 30))[0], st["frames"]), 30)
            if st["proc_fps"] and st["recv_fps"]:
                it["phys"].append((f"처리 fps {st['proc_fps']:.1f} ≤ 받은 fps {st['recv_fps']:.1f}",
                                   st["proc_fps"] <= st["recv_fps"] + 0.5))
    if "1" in its:
        its["1"]["expect"] = {"처리 fps": EXPECT_1}
    out_items = [its[n] for n in order]
    if "4" in order:
        same = _base("R3-2a출력", "2a 출력 동일(지금 방식 vs InferModel · 손 녹화 120장)", "확정", "같은 입력 → 같은 출력")
        r = subprocess.run([sys.executable, os.path.join(TEST, "infer_model_check.py"), SRC_HANDS, "--limit", "120"],
                           cwd=DEMO, capture_output=True, text=True, timeout=1800)
        with open(os.path.join(out, "logs", "R3_2a출력.log"), "w", encoding="utf-8") as f:
            f.write(r.stdout + r.stderr)
        same["same"] = r.returncode == 0
        if r.returncode not in (0, 1):
            same["errors"].append(f"비교 도구 오류 {r.returncode} · {r.stdout[-200:]}")
        out_items.append(same)
    if "4" in its and "5" in its:
        pair = _base("R3-2b", "2b 효과(+2a 와 +2a+2b 가 갈리나)", "임시", "가짜 카메라",
                     values={"+2a": its["4"]["values"]["처리 fps"], "+2a+2b": its["5"]["values"]["처리 fps"]},
                     split=("+2a", "+2a+2b"))
        out_items.append(pair)
    return out_items


def items_R4(out, twice):
    """E1 · E2 — 받기 도구(cam_grab)가 끝까지 돈다(흐름) · E2 의 시연 쪽은 R3 과 같은 흐름."""
    it = _base("R4", "E1 · E2 받기 도구", "흐름", "가짜 카메라(정지 장면)")
    grab = os.path.expanduser("~/lab/화면검사/cam_grab.py")
    for k in range(2 if twice else 1):
        d = os.path.join(out, f"E1_{k + 1}")
        with Devices():
            r = subprocess.run([sys.executable, grab, "grab", d, "5", "127.0.0.1"], capture_output=True, text=True,
                               timeout=120)
        n = len(glob.glob(os.path.join(d, "f*.jpg")))
        if r.returncode != 0 or n == 0 or not os.path.exists(os.path.join(d, "times.csv")):
            it["errors"].append(f"cam_grab 종료 {r.returncode} · 장 {n} · {r.stderr[-200:]}")
    return [it]


def items_R0(out, twice):
    """사전 점검 — 가짜 장치를 띄운 채 --home 으로 끝까지 · ❌ 수(집 · 건너뜀 제외)."""
    it = _base("R0", "사전 점검(school_check --home)", "흐름", "가짜 장치 · 실물 전용 항목은 건너뜀")
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    for k in range(2 if twice else 1):
        with Devices() as dev:
            env = dict(os.environ, **dev.env())
            r = subprocess.run([sys.executable, os.path.join(TEST, "school_check.py"), "--home"], cwd=DEMO, env=env,
                               capture_output=True, text=True, timeout=180)
        with open(os.path.join(out, "logs", f"R0_{k + 1}.log"), "w", encoding="utf-8") as f:
            f.write(r.stdout + r.stderr)
        bad = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("❌") and "건 —" not in ln]
        if r.returncode != 0:
            it["errors"] += bad or [f"종료 코드 {r.returncode} · {r.stderr[-200:]}"]
    return [it]


def items_R7(out, twice):
    """근거 측정 — 대본 14판 전부(G1~G7 · 머묾 낱말 포함) · 장면 띠 · 분석 도구가 끝까지(흐름 · 녹화 장면이라 값은 의미 없음)."""
    it = _base("R7", "근거 측정(대본 전부 · 장면 띠 · 분석)", "흐름", "가짜 카메라(정지 장면 — 손 없음) · 가상 작업자(머묾은 못 함 → 4초 뒤 다음)")
    for k in range(2 if twice else 1):
        with Devices() as dev:
            r = run_session(out, f"R7_{k + 1}", BASIS_SCRIPT, guide=True, timeout=1800, devices=dev)
        _merge(it, r)
        if not r["dir"]:
            continue
        it["script"] = (_script_runs(BASIS_SCRIPT), RJ.session_stats(r["dir"])["runs"])
        b = subprocess.run([sys.executable, os.path.join(TEST, "measure_basis.py"), r["dir"]], capture_output=True,
                           text=True, timeout=120)
        with open(os.path.join(out, "logs", f"R7_{k + 1}_basis.log"), "w", encoding="utf-8") as f:
            f.write(b.stdout + b.stderr)
        if b.returncode not in (0, 1) or not os.path.exists(os.path.join(r["dir"], "basis.json")):
            it["errors"].append(f"분석 도구 종료 {b.returncode} · {b.stderr[-200:]}")
        glog = open(os.path.join(out, "logs", f"R7_{k + 1}_guide.log"), encoding="utf-8", errors="replace").read()
        if "Traceback" in glog:
            it["errors"].append("진행 도우미 오류(로그)")
    return [it]


def items_R6(out, twice):
    """램프 지연 — 도구 정확도(확정 · 가짜 카메라 램프 흉내 지연 0.08초) + --screen 대안이 끝까지(흐름)."""
    import lamp_latency as LL
    acc = _base("R6", "램프 지연 도구 정확도(흉내 지연 80ms)", "확정", "가짜 카메라 19.5장/초 · 램프 흉내 · 가짜 인터락",
                expect={"지연 중앙 ms": (80.0, 135.0)})
    for k in range(2 if twice else 1):
        cam = FakeCamera(load_frames(SRC_STILL, 200), port=config.CAMERA_TCP_PORT, fps=19.5, mimic=True).start()
        fi = FakeInterlock(on_cmd=lambda c, t: cam.lamp(c == "WARN", 0.08)).start()
        try:
            r = LL.run("127.0.0.1", config.CAMERA_TCP_PORT, fi.port, n_meas=24, interval=1.5, settle_s=0.0,
                       out=os.path.join(out, f"R6_{k + 1}"))
        finally:
            cam.stop()
            fi.stop()
            time.sleep(0.5)
        if "error" in r:
            acc["errors"].append(r["error"])
            continue
        acc["values"].setdefault("지연 중앙 ms", []).append(r["med"])
        if r.get("warning"):
            acc["warnings"].append(r["warning"])
        acc["samples"]["잰 횟수"] = (r["n"], 20)
    scr = _base("R6-화면", "램프 대안 --screen(끝까지 · 집은 화면을 못 봄)", "흐름", "offscreen — 자리 못 찾음 오류가 정상")
    with Devices():
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", SOP_CAMERA_HOST="127.0.0.1")
        r = subprocess.run([sys.executable, os.path.join(TEST, "lamp_latency.py"), "--screen", "--n", "2",
                            "--interval", "0.6"], cwd=DEMO, env=env, capture_output=True, text=True, timeout=120)
    if "V11" not in r.stdout or "Traceback" in r.stderr:
        scr["errors"].append(f"--screen 이 끝까지 못 돎 · {r.stdout[-200:]} {r.stderr[-200:]}")
    return [acc, scr]


def items_R5(out, twice):
    """펌웨어 — 변형 4개 컴파일만(확정 · md5 가 서로 달라야 옵션이 먹은 것) + 재압축 검출 비교(임시 · 학교 필수)."""
    import re
    flash = os.path.join(os.path.dirname(DEMO), "arduino", "flash_esp32.sh")
    build = _base("R5", "펌웨어 변형 빌드(굽지 않음)", "확정", "--build-only · 안경에 굽지 않음")
    md5 = {}
    for opt in ([], ["--jpeg-quality", "20"], ["--jpeg-quality", "25"], ["--fb-count", "3"]):
        r = subprocess.run(["bash", flash, "--build-only", *opt], capture_output=True, text=True, timeout=1200,
                           stdin=subprocess.DEVNULL)
        m = re.search(r"컴파일 통과 · ([0-9a-f]{32})", r.stdout)
        if r.returncode != 0 or not m:
            build["errors"].append(f"빌드 실패 {opt} · {r.stdout[-200:]} {r.stderr[-200:]}")
        else:
            md5[" ".join(opt) or "지금"] = m.group(1)
    # 🔑 md5 차이는 근거가 아니다 — 같은 펌웨어도 빌드할 때마다 md5 가 바뀐다(빌드 시각이 들어간다).
    #    옵션이 먹었는지는 스케치 오브젝트 컴파일 명령에 -D 가 붙었는지로 본다(arduino-cli -v).
    cli = os.path.expanduser("~/bin/arduino-cli")
    v = subprocess.run([cli, "compile", "--fqbn", "esp32:esp32:XIAO_ESP32S3:PSRAM=opi", "--clean", "--build-property",
                        "compiler.cpp.extra_flags=-DGLASS_JPEG_QUALITY=20 -DGLASS_FB_COUNT=3", "-v",
                        os.path.join(os.path.dirname(flash), "glass_voice")], capture_output=True, text=True, timeout=1200)
    obj = [ln for ln in v.stdout.splitlines() if "sketch/glass_voice.ino.cpp.o" in ln and " -E " not in ln]
    if v.returncode != 0 or not any("-DGLASS_JPEG_QUALITY=20 -DGLASS_FB_COUNT=3" in ln for ln in obj):
        build["errors"].append("스케치 컴파일 명령에 빌드 옵션(-DGLASS_*)이 안 붙었다")
    build["home"] += " · " + " · ".join(f"{k} {v[:8]}" for k, v in md5.items())
    probe = _base("R5-압축", "재압축 검출 비교(파이 JPEG · 방향만)", "임시", "파이 JPEG 품질 ≠ 카메라 칩 품질 — 학교 필수")
    r = subprocess.run([sys.executable, os.path.join(TEST, "jpeg_quality_probe.py"), SRC_STILL, "--limit", "80",
                        "--q", "25", "15"], cwd=DEMO, capture_output=True, text=True, timeout=1200)
    with open(os.path.join(out, "logs", "R5_probe.log"), "w", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    rows = re.findall(r"^\| (\d+) \| ([\d.]+) \| (\d+)% \| (\d+)% \|$", r.stdout, re.M)
    if r.returncode != 0 or not rows:
        probe["errors"].append(f"재압축 비교 실패 · {r.stderr[-200:]}")
    for q, ratio, btn, hand in rows:
        probe["values"][f"q{q} 크기 비"] = [float(ratio)]
        probe["values"][f"q{q} 버튼 같음 %"] = [float(btn)]
    return [build, probe]


def items_R8(out, twice):
    """되돌리기 — 출발 전 태그 · 펌웨어 백업 대조(md5) · esptool · 처리 설정 1 = 스위치 없음(흐름)."""
    it = _base("R8", "되돌리기 수단 점검", "흐름", "실제로 되돌리지 않고 수단이 있는지만")
    rpi5 = os.path.dirname(DEMO)
    r = subprocess.run(["git", "-C", rpi5, "rev-parse", "-q", "--verify", "학교1012-전^{commit}"], capture_output=True, text=True)
    if r.returncode != 0:
        it["errors"].append("출발 전 태그 학교1012-전 없음")
    bins = sorted(glob.glob(os.path.expanduser("~/lab/esp32-link/main_5D38_full_*.bin")))
    if not bins:
        it["errors"].append("안경 펌웨어 백업 없음")
    else:
        r = subprocess.run(["md5sum", "-c", os.path.basename(bins[-1]) + ".md5"], cwd=os.path.dirname(bins[-1]),
                           capture_output=True, text=True)
        if r.returncode != 0:
            it["errors"].append(f"백업 md5 불일치 {os.path.basename(bins[-1])} · {r.stdout[-120:]}")
        it["home"] += f" · 최근 백업 {os.path.basename(bins[-1])}"
    r = subprocess.run(["esptool", "version"], capture_output=True, text=True)
    if r.returncode != 0:
        it["errors"].append("esptool 이 없다")
    r = subprocess.run([sys.executable, os.path.join(DEMO, "selftest", "test_measure_runner.py")], capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0:
        it["errors"].append("실행기 처리 설정 시험 실패(처리 설정 1 = 스위치 없음)")
    return [it]


ITEMS = {"R0": items_R0, "R1": items_R1, "R2": items_R2, "R3": items_R3, "R4": items_R4,
         "R5": items_R5, "R6": items_R6,
         "R7": items_R7, "R8": items_R8}

SCHOOL = {
    "R0": "python3 Demo/test/school_check.py",
    "R1": "bash Demo/run_measure.sh · 대본 장소1_⑤음성 · 처리 설정 엔터 + 진행 도우미(bash Demo/run_guide.sh)",
    "R1-음성": "R1 과 같음 — 세기 V1~V9",
    "R2": "bash Demo/run_measure.sh · 대본 장소1_⑤음성 · 판 1 만",
    "R3-2": "bash Demo/run_measure.sh · 처리 설정 2", "R3-1": "bash Demo/run_measure.sh · 처리 설정 1(엔터)",
    "R3-3": "bash Demo/run_measure.sh · 처리 설정 3", "R3-4": "bash Demo/run_measure.sh · 처리 설정 4",
    "R3-5": "bash Demo/run_measure.sh · 처리 설정 5", "R3-2b": "R3-4 · R3-5 를 번갈아 두 번",
    "R4": "python3 ~/lab/화면검사/cam_grab.py grab ~/lab/화면검사/<날짜>_E1_책상 30 (host 인자 없이)",
    "R3-2a출력": "python3 Demo/test/infer_model_check.py <그날 측정 녹화 mp4> --limit 120 (시연 끔)",
    "R5": "bash arduino/flash_esp32.sh main --jpeg-quality N (굽기 · 진행표 5단계)",
    "R5-압축": "진행표 5단계 — 실제 변형을 굽고 같은 장면 60초(받은 fps · 장 크기 · 버튼 확정 · 손끝 보임)",
    "R6": "python3 Demo/test/lamp_latency.py (시연 끔)",
    "R6-화면": "python3 Demo/test/lamp_latency.py --screen (램프가 안 보일 때 · 안경이 콘솔 모니터를 보게)",
    "R7": "bash Demo/run_measure.sh · 대본 장소1_⑥근거 + 진행 도우미 → python3 Demo/test/measure_basis.py <세션>",
    "R8": "진행표 되돌리기 모음",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="집 리허설(학교 방문 준비 설계 §7)")
    ap.add_argument("--only", default="", help="R1,R3 처럼 · 비우면 전부")
    ap.add_argument("--twice", action="store_true", help="같은 것을 두 번(흩어짐 확인)")
    ap.add_argument("--out", default="")
    ap.add_argument("--proc", default="", help="R3 처리 설정만 골라서(예: 4,5 · 비우면 전부)")
    a = ap.parse_args(argv)
    out = a.out or os.path.expanduser(f"~/lab/리허설/{datetime.datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    keys = [k.strip() for k in a.only.split(",") if k.strip()] or list(ITEMS)
    if a.proc:
        global PROC_ORDER
        PROC_ORDER = [x.strip() for x in a.proc.split(",") if x.strip()]
    items = []
    for k in keys:
        t0 = time.monotonic()
        print(f"── {k} 시작", flush=True)
        try:
            got = ITEMS[k](out, a.twice)
        except Exception as e:                       # noqa: BLE001 — 한 항목이 죽어도 결과표는 남긴다
            got = [_base(k, "도구 오류", "흐름", "—", finished=False, errors=[f"{type(e).__name__}: {e}"])]
        for it in got:
            it.setdefault("title", k)
            it["sec"] = round(time.monotonic() - t0)
        items += got
        for it in got:
            print(f"   {it['id']} {RJ.judge(it)[0]} {' · '.join(RJ.judge(it)[1])[:200]}", flush=True)
    res = RJ.write_table(items, os.path.join(out, "결과.md"), SCHOOL)
    with open(os.path.join(out, "결과.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1, default=str)
    bad = [i for i, m, _ in res if m == "❌"]
    print(f"결과표 = {os.path.join(out, '결과.md')} · ❌ {len(bad)} {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
