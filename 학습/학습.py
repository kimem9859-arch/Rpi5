"""학습 체계 파이 명령 — 데스크톱 GPU(ssh wsl-train)에 실험을 걸고 결과를 받는다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §10 · §11
실행(Rpi5 에서 · 시스템 python3): python3 학습/학습.py <명령> …
  준비 --나눔 place1_v1 [--채점 <목록>]     나눔 파일(없으면 만들기 · 있으면 그대로) → 원본 사진·라벨을 데스크톱으로(바뀐 것만)
  준비 --나눔 place1_v2b --보류 <세션> --바탕판 place1_v1   세션 보류 판(버튼 전용 · 1-3단계)
  속도재기 --입력 늘리기640|원본768x1024     첫 속도 측정을 데스크톱에 띄운다(실험이 없을 때)
  걸기 <설정.yaml …> [--확인]                대기열에 넣고 실행기를 띄운다(예상 24시간 넘으면 --확인 필요)
  걸기 --이어서 <id>                          끊긴 실험을 last.pt 에서 이어서
  상태 [--끝까지 <분>]                        실행기 상태 · --끝까지 = 끝·멈춤·응답 없음까지 그 간격으로 기다린다
  받기                                         끝난 실험의 기록·best.pt 를 받아 해시를 맞추고 장부를 다시 만든다
  재개                                         대기열 멈춤을 풀고 실행기를 띄운다 — 멈춘 이유를 정한 뒤에만
  빼기 <id>                                    대기열에서 뺀다(건너뛰기)
  변환 <id> [--수준 N]                         HEF 변환을 데스크톱에 띄운다 · 다시 치면 상태 · 끝났으면 받는다(1-2단계 §8.3)
  이름표                                      옛 이름 → 새 이름 대조표(학습/이름대조표.md)를 다시 만든다
🔴 코드·설정이 커밋되지 않았으면 걸지 않는다 — 결과의 코드 해시가 저장소를 가리켜야 한다.
🔴 대기열이 멈춰 있으면 걸기는 넣기만 하고 실행기를 띄우지 않는다.
"""
import argparse
import hashlib
import json
import re
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
import hef_convert as H  # noqa: E402
import 이름            # noqa: E402
import ledger          # noqa: E402
import split as SP     # noqa: E402
import stoprules       # noqa: E402
import tool_round as TR  # noqa: E402
import trainconf as TC  # noqa: E402

REMOTE = "wsl-train"
RROOT = "~/학습실험"
SRC = Path.home() / "data" / "label_dataset"
LOCAL = Path.home() / "data" / "학습실험"
CODE_FILES = ["train_one.py", "runner.py", "stoprules.py", "scoring.py", "speedprobe.py", "tune.py", "hef_convert.py"]
DIRTY_PATHS = ["학습/*.py", "학습/설정", "학습/나눔", "Demo/test/score_lib.py", "Demo/test/tool_round.py"]
RECORD = ["요약.json", "채점.json", "채점_검증.json", "채점_세션.json", "설정.json", "args.yaml", "results.csv", "results.png",
          "confusion_matrix.png", "confusion_matrix_normalized.png"]
DEFAULT_TEST = RPI5 / "조사" / "재학습확인-20261003" / "채점사진.txt"
CONVERT_CFG = RPI5 / "조사" / "HEF변환-20261004" / "변환설정.json"
CALIB_SEED = 0
CONVERT_PROC = r"python[^ ]* [^ ]*/[h]ef_convert\.py (onnx|hef) "           # [h] = 이 명령을 부른 셸 자신은 걸리지 않게
TRAIN_PROC = r"python[^ ]* [^ ]*/([r]unner|[t]une|[s]peedprobe)\.py"         # client_runner.py · finetune.py 를 읽는 명령은 안 걸림


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
            "나눔": {"name": d["나눔"], "해시": d["해시"], "train": tr, "val": va, "test": te,
                   "test_session": SP.session_test(d, cfg["group"])},
            "코드": f"{RROOT}/코드/{head}", "코드해시": head, "시간상한_s": time_limit, "설정": cfg, "흐림": cfg.get("흐림")}


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


