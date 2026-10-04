"""학습 체계 파이 명령(학습/학습.py)의 순수 부분을 고정한다 — 작업 만들기 · 예상 시간·상한 · 걸기 전 막기 · 홈 경로 지우기 · 상태 표시.

실행: python3 Demo/selftest/test_train_cli.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §10 · §11
⚠️ ssh·데스크톱이 필요 없다.
"""
import argparse
import json
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("hakseup_cli", os.path.join(_RPI5, "학습", "학습.py"))
CLI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CLI)

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


SPLIT = {"나눔": "place1_v1", "해시": "abc", "공통": {"val": ["v"], "test": ["t"], "gap": [], "unused": []},
         "button": {"train": ["b1", "b2"], "bg_dropped": []}, "tool": {"train": ["x1"], "bg_dropped": []}}


def _cfg(**kw):
    base = CLI.TC.load_yaml(CLI.HERE / "설정" / "기본.yaml")
    return CLI.TC.resolve(base, {"id": "E3-tool-mosaic05", "group": "tool", "train": {"mosaic": 0.5}, **kw})


def test_작업():
    print("[1] 작업 만들기 — 무리 몫 · 입력 방식 · 원격 경로 · 코드 해시")
    j = CLI.make_job(_cfg(), SPLIT, "abc1234567", 0.65, 1234.0)
    check(j["나눔"]["train"] == ["x1"] and j["나눔"]["test"] == ["t"] and j["나눔"]["해시"] == "abc", "공구 몫")
    check(j["train_kwargs"]["mosaic"] == 0.5 and j["train_kwargs"]["imgsz"] == 640 and j["stretch"] == [640, 640], "학습 인자 · 늘리기")
    check(j["출발"] == "~/학습실험/yolov8n.pt" and j["원본"] == "~/학습실험/원본/place1" and j["코드"] == "~/학습실험/코드/abc1234567", "원격 경로")
    check(j["names"] == ["driver", "wrench", "pliers"] and j["conf"] == 0.65 and j["시간상한_s"] == 1234.0, "이름 · conf · 상한")
    check(CLI.place_of("place1_v1") == "place1" and CLI.place_of("place12_v3") == "place12", "나눔 → 장소")


def test_예상():
    print("[2] 예상 시간 · 실험마다 시간 상한")
    jobs = [{"입력": "늘리기640", "train_kwargs": {"epochs": 200}, "멈춤": {"시간상한_배": 2}}] * 2
    speed = {"늘리기640": {"동시": 2, "s_per_epoch": {"1": 20, "2": 30}}}
    h, lim = CLI.estimate(jobs, speed)
    check(abs(h - 2 * 30 * 200 / 2 / 3600) < 1e-9 and lim == [12000, 12000], f"{h:.3f}시간 · 상한 {lim}")
    try:
        CLI.estimate([{"입력": "원본768x1024", "train_kwargs": {"epochs": 200}, "멈춤": {"시간상한_배": 2}}], speed)
        check(False, "속도표에 없는 입력 → ValueError")
    except ValueError:
        check(True, "속도표에 없는 입력 → ValueError")


def test_걸기_전_막기():
    print("[3] 걸기 전 막기 — 커밋 안 됨 · 같은 id 두 번 · 이미 있는 id")
    check(CLI.launch_problems(["a", "b"], [], [], False) == [], "문제 없음")
    p = CLI.launch_problems(["a", "a", "b"], ["b"], ["c"], True)
    check(len(p) == 3 and "커밋" in p[0] and "두 번" in p[1] and "'b'" in p[2], f"세 가지 — {p}")


def test_홈_경로():
    print("[4] 데스크톱 홈 경로 → ~ (공개 저장소)")
    check(CLI.sanitize("save_dir: /home/abc/학습실험/runs/x\ndata: /home/abc/학습실험/d\n", "/home/abc") == "save_dir: ~/학습실험/runs/x\ndata: ~/학습실험/d\n", "바꿈")
    check(CLI.sanitize("x", "") == "x" and CLI.sanitize("/a", "/") == "/a", "빈 홈 · / 는 그대로")


