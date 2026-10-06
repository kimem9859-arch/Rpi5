"""검토 묶음 회수 — 사용자가 고친 X-AnyLabeling 라벨 → 점검 → YOLO 라벨 + 수정 집계 + label_audit.

실행(Demo/ 에서): python3 test/collect_batch.py <돌려받은 images 폴더> --manifest <묶음>/manifest.json --out ~/data/label_dataset/<장소>
받는 조건(설계 §8): ①묶음의 모든 사진에 .json ②검토 흔적 — 다시 저장됨(version ≠ 초벌 표시) · 「검토함」 플래그·검토 완료(checked) · 또는 사용자가 「다 봤다」(--viewed-all) ③이름 = 8종·exclude ④「제안_」 없음(exclude 사진은 통째로 빠지므로 예외) ⑤사각형만
하나라도 어긋나면 아무것도 쓰지 않고 종료 코드 1 과 목록을 낸다.
출력: <out>/labels/<짧은 세션>__fNNNNN.txt · <out>/images.txt(라벨 이름 → 원본 경로) · <out>/data.yaml · <out>/stats/<묶음>.json
      · <out>/sources.json(라벨 이름 → 마지막으로 쓴 묶음·종류)
🔴 채점 묶음(manifest kind = score · score_batch.py)이 쓴 라벨은 학습 묶음을 다시 회수해도 덮지 못한다 — 사진마다 여러 사람이
   검토한 채점 라벨이 1회 검토 라벨로 조용히 되돌아가지 않게(데이터셋 스킬 「분할」 ②). 다시 회수 순서 = 학습 묶음 → 채점 1회차 → 2회차.
🔴 채점 묶음은 --viewed-all 로 받지 않는다 — 사진마다 「검토함」 표시(또는 다시 저장한 흔적)가 그 회차 검토의 증거다.
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

KEYS = ("그대로", "박스 조정", "크게 조정", "이름 바뀜", "지움", "채택")


def check_returned(man, returned_dir, viewed_all=False):
    """viewed_all = 사용자가 「묶음을 다 봤다」고 확인함 — X-AnyLabeling 은 고치지 않은 사진을 저장하지 않으므로
    (3.3.5 · 사용자 확인 2026-09-28) 저장 흔적이 없는 사진도 「봤고 고칠 게 없음」으로 받는다. 이름 점검은 그대로 한다."""
    out = []
    if viewed_all and man.get("kind") == "score":
        out.append("채점 묶음은 --viewed-all 로 받지 않는다 — 사진마다 「검토함」을 켜고 저장해 검토 흔적을 남겨야 한다")
    if (Path(returned_dir) / "images").is_dir():   # scp -r 로 폴더째 두 번 보내면 returned/images/ 로 들어가 옛 파일을 읽게 된다
        out.append("returned 안에 images 폴더가 있다 — 폴더째 다시 보낸 것 같다(다시 보낼 때는 고친 .json 만 returned/ 로)")
    for r in man["images"]:
        p = Path(returned_dir) / (Path(r["file"]).stem + ".json")
        if not p.exists():
            out.append(f"{r['file']}: 라벨 파일 없음")
            continue
        doc = X.read_json(p)
        # 검토한 사진 = 다시 저장됨(version 이 바뀜) 또는 「검토함」 플래그·검토 완료(checked) — 고칠 게 없으면
        # X-AnyLabeling 은 Ctrl+S 를 눌러도 저장하지 않는다(xany_io.REVIEW_FLAG 설명).
        if doc["version"] == X.DRAFT_VERSION and not doc["reviewed"] and not viewed_all:
            out.append(f"{r['file']}: 미검토(저장 흔적 없음 — 다 봤다면 --viewed-all)")
        probs = X.problems(doc["shapes"])
        if any(sh["label"] == X.EXCLUDE for sh in doc["shapes"]):     # exclude 사진은 통째로 빠진다 — 남은 제안은 상관없다
            probs = [m for m in probs if not m.startswith("제안이 남음")]
        else:
            shapes = X.drop_exact_duplicates(doc["shapes"])     # 똑같은 박스는 받을 때 합친다 — 거부할 일이 아니다
            probs += same_spot(shapes) + too_many(shapes)
        out += [f"{r['file']}: {m}" for m in probs]
    return out


def too_many(shapes):
    """같은 이름이 한 사진의 상한(X.max_per_name — wrench 2 · 나머지 1)을 넘는다 — 위치가 달라 어느 쪽이 맞는지 사람이 가린다
    (b005 f07741 B2 둘 중 하나가 노랑 B1 · 사용자 2026-10-03)."""
    n = Counter(s["label"] for s in shapes if s["label"] in X.CLASSES)
    out = []
    for k, v in n.items():
        if v > X.max_per_name(k):
            same = [s["box"] for s in shapes if s["label"] == k]
            hidden = any(LR.iou(a, b) >= 0.9 for i, a in enumerate(same) for b in same[i + 1:])
            out.append(f"같은 이름이 너무 많음: {k} {v}개 — 한 사진에 {X.max_per_name(k)}개까지"
                       + (" · 거의 같은 자리에 겹쳐 숨은 초벌 사본이 있다 — 하나를 지운다" if hidden else ""))
    return out


def same_spot(shapes, thr=0.9):
    """같은 자리(IoU ≥ thr)에 이름이 다른 박스 둘 — 한 물체에 이름 둘은 가장 해로운 라벨 오류(b003 f00205 B3·EMO · 사용자 승인 2026-09-29)."""
    out = []
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            a, b = shapes[i], shapes[j]
            if a["label"] != b["label"] and LR.iou(a["box"], b["box"]) >= thr:
                out.append(f"같은 자리에 이름 둘: {a['label']} · {b['label']} — 맞는 하나만 남긴다")
    return out


def unchanged(man, returned_dir):
    """저장 흔적이 없는(고치지 않은) 사진을 묶음 종류별로 — 「사람 확인」 사진을 하나도 안 고쳤다면 눈여겨본다."""
    out = {}
    for r in man["images"]:
        p = Path(returned_dir) / (Path(r["file"]).stem + ".json")
        if p.exists() and X.read_json(p)["version"] == X.DRAFT_VERSION:
            out.setdefault(r["kind"], []).append(r["file"])
    return out


def _center_in(a, b):
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


SOURCES = "sources.json"


def label_name(file):
    """묶음 파일 이름 <앞머리>__<짧은 세션>__fNNNNN.png → 라벨 이름 <짧은 세션>__fNNNNN."""
    return file.split("__", 1)[1].rsplit(".", 1)[0]


def load_sources(out):
    p = Path(out) / SOURCES
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def score_conflicts(man, sources):
    """학습 묶음이 채점 묶음의 라벨을 덮으려는 이름 — 채점 묶음끼리(1회차 → 2회차)는 덮어도 된다."""
    if man.get("kind") == "score":
        return []
    return sorted(n for n in (label_name(r["file"]) for r in man["images"])
                  if sources.get(n, {}).get("kind") == "score")


def write_index(path, rows, gone):
    """images.txt(라벨 이름 → 원본 경로)를 이름을 열쇠로 합쳐 통째로 다시 쓴다 — 다시 회수해도 줄이 겹치지 않고,
    exclude 로 바뀐 사진(gone)의 옛 줄은 지운다."""
    idx = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1); idx[k] = v
    for k in gone:
        idx.pop(k, None)
    idx.update(rows)
    path.write_text("".join(f"{k}\t{v}\n" for k, v in idx.items()), encoding="utf-8")


def tool_catch(stats):
    """공구 초벌이 잡아 준 비율(spec 2026-09-28-공구초벌-반복학습 §1) — 최종 공구 박스 중 초벌과 짝지어진 것.
    이름이 바뀐 박스도 새로 그리는 수고는 덜었으므로 넣고 따로 센다. 가짜 = 사람이 지운 공구 초벌."""
    t = stats.get("tool", {})
    caught = sum(t.get(k, 0) for k in ("그대로", "박스 조정", "크게 조정", "이름 바뀜"))
    total = caught + sum(stats.get("추가", {}).get(n, 0) for n in X.CLASSES[5:])
    return {"caught": caught, "total": total, "renamed": t.get("이름 바뀜", 0), "fake": t.get("지움", 0)}


def button_work(stats):
    """버튼 수고(spec 2026-09-29-버튼초벌-반복학습 §1 · §7 — 묶음 집계와 버튼 관문이 같은 잣대).
    사람이 손댈 버튼 박스 = 사람 확인 초벌 + 빠진 자리 제안 + 새로 그린 버튼 · 가짜 = 사람 확인 초벌 중 지운 것 ·
    기계 확정 틀림 = 기계 확정 초벌 중 같은 이름 IoU 0.5 짝이 없는 것(이름 바뀜 · 크게 조정 · 지움)."""
    ch, pr, au = stats.get("check", {}), stats.get("propose", {}), stats.get("auto", {})
    added = sum(stats.get("추가", {}).get(n, 0) for n in X.CLASSES[:5])
    c, p = sum(ch.values()), sum(pr.values())
    return {"work": c + p + added, "check": c, "propose": p, "added": added, "fake": ch.get("지움", 0),
            "auto_wrong": sum(au.get(k, 0) for k in ("이름 바뀜", "크게 조정", "지움"))}


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
    # 크게 고친 박스 — IoU 0.5 에 못 미쳐도 같은 이름으로 겹치면(IoU > 0.1 또는 한쪽 중심이 다른 쪽 안) 「지움 + 추가」가 아니다
    near = []
    for i in ud:
        d = drafts[i]
        name = d["label"][len(X.PROPOSAL_PREFIX):] if d["kind"] == "propose" else d["label"]
        for j in uf:
            f = finals[j]
            v = LR.iou(d["box"], f["box"])
            if f["label"] == name and (v > 0.1 or _center_in(d["box"], f["box"]) or _center_in(f["box"], d["box"])):
                near.append((v, i, j))
    for v, i, j in sorted(near, reverse=True):
        if i in ud and j in uf:
            ud.discard(i); uf.discard(j)
            stats[drafts[i]["kind"]]["크게 조정"] += 1
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
    ap.add_argument("--viewed-all", action="store_true", help="사용자가 묶음을 다 봤다고 확인함 — 저장 흔적 없는 사진도 받는다")
    a = ap.parse_args()
    man = json.loads(Path(a.manifest).expanduser().read_text(encoding="utf-8"))
    ret = Path(a.returned).expanduser()
    probs = check_returned(man, ret, viewed_all=a.viewed_all)
    if probs:
        print(f"❌ 회수 거부 — 문제 {len(probs)}건(아무것도 쓰지 않았다)")
        for m in probs:
            print("  -", m)
        sys.exit(1)
    un = unchanged(man, ret)
    if un:
        print("고치지 않은 사진(종류별):", {k: len(v) for k, v in un.items()})
        if un.get("check"):
            print("  ⚠️ 사람 확인 박스가 있는데 하나도 고치지 않은 사진 — 확인 박스를 모두 맞다고 본 것인지 눈여겨볼 것:")
            for f in un["check"]:
                print("   -", f)
    out = Path(a.out).expanduser()
    sources = load_sources(out)
    conflicts = score_conflicts(man, sources)
    if conflicts:
        print(f"❌ 회수 거부 — 채점 묶음이 쓴 라벨 {len(conflicts)}개를 학습 묶음 {man['batch']} 이 덮으려 한다(아무것도 쓰지 않았다)")
        for n in conflicts[:10]:
            print(f"  - {n} ← {sources[n]['batch']}")
        print("  다시 회수 순서 = 학습 묶음 → 채점 1회차 → 2회차(채점 묶음을 다시 회수하면 된다)")
        sys.exit(1)
    (out / "labels").mkdir(parents=True, exist_ok=True); (out / "stats").mkdir(exist_ok=True)
    total = {k: Counter() for k in ("auto", "check", "propose", "tool")}; added = Counter()
    excluded, rows, gone, merged = 0, {}, set(), 0
    for r in man["images"]:
        doc = X.read_json(ret / (Path(r["file"]).stem + ".json"))
        shapes = X.drop_exact_duplicates(doc["shapes"])
        merged += len(doc["shapes"]) - len(shapes)
        doc["shapes"] = shapes
        name = label_name(r["file"])          # <짧은 세션>__fNNNNN
        lines = X.to_yolo_lines(doc["shapes"], r["w"], r["h"])
        if lines is None:          # exclude 사진은 수정 집계에서도 뺀다 — 박스를 남기든 지우든 기계 정확도와 무관하다
            excluded += 1
            (out / "labels" / f"{name}.txt").unlink(missing_ok=True)   # 다시 회수했을 때 exclude 로 바뀐 사진의 옛 라벨
            gone.add(name)
            continue
        s = edit_stats(X.drop_exact_duplicates(r["drafts"]), doc["shapes"])   # 초벌의 똑같은 박스를 「지움」으로 세지 않는다
        for k in total:
            total[k].update(s[k])
        added.update(s["추가"])
        (out / "labels" / f"{name}.txt").write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        rows[name] = r["original"]
    write_index(out / "images.txt", rows, gone)
    kind = "score" if man.get("kind") == "score" else "train"
    sources.update({n: {"batch": man["batch"], "kind": kind} for n in list(rows) + sorted(gone)})
    (out / SOURCES).write_text(json.dumps(sources, ensure_ascii=False, indent=0), encoding="utf-8")
    (out / "data.yaml").write_text("names: [" + ", ".join(X.CLASSES) + "]\n", encoding="utf-8")
    stats = {"batch": man["batch"], "images": len(man["images"]), "exclude": excluded,
             **{k: dict(v) for k, v in total.items()}, "추가": dict(added)}
    stats["공구 초벌"] = tool_catch(stats)
    stats["버튼 수고"] = button_work(stats)
    (out / "stats" / f"{man['batch']}.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 회수 {len(rows)}장 · exclude {excluded}" + (f" · 똑같은 박스 합침 {merged}" if merged else ""))
    for k in ("auto", "check", "propose", "tool"):
        print(f"  {k:8}", dict(total[k]))
    print("  추가    ", dict(added))
    tc = stats["공구 초벌"]
    print(f"  공구 초벌이 잡아 준 비율 {tc['caught']}/{tc['total']}"
          + (f" = {tc['caught'] / tc['total']:.0%}" if tc["total"] else "")
          + f" (이름 바뀜 {tc['renamed']} 포함) · 가짜(지움) {tc['fake']}")
    bw = stats["버튼 수고"]
    print(f"  버튼 — 사람이 손댈 박스 {bw['work']}(사람 확인 {bw['check']} · 제안 {bw['propose']} · 새로 그림 {bw['added']})"
          f" · 가짜(사람 확인 중 지움) {bw['fake']} · 기계 확정 틀림 {bw['auto_wrong']}")
    import label_audit
    rep = label_audit.audit(out)
    print("label_audit — 모르는 클래스", rep["unknown_classes"], "· 조각 의심", len(rep["suspects"]),
          "· 배경 비율 %.2f" % rep["background_ratio"], "· 클래스별", rep["per_class"])


if __name__ == "__main__":
    main()