def convert_calib(d, group, cfg):
    """HEF 보정 사진 = 그 무리의 학습 몫에서만(검증 몫 · 채점 사진 금지 · 설계 §8.3) · 시드 CALIB_SEED 로 섞은 순서."""
    return H.pick_calib(SP.lists_for(d, group)[0], cfg["calib_n"][group], CALIB_SEED)


def input_problems(job_cfg, cfg):
    """학습 입력 = 변환 입력 — 실험의 늘리기 크기([가로, 세로]) 또는 추론 크기([세로, 가로] · 숫자면 정사각)가 결정표 onnx.imgsz 와 같아야 한다(§8.6)."""
    if job_cfg.get("stretch"):
        want = [job_cfg["stretch"][1], job_cfg["stretch"][0]]
    else:
        p = job_cfg["predict_imgsz"]
        want = [p, p] if isinstance(p, int) else list(p)
    got = list(cfg["onnx"]["imgsz"])
    return [] if want == got else [f"학습 입력 [세로, 가로] {want} ≠ 결정표 onnx.imgsz {got} — 학습과 다른 크기로 변환하면 조용히 나빠진다(§8.6)"]


def convert_dirname(i, level):
    """최적화 수준을 바꿔 보는 변환은 따로 둔다 — 결정표대로 한 변환을 덮지 않게."""
    return i if level is None else f"{i}_L{level}"


def sanitize(text, home):
    return text.replace(home, "~") if home and home != "/" else text


LEAK_RE = re.compile(r"/home/[A-Za-z0-9_.-]+|/mnt/[a-z]/Users/[^/\s\"']+")


def leaks(text):
    """홈 경로를 지운 뒤에도 남은 개인 경로(다른 계정 · Windows 사용자 폴더) — 공개 저장소로 새지 않게 받기가 멈춘다."""
    return LEAK_RE.findall(text)


def _age(st, now):
    return now - datetime.fromisoformat(st["시각"]).timestamp()


def finished(st, now):
    return bool(not st or st.get("끝") or st.get("멈춤") or st.get("오류") or _age(st, now) > 600)


def launch_state(st, now):
    """걸기 직후 쓸 상태 — 지난번 「끝」이 남아 있으면 새 실행기가 상태를 쓰기 전에 「끝남」으로 읽히므로 덮는다.
    도는 실행기의 상태는 덮지 않는다(None)."""
    if st and not st.get("끝"):
        return None
    return {"시각": datetime.fromtimestamp(now).isoformat(timespec="seconds"), "끝": False, "도는중": [], "대기": [],
            "기다리는이유": "실행기 시작 중(걸기 직후)", "끝남": (st or {}).get("끝남", 0)}


def atomic_write_cmd(path):
    """원격 파일을 임시 이름(.tmp — 실행기의 *.json 밖)에 다 쓴 뒤 이름을 바꾼다 — 실행기가 반쯤 쓴 파일을 읽지 않게."""
    return f"cat > {path}.tmp && mv {path}.tmp {path}"


