"""HEF 변환 — 1-2단계 설계 §8.3. 값은 조사/HEF변환-20261004/변환설정.json(조사 결론)만 읽는다.

데스크톱에서 두 단계로 돈다(파이 명령 = 학습.py 변환 <id> 가 작업 폴더를 만들고 띄운다):
  onnx 단계 = ~/학습실험/venv(ultralytics 8.4.171)  : python hef_convert.py onnx <작업폴더>
  hef 단계  = ~/hailo-venv(DFC 3.33.1 · CPU)       : python hef_convert.py hef <작업폴더>
작업 폴더 = best.pt · 입력.json(id · group · names · calib · 수준) · 변환설정.json → model.onnx · model.hef · 변환.json
레시피 = ultralytics 8.4.171 export_hailo(끝 노드 6개 · 분류 시그모이드 · NMS json) — 바꾼 것은 조사보고서 §4:
보정 = 학습 몫 · 런타임과 같은 늘리기(크기 = 결정표 onnx.imgsz) · 고정 시드 · 최적화 수준 명시(CPU 에서 빠뜨리면 0 으로 떨어진다).
"""
import copy
import hashlib
import inspect
import json
import os
import random
import re
import sys
import time
from pathlib import Path

CLS_SLOTS = {"<cls_s8>": 1, "<cls_s16>": 3, "<cls_s32>": 5}     # HN 출력층 순서 = 끝 노드 순서(reg8 cls8 reg16 cls16 reg32 cls32)
STRIDES = (8, 16, 32)
REG_CH = 64                                                     # 4 × reg_max 16
LEVEL_RE = re.compile(r"(?<![A-Za-z_])optimization_level=\d")         # compiler_optimization_level 은 건드리지 않는다
FINETUNE_ON_RE = re.compile(r"post_quantization_optimization\(finetune,\s*policy=enabled[^)]*\)")
EVIDENCE_RE = re.compile(r"optimization level|compression level|entries for|Starting |skipped|is done \(completion", re.I)


# ── 순수 함수(시험 대상) ─────────────────────────────────────────────
def pick_calib(train_names, n, seed):
    """학습 몫을 시드로 섞어 앞 n장 — **섞인 순서 그대로** 돌려준다. DFC 는 받은 순서로 통계 앞 N장·미세 학습 배치를 만들고
    (셔플 버퍼 기본 1 · qft.py), 파일 이름은 세션순이다. 모자라면 전부를 섞는다."""
    names = sorted(train_names)
    random.Random(seed).shuffle(names)
    return names[:n]


def alls_text(cfg, group):
    return "".join(l + "\n" for l in cfg["alls"][group])


def _need_six(outs):
    if len(outs) != 6:
        raise ValueError(f"HN 출력층이 6개가 아니다({len(outs)}): {outs} — 끝 노드를 확인한다")


def model_script(cfg, group, outs, nms_path, level=None, n=None):
    """결정표 줄의 자리(<cls_s*> · NMS json 이름)를 파싱 결과로 채운다. level 이 있으면 최적화 수준만 바꿔 시험한다.
    n = 실제로 넘기는 보정 장수 — 학습 몫이 calib_n 보다 적은 나눔(예: place1_v2b 버튼 1022)이면 보정·미세 학습 장수를
    그 수로 맞춘다(크면 DFC 오류 · 작으면 조용히 덜 쓴다 — count_problems). None 이면 결정표 그대로."""
    _need_six(outs)
    s = alls_text(cfg, group)
    if n is not None:
        s = re.sub(r"(calibset_size|dataset_size)=\d+", lambda m: f"{m.group(1)}={int(n)}", s)
    if not LEVEL_RE.search(s):
        raise ValueError("모델 스크립트에 optimization_level 줄이 없다 — CPU 에서는 조용히 수준 0 이 된다")
    if level is not None:
        s = LEVEL_RE.sub(f"optimization_level={int(level)}", s)
        if int(level) < 2:                                   # 명시한 미세 학습 줄은 수준 기본값을 덮는다(mo_script_parser deep_update)
            s = FINETUNE_ON_RE.sub("post_quantization_optimization(finetune, policy=disabled)", s)
    for slot, i in CLS_SLOTS.items():
        s = s.replace(slot, outs[i])
    s = re.sub(r'nms_postprocess\("[^"]*"', f'nms_postprocess("{nms_path}"', s)
    left = re.findall(r"<[A-Za-z_0-9]+>", s)
    if left:
        raise ValueError(f"채우지 못한 자리: {left}")
    return s


