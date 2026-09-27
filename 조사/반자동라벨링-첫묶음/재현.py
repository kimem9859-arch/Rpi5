"""재현 관문 — Demo/test/label_review.py 가 조사 시험(기계검토-20260928/machine_review.py)과 같은 표를 내는지.
실행: cd Rpi5/Demo && python3 ../조사/반자동라벨링-첫묶음/재현.py
"""
import glob, json, sys
from collections import Counter, defaultdict
from pathlib import Path
import cv2
sys.path.insert(0, '/home/pi/sop-project/Rpi5/Demo/test'); sys.path.insert(0, '/home/pi/sop-project/Rpi5/Demo')
import label_review as LR
from detector import create_detector

RAW = Path('/home/pi/sop-project/Rpi5/Demo/test/raw')
SESS = {'정지': (['184709_esp32_xga-rt-s1-r1', '184732_esp32_xga-rt-s1-r2', '184758_esp32_xga-rt-s1-r3'], 1),
        '좌우이동': (['184922_esp32_xga-rt-s2-r1', '184950_esp32_xga-rt-s2-r2', '185019_esp32_xga-rt-s2-r3'], 3),
        '누르기': (['185802_esp32_xga-rt-s6-r1', '190129_esp32_xga-rt-s6-r2'], 10),
        '공구': (['193013_esp32_tool-free-r1'], 15)}
det = create_detector()
run = lambda crop: [(det.class_name(c), s, [x1, y1, x2, y2]) for c, s, x1, y1, x2, y2 in det.detect(crop)]
tpl = [cv2.imread(p) for p in sorted(glob.glob(str(RAW / '20260923_184709_esp32_xga-rt-s1-r1_console_v2/f*.png')))]
T = LR.build_template(tpl, run); th = LR.make_thresholds(tpl, run)
sel = json.load(open(Path.home() / 'data/label_exp1/selection.json'))
gap = {f'20260923_{p[0]}_console_v2': p[3] for p in sel['plan']}; seal = defaultdict(list)
for p in sel['picked']:
    seal[p['session']].append(p['frame'])
stat = defaultdict(Counter); why = defaultdict(Counter); miss = Counter(); nfr = Counter()
for scene, (ss, step) in SESS.items():
    for s in ss:
        sess = f'20260923_{s}_console_v2'
        for p in sorted(glob.glob(str(RAW / sess / 'f*.png')))[::step]:
            fr = int(Path(p).stem[1:])
            if any(abs(fr - q) < gap.get(sess, 0) for q in seal.get(sess, [])):
                continue
            out = LR.review(cv2.imread(p), run, T, th); nv = out['nvis']
            g = '1개' if nv == 1 else '2개' if nv == 2 else '3개 이상' if nv >= 3 else '0개'
            k = (scene, g); nfr[k] += 1; miss[k] += len(out['missing'])
            for x in out['boxes']:
                if x['why']:
                    stat[k]['사람'] += 1
                    for w in x['why']:
                        why[k][w] += 1
                else:
                    stat[k]['기계 확정'] += 1
print('장면 · 보이는 버튼 | 사진 | 박스: 기계 확정 / 사람 | 빠진 자리 제안 | 사람에게 넘긴 이유(중복 포함)')
for k in sorted(nfr, key=lambda k: (list(SESS).index(k[0]), k[1])):
    if k[1] == '0개':
        print(f'{k[0]:5} · {k[1]:6} | {nfr[k]:4} | 버튼 없음'); continue
    print(f"{k[0]:5} · {k[1]:6} | {nfr[k]:4} | {stat[k]['기계 확정']:4} / {stat[k]['사람']:4} | {miss[k]:3} | {dict(why[k].most_common())}")
