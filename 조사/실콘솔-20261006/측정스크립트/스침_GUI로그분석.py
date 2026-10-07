"""스침 타이머 확인 — 시연 GUI 로그에서 「오답 버튼 박스 접촉」과 「경고」를 짝지어 센다(2026-10-06 재학습 모델 시연 R1).

사용: python3 스침_GUI로그분석.py <Demo/logs/…_log.txt>
- 시도 = 「작업 시작 — 1단계」마다 하나 · 차례 버튼 = 「단계 진행 → … (Bn)」
- 오답 접촉 = 「손 진입: Bn (박스 안)」 중 차례 버튼이 아닌 것 · 같은 버튼이 3초 안에 다시 찍히면 한 번의 접촉으로 묶는다
- 접촉 앞뒤 1초 안에 「→ WARNING」 이 있으면 경고로 이어진 접촉 · 없으면 경고 없이 지나간 접촉(스침)
🔴 GUI 로그 시각은 1초 단위라 임계 0.3초 자체는 확인할 수 없다 — 정밀 확인은 원본 프레임(test/raw)·dwell_probe 로.
"""
import re
import sys


def sec(t):
    h, m, s = map(int, t.split(':'))
    return h * 3600 + m * 60 + s


def main(path):
    exp = None
    att = 0
    ent, warns = [], []
    for line in open(path, encoding='utf-8'):
        m = re.match(r'\[(\d\d:\d\d:\d\d)(?:\.\d{3})?\] (.*)', line)
        if not m:
            continue
        t, msg = sec(m.group(1)), m.group(2)
        if '작업 시작 — 1단계' in msg:
            att += 1
            exp = 'B1'
        m2 = re.search(r'단계 진행 → \d단계: .*\((B\d)\)', msg)
        if m2:
            exp = m2.group(1)
        if '[결과]' in msg:
            exp = None
        m3 = re.search(r'손 진입: (B\d) \(박스 안\)', msg)
        if m3 and exp and m3.group(1) != exp:
            ent.append((att, t, m3.group(1)))
        if '→ WARNING' in msg:
            warns.append((att, t))
    for a in range(1, att + 1):
        e = [x for x in ent if x[0] == a]
        w = [x for x in warns if x[0] == a]
        grp = []
        for x in e:
            if grp and grp[-1][2] == x[2] and x[1] - grp[-1][3] <= 3:
                grp[-1][3] = x[1]
            else:
                grp.append([x[0], x[1], x[2], x[1]])
        hit = [g for g in grp if any(g[1] - 1 <= y[1] <= g[3] + 1 for y in w)]
        lone = sum(1 for y in w if not any(g[1] - 1 <= y[1] <= g[3] + 1 for g in grp))
        print(f"시도{a}: 오답 버튼 박스 접촉 {len(grp)}번 → 경고로 이어짐 {len(hit)} · "
              f"경고 없이 지나감(스침) {len(grp) - len(hit)} · 경고 총 {len(w)} · 접촉 없이 난 경고 {lone}")


if __name__ == '__main__':
    main(sys.argv[1])
