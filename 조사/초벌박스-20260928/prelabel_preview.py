"""초벌 미리보기 — 실험 1의 50장과 겹치지 않는 사진 12장에 초벌 박스를 그린다(일회용)."""
import csv, glob, json, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
RAW = Path('/home/pi/sop-project/Rpi5/Demo/test/raw'); LOG = Path('/home/pi/sop-project/Rpi5/Demo/test/logs')
sel = json.load(open(Path.home() / 'data/label_exp1/selection.json'))
OUT = Path.home() / 'data/prelabel_preview'; OUT.mkdir(exist_ok=True)
taken = {}
for p in sel['picked']:
    taken.setdefault(p['session'], []).append(p['frame'])
PLAN = [('s1-r2', '184732_esp32_xga-rt-s1-r2', 2, 60), ('s2-r1', '184922_esp32_xga-rt-s2-r1', 3, 40),
        ('s6-r1', '185802_esp32_xga-rt-s6-r1', 2, 120), ('s6-r2', '190129_esp32_xga-rt-s6-r2', 2, 120),
        ('tool-r1', '193013_esp32_tool-free-r1', 3, 300)]
COL = {'B1': (255, 210, 0), 'B2': (0, 200, 255), 'B3': (255, 105, 180), 'B4': (60, 90, 255), 'EMO': (255, 30, 30),
       'driver': (0, 255, 120), 'wrench': (0, 255, 120), 'pliers': (0, 255, 120)}
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 18)
except OSError:
    font = ImageFont.load_default()
rng = random.Random(7)
from ultralytics import YOLO
tool = YOLO('/home/pi/sop-project/Rpi5/Demo/models/tool_v3.pt')
for short, suf, n, gap in PLAN:
    sess = f'20260923_{suf}_console_v2'
    avoid = taken.get(sess, [])
    pngs = sorted((RAW / sess).glob('f*.png')); rng.shuffle(pngs)
    rows = list(csv.DictReader(open(LOG / f'{sess}_rawdet_log.csv')))
    got = []
    for p in pngs:
        fr = int(p.stem[1:])
        if all(abs(fr - a) >= gap for a in avoid + got):
            got.append(fr)
        if len(got) == n:
            break
    for fr in got:
        im = Image.open(RAW / sess / f'f{fr:05d}.png').convert('RGB'); d = ImageDraw.Draw(im)
        dets = [(r['cls_name'], float(r['score']), [int(r[k]) for k in ('x1', 'y1', 'x2', 'y2')])
                for r in rows if int(r['frame']) == fr]
        res = tool.predict(str(RAW / sess / f'f{fr:05d}.png'), conf=0.25, verbose=False)[0]
        dets += [(res.names[int(c)], float(s), [int(v) for v in b])
                 for b, s, c in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist())]
        for name, sc, (x1, y1, x2, y2) in dets:
            d.rectangle([x1, y1, x2, y2], outline=COL[name], width=3)
            txt = f'{name} {sc:.2f}'; tw = d.textlength(txt, font=font)
            d.rectangle([x1, y1 - 22, x1 + tw + 6, y1], fill=(0, 0, 0)); d.text((x1 + 3, y1 - 21), txt, fill=COL[name], font=font)
        im.save(OUT / f'{short}__f{fr:05d}_초벌.png')
print(sorted(x.name for x in OUT.glob('*.png')))
