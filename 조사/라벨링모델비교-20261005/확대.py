"""판정 보조 — 원본 사진의 한 구역을 3배로 키워 저장. 사용: python3 확대.py <번호> x1 y1 x2 y2"""
import json, sys
from pathlib import Path
import cv2
d = json.load(open("예측.json", encoding="utf-8"))["사진"]; p = json.load(open("짝.json", encoding="utf-8"))
k, x1, y1, x2, y2 = map(int, sys.argv[1:6])
n = next(n for n in d if p[n]["번호"] == k)
im = cv2.imread(d[n]["원본"])[y1:y2, x1:x2]
out = Path.home() / f"data/학습실험/라벨링모델비교-20261005/확대_{k:03d}_{x1}_{y1}.png"
cv2.imwrite(str(out), cv2.resize(im, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
print(out)
