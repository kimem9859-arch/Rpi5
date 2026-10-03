"""학습 체계 파이 명령(학습/학습.py)의 순수 부분을 고정한다 — 작업 만들기 · 예상 시간·상한 · 걸기 전 막기 · 홈 경로 지우기 · 상태 표시.

실행: python3 Demo/selftest/test_train_cli.py
정본 설계: 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §10 · §11
⚠️ ssh·데스크톱이 필요 없다.
"""
import importlib.util
import os
import sys
import time
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
             "대기": ["E0-button-s1"], "멈춤": None, "gpu": {"사용률": 45, "used_mb": 3100, "total_mb": 8151}, "끝남": 2, "끝": False}
    out = CLI.render_status(alive, now)
    check("살아 있음" in out and "E0-button-s0" in out and "37/200" in out and "대기 1" in out, "살아 있음 · 도는 중")
    check(not CLI.finished(alive, now), "도는 중 → 계속 기다림")
    stale = {**alive, "시각": iso(900)}
    check("응답 없음" in CLI.render_status(stale, now) and CLI.finished(stale, now), "15분 응답 없음 → 알림")
    stopped = {**alive, "멈춤": "2026-10-04T01:00:00+09:00 진행없음: E0-button-s0"}
    check("진행없음" in CLI.render_status(stopped, now) and CLI.finished(stopped, now), "멈춤 → 알림")
    check(CLI.finished({**alive, "끝": True}, now) and "없음" in CLI.render_status({}, now), "끝 · 상태 파일 없음")


if __name__ == "__main__":
    test_작업()
    test_예상()
    test_걸기_전_막기()
    test_홈_경로()
    test_상태()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for x in _fails:
            print(f"   - {x}")
        sys.exit(1)
    print("✅ 학습 체계 파이 명령 검증 통과")
