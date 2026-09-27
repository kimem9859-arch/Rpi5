"""실험 1·2 — 초벌 오답률과 자리 규칙 적중률 (일회용).

사용:  python3 exp1_compare.py <사람 라벨 폴더(X-AnyLabeling .json)> [--self-check]
  --self-check : 초벌을 정답으로 넣어 대조 로직을 검증한다(전부 「맞음」이어야 한다).
"""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path.home()
IMG = HOME / 'data/label_exp1/images'
PRE = HOME / 'data/label_exp1_prelabel_hidden'
CLASSES = ['B1', 'B2', 'B3', 'B4', 'EMO', 'driver', 'wrench', 'pliers']
BUTTONS = CLASSES[:5]
IOU_MATCH = 0.5
THRESHOLDS = [0.50, 0.65, 0.80]
TOOL_FLOOR = 0.25          # 공구 초벌은 0.25 이상으로 만들어 두었다

# 자리 규칙 — (a, b, 축, 부호): a 의 중심이 b 보다 축 방향으로 작아야 한다(x=왼쪽, y=위)
LAYOUT = [('B2', 'B1', 'y'), ('B3', 'B4', 'y'), ('B2', 'B3', 'x'), ('B1', 'B4', 'x'),
          ('B1', 'EMO', 'y'), ('B4', 'EMO', 'y'), ('B1', 'EMO', 'x'), ('EMO', 'B4', 'x'),
          ('B2', 'EMO', 'y'), ('B3', 'EMO', 'y')]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def load_human(folder, stem):
    f = folder / f'{stem}.json'
    if not f.exists():
        return None
    shapes = json.load(open(f)).get('shapes', [])
    out = []
    for s in shapes:
        xs = [p[0] for p in s['points']]; ys = [p[1] for p in s['points']]
        out.append({'label': s['label'], 'box': [min(xs), min(ys), max(xs), max(ys)]})
    return out


def load_pre(stem):
    b = json.load(open(PRE / 'buttons' / f'{stem}.json'))
    t = json.load(open(PRE / 'tools' / f'{stem}.json'))
    return b + t


def layout_flags(dets):
    """자리 규칙을 어긴 박스의 번호 집합."""
    cen = [((d['box'][0] + d['box'][2]) / 2, (d['box'][1] + d['box'][3]) / 2) for d in dets]
    flagged = set()
    for i, di in enumerate(dets):
        for j, dj in enumerate(dets):
            for a, b, ax in LAYOUT:
                if di['label'] == a and dj['label'] == b:
                    k = 0 if ax == 'x' else 1
                    if not cen[i][k] < cen[j][k]:
                        flagged |= {i, j}
    return flagged


def dup_flags(dets):
    c = Counter(d['label'] for d in dets if d['label'] in BUTTONS)
    return {i for i, d in enumerate(dets) if c[d['label']] > 1}


def match(pre, gt):
    """IoU 큰 순으로 1:1 짝짓기(클래스 무관). 반환 = [(pi, gi)], 남은 pi, 남은 gi."""
    pairs = sorted(((iou(p['box'], g['box']), pi, gi) for pi, p in enumerate(pre) for gi, g in enumerate(gt)),
                   reverse=True)
    up, ug, out = set(range(len(pre))), set(range(len(gt))), []
    for v, pi, gi in pairs:
        if v < IOU_MATCH:
            break
        if pi in up and gi in ug:
            out.append((pi, gi)); up.discard(pi); ug.discard(gi)
    return out, up, ug


def main():
    folder = Path(sys.argv[1]); self_check = '--self-check' in sys.argv
    stems = sorted(p.stem for p in IMG.glob('*.png'))
    missing, excluded, unknown = [], [], Counter()
    for t in THRESHOLDS:
        stat = defaultdict(Counter); confusion = Counter()
        rule = Counter()   # (규칙, 박스 결과) 개수
        for stem in stems:
            pre_all = load_pre(stem)
            gt = pre_all if self_check else load_human(folder, stem)
            if gt is None:
                if t == THRESHOLDS[0]: missing.append(stem)
                continue
            if any(g['label'] == 'exclude' for g in gt):
                if t == THRESHOLDS[0]: excluded.append(stem)
                continue
            for g in gt:
                if g['label'] not in CLASSES and t == THRESHOLDS[0]:
                    unknown[g['label']] += 1
            pre = [p for p in pre_all if p['score'] >= (t if p['label'] in BUTTONS else max(t, TOOL_FLOOR))]
            if self_check:
                gt = pre
            pairs, up, ug = match(pre, gt)
            res = {}
            for pi, gi in pairs:
                pl, gl = pre[pi]['label'], gt[gi]['label']
                if pl == gl:
                    stat[gl]['맞음'] += 1; res[pi] = '맞음'
                else:
                    stat[gl]['클래스 틀림'] += 1; confusion[(gl, pl)] += 1; res[pi] = '틀림'
            for pi in up:
                stat[pre[pi]['label']]['가짜 박스'] += 1; res[pi] = '가짜'
            for gi in ug:
                stat[gt[gi]['label']]['놓침'] += 1
            fl_dup, fl_lay = dup_flags(pre), layout_flags(pre)
            for pi, r in res.items():
                rule[('중복', pi in fl_dup, r)] += 1
                rule[('자리', pi in fl_lay, r)] += 1
                rule[('둘 중 하나', pi in fl_dup or pi in fl_lay, r)] += 1
        print(f'\n=== 초벌 점수 기준 {t:.2f} (공구는 {max(t, TOOL_FLOOR):.2f}) ===')
        print(f"{'클래스':8}{'맞음':>6}{'틀림':>6}{'가짜':>6}{'놓침':>6}")
        for c in CLASSES:
            s = stat[c]
            if sum(s.values()):
                print(f"{c:8}{s['맞음']:6}{s['클래스 틀림']:6}{s['가짜 박스']:6}{s['놓침']:6}")
        if confusion:
            print('클래스 틀림 (정답 → 초벌):', dict(confusion))
        for name in ('중복', '자리', '둘 중 하나'):
            bad = sum(v for (n, f, r), v in rule.items() if n == name and r != '맞음')
            bad_hit = sum(v for (n, f, r), v in rule.items() if n == name and f and r != '맞음')
            ok = sum(v for (n, f, r), v in rule.items() if n == name and r == '맞음')
            ok_hit = sum(v for (n, f, r), v in rule.items() if n == name and f and r == '맞음')
            print(f'규칙[{name}] 틀린·가짜 박스 {bad_hit}/{bad} 표시 · 맞는 박스 {ok_hit}/{ok} 잘못 표시')
    print(f'\n라벨 파일 없음 {len(missing)}장 {missing[:5]} · exclude {len(excluded)}장 · 모르는 이름 {dict(unknown)}')


if __name__ == '__main__':
    main()