def test_상태():
    print("[5] 상태 표시 · 끝까지 기다리기 판단")
    now = time.time()
    iso = lambda s: (datetime.now().astimezone() - timedelta(seconds=s)).isoformat(timespec="seconds")
    alive = {"시각": iso(10), "도는중": [{"id": "E0-button-s0", "입력": "늘리기640", "에폭": 37, "최대": 200, "경과분": 22.0, "남은분어림": 30.0, "최근": {}}],
             "대기": ["E0-button-s1"], "멈춤": None, "gpu": {"사용률": 45, "used_mb": 3100, "total_mb": 8151}, "끝남": 2, "끝": False,
             "데스크톱사용가능MB": 21000, "기다리는이유": "데스크톱 메모리 여유 부족(사용 가능 9000MB − 학습 4032MB < 8192MB)"}
    out = CLI.render_status(alive, now)
    check("살아 있음" in out and "E0-button-s0" in out and "37/200" in out and "대기 1" in out, "살아 있음 · 도는 중")
    check(not CLI.finished(alive, now), "도는 중 → 계속 기다림")
    check("데스크톱 사용 가능 20.5GB" in out and "데스크톱 메모리 여유 부족" in out, "데스크톱 메모리 · 기다리는 이유 표시")
    stale = {**alive, "시각": iso(900)}
    check("응답 없음" in CLI.render_status(stale, now) and CLI.finished(stale, now), "15분 응답 없음 → 알림")
    stopped = {**alive, "멈춤": "2026-10-04T01:00:00+09:00 진행없음: E0-button-s0"}
    check("진행없음" in CLI.render_status(stopped, now) and CLI.finished(stopped, now), "멈춤 → 알림")
    check(CLI.finished({**alive, "끝": True}, now) and "없음" in CLI.render_status({}, now), "끝 · 상태 파일 없음")


def test_걸기_직후_상태():
    print("[6] 걸기 직후 — 지난번 「끝」을 믿지 않는다 · 대기열 파일은 다 쓴 뒤 이름을 바꾼다 · 실행기 오류 표시(최종 리뷰 I2)")
    now = time.time()
    old = {"시각": datetime.fromtimestamp(now - 3600).isoformat(timespec="seconds"), "끝": True, "끝남": 10, "대기": []}
    st = CLI.launch_state(old, now)
    check(st is not None and not CLI.finished(st, now) and "시작 중" in CLI.render_status(st, now),
          f"지난번 끝 → 새 상태 「시작 중」 · 끝까지 기다림 — {st}")
    check(CLI.finished(st, now + 700) and "응답 없음" in CLI.render_status(st, now + 700), "실행기가 끝내 안 뜨면 10분 뒤 응답 없음 알림")
    alive = {"시각": datetime.fromtimestamp(now - 5).isoformat(timespec="seconds"), "끝": False, "도는중": []}
    check(CLI.launch_state(alive, now) is None, "도는 실행기 상태는 덮지 않는다")
    check(CLI.launch_state({}, now) is not None, "상태 파일 없음 → 새 상태")
    cmd = CLI.atomic_write_cmd("~/학습실험/대기열/x_E1-button-a.json")
    check(cmd == "cat > ~/학습실험/대기열/x_E1-button-a.json.tmp && mv ~/학습실험/대기열/x_E1-button-a.json.tmp ~/학습실험/대기열/x_E1-button-a.json",
          f"임시 이름(.json.tmp = 실행기 glob *.json 밖)에 쓴 뒤 mv — {cmd}")
    err = {**alive, "끝": True, "오류": "JSONDecodeError"}
    check(CLI.finished(err, now) and "오류" in CLI.render_status(err, now).splitlines()[0], "실행기 오류 → 첫 줄에 오류 · 알림")


