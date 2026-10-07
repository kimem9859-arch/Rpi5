"""Task 6 — 판정(설계 §5): Q3 지금 ↔ 옛 · 판 확인 · Q4 후보 표시 · Q2 변환 손실 · Q1 시연 값 · 보조 22 · 장소1 참고.

실행(python3): python3 judge.py [--self-test]
출력: 판정.md · 판정.json (이 폴더)
"""
import argparse
import sys

import common as C
import ledger
from score_lib import operating_point



def label(kind, cand, verdict):
    """설계 §5.1~§5.3 표 그대로 — verdict = ledger.adopt 의 지표별 「위로 갈림」·「아래로 갈림」·「겹침」(후보 기준)."""
    up = [k for k, v in verdict.items() if v == "위로 갈림"]
    down = [k for k, v in verdict.items() if v == "아래로 갈림"]
    show = lambda ks: ", ".join(C.KEY_CLASS.get(k, "정밀도") for k in ks)   # noqa: E731
    if kind == "Q3":
        if up and not down:
            return f"장소2 에서 옛 설정이 낫다({show(up)}) → 시연 모델 그대로 · 2단계 설계에 넘김"
        if down and not up:
            return f"장소2 에서도 지금 설정이 낫다({show(down)})"
        if up and down:
            return f"엇갈림(옛 설정 위: {show(up)} · 아래: {show(down)}) → 지표별 2단계에"
        return "장소2 에서 가릴 수 없음 → 지금 설정 유지"
    if kind == "판":
        return f"판 차이가 장소2 에서 드러남({show(up + down)})" if up or down else "판 차이가 장소2 채점에서 드러나지 않음"
    if up and not down:
        if cand in C.DRAFT_BIASED:
            return f"위로 갈림({show(up)}) · 초벌 편향 가능 — 재시험 후보로 표시하지 않음"
        return f"**2단계 재시험 후보**({show(up)})"
    if down and not up:
        return f"장소2 손해 표시({show(down)})"
    if up and down:
        return f"엇갈림(위: {show(up)} · 아래: {show(down)})" + (" · 위쪽은 초벌 편향 가능" if cand in C.DRAFT_BIASED else "")
    return "장소2 에서도 못 가림"


def pan_of_settings():
    """설정 → 판(albumentations 유무) — 시드 3개가 같은 판인지도 확인한다(최종 리뷰 M8)."""
    out = {}
    for name, _g, ids, _use in C.SETTINGS:
        v = {C.load_json(C.RESULTS / i / "요약.json")["판"].get("albumentations") for i in ids}
        if len(v) != 1:
            raise ValueError(f"{name} 시드끼리 판이 다르다 {v}")
        out[name] = v.pop()
    return out


def pan_problems(compare, pan):
    """Q4 = 같은 판의 기준과 · 판 확인 = 다른 판끼리 — 설계 §5.2·§5.3 의 짝이 요약.json 「판」과 맞는지."""
    probs = []
    for kind, cand, base, _d in compare:
        if kind == "Q4" and pan[cand] != pan[base]:
            probs.append(f"Q4 {cand} ↔ {base} 판이 다르다")
        if kind == "판" and pan[cand] == pan[base]:
            probs.append(f"판 확인 {cand} ↔ {base} 가 같은 판이다")
    return probs


def fp_problems(outs, prep):
    """모든 출력의 라벨 지문 = 지금 prep.json 의 묶음 지문 — 옛 라벨 결과가 섞이지 않게(최종 리뷰 I2)."""
    return [f"{k} 라벨지문 {o.get('라벨지문')} ≠ {prep[o['set']]['지문']}" for k, o in outs.items() if o.get("라벨지문") != prep[o["set"]]["지문"]]


def model_info():
    """모델마다 종료이유 · 에폭 · conf · 판 · 이상 · 이어서 — 결과 폴더 요약.json(설계 §3.2 · 최종 리뷰 M9)."""
    out = {}
    for i in C.all_ids():
        su = C.load_json(C.RESULTS / i / "요약.json")
        out[i] = {"설정": C.setting_of_id(i), "종료이유": su.get("종료이유"), "에폭": su.get("에폭"), "best_epoch": su.get("best_epoch"),
                  "conf": su.get("conf"), "판": "B" if su["판"].get("albumentations") else "A",
                  "나눔": (su.get("나눔") or {}).get("name"), "이상": bool(su.get("이상")), "이어서": bool(su.get("이어서"))}
    return out


