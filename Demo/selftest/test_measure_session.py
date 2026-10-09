"""측정 세션 정보(측정 도구 정합 §4.3 세션 정보·용량) — 폴더 이름 · session.json · 남은 공간.

실행: python3 Demo/selftest/test_measure_session.py
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO_DIR)

import measure_session as MS

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def test_dir_name():
    print("\n[세션] 폴더 이름 = 날짜_시각_장소_세션")
    n = MS.session_dir_name(1, 2, now=datetime.datetime(2026, 10, 7, 9, 5, 3))
    check(n == "20261007_090503_장소1_위반", n)


def test_session_json():
    print("\n[세션] session.json — 입력 · 시작 시각 둘 · 코드 버전 · 설정값")
    d = tempfile.mkdtemp()
    rec = MS.write_session(d, {"장소": 1, "세션": 1, "손": 1, "사람": 2, "조명": "형광등"}, measure_on=True)
    with open(os.path.join(d, "session.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    check(on_disk == rec, "파일과 반환이 같다")
    for k in ("입력", "시작_벽시계", "시작_단조_ms", "코드", "설정", "측정기록"):
        check(k in rec, f"칸 {k}")
    missing = [k for k in MS.SETTINGS if rec["설정"][k] is None]
    check(not missing, f"config 에 없는 설정 이름 {missing} — 이름이 틀렸거나 config 에서 사라졌다")


def test_cli_prints_dir():
    print("\n[세션] CLI 가 폴더를 만들고 경로를 한 줄 출력 · 대본은 원래 이름으로 복사 · 펌웨어 기본값")
    base = tempfile.mkdtemp()
    script = os.path.join(tempfile.mkdtemp(), "대본_시험.txt")
    with open(script, "w", encoding="utf-8") as f:
        f.write("1판 B1 B2 B3 B4\n")
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base,
                        "--place", "2", "--kind", "0", "--hand", "1", "--person", "1", "--on", "1",
                        "--script", script],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    check(r.returncode == 0 and os.path.isfile(os.path.join(out, "session.json")) and out.endswith("_장소2_시험"),
          f"{r.returncode} {out} {r.stderr[-200:]}")
    check(os.path.isfile(os.path.join(out, "대본_시험.txt")), "대본 복사")
    with open(os.path.join(out, "session.json"), encoding="utf-8") as f:
        inp = json.load(f)["입력"]
    check(inp["펌웨어"] == "glass_voice", "펌웨어 기본값")
    check(inp.get("안경전원") == "무선(배터리)", f"안경 전원 기본 = 무선(측정 설계 D23) — {inp.get('안경전원')}")


def test_launcher_records_glasses_power():
    print("\n[세션] 실행기 「안경 전원」 2 = 유선(USB) 이 session.json 에 남는다(측정 설계 D23)")
    d = _launcher_copy()
    r = subprocess.run(["bash", os.path.join(d, "run_measure.sh")], input="1\n0\n1\n1\n\n\n\n2\n0\n\n",
                       capture_output=True, text=True, timeout=60)
    found = [os.path.join(d, "measure", x, "session.json") for x in os.listdir(os.path.join(d, "measure"))] \
        if os.path.isdir(os.path.join(d, "measure")) else []
    got = None
    if found:
        with open(found[0], encoding="utf-8") as f:
            got = json.load(f)["입력"].get("안경전원")
    check(got == "유선(USB)", f"안경전원 = {got} · {r.stdout[-200:]}")


def test_voice_off_recorded():
    print("\n[세션] 음성 끔 세션이면 session.json 에 음성 끔 — 실행기가 SOP_VOICE 를 먼저 내보낸다")
    base = tempfile.mkdtemp()
    env = dict(os.environ, SOP_VOICE="0")
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base,
                        "--place", "1", "--kind", "4", "--hand", "1", "--person", "1", "--on", "1"],
                       capture_output=True, text=True, env=env)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    with open(os.path.join(out, "session.json"), encoding="utf-8") as f:
        check(json.load(f)["음성"] is False, "음성 False")
    with open(os.path.join(_DEMO_DIR, "run_measure.sh"), encoding="utf-8") as f:
        sh = f.read()
    check(sh.index("SOP_VOICE=0") < sh.index("measure_session.py --place"),
          "run_measure.sh 가 SOP_VOICE=0 을 세션 정보 쓰기 **앞에** 내보낸다")



def _launcher_copy():
    """실행기를 임시 폴더에 복사 — run_demo.sh 는 가짜(환경변수만 출력) · measure_session 은 진짜(링크)."""
    import shutil
    d = tempfile.mkdtemp()
    shutil.copy(os.path.join(_DEMO_DIR, "run_measure.sh"), d)
    os.symlink(os.path.join(_DEMO_DIR, "measure_session.py"), os.path.join(d, "measure_session.py"))
    with open(os.path.join(d, "run_demo.sh"), "w", encoding="utf-8") as f:
        f.write('echo "STUB MEASURE=${SOP_MEASURE_DIR:-없음}"\n')
    return d


def test_free_space_check_precise():
    print("\n[세션] 1GB 경고는 올림 없는 값으로(리뷰 I-2 — df -BG 는 올려 0.3GB 도 1G 로 보인다)")
    with open(os.path.join(_DEMO_DIR, "run_measure.sh"), encoding="utf-8") as f:
        sh = f.read()
    check("df -BG" not in sh and "measure_session.py --free-gb" in sh, "실행기가 measure_session.free_gb 로 잰다")
    import shutil
    check(abs(MS.free_gb(_DEMO_DIR) - shutil.disk_usage(_DEMO_DIR).free / 1e9) < 0.01, "free_gb = 실제 남은 바이트 / 1e9")
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--free-gb"],
                       capture_output=True, text=True)
    check(r.returncode == 0 and abs(float(r.stdout.strip() or "nan") - MS.free_gb(_DEMO_DIR)) < 0.05,
          f"CLI --free-gb {r.stdout!r} {r.stderr[-200:]}")


def test_launcher_bad_input_keeps_window():
    print("\n[세션] 입력 오류면 이유를 보이고 기다린다 · 세션 폴더를 남기지 않는다(리뷰 I-3)")
    d = _launcher_copy()
    r = subprocess.run(["bash", os.path.join(d, "run_measure.sh")], input="4\n0\n1\n1\n\n\n\n\n1\n\n",
                       capture_output=True, text=True, timeout=60)
    check("세션 정보를 만들지 못했다" in r.stdout and "STUB" not in r.stdout, f"{r.stdout[-300:]}")
    check(not os.path.isdir(os.path.join(d, "measure")) or not os.listdir(os.path.join(d, "measure")),
          "반쪽 세션 폴더 없음")


def test_launcher_off_ignores_inherited_dir():
    print("\n[세션] 기록 끔 회차는 물려받은 SOP_MEASURE_DIR 도 지운다(리뷰 I-3)")
    d = _launcher_copy()
    r = subprocess.run(["bash", os.path.join(d, "run_measure.sh")], input="1\n0\n1\n1\n\n\n\n\n0\n\n",
                       capture_output=True, text=True, timeout=60, env=dict(os.environ, SOP_MEASURE_DIR="/tmp/옛폴더"))
    check("STUB MEASURE=없음" in r.stdout, f"{r.stdout[-300:]}")


def test_script_path_tilde_and_missing():
    print("\n[세션] 대본 경로 ~ 를 펼친다 · 없는 대본이면 폴더를 만들지 않고 끝낸다(리뷰 I-3)")
    home = tempfile.mkdtemp()
    with open(os.path.join(home, "대본.txt"), "w", encoding="utf-8") as f:
        f.write("1판\n")
    base = tempfile.mkdtemp()
    env = dict(os.environ, HOME=home)
    cmd = [sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base,
           "--place", "1", "--kind", "0", "--hand", "1", "--person", "1", "--on", "1"]
    r = subprocess.run(cmd + ["--script", "~/대본.txt"], capture_output=True, text=True, env=env)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    check(r.returncode == 0 and os.path.isfile(os.path.join(out, "대본.txt")), f"~ 펼침 {r.returncode} {r.stderr[-200:]}")
    base2 = tempfile.mkdtemp()
    r = subprocess.run([c if c != base else base2 for c in cmd] + ["--script", "~/없는대본.txt"],
                       capture_output=True, text=True, env=env)
    check(r.returncode != 0 and os.listdir(base2) == [], f"없는 대본 rc={r.returncode} · {os.listdir(base2)}")


def test_place3():
    print("\n[세션] 장소3(시연 영상 장소 · 줄인 판) 을 받는다 — 폴더 이름 · session.json 「장소」")
    base = tempfile.mkdtemp()
    r = subprocess.run([sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base,
                        "--place", "3", "--kind", "1", "--hand", "1", "--person", "1", "--on", "1"],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    check(r.returncode == 0 and out.endswith("_장소3_정상"), f"rc={r.returncode} · {out} {r.stderr[-150:]}")
    with open(os.path.join(_DEMO_DIR, "run_measure.sh"), encoding="utf-8") as f:
        check("3 장소3" in f.read(), "실행기 질문에 「3 장소3」")


def test_script_by_number():
    print("\n[세션] 대본을 번호로 — 시나리오 폴더의 이름순 n번째(터미널에서 한글·①을 치지 않게) · 없는 번호면 폴더를 만들지 않는다")
    sd = tempfile.mkdtemp()
    for n in ("장소1_②위반A.csv", "장소1_①정상.csv"):
        with open(os.path.join(sd, n), "w", encoding="utf-8") as f:
            f.write("판,행동,대상,기대,메모\n")
    base = tempfile.mkdtemp()
    cmd = [sys.executable, os.path.join(_DEMO_DIR, "measure_session.py"), "--base", base, "--script-dir", sd,
           "--place", "1", "--kind", "1", "--hand", "1", "--person", "1", "--on", "1"]
    r = subprocess.run(cmd + ["--script", "1"], capture_output=True, text=True)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    info = json.load(open(os.path.join(out, "session.json"), encoding="utf-8")) if out else {}
    check(r.returncode == 0 and os.path.isfile(os.path.join(out, "장소1_①정상.csv"))
          and info.get("입력", {}).get("대본") == "장소1_①정상.csv", f"1 → ①정상 · rc={r.returncode} {r.stderr[-200:]}")
    base2 = tempfile.mkdtemp()
    r = subprocess.run([c if c != base else base2 for c in cmd] + ["--script", "3"], capture_output=True, text=True)
    check(r.returncode != 0 and os.listdir(base2) == [], f"없는 번호 rc={r.returncode} · {os.listdir(base2)}")
    lst = MS.scenario_files(sd)
    check(lst == ["장소1_①정상.csv", "장소1_②위반A.csv"], f"목록 = 이름순 {lst}")


def test_session_marks_dirty_tree():
    print("\n[세션] 코드 버전에 커밋 안 된 변경 여부(리뷰 M-10)")
    rec = MS.write_session(tempfile.mkdtemp(), {"장소": 1}, measure_on=True)
    check(isinstance(rec["코드"].get("Rpi5_변경있음"), bool), f"{rec['코드']}")


if __name__ == "__main__":
    test_dir_name()
    test_session_json()
    test_cli_prints_dir()
    test_voice_off_recorded()
    test_free_space_check_precise()
    test_launcher_bad_input_keeps_window()
    test_launcher_off_ignores_inherited_dir()
    test_script_path_tilde_and_missing()
    test_session_marks_dirty_tree()
    test_launcher_records_glasses_power()
    test_script_by_number()
    test_place3()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        sys.exit(1)
    print("✅ 측정 세션 정보 검증 통과")
