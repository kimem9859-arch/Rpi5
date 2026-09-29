"""공구 초벌 반복 학습 한 라운드 — 학습 데이터 만들기 → 출발 가중치마다 학습 → 떼어 둔 사진 관문 → 고르기 → 저장.

실행(Demo/ 에서, rfenv): ~/env/rfenv/bin/python test/train_tool_round.py [--group tool|button] --data ~/data/label_dataset/place1 --round N \\
    --start <작은 모델부터 · 가중치 …> --current <공구 = 가중치 · 버튼 = console_v2 또는 가중치> [--template <정지 세션>(버튼)] \\
    [--backend colab|cpu] [--exclude 뺄이름.txt] [--epochs 50] [--probe]
--group button(spec 2026-09-29-버튼초벌-반복학습) = 버튼 5종 · 관문은 초벌 + 기계 검토(gate_button.py · 시스템 python3 · 지금 방식은 Hailo).
--backend colab(기본) = 학습만 Colab T4 — 파이가 colab CLI 로 빌리기·올리기·학습·받기·반납(설계 §5 개정). 관문·고르기는 파이.
  🔴 Colab CLI 함정(저널 §12.41-(6)) — 토큰 1시간 · exec 는 예외에도 종료 코드 0(표지로 판단) · 저장 경로는 표지에서 · stop 필수.
  🔴 올리기 전에 개인정보 관문을 거친다 — 뺄 사진은 --exclude · 통과한 사진은 --cleared(누적 목록)에 있어야 올린다(설계 §5).
출력: <work>/<group>_r<N>/(학습 폴더 · runs/ · 버튼 관문 초벌 JSON) · <models>/<group>_r<N>.pt(채택했을 때만) · <models>/<group>_r<N>.json(항상)
--probe = 첫 출발 가중치로 1 에폭만 돌려 시간을 잰다(<work>/<group>_r<N>_probe · 저장·채택 없음) — 설계 §5
정본 설계 = 상위 docs/superpowers/specs/2026-09-28-공구초벌-반복학습-design.md
🔴 config 를 import 하지 않는다(prelabel_tools 와 같은 이유). 🔴 결과 모델을 Demo/models/ 에 두지 않는다(설계 §7).
"""
import argparse
import datetime
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tool_round as TR          # noqa: E402

CONF = 0.25                      # 공구 — 초벌과 같은 점수 기준(설계 §6)
BUTTON_CONF = 0.50               # 버튼 — config.YOLO_CONF_LOW 와 같아야 한다(시험 [21] · spec 2026-09-29 §6). rfenv 는 config 를 못 읽는다
HOURS_PER_START = 1.4            # 파이 CPU — 출발점마다 시간 상한(두 출발점이 한 라운드 3시간 안 · 설계 §1)
COLAB_EXEC_MIN = 48              # Colab — 원격 실행 전체 상한. 빌리기·올리기 약 3분 + 받기 약 1분을 더해 프록시 토큰 1시간 안
#   (spec 2026-09-29 §5 — 큰 출발점 yolo26s 여유로 40 → 48). ultralytics 의 time 인자는 에폭 수를 덮어써 그 시간을 다 채우므로
#   Colab 에서는 쓰지 않고 에폭 수로만 멈춘다.
SYS_PYTHON = "/usr/bin/python3"  # 버튼 관문의 기계 검토 — 시스템 python3(Hailo · cv2). rfenv 에는 Hailo 가 없다
UL_VERSION = "8.4.117"           # 원격 ultralytics — 파이 rfenv 와 같게(받은 가중치를 파이에서 읽는다)
COLAB = shutil.which("colab") or str(Path.home() / ".local/bin/colab")


def colab(*args, timeout):
    return subprocess.run([COLAB, *args], capture_output=True, text=True, timeout=timeout)