def pair_disagree(hef_rec, pt_rec, names):
    """짝 단위 불일치(참고 · 판정 규칙 아님 · 최종 리뷰 제안 3) — 같은 사진·같은 종류에서 HEF 만 놓침 / .pt 만 놓침.
    종류마다 사진에 박스가 많아야 1개라(설계 §2.1) 좌표계가 달라도(.pt = 640 늘린 좌표) 종류로 짝지을 수 있다."""
    hef_only, pt_only = [], []
    for n in hef_rec:
        h = operating_point({"x": ([tuple(g) for g in hef_rec[n]["gt"]], [tuple(p) for p in hef_rec[n]["pred"]])}, names, C.CONF)
        q = operating_point({"x": ([tuple(g) for g in pt_rec[n]["gt"]], [tuple(p) for p in pt_rec[n]["pred"]])}, names, C.CONF)
        for k in names:
            if h[k]["fn"] and not q[k]["fn"]:
                hef_only.append((n, k))
            if q[k]["fn"] and not h[k]["fn"]:
                pt_only.append((n, k))
    return len(hef_only), len(pt_only), hef_only, pt_only


def count_of(sc, key):
    """§5.4 「개수」 — 재현율 지표 = 그 종류의 맞게 찾은 수 · 정밀도 = 잘못 찾은 수(전체)."""
    return sc["전체"]["fp"] if key == "P" else sc["클래스"][C.KEY_CLASS[key]]["tp"]


def same_level(h, p0, seeds, group):
    """설계 §5.4 — 지표마다 HEF 가 같은 설정 .pt 시드 3개의 최소~최대 안이거나 짝 .pt 와 개수 1 이내면 「같은 수준」."""
    out = {}
    for k, f in ledger.KEYS[group]:
        vs = [f(s) for s in seeds]
        d = count_of(h, k) - count_of(p0, k)
        ok = min(vs) <= f(h) <= max(vs) or abs(d) <= 1
        out[k] = {"hef": f(h), "pt_s0": f(p0), "pt_범위": [min(vs), max(vs)], "개수차": d,
                  "판정": "같은 수준" if ok else "장소2 변환 손실 의심"}
    return out


def self_test():
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + msg)
        ok = ok and cond
    check(label("Q3", "B-early-base", {"B1R": "위로 갈림", "P": "겹침"}).startswith("장소2 에서 옛 설정이 낫다(B1)"), "Q3 옛 위로만")
    check(label("Q3", "B-early-base", {"B1R": "아래로 갈림", "P": "겹침"}).startswith("장소2 에서도 지금 설정이 낫다(B1)"), "Q3 옛 아래로만")
    check(label("Q3", "B-early-base", {"B1R": "위로 갈림", "P": "아래로 갈림"}).startswith("엇갈림"), "Q3 엇갈림")
    check(label("Q3", "T-early-base", {"dR": "겹침", "P": "겹침"}).startswith("장소2 에서 가릴 수 없음"), "Q3 겹침")
    check(label("판", "T-full-base", {"dR": "겹침"}) == "판 차이가 장소2 채점에서 드러나지 않음", "판 겹침")
    check(label("판", "T-full-base", {"dR": "아래로 갈림"}).startswith("판 차이가 장소2 에서 드러남(driver)"), "판 갈림")
    check(label("Q4", "T-full-blur", {"wR": "위로 갈림", "P": "겹침"}) == "**2단계 재시험 후보**(wrench)", "Q4 후보")
    check("표시하지 않음" in label("Q4", "T-full-in1024", {"wR": "위로 갈림"}), "Q4 초벌 편향")
    check(label("Q4", "B-full-blur", {"P": "아래로 갈림"}) == "장소2 손해 표시(정밀도)", "Q4 손해")
    mk = lambda tp, fp: {"클래스": {"driver": {"tp": tp, "recall": tp / 10}, "wrench": {"tp": 5, "recall": 0.5},     # noqa: E731
                                     "pliers": {"tp": 5, "recall": 0.5}}, "전체": {"fp": fp, "precision": 1 - fp / 20}}
    r = same_level(mk(6, 1), mk(7, 1), [mk(7, 1), mk(8, 1), mk(9, 1)], "tool")
    check(r["dR"]["판정"] == "같은 수준" and r["dR"]["개수차"] == -1, "변환 — 범위 밖이어도 개수 1 차이는 같은 수준")
    r = same_level(mk(5, 1), mk(7, 1), [mk(7, 1), mk(8, 1), mk(9, 1)], "tool")
    check(r["dR"]["판정"] == "장소2 변환 손실 의심", "변환 — 범위 밖 · 개수 2 차이")
    r = same_level(mk(8, 4), mk(7, 1), [mk(7, 1), mk(8, 1), mk(9, 1)], "tool")
    check(r["dR"]["판정"] == "같은 수준" and r["P"]["판정"] == "장소2 변환 손실 의심", "변환 — 정밀도는 잘못 찾은 수로")
    print("자체 시험 " + ("✅" if ok else "❌"))
    return 0 if ok else 1