def render_status(st, now):
    if not st:
        return "상태 파일 없음 — 아직 걸지 않았다"
    age = _age(st, now)
    if st.get("오류"):
        head = f"🔴 실행기 오류로 끝남 — {st['오류']} · 데스크톱 ~/학습실험 확인 뒤 `재개`"
    elif st.get("끝"):
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
    """코드 폴더는 다 보낸 뒤 완료 표지를 둔다 — 보내다 끊긴 폴더(표지 없음)는 다시 보낸다."""
    if sh(f"test -f {RROOT}/코드/{head}/.완료 && echo 있음 || true").strip():
        return
    sh(f"mkdir -p {RROOT}/코드/{head}")
    rsync([*(str(HERE / f) for f in CODE_FILES), str(RPI5 / "Demo" / "test" / "score_lib.py"), f"{REMOTE}:{RROOT}/코드/{head}/"])
    sh(f"touch {RROOT}/코드/{head}/.완료")


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

    if not sp_path.exists() and a.보류:
        if not a.바탕판:
            sys.exit("🔴 --보류 는 --바탕판(세션을 뺄 기존 나눔)과 함께 준다")
        base = SP.load_split(HERE / "나눔" / f"{a.바탕판}.json")
        SP.save_split(SP.hold_session(base, a.보류, SP.names_of(base), a.나눔), sp_path)   # 바탕판의 사진만(새 묶음 안 섞음 · 사용자 A)
        print(f"나눔 {a.나눔} 을 만들었다 — {a.바탕판} 에서 세션 {a.보류} 를 버튼 학습·검증에서 빼고 세션 채점으로")
    elif not sp_path.exists():
        test = [l.strip() for l in Path(a.채점).read_text(encoding="utf-8").splitlines() if l.strip()]
        SP.save_split(SP.make_split(a.나눔, sorted(idx), test, labels_of), sp_path)
        print(f"나눔 {a.나눔} 을 만들었다")
    d = SP.load_split(sp_path)
    need = sorted(set(d["button"]["train"]) | set(d["tool"]["train"]) | set(d["공통"]["val"]) | set(d["공통"]["test"])
                  | set(SP.session_test(d, "button")))
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
        if not TC.ID_RE.match(a.이어서):
            sys.exit(f"🔴 실험 id 형식이 아니다: {a.이어서!r}")
        if dirty:
            sys.exit("🔴 커밋 안 된 학습 코드·설정·나눔이 있다 — 커밋한 뒤 건다(실행기는 지금 커밋의 코드로 뜬다)")
        job = json.loads(sh(f"cat {RROOT}/runs/{a.이어서}/작업.json"))
        job["이어서"] = True
        jobs = [job]
        deploy_code(head)                         # 학습은 그 실험의 코드 그대로 · 실행기만 지금 커밋
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
        sh(atomic_write_cmd(f"{RROOT}/대기열/{stamp}-{i:02d}_{j['id']}.json"), input=json.dumps(j, ensure_ascii=False))
    print(f"대기열에 {len(jobs)}개: {', '.join(j['id'] for j in jobs)}")
    stop = sh(f"cat {RROOT}/대기열멈춤 2>/dev/null || true").strip()
    if stop:
        print(f"⏸ 대기열이 멈춰 있다({stop}) — 정한 뒤 `재개` 하면 돈다")
        return
    st = launch_state(remote_json(f"{RROOT}/상태.json", {}), time.time())
    if st:
        sh(atomic_write_cmd(f"{RROOT}/상태.json"), input=json.dumps(st, ensure_ascii=False))
    start_runner(head)


def cmd_status(a):
    while True:
        st = remote_json(f"{RROOT}/상태.json", {})
        now = time.time()
        print(time.strftime("[%H:%M]"), render_status(st, now), flush=True)
        if not a.끝까지 or finished(st, now):
            return
        time.sleep(a.끝까지 * 60)


def write_record(tmp, dst, home, i):
    """한 실험의 기록을 모두 홈 경로 정리·개인 경로 검사한 뒤에 쓴다 — 하나라도 남으면 그 실험은 아무것도 쓰지 않는다."""
    texts, bins = {}, []
    for f in RECORD:
        p = Path(tmp) / f
        if not p.exists():
            continue
        if p.suffix in (".json", ".yaml", ".csv"):
            text = sanitize(p.read_text(encoding="utf-8"), home)
            bad = leaks(text)
            if bad:
                sys.exit(f"🔴 {i}/{f} 에 개인 경로가 남았다 {sorted(set(bad))} — 받기를 멈춘다(공개 저장소)")
            texts[f] = text
        else:
            bins.append(p)
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f, text in texts.items():
        (dst / f).write_text(text, encoding="utf-8")
    for p in bins:
        shutil.copyfile(p, dst / p.name)


