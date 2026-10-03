"""학습 체계 파이 명령 — 데스크톱 GPU(ssh wsl-train)에 실험을 걸고 결과를 받는다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §10 · §11
실행(Rpi5 에서 · 시스템 python3): python3 학습/학습.py <명령> …
  준비 --나눔 place1_v1 [--채점 <목록>]     나눔 파일(없으면 만들기 · 있으면 그대로) → 원본 사진·라벨을 데스크톱으로(바뀐 것만)
  속도재기 --입력 늘리기640|원본768x1024     첫 속도 측정을 데스크톱에 띄운다(실험이 없을 때)
  걸기 <설정.yaml …> [--확인]                대기열에 넣고 실행기를 띄운다(예상 24시간 넘으면 --확인 필요)
  걸기 --이어서 <id>                          끊긴 실험을 last.pt 에서 이어서
  상태 [--끝까지 <분>]                        실행기 상태 · --끝까지 = 끝·멈춤·응답 없음까지 그 간격으로 기다린다
  받기                                         끝난 실험의 기록·best.pt 를 받아 해시를 맞추고 장부를 다시 만든다
  재개                                         대기열 멈춤을 풀고 실행기를 띄운다 — 멈춘 이유를 정한 뒤에만
  빼기 <id>                                    대기열에서 뺀다(건너뛰기)
🔴 코드·설정이 커밋되지 않았으면 걸지 않는다 — 결과의 코드 해시가 저장소를 가리켜야 한다.
🔴 대기열이 멈춰 있으면 걸기는 넣기만 하고 실행기를 띄우지 않는다.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RPI5 = HERE.parent
for _p in (HERE, RPI5 / "Demo" / "test", RPI5 / "Demo"):
    sys.path.insert(0, str(_p))
import ledger          # noqa: E402
import split as SP     # noqa: E402
import stoprules       # noqa: E402
import tool_round as TR  # noqa: E402
import trainconf as TC  # noqa: E402

REMOTE = "wsl-train"
RROOT = "~/학습실험"
SRC = Path.home() / "data" / "label_dataset"
LOCAL = Path.home() / "data" / "학습실험"
CODE_FILES = ["train_one.py", "runner.py", "stoprules.py", "scoring.py", "speedprobe.py"]
DIRTY_PATHS = ["학습/*.py", "학습/설정", "Demo/test/score_lib.py", "Demo/test/tool_round.py"]
RECORD = ["요약.json", "채점.json", "설정.json", "args.yaml", "results.csv", "results.png",
          "confusion_matrix.png", "confusion_matrix_normalized.png"]
SKIP = ("E9-", "SPEED-")
DEFAULT_TEST = RPI5 / "조사" / "재학습확인-20261003" / "채점사진.txt"


# ── 순수 함수(시험 대상) ─────────────────────────────────────────────
def place_of(split_name):
    return split_name.rsplit("_", 1)[0]


def make_job(cfg, d, head, conf, time_limit):
    tr, va, te = SP.lists_for(d, cfg["group"])
    mode = TC.INPUT_MODES[cfg["입력"]]
    return {"id": cfg["id"], "group": cfg["group"], "입력": cfg["입력"], "바꾼것": cfg["바꾼것"],
            "names": TC.GROUP_NAMES[cfg["group"]], "conf": conf, "train_kwargs": TC.train_kwargs(cfg),
            "predict_imgsz": mode["predict_imgsz"], "stretch": mode["stretch"], "멈춤": cfg["멈춤"],
            "출발": f"{RROOT}/{cfg['출발']}", "원본": f"{RROOT}/원본/{place_of(cfg['나눔'])}", "루트": RROOT,
            "나눔": {"name": d["나눔"], "해시": d["해시"], "train": tr, "val": va, "test": te},
            "코드": f"{RROOT}/코드/{head}", "코드해시": head, "시간상한_s": time_limit, "설정": cfg}


def estimate(jobs, speed):
    """→ (예상 총 시간(시) · 실험마다 시간 상한(초)). 속도표에 그 입력 방식이 없으면 ValueError."""
    total, limits = 0.0, []
    for j in jobs:
        sp = speed.get(j["입력"])
        if not sp:
            raise ValueError(f"속도표에 {j['입력']} 가 없다 — 먼저 `속도재기 --입력 {j['입력']}`")
        n = int(sp["동시"])
        spe = float(sp["s_per_epoch"][str(n)])
        ep = j["train_kwargs"]["epochs"]
        total += spe * ep / n
        limits.append(stoprules.time_limit_s(spe, ep, j["멈춤"]["시간상한_배"]))
    return total / 3600, limits


def launch_problems(ids, local_done, remote_known, dirty):
    out = []
    if dirty:
        out.append("코드·설정이 커밋되지 않았다 — 커밋한 뒤에 건다")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        out.append(f"같은 id 를 두 번 걸었다: {dup}")
    seen = sorted(set(ids) & (set(local_done) | set(remote_known)))
    if seen:
        out.append(f"이미 있는 id: {seen} — 새 id 로")
    return out


def sanitize(text, home):
    return text.replace(home, "~") if home and home != "/" else text


def _age(st, now):
    return now - datetime.fromisoformat(st["시각"]).timestamp()


def finished(st, now):
    return bool(not st or st.get("끝") or st.get("멈춤") or _age(st, now) > 600)


def render_status(st, now):
    if not st:
        return "상태 파일 없음 — 아직 걸지 않았다"
    age = _age(st, now)
    if st.get("끝"):
        head = "실행기 끝남(대기열이 비었거나 멈춤)"
    elif age > 120:
        head = f"🔴 실행기 응답 없음 — 마지막 {age / 60:.0f}분 전 · 데스크톱·WSL 확인(다시 뜨면 「끊김」으로 기록된다)"
    else:
        head = f"실행기 살아 있음({age:.0f}초 전)"
    g = st.get("gpu")
    w = st.get("데스크톱사용가능MB")
    lines = [head + (f" · GPU {g['사용률']}% {g['used_mb'] / 1024:.1f}/{g['total_mb'] / 1024:.1f}GB" if g else "")
             + (f" · 데스크톱 사용 가능 {w / 1024:.1f}GB" if w is not None else "")
             + f" · 끝남 {st.get('끝남', 0)} · 대기 {len(st.get('대기', []))}"]
    for r in st.get("도는중", []):
        last = r.get("최근") or {}
        lines.append(f"  도는 중 {r['id']} · {r['입력']} · 에폭 {r['에폭']}/{r['최대']} · {r['경과분']:.0f}분"
                     + (f" · 남은 약 {r['남은분어림']:.0f}분" if r.get("남은분어림") is not None else "")
                     + (f" · 검증 mAP50 {last['metrics/mAP50(B)']:.3f}" if last.get("metrics/mAP50(B)") is not None else ""))
    if st.get("기다리는이유") and not st.get("끝"):
        lines.append(f"  기다리는 이유: {st['기다리는이유']}")
    if st.get("멈춤"):
        lines.append(f"  ⏸ 대기열 멈춤: {st['멈춤']} — 이어서 / 바꿔서 / 건너뛰기를 정한 뒤 `재개`")
    return "\n".join(lines)


# ── 원격 · 파일 ────────────────────────────────────────────────────
def sh(cmd, input=None, timeout=120):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", REMOTE, cmd], input=input, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.exit(f"🔴 원격 명령 실패({r.returncode}): {cmd}\n{r.stderr[-500:]}")
    return r.stdout


def rsync(args, timeout=3600):
    r = subprocess.run(["rsync", "-rLt", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.exit(f"🔴 rsync 실패: {' '.join(args)}\n{r.stderr[-500:]}")


def code_state():
    git = ["git", "-C", str(RPI5)]
    head = subprocess.run([*git, "rev-parse", "--short=10", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run([*git, "status", "--porcelain", "--", *DIRTY_PATHS], capture_output=True, text=True).stdout.strip()
    return head, bool(dirty)


def op_conf(group):
    import config
    return {"button": config.YOLO_CONF_HIGH, "tool": config.TOOL_CONF}[group]


def read_index(src):
    return {k: v for k, v in (l.split("\t", 1) for l in (src / "images.txt").read_text(encoding="utf-8").splitlines() if "\t" in l)}


def remote_json(path, default):
    raw = sh(f"cat {path} 2>/dev/null || true").strip()
    return json.loads(raw) if raw else default


def deploy_code(head):
    if sh(f"test -d {RROOT}/코드/{head} && echo 있음 || true").strip():
        return
    sh(f"mkdir -p {RROOT}/코드/{head}")
    rsync([*(str(HERE / f) for f in CODE_FILES), str(RPI5 / "Demo" / "test" / "score_lib.py"), f"{REMOTE}:{RROOT}/코드/{head}/"])


def start_runner(code_dir):
    sh(f"cd {RROOT} && ( setsid nohup venv/bin/python 코드/{code_dir}/runner.py --루트 {RROOT} >> 실행기.log 2>&1 < /dev/null & )")


# ── 명령 ───────────────────────────────────────────────────────────
def cmd_prepare(a):
    place = place_of(a.나눔)
    src = SRC / place
    idx = read_index(src)
    sp_path = HERE / "나눔" / f"{a.나눔}.json"

    def labels_of(n, g):
        return TR.group_lines((src / "labels" / f"{n}.txt").read_text(encoding="utf-8").splitlines(), g)

    if not sp_path.exists():
        test = [l.strip() for l in Path(a.채점).read_text(encoding="utf-8").splitlines() if l.strip()]
        SP.save_split(SP.make_split(a.나눔, sorted(idx), test, labels_of), sp_path)
        print(f"나눔 {a.나눔} 을 만들었다")
    d = SP.load_split(sp_path)
    need = sorted(set(d["button"]["train"]) | set(d["tool"]["train"]) | set(d["공통"]["val"]) | set(d["공통"]["test"]))
    stage = LOCAL / "stage" / place
    for sub in ("images", "labels8", "labels_button", "labels_tool"):
        (stage / sub).mkdir(parents=True, exist_ok=True)
    for n in need:
        img = stage / "images" / f"{n}.png"
        if not img.is_symlink():
            img.symlink_to(idx[n])
        lines = [x for x in (src / "labels" / f"{n}.txt").read_text(encoding="utf-8").splitlines() if x.strip()]
        (stage / "labels8" / f"{n}.txt").write_text("".join(x + "\n" for x in lines), encoding="utf-8")
        for g in SP.GROUPS:
            (stage / f"labels_{g}" / f"{n}.txt").write_text("".join(x + "\n" for x in TR.group_lines(lines, g)), encoding="utf-8")
    sh(f"mkdir -p {RROOT}/원본/{place} {RROOT}/나눔")
    rsync([f"{stage}/", f"{REMOTE}:{RROOT}/원본/{place}/"])
    rsync([str(sp_path), f"{REMOTE}:{RROOT}/나눔/"])
    print(f"나눔 {d['나눔']} · 해시 {d['해시']} · 보낸 사진 {len(need)}"
          f" · 학습 버튼 {len(d['button']['train'])} · 공구 {len(d['tool']['train'])}"
          f" · 학습 중 검증 {len(d['공통']['val'])} · 채점 {len(d['공통']['test'])}"
          f" · 빈 구간 {len(d['공통']['gap'])} · 안 씀 {len(d['공통']['unused'])}")


def cmd_speed(a):
    head, dirty = code_state()
    if dirty:
        sys.exit("🔴 코드·설정이 커밋되지 않았다 — 커밋한 뒤에 잰다")
    if sh(f"ls {RROOT}/도는중/ 2>/dev/null | head -1").strip():
        sys.exit("🔴 실험이 돌고 있다 — 비었을 때만 잰다")
    base = TC.load_yaml(HERE / "설정" / "기본.yaml")
    cfg = TC.resolve(base, {"id": "E0-button-speed", "group": "button", "입력": a.입력})
    job = make_job(cfg, SP.load_split(HERE / "나눔" / f"{cfg['나눔']}.json"), head, op_conf("button"), None)
    job["train_kwargs"].update({"epochs": a.에폭, "patience": 0, "plots": False})
    job["속도재기"] = True
    deploy_code(head)
    name = f"속도_작업틀_{a.입력}.json"
    sh(f"cat > {RROOT}/{name}", input=json.dumps(job, ensure_ascii=False))
    sh(f"cd {RROOT} && ( setsid nohup venv/bin/python 코드/{head}/speedprobe.py --루트 {RROOT} {name} >> 속도재기.log 2>&1 < /dev/null & )")
    print(f"속도 측정을 띄웠다({a.입력}) — 끝나면 {RROOT}/속도.json · 진행 = {RROOT}/속도재기.log")


def cmd_launch(a):
    head, dirty = code_state()
    if a.이어서:
        job = json.loads(sh(f"cat {RROOT}/runs/{a.이어서}/작업.json"))
        job["이어서"] = True
        jobs = [job]
    else:
        base = TC.load_yaml(HERE / "설정" / "기본.yaml")
        cfgs = [TC.resolve(base, TC.load_yaml(p), Path(p).stem) for p in a.설정]
        ids = [c["id"] for c in cfgs]
        remote = sh(f"cd {RROOT} && ls runs 2>/dev/null; ls 대기열 2>/dev/null | sed 's/^[^_]*_//; s/\\.json$//' ; true").split()
        local = [p.name for p in (HERE / "결과").glob("*") if p.is_dir()]
        probs = launch_problems(ids, local, remote, dirty)
        if probs:
            sys.exit("🔴 " + " · ".join(probs))
        jobs = [make_job(c, SP.load_split(HERE / "나눔" / f"{c['나눔']}.json"), head, op_conf(c["group"]), None) for c in cfgs]
        try:
            hours, limits = estimate(jobs, remote_json(f"{RROOT}/속도.json", {}))
        except ValueError as e:
            sys.exit(f"🔴 {e}")
        for j, lim in zip(jobs, limits):
            j["시간상한_s"] = lim
        print(f"예상 최대 {hours:.1f}시간(최대 에폭 기준 · 일찍 멈춤·포화로 줄어든다)")
        if hours > 24 and not a.확인:
            sys.exit("🔴 24시간을 넘는다 — 나눠 걸거나 사용자 확인 뒤 --확인")
        deploy_code(head)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for i, j in enumerate(jobs):
        sh(f"cat > {RROOT}/대기열/{stamp}-{i:02d}_{j['id']}.json", input=json.dumps(j, ensure_ascii=False))
    print(f"대기열에 {len(jobs)}개: {', '.join(j['id'] for j in jobs)}")
    stop = sh(f"cat {RROOT}/대기열멈춤 2>/dev/null || true").strip()
    if stop:
        print(f"⏸ 대기열이 멈춰 있다({stop}) — 정한 뒤 `재개` 하면 돈다")
        return
    start_runner(jobs[0]["코드해시"])


def cmd_status(a):
    while True:
        st = remote_json(f"{RROOT}/상태.json", {})
        now = time.time()
        print(time.strftime("[%H:%M]"), render_status(st, now), flush=True)
        if not a.끝까지 or finished(st, now):
            return
        time.sleep(a.끝까지 * 60)


def cmd_fetch(a):
    home = sh("echo $HOME").strip()
    ids = [x.rstrip("/") for x in sh(f"cd {RROOT}/runs 2>/dev/null && ls -d */ 2>/dev/null || true").split()]
    got = []
    for i in ids:
        if i.startswith(SKIP) or not sh(f"test -f {RROOT}/runs/{i}/요약.json && echo y || true").strip():
            continue
        tmp = LOCAL / "받기" / i
        tmp.mkdir(parents=True, exist_ok=True)
        filt = [f"--include={f}" for f in RECORD] + ["--include=weights/", "--include=weights/best.pt", "--exclude=*"]
        rsync([*filt, f"{REMOTE}:{RROOT}/runs/{i}/", f"{tmp}/"])
        dst = HERE / "결과" / i
        dst.mkdir(parents=True, exist_ok=True)
        for f in RECORD:
            p = tmp / f
            if p.exists():
                if p.suffix in (".json", ".yaml", ".csv"):
                    (dst / f).write_text(sanitize(p.read_text(encoding="utf-8"), home), encoding="utf-8")
                else:
                    shutil.copyfile(p, dst / f)
        summ = json.loads((dst / "요약.json").read_text(encoding="utf-8"))
        b = tmp / "weights" / "best.pt"
        if summ.get("best_sha256") and b.exists():
            h = hashlib.sha256(b.read_bytes()).hexdigest()
            if h != summ["best_sha256"]:
                sys.exit(f"🔴 {i} best.pt 해시가 다르다 — 받기를 다시 한다")
            (LOCAL / i).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(b, LOCAL / i / "best.pt")
        got.append(i)
    ledger.rebuild(HERE / "결과", HERE / "장부.md")
    print(f"받음 {len(got)}: {', '.join(got)} · 장부 = {HERE / '장부.md'}")


def cmd_resume(a):
    stop = sh(f"cat {RROOT}/대기열멈춤 2>/dev/null || true").strip()
    print(f"멈춤 풀기: {stop or '(멈춰 있지 않음)'}")
    sh(f"rm -f {RROOT}/대기열멈춤")
    code = sh(f"ls -t {RROOT}/코드 | head -1").strip()
    start_runner(code)


def cmd_remove(a):
    names = sh(f"cd {RROOT}/대기열 && ls *_{a.id}.json 2>/dev/null || true").split()
    if not names:
        sys.exit(f"대기열에 {a.id} 가 없다")
    sh(f"mkdir -p {RROOT}/뺀것 && cd {RROOT}/대기열 && mv {' '.join(names)} ../뺀것/")
    print(f"뺐다: {a.id}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="학습 체계 파이 명령")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("준비")
    p.add_argument("--나눔", required=True)
    p.add_argument("--채점", default=str(DEFAULT_TEST))
    p = sub.add_parser("속도재기")
    p.add_argument("--입력", required=True, choices=sorted(TC.INPUT_MODES))
    p.add_argument("--에폭", type=int, default=3)
    p = sub.add_parser("걸기")
    p.add_argument("설정", nargs="*")
    p.add_argument("--확인", action="store_true")
    p.add_argument("--이어서")
    p = sub.add_parser("상태")
    p.add_argument("--끝까지", type=float, default=0)
    sub.add_parser("받기")
    sub.add_parser("재개")
    p = sub.add_parser("빼기")
    p.add_argument("id")
    a = ap.parse_args(argv)
    {"준비": cmd_prepare, "속도재기": cmd_speed, "걸기": cmd_launch, "상태": cmd_status,
     "받기": cmd_fetch, "재개": cmd_resume, "빼기": cmd_remove}[a.cmd](a)


if __name__ == "__main__":
    main()