def nms_config(cfg, group, outs, names):
    _need_six(outs)
    if list(cfg["nms_config"][group]["image_dims"]) != list(cfg["onnx"]["imgsz"]):
        raise ValueError(f"NMS image_dims {cfg['nms_config'][group]['image_dims']} ≠ ONNX imgsz {cfg['onnx']['imgsz']} — 결정표 안에서 크기가 어긋난다")
    n = copy.deepcopy(cfg["nms_config"][group])
    if n["classes"] != len(names):
        raise ValueError(f"NMS classes {n['classes']} ≠ 모델 클래스 {len(names)} — 다르면 DFC 가 조용히 빈 칸으로 둔다")
    n["bbox_decoders"] = [{"name": f"bbox_decoder_{s}", "stride": s, "reg_layer": outs[2 * i], "cls_layer": outs[2 * i + 1]}
                          for i, s in enumerate(STRIDES)]
    return n


def count_problems(cfg, group):
    """모델 스크립트의 보정·미세 학습 장수 = calib_n — 크면 DFC 가 오류, 작으면 조용히 덜 쓴다."""
    n = cfg["calib_n"][group]
    got = [int(x) for x in re.findall(r"(?:calibset_size|dataset_size)=(\d+)", alls_text(cfg, group))]
    return [] if got and all(x == n for x in got) else [f"모델 스크립트 장수 {got} ≠ calib_n {n}"]


_LOG_HEAD = re.compile(r"^(?:\[\w+\]\s*|\d{4}-\d\d-\d\d [\d:,]+ - \w+ - [\w.]+:\d+ - )")


def evidence_lines(text):
    """DFC 로그에서 실제로 돈 최적화의 증거 줄 — 수준을 명시하면 「optimization level」 문구는 안 나온다(기본값을 고르는 경로에서만).
    hef.log 와 hailo_sdk.client.log 가 같은 문장을 앞머리(시각·로거)만 달리 적으므로 문장 기준으로 한 벌만 남긴다(1-2 최종 리뷰 m8)."""
    out, seen = [], set()
    for l in text.splitlines():
        if not EVIDENCE_RE.search(l):
            continue
        key = _LOG_HEAD.sub("", l.strip())
        if key not in seen:
            seen.add(key)
            out.append(l.strip())
    return out


def end_node_problems(conv_out, end_nodes, nc):
    """conv_out = ONNX Conv 노드 이름 → 출력 채널. 끝 노드 6개가 있고 회귀 64 · 분류 nc 인지."""
    out = []
    for e in end_nodes:
        want = REG_CH if "/cv2." in e else nc
        if e not in conv_out:
            out.append(f"ONNX 에 없음: {e}")
        elif conv_out[e] != want:
            out.append(f"채널 {conv_out[e]} ≠ {want}: {e}")
    return out


def out_order_problems(chs, nc):
    """HN 출력층 채널이 (64, nc) × 3 순서인지 — NMS 의 회귀·분류 층 짝이 바뀌지 않게."""
    want = [REG_CH, nc] * 3
    return [] if list(chs) == want else [f"HN 출력층 채널 {list(chs)} ≠ {want}"]


