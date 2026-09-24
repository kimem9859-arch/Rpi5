"""오탐 검수용 사진 만들기 — 저장된 raw PNG 에 「실제 시연 프로그램이 판정에 쓴 박스」만 그린다.

실행 (Rpi5/Demo 안에서):
    python3 ../조사/오탐검토-오버레이.py <세션 이름> <출력 폴더> [--limit N]
    예) python3 ../조사/오탐검토-오버레이.py 20260923_193013_esp32_tool-free-r1_console_v2 ~/data/review/20260923_공구r1_오탐검토

무엇을 그리나 (2026-09-24 사용자 요청으로 정한 규칙):
- `test/logs/<세션>_rawdet_log.csv`(촬영 순간 모델이 낸 값 그대로 — 다시 추론하지 않는다)를
  **실제 시연 프로그램의 추적 함수 `camera_thread._update_tracks`**(클래스당 1개 · 새 박스는 ≥0.65 ·
  가려도 5프레임 유지)로 1프레임부터 차례로 재생한다. 벤치 도구의 추적은 클래스당 1개 규칙이 없어 쓰지 않는다.
- 그 프레임에 **새로 잡힌 트랙(miss == 0)만** 굵게 그린다 — 유지(hold) 박스와 화면에 안 나온 원시 검출은
  그리지 않는다(검수가 쉬워야 한다 · hold 는 앞 프레임 박스의 연장이라 오탐을 놓치지 않는다).
- 박스 색은 런타임 단일 출처 `camera_thread.box_bgr`. 파일 이름·왼쪽 위 = 프레임 번호.
- 원본 PNG 가 있는 프레임(촬영 때 N프레임에 1장)만 나온다. `_목록.csv` 에 프레임별 박스 수·클래스.

🔴 `camera_thread` 를 import 하면 Hailo 탐지기가 열린다 — 끝에서 반드시 닫는다(닫지 않으면 종료 중 크래시).
"""
import argparse
import collections
import csv
import os
import sys

import cv2

sys.path.insert(0, os.getcwd())
import config                  # noqa: E402,F401 — camera_thread 가 쓴다
import camera_thread as ct     # noqa: E402

CLASS = ["B1", "B2", "B3", "B4", "EMO"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N장만 만든다(시험용)")
    a = ap.parse_args()
    raw = os.path.join("test/raw", a.session)
    log = os.path.join("test/logs", f"{a.session}_rawdet_log.csv")
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)

    det = collections.defaultdict(list)
    for r in csv.DictReader(open(log)):
        det[int(r["frame"])].append((CLASS.index(r["cls_name"]), float(r["score"]),
                                     *[int(float(r[k])) for k in ("x1", "y1", "x2", "y2")]))
    saved = {int(n[1:6]) for n in os.listdir(raw) if n.endswith(".png")}

    tracks, rows = [], []
    for k in range(1, max(max(det), max(saved)) + 1):
        tracks = ct._update_tracks(tracks, det.get(k, []))
        fresh = [t for t in tracks if t["miss"] == 0]
        if k not in saved or not fresh:
            continue
        img = cv2.imread(os.path.join(raw, f"f{k:05d}.png"))
        for t in fresh:
            name = CLASS[t["cls"]]
            col = ct.box_bgr(name)
            x1, y1, x2, y2 = t["box"]
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 4)
            for c, w in (((0, 0, 0), 5), (col, 2)):
                cv2.putText(img, f"{name} {t['score']:.2f}", (x1, max(28, y1 - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, c, w)
        for c, w in (((0, 0, 0), 6), ((255, 255, 255), 2)):
            cv2.putText(img, f"f{k:05d}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.3, c, w)
        cv2.imwrite(os.path.join(out, f"f{k:05d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        rows.append([f"f{k:05d}", len(fresh), " ".join(sorted({CLASS[t["cls"]] for t in fresh}))])
        if a.limit and len(rows) >= a.limit:
            break

    with open(os.path.join(out, "_목록.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["프레임", "박스 수", "클래스"])
        w.writerows(rows)
    print(f"저장 {len(rows)}장 → {out}")


if __name__ == "__main__":
    try:
        main()
    finally:
        ct.close_detector()