def preflight(a, models):
    """데이터를 만들기 전에 멈출 것(비면 통과). 라운드 파일 이름에 무리를 붙인다 — 공구·버튼이 서로 막거나 덮어쓰지 않게."""
    out = []
    group = getattr(a, "group", "tool")
    if a.probe and a.backend != "cpu":
        out.append("--probe 는 cpu 에서만 — colab 에서는 그대로 전체 학습·채택으로 흘러간다")
    if not a.probe:
        for f in (models / f"{group}_r{a.round}.pt", models / f"{group}_r{a.round}.json"):
            if f.exists():
                out.append(f"이미 있다: {f} — 라운드 모델·기록을 덮어쓰지 않는다")
    cur = getattr(a, "current", None)          # 관문 입력은 학습(Colab 수십 분) 전에 확인한다(최종 리뷰 중요 1)
    if cur is not None and not (group == "button" and cur == "console_v2") and not Path(cur).expanduser().is_file():
        out.append(f"--current 가 없다: {cur} — 공구 = 가중치 파일 · 버튼 = console_v2 또는 가중치 파일")
    if group == "button":
        t = getattr(a, "template", None)
        if not t or not Path(t).expanduser().is_dir() or not any(Path(t).expanduser().glob("f*.png")):
            out.append(f"--group button 은 --template(배치 틀 정지 세션 폴더 · f*.png)이 필요하다 — 없거나 사진이 없다: {t}")
    return out


def _release(session):
    """반납 — 실패해도 예외를 올리지 않고 크게 알린다(받은 결과를 잃지 않게). 서버에 남았는지도 확인한다."""
    try:
        r = colab("stop", "-s", session, timeout=300)
        if r.returncode != 0:
            print(f"⚠️ 반납 실패 — `colab stop -s {session}` 을 직접: {(r.stdout + r.stderr)[-200:]}")
        left = colab("sessions", timeout=120)
        if session in (left.stdout or ""):
            print(f"🔴 세션 {session} 이 아직 서버에 있다 — `colab stop -s {session}` 을 직접(중단 규칙)")
    except Exception as e:
        print(f"🔴 반납 확인 못 함({type(e).__name__}) — `colab sessions` 로 확인하고 `colab stop -s {session}`(중단 규칙)")


def train_colab(starts, ds, epochs, session, group="tool"):
    """Colab T4 에서 출발점마다 학습하고 last.pt 를 받는다. 반환 = ({이름: (파이 경로, 분)}, 표지, 로그 경로).
    GPU 를 못 빌리면 종료(중단 규칙 — 묻는다). 빌리기부터 무엇이 실패해도(시간 초과 포함) finally 에서 반납한다."""
    parts = TR.pack_parts(ds, ds.parent / f"{ds.name}_up", "/content", group=group)
    print(f"묶음 조각 {len(parts)}개 · {sum(p.stat().st_size for p in parts) / 1e6:.0f}MB")
    rstarts = [(Path(s).stem, f"/content/{Path(s).name}") for s in starts]
    script = ds.parent / f"{ds.name}_remote.py"
    script.write_text(TR.remote_script(ds.name, rstarts, epochs, None, UL_VERSION, [p.name for p in parts]), encoding="utf-8")
    t0 = time.time()
    log_path = ds / "colab_log.txt"
    out = {}
    try:
        r = colab("new", "-s", session, "--gpu", "T4", timeout=900)
        if r.returncode != 0:
            sys.exit(f"🔴 T4 를 못 빌렸다 — 멈추고 묻는다(설계 §5)\n{(r.stdout + r.stderr)[-500:]}")
        for local, remote in [(p, f"/content/{p.name}") for p in parts] + [(Path(s), rp) for s, (_, rp) in zip(starts, rstarts)]:
            r = colab("upload", "-s", session, str(local), remote, timeout=1800)
            if r.returncode != 0:
                raise RuntimeError(f"올리기 실패 {local.name}: {(r.stdout + r.stderr)[-300:]}")
        print(f"올리기 끝 {(time.time() - t0) / 60:.1f}분")
        limit = COLAB_EXEC_MIN * 60
        r = colab("exec", "-s", session, "-f", str(script), "--timeout", str(limit), timeout=limit + 300)
        log = r.stdout + r.stderr
        log_path.write_text(log, encoding="utf-8")
        mk = TR.parse_markers(log)
        print(f"원격 학습 끝 {(time.time() - t0) / 60:.1f}분 · 설치 {'OK' if mk['setup_ok'] else '실패'} · 끝남 {list(mk['done'])} · 실패 {mk['fail']}")
        for stem, _ in rstarts:
            if stem not in mk["done"]:
                continue
            local = ds / "runs" / stem / "last.pt"; local.parent.mkdir(parents=True, exist_ok=True)
            r = colab("download", "-s", session, f"{mk['done'][stem]['dir']}/weights/last.pt", str(local), timeout=900)
            if r.returncode == 0 and local.exists():
                out[stem] = (local, mk["done"][stem]["minutes"])
            else:
                print(f"받기 실패 {stem}: {(r.stdout + r.stderr)[-300:]}")
        print(f"받기 끝 {(time.time() - t0) / 60:.1f}분(토큰 1시간 안이어야 한다)")
        return out, mk, log_path
    finally:
        _release(session)


