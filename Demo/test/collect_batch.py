"""검토 묶음 회수 — 사용자가 고친 X-AnyLabeling 라벨 → 점검 → YOLO 라벨 + 수정 집계 + label_audit.

실행(Demo/ 에서): python3 test/collect_batch.py <돌려받은 images 폴더> --manifest <묶음>/manifest.json --out ~/data/label_dataset/<장소>
받는 조건(설계 §8): ①묶음의 모든 사진에 .json ②검토 흔적 — 다시 저장됨(version ≠ 초벌 표시) 또는 「검토함」 플래그·검토 완료(checked) ③이름 = 8종·exclude ④「제안_」 없음 ⑤사각형만
하나라도 어긋나면 아무것도 쓰지 않고 종료 코드 1 과 목록을 낸다.
출력: <out>/labels/<짧은 세션>__fNNNNN.txt · <out>/images.txt(라벨 이름 → 원본 경로) · <out>/data.yaml · <out>/stats/<묶음>.json
🔴 사진은 파이의 원본과 짝짓는다 — 돌려받은 사진은 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import label_review as LR      # noqa: E402
import xany_io as X            # noqa: E402

KEYS = ("그대로", "박스 조정", "이름 바뀜", "지움", "채택")


def check_returned(man, returned_dir):
    out = []
    for r in man["images"]:
        p = Path(returned_dir) / (Path(r["file"]).stem + ".json")
        if not p.exists():
            out.append(f"{r['file']}: 라벨 파일 없음")
            continue
        doc = X.read_json(p)
        # 검토한 사진 = 다시 저장됨(version 이 바뀜) 또는 「검토함」 플래그·검토 완료(checked) — 고칠 게 없으면
        # X-AnyLabeling 은 Ctrl+S 를 눌러도 저장하지 않는다(xany_io.REVIEW_FLAG 설명).
        if doc["version"] == X.DRAFT_VERSION and not doc["reviewed"]:
            out.append(f"{r['file']}: 미검토(저장도 「검토함」 표시도 없다)")
        out += [f"{r['file']}: {m}" for m in X.problems(doc["shapes"])]
    return out


def edit_stats(drafts, finals):
    stats = {k: Counter({x: 0 for x in KEYS}) for k in ("auto", "check", "propose", "tool")}
    pairs = sorted(((LR.iou(d["box"], f["box"]), i, j) for i, d in enumerate(drafts) for j, f in enumerate(finals)),
                   reverse=True)
    ud, uf = set(range(len(drafts))), set(range(len(finals)))
    for v, i, j in pairs:
        if v < 0.5:
            break
        if i in ud and j in uf:
            ud.discard(i); uf.discard(j)
            d, f = drafts[i], finals[j]
            if d["kind"] == "propose":
                stats["propose"]["채택" if f["label"] == d["label"][len(X.PROPOSAL_PREFIX):] else "이름 바뀜"] += 1
            elif f["label"] != d["label"]:
                stats[d["kind"]]["이름 바뀜"] += 1
            else:                  # 0.5 px 넘게 움직인 변이 하나라도 있으면 조정 — 작은 버튼에서는 1 px 도 뜻이 있다
                same = max(abs(a - b) for a, b in zip(d["box"], f["box"])) < 0.5
                stats[d["kind"]]["그대로" if same else "박스 조정"] += 1
    for i in ud:
        stats[drafts[i]["kind"]]["지움"] += 1
    added = Counter(finals[j]["label"] for j in uf)
    res = {k: dict(v) for k, v in stats.items()}
    res["추가"] = dict(added)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("returned")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).expanduser().read_text(encoding="utf-8"))
    ret = Path(a.returned).expanduser()
    probs = check_returned(man, ret)
    if probs:
        print(f"❌ 회수 거부 — 문제 {len(probs)}건(아무것도 쓰지 않았다)")
        for m in probs:
            print("  -", m)
        sys.exit(1)
    out = Path(a.out).expanduser()
    (out / "labels").mkdir(parents=True, exist_ok=True); (out / "stats").mkdir(exist_ok=True)
    total = {k: Counter() for k in ("auto", "check", "propose", "tool")}; added = Counter()
    excluded, rows = 0, []
    for r in man["images"]:
        doc = X.read_json(ret / (Path(r["file"]).stem + ".json"))
        name = r["file"].split("__", 1)[1].rsplit(".", 1)[0]          # <짧은 세션>__fNNNNN
        lines = X.to_yolo_lines(doc["shapes"], r["w"], r["h"])
        s = edit_stats(r["drafts"], [x for x in doc["shapes"] if x["label"] != X.EXCLUDE])
        for k in total:
            total[k].update(s[k])
        added.update(s["추가"])
        if lines is None:
            excluded += 1
            continue
        (out / "labels" / f"{name}.txt").write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        rows.append(f"{name}\t{r['original']}")
    with open(out / "images.txt", "a", encoding="utf-8") as f:
        f.write("".join(x + "\n" for x in rows))
    (out / "data.yaml").write_text("names: [" + ", ".join(X.CLASSES) + "]\n", encoding="utf-8")
    stats = {"batch": man["batch"], "images": len(man["images"]), "exclude": excluded,
             **{k: dict(v) for k, v in total.items()}, "추가": dict(added)}
    (out / "stats" / f"{man['batch']}.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 회수 {len(rows)}장 · exclude {excluded}")
    for k in ("auto", "check", "propose", "tool"):
        print(f"  {k:8}", dict(total[k]))
    print("  추가    ", dict(added))
    import label_audit
    rep = label_audit.audit(out)
    print("label_audit — 모르는 클래스", rep["unknown_classes"], "· 조각 의심", len(rep["suspects"]),
          "· 배경 비율 %.2f" % rep["background_ratio"], "· 클래스별", rep["per_class"])


if __name__ == "__main__":
    main()
