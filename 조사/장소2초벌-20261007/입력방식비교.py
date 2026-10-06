"""장소2 초벌 입력 방식 비교(읽기 전용 조사) — 사람 라벨이 있고 비교 모델 모두 배우지 않은 장소1 사진.
① T-full-base-s0 · 640×640 늘리기(학습과 같음)  ② T-full-base-s0 · 늘리지 않음(비율 유지 640)
③ T-full-in1024-s0 · 원본 768×1024 비율 그대로(학습과 같음 · predict [1024,768])
사진 = 75장(10/5 비교 · place1_v1 unused ∩ tool_r2 val) · 292장(place1_v1 채점 몫 = 조사/재학습확인-20261003/채점사진.txt)
지표 = conf 0.65 에서 사람이 고칠 곳 = 놓침(fn) + 지울 박스(fp) — 채점 = 학습 체계 scoring.score_model 그대로."""
import json
import sys
from pathlib import Path

import cv2

R5 = Path("/home/pi/sop-project/Rpi5")
sys.path.insert(0, str(R5 / "학습"))
sys.path.insert(0, str(R5 / "Demo/test"))
import scoring  # noqa: E402

OUT = Path(sys.argv[1])
H = Path.home()
SRC = H / "data/label_dataset/place1"
NAMES = ["driver", "wrench", "pliers"]
r2 = json.load(open(H / "data/label_models/tool_r2.json"))
split = json.load(open(R5 / "학습/나눔/place1_v1.json"))
idx = dict(l.split("\t") for l in (SRC / "images.txt").read_text(encoding="utf-8").splitlines() if l.strip())
sets = {
    "75장": sorted(set(split["공통"]["unused"]) & set(r2["val"])),
    "292장": [l.strip() for l in (R5 / "조사/재학습확인-20261003/채점사진.txt").read_text().splitlines() if l.strip()],
}
models = {
    "① T-full-base 늘림": (H / "data/학습실험/E0c-tool-f120/best.pt", "stretch", 640),
    "② T-full-base 안 늘림": (H / "data/학습실험/E0c-tool-f120/best.pt", "orig", 640),
    "③ T-full-in1024 원본비율": (H / "data/학습실험/E1c-tool-f120in1024/best.pt", "orig", [1024, 768]),
}
res = {}
for sname, names in sets.items():
    dirs = {"orig": OUT / sname / "orig", "stretch": OUT / sname / "stretch"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    for n in names:
        o = dirs["orig"] / f"{n}.png"
        if not o.exists():
            o.symlink_to(idx[n])
        s = dirs["stretch"] / f"{n}.png"
        if not s.exists():
            cv2.imwrite(str(s), cv2.resize(cv2.imread(idx[n]), (640, 640)))
    for mname, (w, kind, imgsz) in models.items():
        r = scoring.score_model(w, dirs[kind], SRC / "labels", NAMES, 0.65, imgsz)
        res[f"{sname}|{mname}"] = r
        c, a = r["클래스"], r["전체"]
        print(f"{sname:5} {mname:22} 사진 {r['사진']} 정답 {r['정답박스']} 맞음 {a['tp']} 지울박스 {a['fp']} 놓침 {a['fn']} "
              f"고칠곳 {a['fp'] + a['fn']} | " + " · ".join(f"{n} {c[n]['tp']}/{c[n]['tp'] + c[n]['fn']}" for n in NAMES)
              + f" | 오분류 {r['오분류']} 오검출 {r['오검출']}", flush=True)
(OUT / "결과.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