def train(start, ds, name, epochs, hours):
    from ultralytics import YOLO
    t = time.time()
    # val=False — 학습 중 성적 재기(가장 좋은 에폭 고르기·일찍 멈추기)에 떼어 둔 사진을 쓰지 않는다. 그 사진은 관문 채점에만 쓴다(설계 §4).
    # 그래서 마지막 에폭 모델(last.pt)을 쓰고, 시간은 time 상한이 지킨다.
    YOLO(str(start)).train(data=str(ds / "data.yaml"), imgsz=640, epochs=epochs, time=hours, val=False,
                           device="cpu", workers=2, batch=8, project=str(ds / "runs"), name=name, exist_ok=False,
                           plots=False, verbose=False)
    return ds / "runs" / name / "weights" / "last.pt", (time.time() - t) / 60


def gate(model_path, ds):
    """떼어 둔 사진에서 잡은 수·가짜·놓침 — 번호가 아니라 이름으로 짝짓는다(다른 공구 모델의 이름 표기 대비)."""
    from ultralytics import YOLO
    m = YOLO(str(model_path))
    tot = {"caught": 0, "fake": 0, "missed": 0}
    for p in sorted((ds / "images" / "val").iterdir()):
        r = m.predict(str(p), conf=CONF, imgsz=640, verbose=False)[0]
        h, w = r.orig_shape
        preds = [(TR.tool_index(r.names[int(c)]), b) for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist())]
        preds = [x for x in preds if x[0] is not None]
        truths = TR.yolo_to_boxes((ds / "labels" / "val" / (p.stem + ".txt")).read_text(encoding="utf-8").splitlines(), w, h)
        tot = TR.add_counts(tot, TR.match_counts(preds, truths))
    return tot


class GateFailed(RuntimeError):
    """버튼 관문 도구(시스템 python3)가 실패했다 — 학습한 가중치·초벌 JSON 은 남아 있다(기록을 남기고 멈추려고)."""


def gate_button(weights, ds, template, current):
    """버튼 관문(spec 2026-09-29 §7) — 후보마다 떼어 둔 사진·배치 틀 사진의 초벌을 여기(rfenv)서 JSON 으로 만들고,
    기계 검토·대조는 시스템 python3 의 gate_button.py 가 한다(지금 방식 console_v2 는 Hailo).
    weights = {이름: 가중치} · current = "console_v2" 또는 가중치. 반환 = (후보 셈, 지금 셈)."""
    import prelabel_tools as PT
    vp, tp = TR.gate_paths(ds, template)
    args = []
    for name, w in weights.items():
        j = ds / f"dets_{name}.json"
        j.write_text(json.dumps(PT.predict_boxes(str(w), vp + tp, BUTTON_CONF), ensure_ascii=False), encoding="utf-8")
        args += ["--cand", f"{name}={j}"]
    if current == "console_v2":
        args += ["--current", "console_v2"]
    else:
        j = ds / "dets_current.json"
        j.write_text(json.dumps(PT.predict_boxes(str(current), vp + tp, BUTTON_CONF), ensure_ascii=False), encoding="utf-8")
        args += ["--current", f"current={j}"]
    out = ds / "gate_button.json"
    ds_abs, tpl_abs = str(Path(ds).expanduser().resolve()), str(Path(template).expanduser().resolve())   # 하위 프로세스 cwd 는 Demo — 상대 경로가 다른 곳을 가리키지 않게
    try:
        subprocess.run([SYS_PYTHON, str(HERE / "gate_button.py"), "--ds", ds_abs, "--template", tpl_abs, *args,
                        "--out", str(out)], check=True, cwd=str(HERE.parent))
    except subprocess.CalledProcessError as e:
        raise GateFailed(f"버튼 관문 도구 실패(종료 코드 {e.returncode} · Hailo 사용 중 등) — 초벌 JSON 은 {ds} 에 남아 있어 "
                         f"gate_button.py 를 손으로 다시 돌릴 수 있다") from e
    g = json.loads(out.read_text(encoding="utf-8"))
    return g["cands"], g["current"]


