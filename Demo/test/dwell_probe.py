"""체류(dwell) 측정 — 손끝이 어느 버튼 ROI에 얼마나 머무는가.

왜 필요한가:
    §9.4는 체류 임계를 **dwell 0.5초 + 갭메우기 0.3초**로 정본화했다(색-ROI PoC 실측,
    스침 오탐 0%). 그러나 검출 수단이 **console_v2 + HOI 손 랜드마크**로 바뀌었으므로
    그 값이 새 수단에서도 유효한지 확인해야 한다.

    2026-07-21 관찰: 최근접 버튼이 5프레임 만에 바뀌고 검출이 끊기는 구간이 있었다.
    원인 가설 = `blaze_app_python`에 **프레임 간 트래킹·스무딩이 없다**(MediaPipe 원본은
    이전 랜드마크로 ROI를 유도해 팜 검출을 매 프레임 돌리지 않는다). 즉 모델 한계가
    아니라 빠진 기능이며, **§9.4의 갭메우기가 그 대책**이다. 이 도구가 그것을 측정한다.

무엇을 재는가:
    ① ROI 시계열 — 프레임마다 손끝이 어느 버튼에 있는가
    ② 갭 분포 — 검출이 끊긴 구간의 길이(갭메우기 0.3초로 메워지는가)
    ③ 체류 구간 — 갭메우기 전/후로 나눠, dwell 임계를 넘는 구간이 생기는가

    버튼 박스는 **이미 기록된 rawdet 로그**에서 읽는다(console_v2 재추론 불필요).
    → VDevice 충돌 없음. 손 모델만 올린다.

사용:
    # 기본 (§9.4 정본값 적용)
    python3 test/dwell_probe.py test/raw/<세션>

    # 임계 후보 비교
    python3 test/dwell_probe.py test/raw/<세션> --dwell 0.5 --gap-fill 0.3 --margin 10

⚠️ 이 도구는 **"버튼 누르는 동작" 촬영본**에 쓰라고 만든 것이다. 가림 촬영(154947)처럼
   손을 크게 휘젓는 세션은 조작 장면이 아니라 참고값일 뿐이다.
"""

import argparse
import collections
import csv
import datetime
import os
import statistics as st
import sys

import cv2
import numpy as np

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, _TEST_DIR)

TIP = 8          # MediaPipe 손 랜드마크 인덱스 8 = 검지 끝 (접촉 기준점, §7.2)


def _parse_ts(s):
    """'15:49:48.316' → 초(float). 자정 넘김은 이 용도에선 무시한다."""
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def load_buttons(log_path):
    """rawdet 로그 → {frame: [(cls, x1,y1,x2,y2)]}, {frame: 초}."""
    boxes, times = collections.defaultdict(list), {}
    with open(log_path, newline="") as f:
        for r in csv.DictReader(f):
            fr = int(r["frame"])
            boxes[fr].append((r["cls_name"], int(r["x1"]), int(r["y1"]),
                              int(r["x2"]), int(r["y2"])))
            times.setdefault(fr, _parse_ts(r["timestamp"]))
    return boxes, times


def roi_of(tip, buttons, margin=0):
    """손끝이 들어있는 버튼 ROI 라벨. 없으면 None.

    ⚠️ **런타임(`camera_thread.roi_at_point`)과 동일한 규칙이어야 한다** —
    측정 도구가 다른 규칙을 쓰면 그 수치가 실제 동작을 대표하지 못한다.
      · ROI = **검출 박스 그 자체**(FPV라 고정 좌표는 성립하지 않는다)
      · 겹치면 **더 작은(가까운) 박스 우선** — 오판을 줄이는 런타임 규칙 그대로

    margin 은 실험용 확장이며 기본 0 = 런타임과 완전히 동일. 0이 아닌 값으로
    측정한 결과는 런타임 동작이 아니라 "박스를 넓히면 어떻게 되는가"의 답이다.
    """
    tx, ty = tip
    hit, hit_area = None, None
    for cls, x1, y1, x2, y2 in buttons:
        if x1 - margin <= tx <= x2 + margin and y1 - margin <= ty <= y2 + margin:
            area = (x2 - x1 + 2 * margin) * (y2 - y1 + 2 * margin)
            if hit_area is None or area < hit_area:
                hit, hit_area = cls, area
    return hit


