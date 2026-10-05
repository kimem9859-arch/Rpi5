"""T-full-base(시드 0·1·2) 대 tool_r2 — 두 모델 모두 배우지 않고 둘 다 초벌을 그리지 않은 사진으로 채점(읽기 전용 조사).
사진 = place1_v1 「unused」 ∩ tool_r2 떼어 둔 몫(b001·b002 세션 끝) · 정답 = 사람 검토 8종 라벨.
각 모델은 학습 때 입력 그대로 — T-full-base = 640×640 늘리기(train_one.py:136) · tool_r2 = 원본(imgsz 640 · train_tool_round.py:122).
채점 = 학습 체계 scoring.score_model 그대로."""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, "/home/pi/sop-project/Rpi5/학습")
sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo/test")  # score_lib
import scoring  # noqa: E402

TMP = Path.home() / "data/학습실험/라벨링모델비교-20261005/75장"  # 사진 사본 · 결과.json 은 이 폴더로 옮겨 둠
NAMES = ["driver", "wrench", "pliers"]
H = Path.home()
SRC = H / "data/label_dataset/place1"
r1 = json.load(open(H / "data/label_models/tool_r1.json"))
r2 = json.load(open(H / "data/label_models/tool_r2.json"))
b001 = set(r1["train"]) | set(r1["val"])
split = json.load(open("/home/pi/sop-project/Rpi5/학습/나눔/place1_v1.json"))
pick = sorted(set(split["공통"]["unused"]) & set(r2["val"]))
idx = dict(l.split("\t") for l in (SRC / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip())

sets = {"전체": pick, "b001": [n for n in pick if n in b001], "b002": [n for n in pick if n not in b001]}
models = {
    "T-full-base-s0": (H / "data/학습실험/E0c-tool-f120/best.pt", "stretch"),
    "T-full-base-s1": (H / "data/학습실험/E0c-tool-f120s1/best.pt", "stretch"),
    "T-full-base-s2": (H / "data/학습실험/E0c-tool-f120s2/best.pt", "stretch"),
    "tool_r2": (H / "data/label_models/tool_r2.pt", "orig"),
}
out = {}
for sname, names in sets.items():
    dirs = {"orig": TMP / sname / "orig", "stretch": TMP / sname / "stretch"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    for n in names:
        o = dirs["orig"] / f"{n}.png"
        if not o.exists():
            o.symlink_to(idx[n])
        s = dirs["stretch"] / f"{n}.png"
        if not s.exists():
            cv2.imwrite(str(s), cv2.resize(cv2.imread(idx[n]), (640, 640)))
    for mname, (w, kind) in models.items():
        for conf in (0.65, 0.25):
            r = scoring.score_model(w, dirs[kind], SRC / "labels", NAMES, conf, 640)
            out[f"{sname}|{mname}|{conf}"] = r
            c = r["클래스"]
            print(f"{sname:4} {mname:15} conf {conf}  사진 {r['사진']} 정답 {r['정답박스']}  "
                  f"맞음 {r['전체']['tp']} 틀림(가짜) {r['전체']['fp']} 놓침 {r['전체']['fn']}  "
                  + " · ".join(f"{n} {c[n]['tp']}/{c[n]['tp'] + c[n]['fn']}" for n in NAMES)
                  + f"  오분류 {r['오분류']} 오검출 {r['오검출']}", flush=True)
(TMP / "결과.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