def cmd_fetch(a):
    home = sh("echo $HOME").strip()
    ids = [x.rstrip("/") for x in sh(f"cd {RROOT}/runs 2>/dev/null && ls -d */ 2>/dev/null || true").split()]
    got = []
    for i in ids:
        if 이름.skipped(i) or not sh(f"test -f {RROOT}/runs/{i}/요약.json && echo y || true").strip():
            continue
        tmp = LOCAL / "받기" / i
        tmp.mkdir(parents=True, exist_ok=True)
        filt = [f"--include={f}" for f in RECORD] + ["--include=weights/", "--include=weights/best.pt", "--exclude=*"]
        rsync([*filt, f"{REMOTE}:{RROOT}/runs/{i}/", f"{tmp}/"])
        dst = HERE / "결과" / i
        try:
            write_record(tmp, dst, home, i)
        except SystemExit:
            ledger.rebuild(HERE / "결과", HERE / "장부.md")      # 앞서 받은 실험은 장부에 남긴다
            raise
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


def judge_ids(results, cand_ids, base_ids):
    by = {su["id"]: (su, sc) for su, sc in results}
    miss = [i for i in cand_ids + base_ids if i not in by or by[i][1] is None]
    if miss:
        sys.exit(f"🔴 결과(채점) 없음: {miss}")
    conds = {json.dumps(by[i][0].get("조건"), sort_keys=True, ensure_ascii=False) for i in cand_ids + base_ids}
    groups = {by[i][0]["group"] for i in cand_ids + base_ids}
    if len(conds) > 1 or len(groups) > 1:
        sys.exit("🔴 후보·기준의 운용 조건(멈춤 · 나눔 · conf · 판) 또는 무리가 다르다 — 같은 조건의 기준으로 판정한다")
    return ledger.adopt([by[i][1] for i in cand_ids], [by[i][1] for i in base_ids], groups.pop())


def cmd_judge(a):
    v, ok = judge_ids(ledger.load_results(HERE / "결과", "채점_세션.json" if a.채점 == "세션" else "채점.json"), a.후보, a.기준)
    for k, x in v.items():
        print(f"  {k}: {x}")
    print("✅ 채택" if ok else "— 기각(위로 갈린 지표 없음 또는 아래로 갈린 지표 있음)")


def tune_config(tc, tmpl, head, conc):
    """탐색기 설정(1-2단계 §5.3) — 이름 · 범위 종류 · 기준 id 를 검사하고 데스크톱 탐색기가 읽을 꼴로."""
    name = str(tc.get("이름", ""))
    if not re.fullmatch(r"[A-Za-z0-9]+", name):
        sys.exit(f"🔴 탐색 이름은 영문·숫자만: {name!r}")
    for k, spec in tc["범위"].items():
        if spec[0] not in ("log", "cat"):
            sys.exit(f"🔴 범위 종류는 log·cat 만: {k} {spec}")
    if not tc.get("기준"):
        sys.exit("🔴 기준 실험 id(검증 채점이 있는 E0c 등)를 적는다")
    return {"이름": name, "루트": RROOT, "코드": f"{RROOT}/코드/{head}", "틀": tmpl, "범위": tc["범위"],
            "횟수": int(tc["횟수"]), "시작무작위": int(tc.get("시작무작위", 10)), "시드": int(tc.get("시드", 0)),
            "동시": conc, "기준": list(tc["기준"]), "간격": 30}