def class_problems(model_names, cfg, group, job_names):
    """HEF 에는 클래스 이름이 없다 — best.pt 순서 · 결정표 · 실험 설정이 같아야 런타임 고정 표와 맞는다."""
    got = [model_names[i] for i in sorted(model_names)]
    out = []
    if got != cfg["class_order"][group]:
        out.append(f"best.pt 클래스 {got} ≠ 결정표 {cfg['class_order'][group]}")
    if got != list(job_names):
        out.append(f"best.pt 클래스 {got} ≠ 실험 설정 {list(job_names)}")
    return out


def export_args(cfg):
    o = cfg["onnx"]
    return {k: o[k] for k in ("opset", "imgsz", "batch", "dynamic", "simplify", "device", "nms", "quantize") if o.get(k) is not None}


def preprocess(bgr, imgsz):
    """런타임 HailoDetector.detect(Demo/detector.py)와 같은 늘리기 — imgsz = 결정표 onnx.imgsz [세로, 가로] · 비율 무시 · 보간 기본 · RGB · uint8 0~255."""
    import cv2
    h, w = imgsz
    return cv2.cvtColor(cv2.resize(bgr, (w, h)), cv2.COLOR_BGR2RGB)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _dump(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── 데스크톱 단계 ──────────────────────────────────────────────────
def conv_channels(model):
    init = {i.name: list(i.dims) for i in model.graph.initializer}
    return {n.name: init[n.input[1]][0] for n in model.graph.node if n.op_type == "Conv" and len(n.input) > 1 and n.input[1] in init}


def stage_onnx(work):
    """학습 venv — best.pt 클래스 확인 → ONNX(결정표 인자) → 끝 노드 확인 → onnx.json."""
    job, cfg = _load(work / "입력.json"), _load(work / "변환설정.json")
    os.environ["YOLO_AUTOINSTALL"] = "false"                 # 모자란 패키지를 몰래 깔지 않고 멈춘다
    import onnx
    import torch
    import ultralytics
    from ultralytics import YOLO
    t0 = time.time()
    m = YOLO(str(work / "best.pt"))
    bad = class_problems(m.names, cfg, job["group"], job["names"])
    if bad:
        sys.exit("🔴 " + " · ".join(bad))
    args = export_args(cfg)
    f = Path(m.export(format="onnx", **args))
    f.replace(work / "model.onnx")
    bad = end_node_problems(conv_channels(onnx.load(str(work / "model.onnx"))), cfg["end_nodes"][job["group"]], len(job["names"]))
    if bad:
        sys.exit("🔴 " + " · ".join(bad))
    import onnxslim
    _dump(work / "onnx.json", {"판": {"ultralytics": ultralytics.__version__, "torch": torch.__version__, "onnx": onnx.__version__,
                                       "onnxslim": onnxslim.__version__},
                                "클래스": [m.names[i] for i in sorted(m.names)], "내보내기_인자": args,
                                "해시": {"best.pt": _sha(work / "best.pt"), "model.onnx": _sha(work / "model.onnx")},
                                "시간_s": {"onnx": round(time.time() - t0, 1)}})
    print(f"onnx 끝 — {work / 'model.onnx'}")


def stage_hef(work):
    """hailo-venv(CPU) — 파싱 → 자리 채운 모델 스크립트 → 보정(학습 몫 · 런타임 늘리기) → 최적화 → 컴파일 → 변환.json."""
    job, cfg = _load(work / "입력.json"), _load(work / "변환설정.json")
    os.chdir(work)                                           # DFC 로그(hailo_sdk.client.log · acceleras.log)가 작업 폴더에 남게
    import cv2
    import numpy as np
    import tensorflow as tf
    import hailo_sdk_client
    from hailo_sdk_client import ClientRunner
    g, nc, t = job["group"], len(job["names"]), {}
    r = ClientRunner(hw_arch=cfg["hw_arch"])
    t0 = time.time()
    r.translate_onnx_model(str(work / "model.onnx"), g, start_node_names=cfg["start_nodes"] or None,
                           end_node_names=cfg["end_nodes"][g])
    t["파싱"] = round(time.time() - t0, 1)
    layers = r.get_hn_model().get_output_layers()
    outs = [l.inputs[0].rsplit("/", 1)[-1] for l in layers]
    chs = [l.output_features for l in layers]
    bad = out_order_problems(chs, nc)
    if bad:
        sys.exit("🔴 " + " · ".join(bad))
    nms = nms_config(cfg, g, outs, job["names"])
    _dump(work / "nms_config.json", nms)
    script = model_script(cfg, g, outs, str((work / "nms_config.json").resolve()), job.get("수준"), n=len(job["calib"]))
    (work / "model.alls").write_text(script, encoding="utf-8")
    r.load_model_script(script)
    arr = None                                               # 목록 + 쌓은 배열을 함께 들지 않는다(데스크톱 메모리)
    for k, p in enumerate(job["calib"]):
        im = cv2.imread(os.path.expanduser(p))
        if im is None:
            sys.exit(f"🔴 보정 사진을 못 읽음: {p}")
        x = preprocess(im, cfg["onnx"]["imgsz"])
        if arr is None:
            arr = np.empty((len(job["calib"]), *x.shape), np.uint8)
        arr[k] = x
    ds = tf.data.Dataset.from_generator(lambda: ((x.astype(np.float32), {}) for x in arr),
                                        output_signature=(tf.TensorSpec(shape=arr.shape[1:], dtype=tf.float32), {}))
    t0 = time.time()
    r.optimize(ds)
    t["최적화"] = round(time.time() - t0, 1)
    r.save_har(str(work / "model.har"))
    t0 = time.time()
    (work / "model.hef").write_bytes(r.compile())
    t["컴파일"] = round(time.time() - t0, 1)
    sys.stdout.flush()
    logs = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in (work / "hef.log", work / "hailo_sdk.client.log") if f.exists())
    lv = list(dict.fromkeys(evidence_lines(logs)))
    o = _load(work / "onnx.json")
    _dump(work / "변환.json", {
        "id": job["id"], "group": g, "시각": _now(), "코드해시": job["코드해시"],
        "판": {**o["판"], "dfc": hailo_sdk_client.__version__, "tensorflow": tf.__version__, "numpy": np.__version__, "cv2": cv2.__version__,
              "hailort_요구": cfg["hailort_target"]},
        "결정표": {"파일": "조사/HEF변환-20261004/변환설정.json", "sha256": _sha(work / "변환설정.json")},
        "수준": {"지정": int(LEVEL_RE.search(script).group(0)[-1]), "결정표와_다름": job.get("수준") is not None,
                 "미세학습": "enabled" if FINETUNE_ON_RE.search(script) else "disabled", "DFC_로그": lv},
        "클래스": o["클래스"], "내보내기_인자": o["내보내기_인자"], "hw_arch": cfg["hw_arch"],
        "끝_노드": cfg["end_nodes"][g], "HN_출력층": [{"이름": a, "채널": c} for a, c in zip(outs, chs)],
        "모델_스크립트": script, "NMS": nms,
        "보정": {"장수": len(job["calib"]), **job["보정출처"],
                 "목록_sha256": hashlib.sha256("\n".join(Path(c).stem for c in job["calib"]).encode()).hexdigest(),
                 "전처리": inspect.getsource(preprocess)},
        "해시": {**o["해시"], "model.har": _sha(work / "model.har"), "model.hef": _sha(work / "model.hef")},
        "시간_s": {**o["시간_s"], **t},
        "출력_vstream": "파이 hailortcli parse-hef 로 확인(관문 2 · 데스크톱엔 HailoRT 없음)"})
    print(f"hef 끝 — {work / 'model.hef'}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("onnx", "hef"):
        sys.exit("쓰는 법: hef_convert.py onnx|hef <작업폴더>")
    {"onnx": stage_onnx, "hef": stage_hef}[sys.argv[1]](Path(sys.argv[2]).resolve())