def _sha16(p):
    import hashlib
    return hashlib.sha256(Path(p).expanduser().read_bytes()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--start", nargs="+", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--backend", choices=("colab", "cpu"), default="colab")
    ap.add_argument("--exclude", help="개인정보 관문에서 뺀 사진 이름(한 줄에 하나)")
    ap.add_argument("--cleared", default="~/data/label_train/privacy_cleared.txt",
                    help="개인정보 관문을 통과한 사진 이름(누적 · 한 줄에 하나) — colab 에 올릴 사진은 전부 여기 있어야 한다")
    ap.add_argument("--work", default="~/data/label_train")
    ap.add_argument("--models", default="~/data/label_models")
    ap.add_argument("--group", choices=("tool", "button"), default="tool",
                    help="tool = 공구 3종(tool_rN) · button = 버튼 5종(button_rN · spec 2026-09-29) — --start 는 작은 모델부터")
    ap.add_argument("--template", help="버튼 관문의 배치 틀 정지 세션 폴더(--group button 에 필요)")
    a = ap.parse_args()
    models = Path(a.models).expanduser()
    if TR.is_demo_models(models, HERE.parent / "models"):
        sys.exit("🔴 결과 모델을 Demo/models 에 두지 않는다(설계 §7)")
    probs = preflight(a, models)
    excl = set(Path(a.exclude).read_text(encoding="utf-8").split()) if a.exclude else set()
    if a.backend == "colab":
        names = [l.split("\t", 1)[0] for l in (Path(a.data).expanduser() / "images.txt").read_text(encoding="utf-8").splitlines() if "\t" in l]
        cp = Path(a.cleared).expanduser()
        cleared = set(cp.read_text(encoding="utf-8").split()) if cp.exists() else set()
        probs += TR.privacy_problems(names, excl, cleared)
    if probs:
        sys.exit("🔴 시작 전 확인에서 멈춘다(데이터를 만들지 않았다)\n" + "\n".join(f"  - {m}" for m in probs))
    kind = "공구" if a.group == "tool" else "버튼"
    ds = Path(a.work).expanduser() / (f"{a.group}_r{a.round}" + ("_probe" if a.probe else ""))
    info = TR.build_dataset(a.data, ds, exclude=excl, group=a.group)
    print(f"학습 {len(info['train'])}장({kind} {info['boxes']['train']}) · 떼어 둔 {len(info['val'])}장({kind} {info['boxes']['val']})")
    if a.probe and a.backend == "cpu":
        _, minutes = train(a.start[0], ds, "probe", 1, None)
        print(f"1 에폭 {minutes:.1f}분 → 예상 {minutes * a.epochs * len(a.start):.0f}분"
              f"(출발 {len(a.start)} × {a.epochs} 에폭 · 시간 상한 전 · 1 에폭 값은 학습 중 성적 재기 포함)")
        return
    rec = {"group": a.group, "round": a.round, "data": str(Path(a.data).expanduser()),
           "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "train": info["train"], "val": info["val"], "boxes": info["boxes"], "epochs": a.epochs, "val_during_train": False,
           "backend": a.backend, "excluded": sorted(excl), "conf": CONF if a.group == "tool" else BUTTON_CONF,
           "template": a.template, "starts": {},
           "hours_per_start": None if a.backend == "colab" else HOURS_PER_START,
           "colab_exec_min": COLAB_EXEC_MIN if a.backend == "colab" else None}
    if a.backend == "colab":
        got, mk, log_path = train_colab(a.start, ds, a.epochs, f"{a.group}-r{a.round}", group=a.group)
        rec["colab"] = {"log": str(log_path), **mk}
    cands, bests = {}, {}
    for s in a.start:
        name = Path(s).stem
        if a.backend == "colab":
            if name not in got:
                why = mk["fail"].get(name) or ("설치·풀기 실패" if not mk["setup_ok"] else "표지 없음(시간 초과 등) 또는 받기 실패")
                rec["starts"][name] = {"weights": s, "failed": why}
                print(f"[{name}] ❌ 학습·받기 실패 — {why}"); continue
            best, minutes = got[name]
        else:
            best, minutes = train(s, ds, name, a.epochs, HOURS_PER_START)
        rec["starts"][name] = {"weights": s, "sha256_16": _sha16(s), "best": str(best), "minutes": round(minutes, 1)}
        bests[name] = best
        if a.group == "tool":
            c = gate(best, ds); cands[name] = c
            rec["starts"][name].update(c, net=TR.net(c))
            print(f"[{name}] {minutes:.0f}분 · 떼어 둔 사진: 잡음 {c['caught']} · 가짜 {c['fake']} · 놓침 {c['missed']} · 순이익 {TR.net(c)}")
    cur = None
    if a.group == "button" and bests:
        try:
            bc, cur = gate_button(bests, ds, a.template, a.current)
        except GateFailed as e:
            models.mkdir(parents=True, exist_ok=True)
            rec.update(status="관문 실패", chosen=None, model=None, error=str(e))
            (models / f"{a.group}_r{a.round}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            sys.exit(f"🔴 {e} · 학습한 가중치 = 기록 JSON 의 starts[*].best")
        for name, c in bc.items():
            if "error" in c:
                rec["starts"][name]["failed"] = c["error"]
                print(f"[{name}] ❌ 관문 못 함 — {c['error']}"); continue
            cands[name] = c; rec["starts"][name].update(c)
            print(f"[{name}] {rec['starts'][name]['minutes']:.0f}분 · 떼어 둔 사진: 사람 몫 {c['work']}"
                  f"(확인 {c['check']} · 제안 {c['propose']} · 새로 {c['added']}) · 가짜 {c['fake']} · 기계 확정 틀림 {c['auto_wrong']}")
    models.mkdir(parents=True, exist_ok=True)
    rec_path = models / f"{a.group}_r{a.round}.json"
    if not cands:
        rec.update(status="학습 실패", chosen=None, model=None)
        rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        sys.exit("🔴 학습 실패 — 후보가 하나도 없다(관문 패배가 아니다) · 기록 JSON 참조")
    if a.group == "tool":
        cur = gate(a.current, ds)
        rec["current"] = {"weights": a.current, **cur, "net": TR.net(cur)}
        print(f"[지금 {Path(a.current).stem}] 잡음 {cur['caught']} · 가짜 {cur['fake']} · 놓침 {cur['missed']} · 순이익 {TR.net(cur)}")
        status, chosen = TR.decide(cands, cur)
    else:
        rec["current"] = {"weights": a.current, **cur}
        print(f"[지금 {a.current}] 사람 몫 {cur['work']}(확인 {cur['check']} · 제안 {cur['propose']} · 새로 {cur['added']})"
              f" · 가짜 {cur['fake']} · 기계 확정 틀림 {cur['auto_wrong']}")
        status, chosen = TR.decide(cands, cur, chooser=TR.pick_button)
    rec["status"], rec["chosen"] = status, chosen
    if chosen:
        dst = models / f"{a.group}_r{a.round}.pt"
        shutil.copy2(rec["starts"][chosen]["best"], dst)
        rec["model"] = str(dst)
        print(f"✅ 채택 {chosen} → {dst}")
    else:
        rec["model"] = None
        print("❌ 관문 패배 — 지금 모델을 계속 쓴다")
    rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