def test_사소_고침():
    print("[7] 2단계 전 사소 — 코드 완료 표지 · 나눔 dirty · 빼기 id 검사 · 재개 코드 · 홈 경로 자가 점검(최종 리뷰 M5~M8 · M10)")
    calls, started = [], []
    orig = (CLI.sh, CLI.rsync, CLI.code_state, CLI.start_runner)
    try:
        CLI.sh = lambda cmd, input=None, timeout=120: calls.append(("sh", cmd)) or ""
        CLI.rsync = lambda args, timeout=3600: calls.append(("rsync", args))
        CLI.deploy_code("abc")
        check(any(k == "rsync" for k, _ in calls) and any(k == "sh" and "touch" in c and ".완료" in c for k, c in calls),
              f"코드를 다 보낸 뒤 완료 표지 — {[c for k, c in calls if k == 'sh']}")
        calls.clear()
        CLI.sh = lambda cmd, input=None, timeout=120: calls.append(("sh", cmd)) or ("있음" if "test -f" in cmd and ".완료" in cmd else "")
        CLI.deploy_code("abc")
        check(not any(k == "rsync" for k, _ in calls), "완료 표지가 있으면 건너뜀(표지 없는 반쯤 보낸 폴더는 다시 보냄)")
        calls.clear()
        try:
            CLI.cmd_remove(argparse.Namespace(id="E4*"))
            stopped = False
        except SystemExit:
            stopped = True
        check(stopped and not calls, f"빼기 — id 형식이 아니면 원격에 손대지 않고 멈춤 — {calls}")
        CLI.code_state = lambda: ("h123", False)
        CLI.start_runner = lambda c: started.append(c)
        CLI.cmd_resume(argparse.Namespace())
        check(started == ["h123"], f"재개 = 지금 커밋의 실행기 코드(가장 최근 폴더 아님) — {started}")
        CLI.code_state = lambda: ("h123", True)
        try:
            CLI.cmd_resume(argparse.Namespace())
            stopped = False
        except SystemExit:
            stopped = True
        check(stopped and started == ["h123"], "커밋 안 된 학습 코드면 재개하지 않는다")
    finally:
        CLI.sh, CLI.rsync, CLI.code_state, CLI.start_runner = orig
    check(any(x.startswith("학습/나눔") for x in CLI.DIRTY_PATHS), f"커밋 안 됨 검사에 학습/나눔 — {CLI.DIRTY_PATHS}")
    lk = getattr(CLI, "leaks", lambda x: None)
    check(lk("data: ~/학습실험/x") == [] and lk("a /home/kim/x b") == ["/home/kim"] and lk("p: /mnt/c/Users/kimem/D") == ["/mnt/c/Users/kimem"],
          f"받기 홈 경로 자가 점검 — {lk('a /home/kim/x b')}")