def fill_gaps(series, times, gap_sec):
    """같은 ROI 사이의 짧은 공백을 메운다 (§9.4 갭메우기).

    A … None … A 형태에서 공백이 gap_sec 이하면 A 로 채운다.
    누름 순간 손이 버튼을 가려 인식이 끊기는 채터를 메우는 것이 목적이다.
    """
    out = list(series)
    n = len(out)
    i = 0
    filled = 0
    while i < n:
        if out[i] is None:
            j = i
            while j < n and out[j] is None:
                j += 1
            prev_roi = out[i - 1] if i > 0 else None
            next_roi = out[j] if j < n else None
            if prev_roi is not None and prev_roi == next_roi:
                span = times[j] - times[i - 1] if j < n else 0
                if span <= gap_sec:
                    for k in range(i, j):
                        out[k] = prev_roi
                    filled += j - i
            i = j
        else:
            i += 1
    return out, filled


def load_presses(path):
    """gpio 로그 → [(초, 버튼, 프레임)]. 없으면 빈 목록."""
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out.append((_parse_ts(r["timestamp"]), r["button"], int(r["frame"])))
    return sorted(out)


def analyze_presses(presses, series, frames, times, dwell):
    """눌림 하나하나에 대해 '비전이 언제 그 버튼을 봤는가'를 대조한다.

    선행시간 = t_눌림 − t_도착. t_도착은 **눌림 직전의 연속 ROI 구간이 시작된 시각**이다.
    이 값이 양수여야 "누르기 직전에 사전 감지"라는 프로젝트 명제가 성립한다.
    """
    rows = []
    for t_press, btn, fr in presses:
        # 눌림 시각 이하인 마지막 프레임 인덱스
        idx = max((i for i, t in enumerate(times) if t <= t_press), default=None)
        if idx is None:
            rows.append((btn, fr, None, None, "프레임 없음"))
            continue
        seen = series[idx]
        if seen != btn:
            rows.append((btn, fr, None, seen, "ROI 불일치" if seen else "미검출"))
            continue
        # 같은 ROI가 연속으로 유지된 구간의 시작까지 거슬러 올라간다
        j = idx
        while j > 0 and series[j - 1] == btn:
            j -= 1
        rows.append((btn, fr, t_press - times[j], seen, "OK"))
    return rows


