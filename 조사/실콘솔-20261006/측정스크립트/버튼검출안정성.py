"""rawdet 로그 → 버튼 종류별 「잡힌 프레임」 비율·점수 중앙값·같은 종류 두 개 프레임(읽기 전용 · 정답 없는 안정성 지표)."""
import csv, sys, statistics as st, collections
NAMES = ["B1", "B2", "B3", "B4", "EMO"]
def stats(path, frames_total=None, thr=0.65):
    by = collections.defaultdict(list)
    for r in csv.DictReader(open(path)):
        if r["cls_name"]:
            by[int(r["frame"])].append((r["cls_name"], float(r["score"])))
    frames = sorted(by) if frames_total is None else frames_total
    n = len(frames)
    out = {"프레임": n}
    for c in NAMES:
        hit = [max(s for k, s in by.get(f, []) if k == c) for f in frames if any(k == c and s >= thr for k, s in by.get(f, []))]
        dup = sum(1 for f in frames if sum(1 for k, s in by.get(f, []) if k == c and s >= thr) > 1)
        out[c] = (len(hit) / n * 100, st.median(hit) if hit else 0, dup)
    out["다섯 다"] = sum(1 for f in frames if all(any(k == c and s >= thr for k, s in by.get(f, [])) for c in NAMES)) / n * 100
    return out, frames
if __name__ == "__main__":
    for p in sys.argv[1:]:
        o, _ = stats(p)
        print(p.split("esp32_")[-1][:40], f"프레임 {o['프레임']} · 다섯 다 {o['다섯 다']:.0f}% · " +
              " · ".join(f"{c} {o[c][0]:.0f}%/{o[c][1]:.2f}" + (f"(둘 {o[c][2]})" if o[c][2] else "") for c in NAMES))
