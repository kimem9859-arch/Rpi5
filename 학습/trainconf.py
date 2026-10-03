"""학습 설정 — 기본.yaml 위에 실험 설정(바꾼 것만)을 합쳐 검사하고 ultralytics 학습 인자를 만든다.

정본 설계 = 상위 docs/superpowers/specs/2026-10-03-학습파라미터-체계-design.md §6 · §9
- 실험 설정 파일 이름 = id(`E<번호>[a-z]-<button|tool>-<이름>`) · `E9-` = 점검 예약(받기·장부 제외).
- 체계가 정하는 인자(data · imgsz · seed · 저장 위치 등)는 실험에서 바꾸지 않는다.
- optimizer auto 는 적은 lr0 를 무시한다(함정① · 8.4.171 trainer.py 1175~1177) — 금지.
시스템 python3(PyYAML)로 돈다 — ultralytics 를 import 하지 않는다.
"""
import copy
import re
from pathlib import Path

import yaml

GROUP_NAMES = {"button": ["B1", "B2", "B3", "B4", "EMO"], "tool": ["driver", "wrench", "pliers"]}
INPUT_MODES = {
    "늘리기640": {"train_imgsz": 640, "predict_imgsz": 640, "stretch": [640, 640]},           # detector.py 110행과 같은 늘리기
    "원본768x1024": {"train_imgsz": 1024, "predict_imgsz": [1024, 768], "stretch": None},     # [세로, 가로] = 카메라 원본
}
TRAIN_KEYS = {
    "epochs", "patience", "batch", "workers", "cache", "optimizer", "lr0", "lrf", "momentum", "weight_decay",
    "warmup_epochs", "warmup_momentum", "warmup_bias_lr", "cos_lr", "close_mosaic", "deterministic", "amp", "plots",
    "hsv_h", "hsv_s", "hsv_v", "degrees", "translate", "scale", "shear", "perspective", "flipud", "fliplr",
    "mosaic", "mixup", "cutmix", "copy_paste", "freeze", "box", "cls", "dfl", "multi_scale",
}
SYSTEM_KEYS = {"data", "imgsz", "seed", "project", "name", "exist_ok", "resume", "device", "val", "save"}
STOP_KEYS = {"포화_에폭", "포화_향상", "점수0_에폭", "점수0_mAP50", "진행없음_분", "시간상한_배"}
TOP_KEYS = {"id", "group", "나눔", "입력", "출발", "seed", "train", "멈춤", "메모"}
ID_RE = re.compile(r"^E\d+[a-z]?-(button|tool)-[A-Za-z0-9.]+$")


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def changes(base, exp):
    """장부용 — 기본과 다른 것만 「키=값」(입력 · 출발 · seed · train · 멈춤 순)."""
    out = [f"{k}={exp[k]}" for k in ("입력", "출발", "seed") if k in exp and exp[k] != base.get(k)]
    for sect in ("train", "멈춤"):
        out += [f"{k}={v}" for k, v in sorted((exp.get(sect) or {}).items()) if (base.get(sect) or {}).get(k) != v]
    return " · ".join(out) or "없음"


def resolve(base, exp, exp_stem=None):
    """기본 + 실험 → 합친 설정. 틀리면 ValueError(무엇이 틀렸는지)."""
    bad = sorted(set(exp) - TOP_KEYS)
    if bad:
        raise ValueError(f"모르는 최상위 키: {bad}")
    for k in ("id", "group"):
        if k not in exp:
            raise ValueError(f"실험 설정에 {k} 가 없다")
    if exp_stem is not None and exp["id"] != exp_stem:
        raise ValueError(f"id({exp['id']})와 파일 이름({exp_stem})이 다르다")
    m = ID_RE.match(exp["id"])
    if not m:
        raise ValueError(f"id 형식 = E<번호>[a-z]-<button|tool>-<영문·숫자> — {exp['id']}")
    if exp["group"] not in GROUP_NAMES or m.group(1) != exp["group"]:
        raise ValueError(f"group({exp['group']})이 없거나 id 의 무리와 다르다")
    tr = exp.get("train") or {}
    for k in tr:
        if k in SYSTEM_KEYS:
            raise ValueError(f"train.{k} 는 체계가 정한다 — 실험에서 바꾸지 않는다")
        if k not in TRAIN_KEYS:
            raise ValueError(f"모르는 train 키(오타?): {k}")
    st = exp.get("멈춤") or {}
    bad = sorted(set(st) - STOP_KEYS)
    if bad:
        raise ValueError(f"모르는 멈춤 키: {bad}")
    cfg = copy.deepcopy(base)
    for k in ("나눔", "입력", "출발", "seed", "메모"):
        if k in exp:
            cfg[k] = exp[k]
    cfg["train"] = {**(base.get("train") or {}), **tr}
    cfg["멈춤"] = {**(base.get("멈춤") or {}), **st}
    cfg["id"], cfg["group"] = exp["id"], exp["group"]
    if cfg.get("입력") not in INPUT_MODES:
        raise ValueError(f"모르는 입력 방식: {cfg.get('입력')} — {sorted(INPUT_MODES)}")
    if str(cfg["train"].get("optimizer", "auto")).lower() == "auto":
        raise ValueError("optimizer auto 는 적은 lr0 를 무시한다(함정①) — 직접 적는다")
    if set(cfg["멈춤"]) != STOP_KEYS:
        raise ValueError(f"멈춤 키가 빠졌다: {sorted(STOP_KEYS - set(cfg['멈춤']))}")
    cfg["바꾼것"] = changes(base, exp)
    return cfg


def train_kwargs(cfg):
    """ultralytics YOLO.train 인자 — 데이터 경로·저장 위치는 train_one 이 붙인다."""
    return {**cfg["train"], "imgsz": INPUT_MODES[cfg["입력"]]["train_imgsz"], "seed": int(cfg["seed"])}