def pt(set_name, rid):
    return C.load_json(C.W / "out" / "pt" / set_name / f"{rid}.json")["요약"]


def hef(set_name, name):
    return C.load_json(C.W / "out" / "hef" / set_name / f"{name}.json")


def fmt(sc, k):
    if k == "P":
        if sc["전체"]["tp"] + sc["전체"]["fp"] == 0:
            return "—(예측 0)"                     # 0/0 을 0.000 으로 쓰지 않는다
        return f"{sc['전체']['precision']:.3f}"
    c = sc["클래스"][C.KEY_CLASS[k]]
    return f"{c['tp']}/{c['tp'] + c['fn']}"


def seeds_cell(scs, k):
    return " · ".join(fmt(s, k) for s in scs)


def off_diag(sc, names):
    m, k = sc["혼동"], len(names)
    return ", ".join(f"{names[i]}→{names[j]} {m[i][j]}" for i in range(k) for j in range(k) if i != j and m[i][j]) or "없음"


def tool_fp_on_empty(rec):
    """공구 없는 사진(정답 공구 0) 위의 0.65 이상 예측 수 — 설계 §4.8."""
    return sum(sum(1 for p in r["pred"] if p[1] >= C.CONF) for r in rec.values() if not r["gt"])


def main():
    probs = pan_problems(C.COMPARE, pan_of_settings())
    prep = C.load_json(C.W / "prep.json")["묶음"]
    outs = {f"pt/{s}/{i}": C.load_json(C.W / "out" / "pt" / s / f"{i}.json") for s in ("c001", "dark") for i in C.all_ids()}
    outs.update({f"hef/{s}/{h[0]}": C.load_json(C.W / "out" / "hef" / s / f"{h[0]}.json") for s in ("c001", "dark") for h in C.HEFS})
    probs += fp_problems(outs, prep)
    if probs:
        print("🔴 판정 전 확인 실패 — " + " · ".join(probs[:10]))
        return 1
    md, js = ["# c001 채점 판정 (자동 생성 — judge.py · 손으로 고치지 않는다)", "",
              "> 칸의 재현율 = 맞게 찾은 수/정답 · 정밀도 = 소수 · 시드 칸 = 시드 0 · 1 · 2 · conf 0.65 · IoU 0.5 · 규칙 = 설계 §5(채점 전 고정)", ""], {}
    js["모델요약"] = {s: {i: pt(s, i) for i in C.all_ids()} for s in ("c001", "dark")}
    for s in ("c001", "dark"):
        js["모델요약"][s].update({h[0]: hef(s, h[0])["요약"] for h in C.HEFS})

    # Q1 — 시연 HEF
    md += ["## Q1 시연 모델의 장소2 값 (HEF · 파이 Hailo-8 · 시연 검출기)", ""]
    for name in C.DEMO_HEFS:
        h = hef("c001", name)
        sc, names = h["요약"], C.NAMES[h["group"]]
        md += [f"### {name} — c001 {sc['사진']}장 · 정답 {sc['정답박스']}", "",
               "| 종류 | 맞게 찾음 | 잘못 찾음 | 놓침 | 정밀도 | 재현율 |", "|---|---|---|---|---|---|"]
        md += [f"| {n} | {sc['클래스'][n]['tp']} | {sc['클래스'][n]['fp']} | {sc['클래스'][n]['fn']} | "
               f"{sc['클래스'][n]['precision']:.3f} | {sc['클래스'][n]['recall']:.3f} |" for n in names]
        md += [f"| 전체 | {sc['전체']['tp']} | {sc['전체']['fp']} | {sc['전체']['fn']} | {sc['전체']['precision']:.3f} | {sc['전체']['recall']:.3f} |", "",
               f"- 오분류 {sc['오분류']}({off_diag(sc, names)}) · 오검출 {sc['오검출']}"
               + (f" · 공구 없는 사진 위 오검출 {tool_fp_on_empty(h['사진별'])}" if h["group"] == "tool" else ""),
               "- conf 훑기(참고 · 문턱 안 바꿈) — " + " · ".join(
                   f"{c} 맞게 {sum(v['tp'] for v in d.values())} 잘못 {sum(v['fp'] for v in d.values())} 놓침 {sum(v['fn'] for v in d.values())}"
                   for c, d in h["훑기"].items()), ""]

    # Q2 — 변환 손실
    md += ["## Q2 변환 손실 — HEF ↔ 같은 설정 .pt (설계 §5.4)", ""]
    js["변환"] = []
    for name, _path, g, pair, sname in C.HEFS:
        h = hef("c001", name)["요약"]
        seeds = [pt("c001", i) for i in C.setting(sname)[2]]
        r = same_level(h, pt("c001", pair), seeds, g)
        js["변환"].append({"hef": name, "지표": r})
        md += [f"### {name} ↔ {sname}", "", "| 지표 | HEF | .pt 시드 0 | .pt 시드 3개 범위 | 개수 차(HEF − 시드 0) | 판정 |", "|---|---|---|---|---|---|"]
        md += [f"| {C.KEY_CLASS.get(k, '정밀도')} | {v['hef']:.3f} | {v['pt_s0']:.3f} | {v['pt_범위'][0]:.3f}~{v['pt_범위'][1]:.3f} | {v['개수차']:+d} | {v['판정']} |"
               for k, v in r.items()] + [""]
        dis = {}
        for s in ("c001", "dark"):
            a, b, ha, pb = pair_disagree(hef(s, name)["사진별"], C.load_json(C.W / "out" / "pt" / s / f"{pair}.json")["사진별"], C.NAMES[g])
            dis[s] = {"HEF만": a, "pt만": b, "HEF만_목록": ha, "pt만_목록": pb}
            md.append(f"- 짝 단위 불일치(참고 · 판정 규칙 아님) {s} — HEF 만 놓침 {a}" + (f"({', '.join(f'{x}·{k}' for x, k in ha)})" if s == "dark" and ha else "")
                      + f" · .pt 시드 0 만 놓침 {b}")
        js["변환"][-1]["짝불일치"] = dis
        md.append("")

    # Q3 · 판 · Q4
    js["비교"] = []
    for kind, title in (("Q3", "## Q3 지금 기준 ↔ 옛 설정 (설계 §5.1)"), ("판", "## 판 확인 (설계 §5.2)"),
                        ("Q4", "## Q4 장소1 후보 다시 보기 — 표시만 · 채택 아님 (설계 §5.3)")):
        md += [title, ""]
        for k2, cand, base, diff in [c for c in C.COMPARE if c[0] == kind]:
            g = C.setting(cand)[1]
            cs = [pt("c001", i) for i in C.setting(cand)[2]]
            bs = [pt("c001", i) for i in C.setting(base)[2]]
            verdict, _adopted = ledger.adopt(cs, bs, g)
            mark = label(kind, cand, verdict)
            js["비교"].append({"묻는것": kind, "후보": cand, "기준": base, "다른점": diff, "지표": verdict, "표시": mark})
            md += [f"### {cand} ↔ {base} — {mark}", "", f"- 다른 점: {diff}", "",
                   f"| 지표 | {cand} | {base} | 갈림 |", "|---|---|---|---|"]
            md += [f"| {C.KEY_CLASS.get(k, '정밀도')} | {seeds_cell(cs, k)} | {seeds_cell(bs, k)} | {verdict[k]} |" for k, _f in ledger.KEYS[g]]
            md += [f"| 오분류 · 오검출 | {' · '.join(str(s['오분류']) for s in cs)} / {' · '.join(str(s['오검출']) for s in cs)} | "
                   f"{' · '.join(str(s['오분류']) for s in bs)} / {' · '.join(str(s['오검출']) for s in bs)} | (참고) |", ""]
        if kind == "Q4":
            md += ["> 🔴 후보 15개 × 지표 4~6개를 견줬다 — 효과가 없어도 몇 개는 우연히 위로 갈린다(1/20 씩). 「재시험 후보」는 2단계에서 시드 3개로 다시 보고 장소3 으로 확인한다.", ""]

    # 모델 정보(설계 §3.2)
    js["모델정보"] = model_info()
    md += ["## 모델 정보 (결과 폴더 요약.json · 설계 §3.2)", "", "| 설정 | 판 · 나눔 | 종료이유(시드 0 · 1 · 2) | 에폭(끝 / 가장 좋은) | conf | 이상 · 이어서 |", "|---|---|---|---|---|---|"]
    for sname, _g, ids, _use in C.SETTINGS:
        v = [js["모델정보"][i] for i in ids]
        md.append(f"| {sname} | {v[0]['판']} · {v[0]['나눔']} | {' · '.join(str(x['종료이유']) for x in v)} | "
                  f"{' · '.join(str(x['에폭']) + '/' + str(x['best_epoch']) for x in v)} | {v[0]['conf']} | "
                  f"{'없음' if not any(x['이상'] or x['이어서'] for x in v) else '있음'} |")
    md.append("")

    # 장소1 참고
    md += ["## 장소1 채점 292장 (참고 · 다른 사진 · 저장된 채점.json)", "", "| 설정 | 지표별 시드 0 · 1 · 2 |", "|---|---|"]
    for sname, g, ids, _use in C.SETTINGS:
        scs = [C.load_json(C.RESULTS / i / "채점.json") for i in ids]
        md.append(f"| {sname} | " + " / ".join(f"{C.KEY_CLASS.get(k, '정밀도')} {seeds_cell(scs, k)}" for k, _f in ledger.KEYS[g]) + " |")
    md.append("")

    # 보조 22
    md += ["## 보조 — 어두운 조명 세션 22장 (참고 · 판정 안 함 · 설계 §2.3)", "", "| 모델 | 지표 |", "|---|---|"]
    for name in C.DEMO_HEFS:
        h = hef("dark", name)["요약"]
        g = hef("dark", name)["group"]
        md.append(f"| {name} | " + " · ".join(f"{C.KEY_CLASS.get(k, '정밀도')} {fmt(h, k)}" for k, _f in ledger.KEYS[g])
                  + f" · 오분류 {h['오분류']}({off_diag(h, C.NAMES[g])}) · 오검출 {h['오검출']} |")
    for sname in ("B-full-base", "T-full-base-albu"):
        g = C.setting(sname)[1]
        scs = [pt("dark", i) for i in C.setting(sname)[2]]
        md.append(f"| {sname} .pt | " + " · ".join(f"{C.KEY_CLASS.get(k, '정밀도')} {seeds_cell(scs, k)}" for k, _f in ledger.KEYS[g]) + " |")
    md.append("")
    (C.HERE / "판정.md").write_text("\n".join(md), encoding="utf-8")
    C.write_json(C.HERE / "판정.json", js)
    print("판정.md · 판정.json 저장")
    for c in js["비교"]:
        print(f"  {c['묻는것']} {c['후보']} ↔ {c['기준']}: {c['표시']}")
    for v in js["변환"]:
        print(f"  Q2 {v['hef']}: " + ", ".join(f"{k} {x['판정']}" for k, x in v["지표"].items()))
    return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    sys.exit(self_test() if a.self_test else main())
