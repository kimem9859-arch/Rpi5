"""시연 경로 대조 — 시연 프로그램이 모델을 부르는 길(config · create_detector · create_tool_gate)이
같은 HEF 를 HailoDetector 로 직접 부른 결과와 같은가(시연 모델 전환 계획 2026-10-07 Task 3 Step 2).

사용(Rpi5/Demo 에서 · 시스템 python3 · Hailo):
  python3 ../조사/HEF변환-20261004/시연경로대조.py <프레임 폴더> f00259 f00273 … [--btn <hef>] [--tool <hef>] [--force-hailo]
  (--btn·--tool 을 주면 config 대신 그 HEF · --force-hailo 는 config.TOOL_BACKEND 를 무시하고 NPU 갈래로 —
   셋 다 새 모델을 넣기 전 옛 HEF 로 길만 미리 볼 때만. 🔴 관문으로 쓸 때는 아무것도 주지 않는다 —
   시연 경로를 정하는 스위치(TOOL_BACKEND)까지 확인하는 것이 관문이다(리뷰 I-2))
- 시연 경로 = `detector.create_detector()` + `tool_gate.create_tool_gate()`(start → request → poll · TOOL_CONF 거름은 게이트 안)
- 직접 = `HailoDetector(hef_path=…)` 두 개 + 운용 문턱(버튼 YOLO_CONF_HIGH · 공구 TOOL_CONF)
- 🔴 두 길을 **다른 프로세스**에서 돈다 — 한 프로세스에서 같은 HEF 로 검출기를 두 번 만들면 두 번째 추론이 멈춘다
  (2026-10-07 확인 · 공유 장치가 같은 HEF 를 한 network group 으로 묶는다 · 시연은 HEF 마다 하나라 해당 없음).
- 판정 = 프레임마다 (이름, 박스 소수 1자리, 점수 소수 3자리) 목록이 같다. 다르면 종료 코드 1.
🔴 문턱을 바꿔 맞추지 않는다(계획 중단 규칙).
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(os.path.dirname(os.path.dirname(HERE)), "Demo")


def norm(dets):
    return sorted([n, round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1), round(float(s), 3)]
                  for n, s, x1, y1, x2, y2 in dets)


def _setup(btn, tool, force):
    sys.path.insert(0, DEMO)
    import config
    if force:
        config.TOOL_BACKEND = "hailo"        # 미리 보기 전용 — 관문에서는 쓰지 않는다
    if btn:
        config.HEF_MODEL_PATH = btn
    if tool:
        config.TOOL_HEF_PATH = tool
    return config


def run(mode, folder, names, btn, tool, force, out):
    import cv2
    backend = None
    config = _setup(btn, tool, force)
    backend = config.TOOL_BACKEND
    import detector
    res = {"버튼HEF": os.path.basename(config.HEF_MODEL_PATH), "공구HEF": os.path.basename(config.TOOL_HEF_PATH),
           "TOOL_BACKEND": backend, "덮어씀": bool(force or btn or tool), "프레임": {}}
    if mode == "rt":
        import tool_gate
        said = []
        b = detector.create_detector()
        g = tool_gate.create_tool_gate(log=said.append)
        res["공구갈래"] = type(g).__name__
        res["로그"] = said
        if g is None or type(g).__name__ != "HailoToolGate":
            json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)
            return                                   # 부르는 쪽이 「NPU 갈래 아님」으로 실패시킨다
        g.start()
    else:
        b = detector.HailoDetector(hef_path=config.HEF_MODEL_PATH)
        t = detector.HailoDetector(hef_path=config.TOOL_HEF_PATH, names=dict(enumerate(config.TOOL_NAMES)))
    for n in names:
        img = cv2.imread(os.path.join(folder, n + ".png"))
        btn_d = norm((b.class_name(c), s, *bb) for c, s, *bb in b.detect(img) if s >= config.YOLO_CONF_HIGH)
        if mode == "rt":
            g.request(img, None)
            got = g.poll()
            tool_d = norm(got[0]) if got else None
        else:
            tool_d = norm((t.class_name(c), s, *bb) for c, s, *bb in t.detect(img) if s >= config.TOOL_CONF)
        res["프레임"][n] = {"버튼": btn_d, "공구": tool_d}
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)


def main():
    args = sys.argv[1:]
    btn = tool = None
    force = "--force-hailo" in args
    if force:
        args.remove("--force-hailo")
    if "--btn" in args:
        i = args.index("--btn"); btn = args[i + 1]; del args[i:i + 2]
    if "--tool" in args:
        i = args.index("--tool"); tool = args[i + 1]; del args[i:i + 2]
    if args and args[0] in ("rt", "direct"):
        mode, out, folder, names = args[0], args[1], args[2], args[3:]
        run(mode, folder, names, btn, tool, force, out)
        return
    folder, names = args[0], args[1:]
    tmp = tempfile.mkdtemp()
    outs = {}
    for mode in ("rt", "direct"):
        outs[mode] = os.path.join(tmp, mode + ".json")
        extra = (["--btn", btn] if btn else []) + (["--tool", tool] if tool else []) + (["--force-hailo"] if force else [])
        r = subprocess.run([sys.executable, os.path.abspath(__file__), mode, outs[mode], folder, *names, *extra],
                           stderr=subprocess.PIPE, text=True, timeout=120)
        if r.returncode != 0:                        # HailoRT 로그가 많아 평소엔 숨기고, 죽었을 때만 꼬리를 보인다(리뷰 m11)
            sys.exit(f"❌ {mode} 단계 실패(종료 {r.returncode}):\n" + "\n".join(r.stderr.splitlines()[-15:]))
    rt = json.load(open(outs["rt"], encoding="utf-8"))
    print("config.TOOL_BACKEND:", rt["TOOL_BACKEND"], "· 덮어쓴 것:", "있음(미리 보기)" if rt["덮어씀"] else "없음(관문)")
    print("버튼 HEF:", rt["버튼HEF"], "· 공구 HEF:", rt["공구HEF"], "· 공구 갈래:", rt["공구갈래"])
    if rt["공구갈래"] != "HailoToolGate" or not rt["프레임"]:
        print("판정: ❌ 시연 경로가 NPU 공구 갈래가 아니다 — config.TOOL_BACKEND 와 모델 파일을 확인한다")
        sys.exit(1)
    di = json.load(open(outs["direct"], encoding="utf-8"))
    print("시연 경로 로그:", " / ".join(rt["로그"]))
    bad = 0
    for n in names:
        a, b = rt["프레임"][n], di["프레임"][n]
        ok_b, ok_t = a["버튼"] == b["버튼"], a["공구"] == b["공구"]
        bad += not (ok_b and ok_t)
        print(f"{n}: 버튼 {'같음' if ok_b else '다름'}({len(b['버튼'])}개 {[x[0] for x in b['버튼']]}) · "
              f"공구 {'같음' if ok_t else '다름'}({[(x[0], x[5]) for x in b['공구']]})")
    print("판정:", "✅ 모두 같다" if not bad else f"❌ 다른 프레임 {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