def test_사소_2차():
    print("[8] 2차 리뷰 사소 — 이어서 걸기(id 검사 · 커밋 확인 · 지금 커밋 실행기) · 재개(배포 뒤에 멈춤 해제) · 받기(한 실험 통째 검사 뒤 씀)")
    calls, started, sent = [], [], []
    orig = (CLI.sh, CLI.rsync, CLI.code_state, CLI.start_runner)
    def fake(cmd, input=None, timeout=120):
        calls.append(cmd)
        if cmd.startswith("cat") and "작업.json" in cmd:
            return json.dumps({"id": "E4a-tool-x", "입력": "늘리기640", "코드해시": "old", "코드": "~/학습실험/코드/old"})
        return ""
    try:
        CLI.sh, CLI.rsync = fake, (lambda args, timeout=3600: sent.append(args))
        CLI.start_runner = lambda c: started.append(c)
        CLI.code_state = lambda: ("h123", False)
        try:
            CLI.cmd_launch(argparse.Namespace(이어서="E4*", 설정=[], 확인=False))
            stopped = False
        except SystemExit:
            stopped = True
        check(stopped and not calls, f"이어서 — id 형식이 아니면 원격에 손대지 않고 멈춤 — {calls}")
        CLI.code_state = lambda: ("h123", True)
        try:
            CLI.cmd_launch(argparse.Namespace(이어서="E4a-tool-x", 설정=[], 확인=False))
            stopped = False
        except SystemExit:
            stopped = True
        check(stopped and not started, "이어서 — 커밋 안 된 학습 코드면 걸지 않음")
        CLI.code_state = lambda: ("h123", False)
        calls.clear(); sent.clear()
        CLI.cmd_launch(argparse.Namespace(이어서="E4a-tool-x", 설정=[], 확인=False))
        check(started == ["h123"] and sent, f"이어서 — 실행기는 지금 커밋 코드(배포 뒤) — {started} · 보냄 {len(sent)}")
        calls.clear(); sent.clear(); started.clear()
        CLI.cmd_resume(argparse.Namespace())
        check(started == ["h123"] and sent, f"재개 — 완료 표지가 없으면 코드를 보낸 뒤 실행기 — {started} · 보냄 {len(sent)}")
        calls.clear()
        def boom(args, timeout=3600):
            raise RuntimeError("rsync 실패")
        CLI.rsync = boom
        try:
            CLI.cmd_resume(argparse.Namespace())
        except RuntimeError:
            pass
        check(not any("rm -f" in c and "대기열멈춤" in c for c in calls), f"재개 — 배포가 실패하면 멈춤을 풀지 않음 — {calls}")
    finally:
        CLI.sh, CLI.rsync, CLI.code_state, CLI.start_runner = orig
    wr = getattr(CLI, "write_record", None)
    with tempfile.TemporaryDirectory() as t:
        tmp, dst = Path(t) / "tmp", Path(t) / "dst"
        tmp.mkdir(); dst.mkdir()
        (tmp / "요약.json").write_text('{"id": "x", "save": "/home/abc/학습실험/x"}', encoding="utf-8")
        (tmp / "args.yaml").write_text("project: /mnt/c/Users/kim/runs\n", encoding="utf-8")
        try:
            wr(tmp, dst, "/home/abc", "x") if wr else None
            stopped = False
        except SystemExit:
            stopped = True
        check(wr is not None and stopped and not list(dst.iterdir()), f"받기 — 한 파일이라도 개인 경로가 남으면 그 실험은 아무것도 쓰지 않음 — {[x.name for x in dst.iterdir()]}")
        (tmp / "args.yaml").write_text("project: /home/abc/학습실험/runs\n", encoding="utf-8")
        if wr:
            wr(tmp, dst, "/home/abc", "x")
        check(wr is not None and (dst / "args.yaml").read_text(encoding="utf-8") == "project: ~/학습실험/runs\n" and (dst / "요약.json").exists(), "깨끗하면 홈을 ~ 로 바꿔 씀")


def test_판정_조건():
    print("[9] 판정 — 후보·기준의 운용 조건이 다르면 거부(1-2단계 Review Focus 4)")
    mk = lambda i, stop: ({"id": i, "group": "tool", "조건": {"멈춤": stop}}, {"전체": {"precision": .9}, "클래스": {n: {"recall": .7} for n in ("driver", "wrench", "pliers")}})
    res = [mk(f"E0c-tool-x{i}", {"포화_향상": 0}) for i in range(3)] + [mk(f"E4-tool-y{i}", {"포화_향상": 0.002}) for i in range(3)]
    try:
        CLI.judge_ids(res, [f"E4-tool-y{i}" for i in range(3)], [f"E0c-tool-x{i}" for i in range(3)])
        stopped = False
    except SystemExit:
        stopped = True
    check(stopped, "조건 다름 → 멈춤")


def test_탐색_설정():
    print("[10] 탐색 설정 — 이름 형식 · 범위 종류 · 동시 개수 · 기준 id")
    tmpl = {"id": "E8-tool-T1t000", "group": "tool", "train_kwargs": {}, "설정": {}}
    tc = {"이름": "T1", "group": "tool", "범위": {"lr0": ["log", 0.0002, 0.003]}, "횟수": 30, "기준": ["E0c-tool-f120"]}
    c = CLI.tune_config(tc, tmpl, "abc123", 2)
    check(c["이름"] == "T1" and c["동시"] == 2 and c["코드"].endswith("/코드/abc123") and c["시작무작위"] == 10
          and c["기준"] == ["E0c-tool-f120"], f"{c}")
    for bad in ({**tc, "이름": "T 1"}, {**tc, "범위": {"lr0": ["lin", 0, 1]}}, {**tc, "기준": []}):
        try:
            CLI.tune_config(bad, tmpl, "abc123", 2)
            stopped = False
        except SystemExit:
            stopped = True
        check(stopped, f"막음 — {bad.get('이름')} {bad.get('범위')} {bad.get('기준')}")


