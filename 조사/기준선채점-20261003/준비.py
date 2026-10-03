"""기준선 채점 준비 — 장소1 사람 검토 라벨(b004~b009)을 기존 채점 도구의 입력 형태로 만든다.

실행: python3 준비.py <출력 폴더>
  버튼 → <출력>/btn/labels(버튼 줄만) · <출력>/btn/images(원본 PNG 링크 · 이름 = 라벨 이름)
         → `Demo/test/score_hef.py --labels … --images …`
  공구 → <출력>/tool/labels(공구 줄만) · <출력>/tool/images(원본을 JPEG 로 · 시연 `tool_gate` 와 같은 품질)
         · <출력>/tool/data.yaml → `Demo/test/holdout_score.py <출력>/tool --model models/tool_v3.pt`

왜 b004~b009 만 — b001~b003 버튼 초벌은 지금 시연 버튼 모델(console_v2.hef), b001 공구 초벌은 지금 시연
공구 모델(tool_v3.pt)이 그렸다. 자기가 그린 답으로 자기를 채점하면 점수가 부풀려진다.
exclude 사진은 place1 에 라벨이 없어 저절로 빠진다. 박스 없는 사진(배경)은 빈 라벨로 들어가 오검출만 센다.
"""
import json
import sys
from pathlib import Path

import cv2

DEMO = Path(__file__).resolve().parents[2] / "Demo"      # Rpi5/조사/<이 폴더>/준비.py → Rpi5/Demo
sys.path.insert(0, str(DEMO))
from tool_gate import _JPEG_QUALITY   # noqa: E402  시연이 공구 모델에 넘기는 JPEG 품질 — 다시 정하지 않는다

BATCHES = [f"b{i:03d}" for i in range(4, 10)]
NAMES = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]
BTN, TOOL = range(0, 5), range(5, 8)
PLACE1 = Path.home() / "data/label_dataset/place1"
BATCH_DIR = Path.home() / "data/label_batches"


def main(out):
    out = Path(out)
    for d in ("btn/labels", "btn/images", "tool/labels", "tool/images"):
        (out / d).mkdir(parents=True, exist_ok=True)
    (out / "tool/data.yaml").write_text("names:\n" + "".join(f"- {n}\n" for n in NAMES), encoding="utf-8")
    origin = dict(l.rstrip("\n").split("\t") for l in open(PLACE1 / "images.txt", encoding="utf-8") if l.strip())
    n = {"사진": 0, "버튼 박스": 0, "공구 박스": 0}
    for b in BATCHES:
        for r in json.load(open(BATCH_DIR / b / "manifest.json", encoding="utf-8"))["images"]:
            name = r["file"].split("__", 1)[1].rsplit(".", 1)[0]
            lab = PLACE1 / "labels" / f"{name}.txt"
            if not lab.exists():
                continue                      # exclude 사진
            lines = [l.split() for l in open(lab) if l.strip()]
            btn = [" ".join(v) for v in lines if int(v[0]) in BTN]
            tool = [" ".join(v) for v in lines if int(v[0]) in TOOL]
            (out / "btn/labels" / f"{name}.txt").write_text("".join(x + "\n" for x in btn))
            (out / "tool/labels" / f"{name}.txt").write_text("".join(x + "\n" for x in tool))
            link = out / "btn/images" / f"{name}.png"
            if not link.exists():
                link.symlink_to(origin[name])
            img = cv2.imread(origin[name])
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
            assert ok, name
            (out / "tool/images" / f"{name}.jpg").write_bytes(buf.tobytes())
            n["사진"] += 1; n["버튼 박스"] += len(btn); n["공구 박스"] += len(tool)
    print(f"묶음 {BATCHES[0]}~{BATCHES[-1]} · JPEG 품질 {_JPEG_QUALITY} ·", n)


if __name__ == "__main__":
    main(sys.argv[1])