def cmd_tune(a):
    head, dirty = code_state()
    if dirty:
        sys.exit("🔴 커밋 안 된 학습 코드·설정·나눔이 있다 — 커밋한 뒤 건다")
    tc = TC.load_yaml(Path(a.설정))
    sid = f"E8-{tc['group']}-{tc['이름']}t000"
    cfg = TC.resolve(TC.load_yaml(HERE / "설정" / "기본.yaml"), {"id": sid, "group": tc["group"], **tc.get("틀", {})}, sid)
    tmpl = make_job(cfg, SP.load_split(HERE / "나눔" / f"{cfg['나눔']}.json"), head, op_conf(cfg["group"]), None)
    speed = remote_json(f"{RROOT}/속도.json", {})
    _, limits = estimate([tmpl], speed)
    tmpl["시간상한_s"] = limits[0]
    c = tune_config(tc, tmpl, head, speed[cfg["입력"]]["동시"])
    deploy_code(head)
    d = f"{RROOT}/탐색/{c['이름']}"
    sh(f"mkdir -p {d}")
    sh(atomic_write_cmd(f"{d}/설정.json"), input=json.dumps(c, ensure_ascii=False))
    sh(f"cd {RROOT} && ( setsid nohup venv/bin/python 코드/{head}/tune.py --설정 {d}/설정.json >> {d}/탐색.log 2>&1 < /dev/null & )")
    print(f"탐색 {c['이름']} 시작 — {c['횟수']}회 · 동시 {c['동시']} · 상태 = 학습.py 탐색상태 {c['이름']}")


