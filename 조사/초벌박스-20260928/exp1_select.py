"""실험 1(초벌 오답률) 사진 50장 뽑기 — 일회용.
모델 출력을 보지 않고 세션별 무작위(시드 고정) + 같은 세션 안 최소 간격으로 뽑는다."""
import hashlib, json, random, shutil
from pathlib import Path

RAW = Path('/home/pi/sop-project/Rpi5/Demo/test/raw')
OUT = Path.home() / 'data/label_exp1'
SEED = 20260928
# (세션 폴더 접미어, 짧은 이름, 뽑을 장수, 최소 프레임 간격)
PLAN = [
    ('184709_esp32_xga-rt-s1-r1', 's1-r1', 2, 30), ('184732_esp32_xga-rt-s1-r2', 's1-r2', 2, 30),
    ('184758_esp32_xga-rt-s1-r3', 's1-r3', 1, 30),
    ('184922_esp32_xga-rt-s2-r1', 's2-r1', 4, 20), ('184950_esp32_xga-rt-s2-r2', 's2-r2', 4, 20),
    ('185019_esp32_xga-rt-s2-r3', 's2-r3', 4, 20),
    ('185802_esp32_xga-rt-s6-r1', 's6-r1', 9, 60), ('190129_esp32_xga-rt-s6-r2', 's6-r2', 9, 60),
    ('193013_esp32_tool-free-r1', 'tool-r1', 15, 150),
]
rng = random.Random(SEED)
img_dir = OUT / 'images'
if img_dir.exists() and any(img_dir.iterdir()):
    raise SystemExit(f'이미 있음: {img_dir} — 덮어쓰지 않는다')
img_dir.mkdir(parents=True, exist_ok=True)
picked = []
for suffix, short, n, gap in PLAN:
    sess = RAW / f'20260923_{suffix}_console_v2'
    pngs = sorted(sess.glob('f*.png'))
    order = pngs[:]; rng.shuffle(order)
    chosen = []
    for p in order:
        fr = int(p.stem[1:])
        if all(abs(fr - c) >= gap for c in chosen):
            chosen.append(fr)
        if len(chosen) == n:
            break
    for fr in sorted(chosen):
        src = sess / f'f{fr:05d}.png'
        dst = img_dir / f'{short}__f{fr:05d}.png'
        shutil.copy2(src, dst)
        picked.append({'file': dst.name, 'session': sess.name, 'frame': fr,
                       'sha256': hashlib.sha256(src.read_bytes()).hexdigest()})
(OUT / 'selection.json').write_text(json.dumps(
    {'seed': SEED, 'rule': '세션별 무작위·최소 간격 · 모델 출력 미사용', 'plan': PLAN, 'picked': picked},
    ensure_ascii=False, indent=1))
print(len(picked), '장 →', img_dir)