def segments(series, frames, times):
    """연속 동일 ROI 구간 → [(roi, 시작프레임, 끝프레임, 지속초)]."""
    segs = []
    i = 0
    n = len(series)
    while i < n:
        if series[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and series[j + 1] == series[i]:
            j += 1
        segs.append((series[i], frames[i], frames[j], times[j] - times[i]))
        i = j + 1
    return segs


def main():
    ap = argparse.ArgumentParser(description="손끝 ROI 체류 측정 (§9.4 임계 검증)")
    ap.add_argument("raw_dir", help="test/raw/<세션> 경로")
    ap.add_argument("--log", default=None, help="rawdet 로그 (기본: 세션명으로 자동 탐색)")
    ap.add_argument("--dwell", type=float, default=0.5,
                    help="체류 임계(초). 기본 0.5 = §9.4 정본(PoC 실측)")
    ap.add_argument("--gap-fill", type=float, default=0.3,
                    help="갭메우기(초). 기본 0.3 = §9.4 정본. 0 이면 끔")
    ap.add_argument("--margin", type=int, default=0,
                    help="버튼 박스를 이 픽셀만큼 넓혀 ROI 판정 (기본 0 = 박스 안)")
    ap.add_argument("--conf", type=float, default=0.5, help="손 랜드마크 최소 score")
    ap.add_argument("--gpio-log", default=None,
                    help="GPIO 눌림 로그(기본: 세션명으로 자동 탐색). 있으면 선행시간·"
                         "사전 감지율·오경보 후보를 함께 산출한다")
    args = ap.parse_args()

    sess = os.path.basename(os.path.normpath(args.raw_dir))
    log = args.log or os.path.join(_TEST_DIR, "logs", f"{sess}_rawdet_log.csv")
    if not os.path.exists(log):
        print(f"❌ rawdet 로그가 없습니다: {log}")
        return 2
    buttons, times_by_frame = load_buttons(log)

    # hoi_probe 를 먼저 import 해야 blaze 경로가 sys.path 에 들어간다
    from hoi_probe import load_hand_models, run_hand
    from hailo_inference import HailoInference
    infer = HailoInference()
    det, lm = load_hand_models(infer)

    pngs = sorted(f for f in os.listdir(args.raw_dir) if f.endswith(".png"))
    frames, series, times = [], [], []
    hand_hit = 0
    for f in pngs:
        fr = int(f[1:6])
        if fr not in times_by_frame:
            continue                      # 버튼 검출이 없는 프레임 = 판정 불가
        img = cv2.imread(os.path.join(args.raw_dir, f))
        lms, flags = run_hand(img, det, lm)
        roi = None
        if len(lms) and flags is not None and float(np.max(flags)) >= args.conf:
            hand_hit += 1
            roi = roi_of(lms[0][TIP][:2], buttons[fr], args.margin)
        frames.append(fr)
        series.append(roi)
        times.append(times_by_frame[fr])

    n = len(frames)
    if n == 0:
        print("❌ 분석할 프레임이 없습니다.")
        return 2
    dur = times[-1] - times[0]
    print(f"\n세션 : {sess}")
    print(f"프레임 {n}개 · {dur:.1f}초 · 실효 {n/max(dur,1e-9):.1f} fps")
    print(f"손 검출 {hand_hit}/{n} ({hand_hit/n*100:.1f}%) · "
          f"ROI 판정 {sum(1 for s in series if s)}/{n} "
          f"({sum(1 for s in series if s)/n*100:.1f}%)")

    # ── 갭 분포 ────────────────────────────────────────────────────────────
    gaps = []
    i = 0
    while i < n:
        if series[i] is None:
            j = i
            while j < n and series[j] is None:
                j += 1
            prev_roi = series[i - 1] if i > 0 else None
            nxt = series[j] if j < n else None
            span = (times[j] if j < n else times[-1]) - times[i - 1 if i else 0]
            gaps.append((span, prev_roi is not None and prev_roi == nxt))
            i = j
        else:
            i += 1
    same = [g for g, s in gaps if s]
    if gaps:
        print(f"\n【공백 구간】 총 {len(gaps)}개 · 그중 앞뒤 ROI가 같은 것 {len(same)}개")
        if same:
            print(f"  같은 ROI 사이 공백 길이: median {st.median(same):.2f}s · "
                  f"max {max(same):.2f}s · ≤{args.gap_fill}s 인 것 "
                  f"{sum(1 for g in same if g <= args.gap_fill)}개")

    # ── 갭메우기 전/후 체류 비교 ───────────────────────────────────────────
    def report(tag, ser):
        segs = segments(ser, frames, times)
        ok = [s for s in segs if s[3] >= args.dwell]
        print(f"\n【체류 구간 — {tag}】 총 {len(segs)}개")
        if segs:
            longest = max(segs, key=lambda s: s[3])
            print(f"  최장: {longest[0]} · f{longest[1]}~f{longest[2]} · {longest[3]:.2f}초")
            print(f"  길이: median {st.median([s[3] for s in segs]):.2f}s")
        print(f"  ⭐ dwell {args.dwell}초 이상: **{len(ok)}개**"
              + (f"  → {', '.join(f'{r}({d:.2f}s)' for r, _a, _b, d in ok[:6])}" if ok else "  ← 없음"))
        return len(ok), segs

    before, _ = report("갭메우기 없음", series)
    after = before
    if args.gap_fill > 0:
        filled_series, nfill = fill_gaps(series, times, args.gap_fill)
        after, _ = report(f"갭메우기 {args.gap_fill}초 적용 (프레임 {nfill}개 보정)",
                          filled_series)

    # ── GPIO 눌림 대조 (정답이 있을 때만) ──────────────────────────────────
    gpio_log = args.gpio_log or os.path.join(_TEST_DIR, "logs", f"{sess}_gpio_log.csv")
    presses = load_presses(gpio_log)
    if presses:
        rows = analyze_presses(presses, series, frames, times, args.dwell)
        lead = [r[2] for r in rows if r[2] is not None]
        ok_pre = [x for x in lead if x > 0]
        print(f"\n【GPIO 눌림 대조】 {len(presses)}회  ({os.path.basename(gpio_log)})")
        print(f"  {'버튼':<5}{'프레임':>7}{'선행시간':>10}{'비전이 본 ROI':>14}  비고")
        for btn, fr, ld, seen, note in rows:
            print(f"  {btn:<5}{fr:>7}"
                  f"{(f'{ld:+.2f}s' if ld is not None else '-'):>10}"
                  f"{(seen or '-'):>14}  {note}")
        print(f"\n  ⭐ **사전 감지율** : {len(ok_pre)}/{len(presses)} "
              f"({len(ok_pre)/len(presses)*100:.0f}%)  ← 눌림보다 먼저 본 비율")
        print(f"  ROI 일치율   : {sum(1 for r in rows if r[4]=='OK')}/{len(presses)}")
        if lead:
            print(f"  선행시간     : median {st.median(lead):.2f}s · "
                  f"min {min(lead):.2f}s · max {max(lead):.2f}s")
            print(f"  → dwell 임계 후보: **min({min(lead):.2f}s) 미만**이어야 눌림 전에 판정된다")
        # 눌림 없이 임계를 넘긴 체류 = 오경보 후보
        press_frames = {fr for _t, _b, fr in presses}
        false_pos = [s for s in segments(series, frames, times)
                     if s[3] >= args.dwell and not any(s[1] <= pf <= s[2] for pf in press_frames)]
        print(f"  오경보 후보  : {len(false_pos)}개 "
              f"(dwell {args.dwell}s를 넘겼으나 눌림이 없던 구간)")
    else:
        print(f"\n【GPIO 눌림 대조】 기록 없음 — `bench_detector.py --gpio` 로 촬영하면"
              f"\n  선행시간·사전 감지율·오경보율을 함께 낼 수 있다(§9.4가 요구하는 값).")

    # ── 판정 ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"【§9.4 임계 검증】 dwell {args.dwell}s + 갭메우기 {args.gap_fill}s")
    print(f"  갭메우기 전 {before}개 → 후 **{after}개**")
    if after > 0:
        print(f"  ✅ 임계를 넘는 체류가 존재 — 현 설정으로 위반 판정이 가능하다")
        if after > before:
            print(f"  ⭐ 갭메우기가 {after-before}개를 살렸다 — §9.4의 근거가 재확인됨")
    else:
        print(f"  🔴 임계를 넘는 체류가 없다 — 다음 중 하나가 필요하다:")
        print(f"     ① 이 세션이 조작 장면이 아님(가림·이동 촬영이면 정상)")
        print(f"     ② 갭메우기 시간을 늘려야 함  ③ 트래킹/스무딩 보강 필요")
    print("\n🔴 이 수치는 §10 기재 전 사용자 확인을 거친다(단일정본 규칙).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
