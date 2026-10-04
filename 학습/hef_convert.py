"""HEF 변환 — 1-2단계 설계 §8.3. 값은 조사/HEF변환-20261004/변환설정.json(조사 결론)만 읽는다.

데스크톱에서 두 단계로 돈다(파이 명령 = 학습.py 변환 <id> 가 작업 폴더를 만들고 띄운다):
  onnx 단계 = ~/학습실험/venv(ultralytics 8.4.171)  : python hef_convert.py onnx <작업폴더>
  hef 단계  = ~/hailo-venv(DFC 3.33.1 · CPU)       : python hef_convert.py hef <작업폴더>
작업 폴더 = best.pt · 입력.json(id · group · names · calib · 수준) · 변환설정.json → model.onnx · model.hef · 변환.json
레시피 = ultralytics 8.4.171 export_hailo(끝 노드 6개 · 분류 시그모이드 · NMS json) — 바꾼 것은 조사보고서 §4:
보정 = 학습 몫 · 런타임과 같은 늘리기 · 고정 시드 · 최적화 수준 명시(CPU 에서 빠뜨리면 0 으로 떨어진다).
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
LEVEL_RE = re.compile(r"optimization_level=\d")


# ── 순수 함수(시험 대상) ─────────────────────────────────────────────
def pick_calib(train_names, n, seed):
    names = sorted(train_names)
    if n >= len(names):
        return names
    return sorted(random.Random(seed).sample(names, n))


def alls_text(cfg, group):
    return "".join(l + "\n" for l in cfg["alls"][group])


def _need_six(outs):
    if len(outs) != 6:
        raise ValueError(f"HN 출력층이 6개가 아니다({len(outs)}): {outs} — 끝 노드를 확인한다")


def model_script(cfg, group, outs, nms_path, level=None):
    """결정표 줄의 자리(<cls_s*> · NMS json 이름)를 파싱 결과로 채운다. level 이 있으면 최적화 수준만 바꿔 시험한다."""
    _need_six(outs)
    s = alls_text(cfg, group)
    if not LEVEL_RE.search(s):
        raise ValueError("모델 스크립트에 optimization_level 줄이 없다 — CPU 에서는 조용히 수준 0 이 된다")
    if level is not None:
        s = LEVEL_RE.sub(f"optimization_level={int(level)}", s)
    for slot, i in CLS_SLOTS.items():
        s = s.replace(slot, outs[i])
    s = re.sub(r'nms_postprocess\("[^"]*"', f'nms_postprocess("{nms_path}"', s)
    left = re.findall(r"<[A-Za-z_0-9]+>", s)
    if left:
        raise ValueError(f"채우지 못한 자리: {left}")
    return s


def nms_config(cfg, group, outs, names):
    _need_six(outs)
    n = copy.deepcopy(cfg["nms_config"][group])
    if n["classes"] != len(names):
        raise ValueError(f"NMS classes {n['classes']} ≠ 모델 클래스 {len(names)} — 다르면 DFC 가 조용히 빈 칸으로 둔다")
    n["bbox_decoders"] = [{"name": f"bbox_decoder_{s}", "stride": s, "reg_layer": outs[2 * i], "cls_layer": outs[2 * i + 1]}
                          for i, s in enumerate(STRIDES)]
    return n


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


def preprocess(bgr, size=640):
    """런타임 HailoDetector.detect(Demo/detector.py)와 같은 늘리기 — 비율 무시 · 보간 기본 · RGB · uint8 0~255."""
    import cv2
    return cv2.cvtColor(cv2.resize(bgr, (size, size)), cv2.COLOR_BGR2RGB)


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
    _dump(work / "onnx.json", {"판": {"ultralytics": ultralytics.__version__, "torch": torch.__version__, "onnx": onnx.__version__},
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
    script = model_script(cfg, g, outs, str((work / "nms_config.json").resolve()), job.get("수준"))
    (work / "model.alls").write_text(script, encoding="utf-8")
    r.load_model_script(script)
    imgs = []
    for p in job["calib"]:
        im = cv2.imread(os.path.expanduser(p))
        if im is None:
            sys.exit(f"🔴 보정 사진을 못 읽음: {p}")
        imgs.append(preprocess(im))
    arr = np.stack(imgs)
    ds = tf.data.Dataset.from_generator(lambda: ((x.astype(np.float32), {}) for x in arr),
                                        output_signature=(tf.TensorSpec(shape=arr.shape[1:], dtype=tf.float32), {}))
    t0 = time.time()
    r.optimize(ds)
    t["최적화"] = round(time.time() - t0, 1)
    r.save_har(str(work / "model.har"))
    t0 = time.time()
    (work / "model.hef").write_bytes(r.compile())
    t["컴파일"] = round(time.time() - t0, 1)
    log = work / "hailo_sdk.client.log"
    lv = [l.strip() for l in (log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else [])
          if "optimization level" in l.lower()]
    o = _load(work / "onnx.json")
    _dump(work / "변환.json", {
        "id": job["id"], "group": g, "시각": _now(), "코드해시": job["코드해시"],
        "판": {**o["판"], "dfc": hailo_sdk_client.__version__, "hailort_요구": cfg["hailort_target"]},
        "결정표": {"파일": "조사/HEF변환-20261004/변환설정.json", "sha256": _sha(work / "변환설정.json")},
        "수준": {"지정": int(LEVEL_RE.search(script).group(0)[-1]), "결정표와_다름": job.get("수준") is not None,
                 "DFC_로그": lv},
        "클래스": o["클래스"], "내보내기_인자": o["내보내기_인자"], "hw_arch": cfg["hw_arch"],
        "끝_노드": cfg["end_nodes"][g], "HN_출력층": [{"이름": a, "채널": c} for a, c in zip(outs, chs)],
        "모델_스크립트": script, "NMS": nms,
        "보정": {"장수": len(job["calib"]), "시드": 0, "몫": "train", "목록_sha256": hashlib.sha256("\n".join(job["calib"]).encode()).hexdigest(),
                 "전처리": inspect.getsource(preprocess)},
        "해시": {**o["해시"], "model.hef": _sha(work / "model.hef")},
        "시간_s": {**o["시간_s"], **t},
        "출력_vstream": "파이 hailortcli parse-hef 로 확인(관문 2 · 데스크톱엔 HailoRT 없음)"})
    print(f"hef 끝 — {work / 'model.hef'}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("onnx", "hef"):
        sys.exit("쓰는 법: hef_convert.py onnx|hef <작업폴더>")
    {"onnx": stage_onnx, "hef": stage_hef}[sys.argv[1]](Path(sys.argv[2]).resolve())
