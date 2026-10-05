"""판정 보조 — 원본 한 구역에 50px 격자(원본 좌표 숫자)를 그려 2배로 저장. 사용: python3 격자.py <번호> x1 y1 x2 y2"""
import json, sys
from pathlib import Path
import cv2
d = json.load(open("예측.json", encoding="utf-8"))["사진"]; p = json.load(open("짝.json", encoding="utf-8"))
k, x1, y1, x2, y2 = map(int, sys.argv[1:6])
n = next(n for n in d if p[n]["번호"] == k)
im = cv2.imread(d[n]["원본"])[y1:y2, x1:x2].copy()
im = cv2.resize(im, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
for x in range((x1 // 50 + 1) * 50, x2, 50):
    cv2.line(im, ((x - x1) * 2, 0), ((x - x1) * 2, im.shape[0]), (0, 255, 255), 1)
    cv2.putText(im, str(x), ((x - x1) * 2 + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
for y in range((y1 // 50 + 1) * 50, y2, 50):
    cv2.line(im, (0, (y - y1) * 2), (im.shape[1], (y - y1) * 2), (0, 255, 255), 1)
    cv2.putText(im, str(y), (2, (y - y1) * 2 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
out = Path.home() / f"data/학습실험/라벨링모델비교-20261005/격자_{k:03d}.png"
cv2.imwrite(str(out), im); print(out)
