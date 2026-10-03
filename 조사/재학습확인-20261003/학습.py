"""재학습 확인 — 장소1 place1(b001~b009 2,010장)으로 버튼·공구 yolov8n 을 Colab T4 에서 시험 학습한다(확인용 · 시연 모델 교체 아님).

실행(Rpi5/Demo/ 에서, rfenv): ~/env/rfenv/bin/python ../조사/재학습확인-20261003/학습.py --group button|tool [--build-only]
- 데이터 = `tool_round.build_dataset`(촬영 세션마다 프레임 순서 마지막 20% 를 떼어 둠 — 반복 학습과 같은 나눔)
  → 학습용에서만 그 모델의 배경(찾을 물체가 없는 사진)을 10% 로 줄인다(무작위 · 시드 고정 · 사용자 2026-10-03) · 떼어 둔 사진은 그대로
    (줄이기 전 배경 = 버튼 29% · 공구 60% · 권장 0~10% = dev/ai_model/학습이론.md)
- 학습 = `train_tool_round.train_colab`(Colab T4 · 50 에폭 · val=False · last.pt) — 새로 짜지 않는다
- 출발 가중치 = Demo/models/yolov8n.pt — 시연 모델(console_v2 · tool_v3)과 같은 구조. 🔴 그래도 차이 = 장소1 데이터 + 학습 설정(tool_v3 = 100 에폭·회전 30·val 사용 · 이번 = 50 에폭·회전 0·val=False) + (버튼) 배포 경로(HEF int8) — 데이터 탓만으로 읽지 않는다(리뷰 2026-10-03)
- 개인정보 관문 = 올릴 사진 전부가 ~/data/label_train/privacy_cleared.txt 에 있어야 한다(사용자 2026-10-03 「이전 근거대로 올려도 되」)
출력 = ~/data/label_train/check_<group>_20261003/(학습 폴더 · runs/yolov8n/last.pt · colab_log.txt) — Demo/models/ 에 두지 않는다.
"""
import argparse
import random
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2] / "Demo"
sys.path.insert(0, str(DEMO / "test"))
import tool_round as TR             # noqa: E402
import train_tool_round as TTR      # noqa: E402

PLACE1 = Path.home() / "data/label_dataset/place1"
CLEARED = Path.home() / "data/label_train/privacy_cleared.txt"
WORK = Path.home() / "data/label_train"


def cap_background(ds, frac=0.10, seed=20261003):
    """학습용(images/train · labels/train)에서 빈 라벨 사진을 전체의 frac 이 되게 뺀다. 반환 = (물체 있음, 남긴 배경, 뺀 배경)."""
    lab = ds / "labels" / "train"
    files = sorted(lab.glob("*.txt"))
    bg = [f for f in files if not f.read_text(encoding="utf-8").strip()]
    pos = len(files) - len(bg)
    keep = round(pos * frac / (1 - frac))
    drop = sorted(set(bg) - set(random.Random(seed).sample(bg, min(keep, len(bg)))))
    for f in drop:
        f.unlink()
        for img in (ds / "images" / "train").glob(f.stem + ".*"):
            img.unlink()
    return pos, len(bg) - len(drop), len(drop)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=("button", "tool"), required=True)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--build-only", action="store_true", help="데이터만 만들고(이미 있으면 그대로) 멈춘다")
    a = ap.parse_args()
    names = [l.split("\t")[0] for l in (PLACE1 / "images.txt").read_text(encoding="utf-8").splitlines() if "\t" in l]
    probs = TR.privacy_problems(names, [], set(CLEARED.read_text(encoding="utf-8").split()))
    if probs:
        sys.exit("🔴 " + " · ".join(probs))
    ds = WORK / f"check_{a.group}_20261003"
    if not ds.exists():
        r = TR.build_dataset(PLACE1, ds, frac=0.2, group=a.group)
        pos, kept, dropped = cap_background(ds)
        print(f"데이터 {ds} · 나눔 학습 {len(r['train'])} · 떼어 둠 {len(r['val'])} · 박스 {r['boxes']}"
              f" · 학습용 배경 줄임 — 물체 있음 {pos} · 배경 남김 {kept} · 뺌 {dropped}")
    n = {part: len(list((ds / "labels" / part).glob("*.txt"))) for part in ("train", "val")}
    bgn = {part: sum(1 for f in (ds / "labels" / part).glob("*.txt") if not f.read_text(encoding="utf-8").strip()) for part in n}
    print(f"지금 {ds.name} · 학습 {n['train']}장(배경 {bgn['train']} · {bgn['train'] / n['train']:.1%}) · 떼어 둠 {n['val']}장(배경 {bgn['val']} · {bgn['val'] / n['val']:.1%})")
    if a.build_only:
        return
    out, _, log = TTR.train_colab([DEMO / "models/yolov8n.pt"], ds, a.epochs, f"chk-{a.group}-1003", group=a.group)
    print("결과", {k: (str(p), f"{m}분") for k, (p, m) in out.items()}, "· 로그", log)
    if not out:
        sys.exit("🔴 받은 가중치가 없다 — colab_log.txt 확인")


if __name__ == "__main__":
    main()
