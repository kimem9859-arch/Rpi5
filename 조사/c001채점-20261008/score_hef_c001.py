"""Task 4·5 — HEF 채점: 시연 검출기(detector.HailoDetector) 그대로 + 사진별 기록 + conf 훑기 (설계 §4.3).

실행(python3 · HEF 마다 따로): python3 score_hef_c001.py --hef <HEF 이름> --set <c001|dark>
🔴 같은 HEF 를 한 프로세스에서 두 번 올리지 않는다 · 다른 프로세스(시연 Demo/main.py 등)가 NPU 를 쓰고 있으면 멈춘다.
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

import cv2

import common as C

SWEEP = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]       # score_hef 와 같은 칸


def npu_users():
    """/dev/hailo0 을 연 다른 프로세스(pid · 명령줄) — 시연은 Demo/main.py 로 뜨므로 이름이 아니라 장치로 본다.
    ⚠️ 다른 사용자(root 등)의 프로세스는 fd 를 볼 수 없어 건너뛴다 — 그때 장치 경쟁은 HailoRT 오류로 크게 드러난다(조용히 틀리지 않음)."""
    me, out = os.getpid(), []
    for pdir in Path("/proc").glob("[0-9]*"):
        try:
            if int(pdir.name) != me and any("hailo" in os.readlink(f) for f in (pdir / "fd").iterdir()):
                out.append(f"{pdir.name} {(pdir / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')[:60]}")
        except (PermissionError, FileNotFoundError, OSError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hef", required=True, choices=[h[0] for h in C.HEFS])
    ap.add_argument("--set", required=True, choices=["c001", "dark"])
    a = ap.parse_args()
    busy = npu_users()
    if busy:
        sys.exit(f"🔴 다른 프로세스가 NPU(/dev/hailo0)를 쓰고 있다 — {busy} · 시연(Demo/main.py) 등을 끄고 다시(Review Focus 4)")
    name, path, g, _pair, _s = next(h for h in C.HEFS if h[0] == a.hef)
    import config
    config.HEF_MODEL_PATH = str(path)                    # create_detector 전에(score_hef 와 같은 방법)
    from detector import create_detector
    import score_hef as SH
    import scoring
    from score_lib import operating_point
    names = C.NAMES[g]
    sd = C.set_dir(a.set)
    labels = SH.load_labels(str(sd / f"labels_{g}"), (768, 1024))
    det = create_detector()
    per_image, rec = {}, {}
    try:
        for n in C.set_names(a.set):
            dets = det.detect(cv2.imread(str(sd / "orig" / f"{n}.png")))      # 런타임과 같은 길
            per_image[n] = (labels[n], [tuple(d) for d in dets])
            rec[n] = {"gt": [list(x) for x in labels[n]], "pred": [list(d) for d in dets]}
    finally:
        det.close()
    sweep = {f"{c:.2f}": {k: {x: v[x] for x in ("tp", "fp", "fn")} for k, v in operating_point(per_image, names, c).items()}
             for c in SWEEP}
    C.write_json(C.W / "out" / "hef" / a.set / f"{name}.json",
                 {"hef": name, "group": g, "set": a.set, "요약": scoring.summarize(per_image, names, C.CONF),
                  "사진별": rec, "훑기": sweep, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "라벨지문": C.load_json(C.W / "prep.json")["묶음"][a.set]["지문"]})
    s = scoring.summarize(per_image, names, C.CONF)
    print(f"{name} {a.set} 사진 {s['사진']} · 정답 {s['정답박스']} — 저장")


if __name__ == "__main__":
    main()