def test_받기_검증채점():
    print("[11] 받기 — 검증 몫 채점(채점_검증.json)도 가져온다(탐색 목표값의 근거)")
    with tempfile.TemporaryDirectory() as t:
        tmp, dst = Path(t) / "tmp", Path(t) / "dst"
        tmp.mkdir()
        (tmp / "요약.json").write_text('{"id": "x"}', encoding="utf-8")
        (tmp / "채점_검증.json").write_text('{"전체": {}}', encoding="utf-8")
        CLI.write_record(tmp, dst, "/home/abc", "x")
        check((dst / "채점_검증.json").exists(), f"가져옴 — {[x.name for x in dst.iterdir()]}")


def test_작업_세션몫():
    print("[w-s] 작업 — 나눔의 세션 보류 몫을 싣고, 없는 판은 빈 목록 · 받기가 채점_세션.json 도 가져옴")
    check(CLI.make_job(_cfg(), SPLIT, "abc1234567", 0.65, 1.0)["나눔"]["test_session"] == [], "없는 판 → []")
    sp2 = json.loads(json.dumps(SPLIT))
    sp2[_cfg()["group"]]["test_session"] = ["s1"]
    check(CLI.make_job(_cfg(), sp2, "abc1234567", 0.65, 1.0)["나눔"]["test_session"] == ["s1"], "있는 판 → 실림")
    check("채점_세션.json" in CLI.RECORD, "받기 RECORD 에 채점_세션.json")


def test_세션_채점_판정():
    print("[j2] 판정 --채점 세션 — 채점_세션.json 만 읽고, 하나라도 없으면 멈춤(1-3 Review Focus 3)")
    sc = {"전체": {"precision": .9, "recall": .9}, "클래스": {n: {"recall": .9} for n in ("B1", "B2", "B3", "B4", "EMO")}}
    base = ["E15-button-base", "E15-button-bases1", "E15-button-bases2"]
    cand = ["E16-button-color", "E16-button-colors1", "E16-button-colors2"]
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        for i in base + cand:
            d = root / i
            d.mkdir()
            (d / "요약.json").write_text(json.dumps({"id": i, "group": "button", "나눔": {"해시": "h"}, "conf": 0.65, "판": {}}), encoding="utf-8")
            (d / "설정.json").write_text(json.dumps({"멈춤": {"포화_향상": 0}}), encoding="utf-8")
            (d / "채점.json").write_text(json.dumps(sc), encoding="utf-8")
            if i != cand[-1]:
                (d / "채점_세션.json").write_text(json.dumps(sc), encoding="utf-8")
        _, ok = CLI.judge_ids(CLI.ledger.load_results(root), cand, base)
        check(ok is False, "기본 = 채점.json 으로 판정(같은 값 → 기각)")
        try:
            CLI.judge_ids(CLI.ledger.load_results(root, "채점_세션.json"), cand, base)
            stopped = False
        except SystemExit:
            stopped = True
        check(stopped, "세션 채점이 하나라도 없으면 멈춤")


if __name__ == "__main__":
    test_작업()
    test_예상()
    test_걸기_전_막기()
    test_홈_경로()
    test_상태()
    test_걸기_직후_상태()
    test_사소_고침()
    test_사소_2차()
    test_판정_조건()
    test_탐색_설정()
    test_받기_검증채점()
    test_작업_세션몫()
    test_세션_채점_판정()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for x in _fails:
            print(f"   - {x}")
        sys.exit(1)
    print("✅ 학습 체계 파이 명령 검증 통과")
