"""HEF 변환(학습/hef_convert.py) 순수 부분과 파이 명령의 캘리브레이션 목록을 고정한다.

실행: python3 Demo/selftest/test_train_hef.py
정본 설계: 상위 docs/superpowers/specs/2026-10-04-학습파라미터-체계-1-2단계-design.md §8.3
값의 근거 = 조사/HEF변환-20261004/변환설정.json · 조사보고서.md(§2 끝 노드 · NMS · §4 함정)
⚠️ DFC·ultralytics 없이 돈다 — hef_convert.py 는 그것들을 단계 함수 안에서만 import 한다.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

_RPI5 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_RPI5, "학습"))

import hef_convert as H
import split as SP

_spec = importlib.util.spec_from_file_location("hakseup_cli", os.path.join(_RPI5, "학습", "학습.py"))
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)

_fails = []
CFG = json.loads((Path(_RPI5) / "조사" / "HEF변환-20261004" / "변환설정.json").read_text(encoding="utf-8"))
OUTS = ["conv41", "conv42", "conv52", "conv53", "conv62", "conv63"]


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def test_캘리브():
    print("[1] 캘리브레이션 = 학습 몫에서만 · 시드로 섞은 순서 그대로(DFC 는 받은 순서로 배치 · 셔플 버퍼 1) · 같은 시드면 같은 목록(Review Focus 5)")
    d = {"train": [f"a__f{i:05d}" for i in range(100)], "val": ["v1"], "test": ["t1"]}
    c = H.pick_calib(d["train"], 20, 0)
    check(len(c) == 20 and set(c) <= set(d["train"]) and not set(c) & {"v1", "t1"}, "학습 몫만 20장")
    check(c == H.pick_calib(d["train"], 20, 0) and c != H.pick_calib(d["train"], 20, 1), "시드로 재현")
    a = H.pick_calib(d["train"], 500, 0)
    check(sorted(a) == sorted(d["train"]) and a != sorted(d["train"]), "모자라면 전부 · 그래도 섞는다(이름순 = 세션순이 아님)")
    check(c != sorted(c), "고른 것도 섞인 순서 그대로(다시 정렬하지 않음)")
    sp = SP.load_split(Path(_RPI5) / "학습" / "나눔" / "place1_v1.json")
    for g in ("button", "tool"):
        tr, va, te = SP.lists_for(sp, g)
        c = T.convert_calib(sp, g, CFG)
        check(len(c) == min(CFG["calib_n"][g], len(tr)) and set(c) <= set(tr) and not set(c) & (set(va) | set(te)),
              f"place1_v1 {g}: {len(c)}장 · 학습 몫만 · 검증·채점 없음")


def test_모델_스크립트():
    print("[2] 결정표 → 모델 스크립트 줄 · 무리별")
    cfg = {"alls": {"button": ["normalization1 = normalization([0.0, 0.0, 0.0], [255.0, 255.0, 255.0])"], "tool": ["a", "b"]}}
    check(H.alls_text(cfg, "tool") == "a\nb\n" and "normalization" in H.alls_text(cfg, "button"), "무리별 줄")


def test_자리_채우기():
    print("[3] 모델 스크립트 자리 채우기 — 분류 출력 3개 · NMS json 절대경로 · 수준(조사보고서 §2 NMS · 원문대조)")
    s = H.model_script(CFG, "tool", OUTS, "/x/nms_config.json")
    check("<" not in s.replace("<=", ""), "규칙 자리(<cls_s*>) 남지 않음")
    check(all(f"change_output_activation({o}, sigmoid)" in s for o in ("conv42", "conv53", "conv63")), "분류 = HN 출력 1·3·5번")
    check(not any(f"change_output_activation({o}," in s for o in ("conv41", "conv52", "conv62")), "회귀(0·2·4번)에는 시그모이드 없음")
    check('nms_postprocess("/x/nms_config.json", meta_arch=yolov8, engine=cpu)' in s, "NMS json = 절대경로(문자열 스크립트는 현재 폴더 기준)")
    check("optimization_level=2" in s and "calibset_size=634" in s, "결정표 수준·캘리브 장수 그대로")
    s1 = H.model_script(CFG, "tool", OUTS, "/x/n.json", level=1)
    check("optimization_level=1" in s1 and "optimization_level=2" not in s1, "수준 바꿔 시험(1 대 2)")
    check("post_quantization_optimization(finetune, policy=disabled)" in s1 and "policy=enabled" not in s1,
          "수준 1 은 미세 학습을 끈다(명시 줄이 수준 기본값을 덮는다 · mo_script_parser deep_update)")
    check("post_quantization_optimization(finetune, policy=enabled, dataset_size=634)" in s, "수준 2(결정표)는 미세 학습 그대로")
    comp = {"alls": {"tool": CFG["alls"]["tool"] + ["performance_param(compiler_optimization_level=2)"]}}
    check("compiler_optimization_level=2" in H.model_script(comp, "tool", OUTS, "/x/n.json", level=1), "컴파일러 수준 줄은 건드리지 않음")
    check(raises(lambda: H.model_script(CFG, "tool", OUTS[:5], "/x/n.json")), "출력층이 6개가 아니면 멈춤")
    no_flavor = {"alls": {"tool": [l for l in CFG["alls"]["tool"] if "optimization_flavor" not in l]}}
    check(raises(lambda: H.model_script(no_flavor, "tool", OUTS, "/x/n.json")),
          "수준 줄이 없으면 멈춤(CPU 에서 조용히 0 으로 떨어진다 · 조사보고서 §4 함정 4)")
    left = {"alls": {"tool": CFG["alls"]["tool"] + ["foo(<cls_s64>)"]}}
    check(raises(lambda: H.model_script(left, "tool", OUTS, "/x/n.json")), "모르는 자리가 남으면 멈춤")


def test_NMS_설정():
    print("[4] NMS 설정 — 회귀·분류 층 채움 · 클래스 수 명시(원문대조: 다르면 조용히 빈 칸)")
    n = H.nms_config(CFG, "button", OUTS, ["B1", "B2", "B3", "B4", "EMO"])
    dec = n["bbox_decoders"]
    check([(x["stride"], x["reg_layer"], x["cls_layer"]) for x in dec]
          == [(8, "conv41", "conv42"), (16, "conv52", "conv53"), (32, "conv62", "conv63")], "stride 8·16·32 = (0,1)·(2,3)·(4,5)")
    check(n["classes"] == 5 and "규칙" not in json.dumps(n, ensure_ascii=False), "클래스 5 · 규칙 문자열 없음")
    check(CFG["nms_config"]["button"]["bbox_decoders"][0]["reg_layer"].startswith("규칙"), "결정표 원본은 바꾸지 않음")
    check(raises(lambda: H.nms_config(CFG, "tool", OUTS, ["driver", "wrench"])), "클래스 수가 모델과 다르면 멈춤")


def test_끝_노드():
    print("[5] 끝 노드 6개 — ONNX 에 있고 채널 = 회귀 64 · 분류 nc(조사보고서 §2.1)")
    ends = CFG["end_nodes"]["tool"]
    good = {e: (64 if "/cv2." in e else 3) for e in ends}
    check(H.end_node_problems(good, ends, 3) == [], "모두 맞음 → 문제 없음")
    p = H.end_node_problems({k: v for k, v in good.items() if "cv3.2" not in k}, ends, 3)
    check(len(p) == 1 and "cv3.2" in p[0], "하나 없음 → 그 이름")
    p = H.end_node_problems(good, ends, 5)
    check(len(p) == 3 and all("cv3." in x for x in p), "분류 채널이 nc 와 다름 → 분류 3개")
    check(H.out_order_problems([64, 3, 64, 3, 64, 3], 3) == [] and H.out_order_problems([3, 64, 3, 64, 3, 64], 3) != [],
          "HN 출력층 = (회귀 64, 분류 nc) × 3 순서 — 짝이 바뀌면 멈춤")


def test_클래스_순서():
    print("[6] 클래스 순서 — best.pt model.names · 결정표 · 실험 설정이 같아야(HEF 에는 이름이 없다 · §4 함정 10)")
    names = {0: "driver", 1: "wrench", 2: "pliers"}
    check(H.class_problems(names, CFG, "tool", ["driver", "wrench", "pliers"]) == [], "같음 → 문제 없음")
    check(H.class_problems({0: "wrench", 1: "driver", 2: "pliers"}, CFG, "tool", ["driver", "wrench", "pliers"]) != [], "순서 다름 → 문제")
    check(H.class_problems(names, CFG, "tool", ["driver", "pliers", "wrench"]) != [], "실험 설정과 다름 → 문제")


def test_전처리_크기():
    print("[8] 보정 전처리 크기 = 결정표 onnx.imgsz [세로, 가로] · BGR→RGB · NMS 크기 대조 · 학습 입력 = 변환 크기(학습=변환=보정=시연 한 묶음 · §8.6)")
    import numpy as np
    img = np.zeros((1024, 768, 3), np.uint8)
    img[..., 0] = 255                                            # BGR 의 파랑
    a, b = H.preprocess(img, [640, 640]), H.preprocess(img, [1024, 768])
    check(a.shape == (640, 640, 3) and b.shape == (1024, 768, 3), "크기 = 결정표 값(세로, 가로)")
    check(a[0, 0].tolist() == [0, 0, 255], "BGR → RGB")
    check(H.preprocess(img, CFG["onnx"]["imgsz"]).shape == (640, 640, 3), "지금 결정표 = 640×640")
    bad = json.loads(json.dumps(CFG))
    bad["onnx"]["imgsz"] = [1024, 768]
    check(raises(lambda: H.nms_config(bad, "button", OUTS, ["B1", "B2", "B3", "B4", "EMO"])), "NMS image_dims ≠ ONNX imgsz → 멈춤")
    check(T.input_problems({"stretch": [640, 640], "predict_imgsz": 640}, CFG) == [], "늘리기640 으로 학습 = 결정표 640 → 문제 없음")
    check(T.input_problems({"stretch": None, "predict_imgsz": [1024, 768]}, CFG) != [], "768×1024 원본으로 학습했는데 결정표 640 → 멈춤")
    check(T.input_problems({"stretch": None, "predict_imgsz": [1024, 768]}, bad) == [], "결정표도 [1024, 768] 이면 → 문제 없음")


def test_장수_대조():
    print("[9] 모델 스크립트의 보정·미세 학습 장수 = calib_n(크면 DFC 오류 · 작으면 조용히 덜 씀)")
    check(H.count_problems(CFG, "button") == [] and H.count_problems(CFG, "tool") == [], "결정표 두 무리 = calib_n")
    bad = json.loads(json.dumps(CFG))
    bad["calib_n"]["tool"] = 600
    check(H.count_problems(bad, "tool") != [], "calib_n 만 바꾸면 → 문제")


def test_로그_증거():
    print("[10] DFC 로그의 증거 줄 — 수준을 명시하면 「optimization level」 문구가 안 나온다 → 알고리즘 줄을 남긴다")
    log = ("[info] Starting Finetune\n잡음 줄\n[info] Using dataset with 1024 entries for finetune\n"
           "[info] Model Optimization Algorithm Finetune is done (completion time is 01:02:03.4)\n"
           "[info] Bias Correction skipped\n[warning] Reducing compression level to 0 because requested optimization level equal or less than 1")
    got = H.evidence_lines(log)
    check(len(got) == 5 and "잡음 줄" not in got, "알고리즘 시작·끝·건너뜀·장수·수준 문구만")


def test_파이_명령():
    print("[7] 파이 명령 — 원격 폴더 이름 · CODE_FILES")
    check("hef_convert.py" in T.CODE_FILES, "데스크톱 코드 폴더로 보냄")
    check(T.convert_dirname("E0b-button-s0", None) == "E0b-button-s0" and T.convert_dirname("E0b-button-s0", 1) == "E0b-button-s0_L1",
          "수준을 바꾼 시험은 따로(결정표 변환을 덮지 않음)")
    check(T.CALIB_SEED == 0, "보정 시드는 한 곳(CALIB_SEED)")


def test_로그_증거_한벌():
    print("[11] 로그 증거 줄 — hef.log 와 client.log 의 같은 문장은 한 벌만(앞머리 시각·로거만 다름 · 1-2 최종 리뷰 m8)")
    a = "[info] Using dataset with 1024 entries for finetune"
    b = "2026-10-04 23:10:01,123 - INFO - qft.py:332 - Using dataset with 1024 entries for finetune"
    c = "[info] Model Optimization Algorithm Quantization-Aware Fine-Tuning is done (completion time is 00:30:20.00)"
    got = H.evidence_lines("\n".join([a, c, b]))
    check(len(got) == 2 and got[0] == a, f"같은 문장 두 벌 → 한 벌 · 첫 줄 그대로 — {got}")

if __name__ == "__main__":
    test_캘리브()
    test_모델_스크립트()
    test_자리_채우기()
    test_NMS_설정()
    test_끝_노드()
    test_클래스_순서()
    test_전처리_크기()
    test_장수_대조()
    test_로그_증거()
    test_파이_명령()
    test_로그_증거_한벌()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ HEF 변환 검증 통과")
