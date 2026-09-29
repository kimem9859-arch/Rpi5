"""b001~b004 초벌 박스 하나하나의 결말(그대로·조정·크게 조정·이름 바뀜·지움)을 이유별·클래스별로 모은다 — 읽기 전용 분석."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo/test")
import label_review as LR   # noqa: E402
import xany_io as X          # noqa: E402

B = Path.home() / "data/label_batches"
BTN = set(X.CLASSES[:5])


def center_in(a, b):
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def outcomes(drafts, finals):
    """collect_batch.edit_stats 와 같은 짝짓기 — 초벌마다 결말 · 짝 없는 최종(추가)."""
    out = [None] * len(drafts)
    pairs = sorted(((LR.iou(d["box"], f["box"]), i, j) for i, d in enumerate(drafts) for j, f in enumerate(finals)), reverse=True)
    ud, uf = set(range(len(drafts))), set(range(len(finals)))
    for v, i, j in pairs:
        if v < 0.5:
            break
        if i in ud and j in uf:
            ud.discard(i); uf.discard(j)
            d, f = drafts[i], finals[j]
            name = d["label"][len(X.PROPOSAL_PREFIX):] if d["kind"] == "propose" else d["label"]
            if f["label"] != name:
                out[i] = ("이름 바뀜", f["label"])
            elif d["kind"] == "propose":
                out[i] = ("채택", None)
            else:
                same = max(abs(a - b) for a, b in zip(d["box"], f["box"])) < 0.5
                out[i] = ("그대로" if same else "박스 조정", [f["box"][k] - d["box"][k] for k in range(4)])
    near = []
    for i in ud:
        d = drafts[i]
        name = d["label"][len(X.PROPOSAL_PREFIX):] if d["kind"] == "propose" else d["label"]
        for j in uf:
            f = finals[j]
            v = LR.iou(d["box"], f["box"])
            if f["label"] == name and (v > 0.1 or center_in(d["box"], f["box"]) or center_in(f["box"], d["box"])):
                near.append((v, i, j))
    for v, i, j in sorted(near, reverse=True):
        if i in ud and j in uf:
            ud.discard(i); uf.discard(j); out[i] = ("크게 조정", None)
    for i in ud:
        out[i] = ("지움", None)
    return out, [finals[j] for j in uf]


rep = {}
for b in ("b001", "b002", "b003", "b004"):
    man = json.loads((B / b / "manifest.json").read_text(encoding="utf-8"))
    kind_out = defaultdict(Counter); why_out = defaultdict(Counter); single_why = defaultdict(Counter)
    cls_out = defaultdict(Counter); added = Counter(); img_state = Counter(); rename = Counter()
    nwhy = Counter(); excl = 0; blur_excl = 0; blur_n = 0
    for r in man["images"]:
        doc = X.read_json(B / b / "returned" / (Path(r["file"]).stem + ".json"))
        if any(s["label"] == X.EXCLUDE for s in doc["shapes"]):
            excl += 1; blur_excl += bool(r.get("blur")); continue
        blur_n += bool(r.get("blur"))
        oc, add = outcomes(r["drafts"], doc["shapes"])
        for d, (o, extra) in zip(r["drafts"], oc):
            kind_out[d["kind"]][o] += 1
            cls_out[(d["kind"], d["label"])][o] += 1
            if o == "이름 바뀜":
                rename[(d["kind"], d["label"], extra)] += 1
            if d["kind"] == "check":
                for w in d.get("why", []):
                    why_out[w][o] += 1
                if len(d.get("why", [])) == 1:
                    single_why[d["why"][0]][o] += 1
                nwhy[len(d.get("why", []))] += 1
        for f in add:
            added[f["label"]] += 1
        touched = add or any(o not in ("그대로",) for o, _ in oc if o) or any(o == "채택" for o, _ in oc)
        img_state[(r["kind"], "손댐" if touched else "안 손댐")] += 1
    rep[b] = {"kind": {k: dict(v) for k, v in kind_out.items()}, "why": {k: dict(v) for k, v in why_out.items()},
              "single_why": {k: dict(v) for k, v in single_why.items()},
              "cls": {f"{k[0]}:{k[1]}": dict(v) for k, v in cls_out.items()}, "added": dict(added),
              "rename": {f"{k[0]}:{k[1]}→{k[2]}": v for k, v in rename.items()}, "img": {f"{k[0]}/{k[1]}": v for k, v in img_state.items()},
              "exclude": excl, "blur_in_exclude": blur_excl, "blur_kept": blur_n}

json.dump(rep, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print("ok")