def cmd_tune_status(a):
    if not re.fullmatch(r"[A-Za-z0-9]+", a.이름):
        sys.exit(f"🔴 탐색 이름은 영문·숫자만: {a.이름!r}")
    s = remote_json(f"{RROOT}/탐색/{a.이름}/요약.json", {})
    if not s:
        sys.exit("요약 없음 — 아직 시작 전이거나 이름이 다르다")
    print(f"탐색 {a.이름} · {s.get('상태')} · 끝 {s.get('끝')}/{s.get('횟수')} · 이상 {s.get('이상')} · 도는 중 {s.get('도는중')}")
    for r in s.get("상위", []):
        print(f"  {r['id']} 목표 {r['목표']:.4f} · 검증P {r['검증P']:.3f} · {r.get('바꾼것', '')}")
    if a.저장:
        (HERE / "탐색").mkdir(exist_ok=True)
        (HERE / "탐색" / f"{a.이름}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_resume(a):
    head, dirty = code_state()
    if dirty:
        sys.exit("🔴 커밋 안 된 학습 코드·설정·나눔이 있다 — 커밋한 뒤 재개한다(실행기는 지금 커밋의 코드로 뜬다)")
    stop = sh(f"cat {RROOT}/대기열멈춤 2>/dev/null || true").strip()
    deploy_code(head)                             # 배포가 실패하면 멈춤을 풀지 않는다
    print(f"멈춤 풀기: {stop or '(멈춰 있지 않음)'}")
    sh(f"rm -f {RROOT}/대기열멈춤")
    start_runner(head)


def cmd_remove(a):
    if not TC.ID_RE.match(a.id):
        sys.exit(f"🔴 실험 id 형식이 아니다: {a.id} — 하나씩 정확한 id 로 뺀다")
    names = sh(f"cd {RROOT}/대기열 && ls *_{a.id}.json 2>/dev/null || true").split()
    if not names:
        sys.exit(f"대기열에 {a.id} 가 없다")
    sh(f"mkdir -p {RROOT}/뺀것 && cd {RROOT}/대기열 && mv {' '.join(names)} ../뺀것/")
    print(f"뺐다: {a.id}")


def convert_fetch(a, name, wd, code):
    """끝난 변환 받기 — HEF 해시를 맞추고 변환.json 은 홈 경로를 지워 결과 폴더에(가중치·HEF 는 저장소 밖)."""
    dst = LOCAL / a.id / ("" if a.수준 is None else f"L{a.수준}")
    dst.mkdir(parents=True, exist_ok=True)
    logs = ["onnx.log", "hef.log", "hailo_sdk.client.log"]
    if code != "0":                                      # 실패해도 로그는 받는다(중단 규칙 = 로그로 원인 확인)
        rsync([*(f"--include={f}" for f in logs), "--exclude=*", f"{REMOTE}:{wd}/", f"{dst}/"])
        sys.exit(f"🔴 변환 {name} 실패(종료 {code}) — 로그 = {dst} · 꼬리:\n" + sh(f"cd {wd} && tail -n 8 onnx.log hef.log 2>/dev/null || true"))
    keep = ["변환.json", "model.hef", "model.alls", "nms_config.json", *logs]
    rsync([*(f"--include={f}" for f in keep), "--exclude=*", f"{REMOTE}:{wd}/", f"{dst}/"])
    raw = (dst / "변환.json").read_text(encoding="utf-8")
    rec = json.loads(raw)
    if hashlib.sha256((dst / "model.hef").read_bytes()).hexdigest() != rec["해시"]["model.hef"]:
        sys.exit(f"🔴 {name} model.hef 해시가 변환.json 과 다르다 — 다시 받는다")
    text = sanitize(raw, sh("echo $HOME").strip())
    bad = leaks(text)
    if bad:
        sys.exit(f"🔴 {name}/변환.json 에 개인 경로가 남았다 {sorted(set(bad))} — 받기를 멈춘다(공개 저장소)")
    out = HERE / "결과" / a.id / ("변환.json" if a.수준 is None else f"변환_L{a.수준}.json")
    out.write_text(text, encoding="utf-8")
    t = rec["시간_s"]
    print(f"받음 {name} — 수준 {rec['수준']['지정']} · 미세 학습 {rec['수준']['미세학습']} · 시간(초) {t} · HEF {dst / 'model.hef'} · 기록 {out}")
    for l in rec["수준"]["DFC_로그"]:
        print(f"  DFC: {l}")


def cmd_convert(a):
    if not TC.ID_RE.match(a.id):
        sys.exit(f"🔴 실험 id 형식이 아니다: {a.id!r}")
    name = convert_dirname(a.id, a.수준)
    wd = f"{RROOT}/변환/{name}"
    code = sh(f"cat {wd}/끝 2>/dev/null || true").strip()
    if code:
        return convert_fetch(a, name, wd, code)
    running = sh(f"pgrep -af '{CONVERT_PROC}' || true").strip()
    if running:
        mine = any(l.rstrip().endswith(f"/변환/{name}") for l in running.splitlines())
        print(f"{'이 변환' if mine else '다른 변환'} 도는 중 — {running}"
              + (f"\n  진행 = 데스크톱 {wd}/onnx.log · hef.log 끝 줄: " + sh(f"tail -n 1 {wd}/hef.log {wd}/onnx.log 2>/dev/null | tail -n 1 || true").strip()
                 if mine else " · 그 변환이 끝난 뒤 다시 친다(메모리 · 한 번에 하나)"))
        return
    code = sh(f"cat {wd}/끝 2>/dev/null || true").strip()     # 위 두 확인 사이에 끝났을 수 있다 — 끝난 결과를 지우라고 하지 않게
    if code:
        return convert_fetch(a, name, wd, code)
    if sh(f"test -d {wd} && echo y || true").strip():
        sys.exit(f"🔴 끊긴 변환(끝 표지도 프로세스도 없음) — 로그 확인 뒤 데스크톱 `rm -rf {wd}` 하고 다시:\n"
                 + sh(f"cd {wd} && tail -n 5 onnx.log hef.log 2>/dev/null || true"))
    head, dirty = code_state()
    cfg_dirty = subprocess.run(["git", "-C", str(RPI5), "status", "--porcelain", "--", str(CONVERT_CFG)],
                               capture_output=True, text=True).stdout.strip()
    if dirty or cfg_dirty:
        sys.exit("🔴 커밋 안 된 학습 코드·결정표가 있다 — 커밋한 뒤 변환한다(변환.json 의 코드 해시가 저장소를 가리키게)")
    if sh(f"pgrep -af '{TRAIN_PROC}' || true").strip():
        sys.exit("🔴 학습·탐색이 돌고 있다 — 변환은 학습이 없을 때(데스크톱 메모리·CPU · 계획 「병행 트랙」)")
    res = HERE / "결과" / a.id
    if not (res / "설정.json").exists() or not (res / "요약.json").exists():
        sys.exit(f"🔴 {res} 에 설정.json·요약.json 이 없다 — 먼저 `받기`")
    job_cfg = json.loads((res / "설정.json").read_text(encoding="utf-8"))
    summ = json.loads((res / "요약.json").read_text(encoding="utf-8"))
    cfg = json.loads(CONVERT_CFG.read_text(encoding="utf-8"))
    g = job_cfg["group"]
    d = SP.load_split(HERE / "나눔" / f"{job_cfg['나눔']['name']}.json")
    if d["해시"] != job_cfg["나눔"]["해시"]:
        sys.exit(f"🔴 나눔 해시가 그 실험과 다르다({d['해시']} ≠ {job_cfg['나눔']['해시']})")
    bad = input_problems(job_cfg, cfg)
    if bad:
        sys.exit("🔴 " + " · ".join(bad))
    calib = convert_calib(d, g, cfg)
    bad = H.count_problems(cfg, g)
    if len(calib) != cfg["calib_n"][g] or bad:
        sys.exit(f"🔴 보정 {len(calib)}장 · 결정표 calib_n {cfg['calib_n'][g]} · {bad} — 셋이 같아야 한다")
    deploy_code(head)
    if sh(f"mkdir -p {RROOT}/변환 && mkdir {wd} 2>/dev/null && echo 새로 || echo 있음").strip() != "새로":   # 폴더 = 잠금(두 번 동시에 쳐도 하나만)
        sys.exit(f"🔴 {wd} 가 이미 있다 — 다른 창에서 막 띄웠는지 확인한다")
    sh(f"cp {RROOT}/runs/{a.id}/weights/best.pt {wd}/best.pt")
    if sh(f"sha256sum {wd}/best.pt").split()[0] != summ.get("best_sha256"):
        sh(f"rm -rf {wd}")
        sys.exit(f"🔴 데스크톱 runs/{a.id} 의 best.pt 해시가 요약과 다르다")
    place = place_of(job_cfg["나눔"]["name"])
    job = {"id": a.id, "group": g, "names": job_cfg["names"], "수준": a.수준, "코드해시": head,
           "보정출처": {"나눔": d["나눔"], "나눔해시": d["해시"], "몫": "train", "시드": CALIB_SEED},
           "calib": [f"{RROOT}/원본/{place}/images/{n}.png" for n in calib]}
    sh(atomic_write_cmd(f"{wd}/입력.json"), input=json.dumps(job, ensure_ascii=False))
    rsync([str(CONVERT_CFG), f"{REMOTE}:{wd}/변환설정.json"])
    py = f"{RROOT}/코드/{head}/hef_convert.py"
    sh(f"cd {wd} && ( setsid nohup bash -c '{RROOT}/venv/bin/python {py} onnx {wd} > onnx.log 2>&1"
       f" && ~/hailo-venv/bin/python {py} hef {wd} > hef.log 2>&1; echo $? > 끝' < /dev/null > /dev/null 2>&1 & )")
    print(f"변환 {name} 띄움 — 보정 {len(calib)}장(학습 몫) · 수준 {'결정표' if a.수준 is None else a.수준}"
          f" · 같은 명령을 다시 치면 상태 · 끝나면 받는다")


def names_table():
    """대조표 본문 — 옛 꼴 id(설정 파일 · 결과 폴더) → 새 이름. 학습 방식 근거 = 멈춤 조건(설계 모델이름 §4)."""
    base = TC.load_yaml(HERE / "설정" / "기본.yaml")
    rows = {}
    for sub in ("실험", "점검"):
        for p in sorted((HERE / "설정" / sub).glob("E*.yaml")):
            c = TC.resolve(base, TC.load_yaml(p), p.stem)
            rows[p.stem] = (c["멈춤"]["포화_향상"], int(c["seed"]), c["train"].get("epochs"), c["train"].get("patience"))
    for d in sorted((HERE / "결과").iterdir()):
        s = d / "설정.json"
        if d.name.startswith("E") and s.exists():
            c = json.loads(s.read_text(encoding="utf-8"))
            tk = c["train_kwargs"]
            rows[d.name] = (c["멈춤"]["포화_향상"], int(tk["seed"]), tk.get("epochs"), tk.get("patience"))
    key = lambda i: (int(re.match(r"E(\d+)", i).group(1)), i)
    out = ["# 이름 대조표 — 옛 이름 → 새 이름", "",
           "> 자동 생성 — `python3 학습/학습.py 이름표` 가 설정 파일·결과 폴더에서 다시 만든다. 손으로 고치지 않는다.",
           "> 규칙·모델 설명 정본 = 상위 `docs/통합문서.md` §6.4. 보고·대화에서는 **새 이름**으로 부른다 — 옛 이름은 파일·폴더·기록에만 남는다.",
           "> 다른 머신의 git 밖 공구 모델 사본 이름 바꾸기(Demo/ 에서): `for f in models/tool_*.pt; do mv \"$f\" \"models/T_${f#models/tool_}\"; done`",
           "", "| 옛 이름 | 새 이름 | 결과 폴더 | 근거(에폭 · patience · 포화_향상) |", "|---|---|---|---|"]
    for i in sorted(rows, key=key):
        sat, seed, ep, pat = rows[i]
        has = "있음" if (HERE / "결과" / i / "설정.json").exists() else "—"
        out.append(f"| {i} | {이름.new_name(i, sat, seed)} | {has} | {ep} · {pat} · {sat} |")
    return "\n".join(out) + "\n"


def cmd_names(a):
    p = HERE / "이름대조표.md"
    p.write_text(names_table(), encoding="utf-8")
    print(f"대조표 = {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="학습 체계 파이 명령")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("준비")
    p.add_argument("--나눔", required=True)
    p.add_argument("--채점", default=str(DEFAULT_TEST))
    p.add_argument("--보류", help="이 세션을 버튼 학습·검증에서 빼고 세션 채점으로(1-3단계 §4)")
    p.add_argument("--바탕판", help="--보류 로 만들 때 세션을 뺄 기존 나눔")
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
    p = sub.add_parser("탐색")
    p.add_argument("설정")
    p = sub.add_parser("탐색상태")
    p.add_argument("이름")
    p.add_argument("--저장", action="store_true")
    p = sub.add_parser("변환")
    p.add_argument("id")
    p.add_argument("--수준", type=int, choices=[1, 2])        # 3·4(adaround)는 정한 적 없다
    p = sub.add_parser("판정")
    p.add_argument("--후보", nargs="+", required=True)
    p.add_argument("--기준", nargs="+", required=True)
    p.add_argument("--채점", choices=["기본", "세션"], default="기본", help="세션 = 처음 보는 세션 채점(채점_세션.json · 1-3단계)")
    sub.add_parser("이름표")
    a = ap.parse_args(argv)
    {"준비": cmd_prepare, "속도재기": cmd_speed, "걸기": cmd_launch, "상태": cmd_status,
     "받기": cmd_fetch, "재개": cmd_resume, "빼기": cmd_remove, "판정": cmd_judge, "탐색": cmd_tune, "탐색상태": cmd_tune_status, "변환": cmd_convert,
     "이름표": cmd_names}[a.cmd](a)


if __name__ == "__main__":
    main()
