"""Task 8 — 그래프·표 이미지(사용자 2026-10-08 「모델 채점에 대한 그래프와 표 이미지를 만들었으면해」).

실행(rfenv — matplotlib 은 rfenv 에만 있다): ~/env/rfenv/bin/python charts.py
입력: 판정.json · 오류분석.json(이 폴더) · ~/data/c001채점/prep.json
출력: 그림/F1~F5 그래프 · T1~T3 표 이미지(PNG · 밝은 바탕 · 문서·발표용). 값의 원본 표 = 판정.md · 오류분석.md.
색 = dataviz 기준 팔레트 — 5칸 검사기 통과(밝은 바탕 · 대비 3:1 미만 3칸은 글자·표 이미지로 보완).
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                   # noqa: E402
from matplotlib import font_manager as fm         # noqa: E402
from matplotlib.lines import Line2D               # noqa: E402
from matplotlib.patches import Patch              # noqa: E402

import common as C                                # noqa: E402
import ledger                                     # noqa: E402
from analyze import cell_key                      # noqa: E402  칸 순서(오류분석.md 와 같게)

for _f in sorted((Path.home() / ".local" / "share" / "fonts" / "Pretendard").glob("Pretendard-*.otf")):
    fm.fontManager.addfont(str(_f))
SURF, INK, INK2, MUTED, GRID, AXIS, HEAD = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#f0efec"
ACCENT = "#2a78d6"
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]       # 기준 팔레트 1~5 · 고정 순서
ON_DARK = {"#2a78d6", "#eb6834"}                                    # 막대 안 글자 = 흰색(그 밖 = 잉크)
plt.rcParams.update({"font.family": ["Pretendard", "NanumGothic", "DejaVu Sans"], "axes.unicode_minus": False,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
                     "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": INK2,
                     "axes.edgecolor": AXIS, "font.size": 10})
OUT = C.HERE / "그림"
CITE = "장소2 c001 194장 · 채점 라벨 = 초벌 + 사진마다 2명 검토(총 3회) · conf 0.65 · IoU 0.5 · 장소1 만 배운 모델"


def kn(k):
    return C.KEY_CLASS.get(k, "정밀도")


def value(sc, k):
    return sc["전체"]["precision"] if k == "P" else sc["클래스"][C.KEY_CLASS[k]]["recall"]


def style(ax):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_linewidth(0.8)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("그림", name)


def f1(J):
    """시연 HEF 2개 — 종류별 재현율(한 계열 · 파랑) · 막대 끝에 맞게/정답."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [5, 3.4]})
    fig.subplots_adjust(top=0.76, wspace=0.3)
    for ax, name in zip(axes, C.DEMO_HEFS):
        sc = J["모델요약"]["c001"][name]
        names = C.NAMES["button" if name.startswith("B") else "tool"]
        ys = list(range(len(names)))[::-1]
        rec = [sc["클래스"][n]["recall"] for n in names]
        ax.barh(ys, rec, height=0.42, color=ACCENT)
        for y, n, r in zip(ys, names, rec):
            c = sc["클래스"][n]
            ax.text(r + 0.015, y, f"{c['tp']}/{c['tp'] + c['fn']} ({r:.3f})", va="center", color=INK2, fontsize=9)
        ax.set_yticks(ys)
        ax.set_yticklabels(names)
        ax.set_xlim(0, 1.25)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_xlabel("재현율(맞게 찾은 수 / 정답)")
        ax.set_title(f"{name}\n정밀도 {sc['전체']['precision']:.3f} · 잘못 찾음 {sc['전체']['fp']} · 오분류 {sc['오분류']}",
                     loc="left", fontsize=10)
        style(ax)
    fig.suptitle("시연 모델(HEF · 파이 Hailo-8) — 처음 보는 장소2 c001", x=0.01, y=0.99, ha="left", fontsize=13, fontweight="semibold")
    fig.text(0.01, -0.03, CITE, fontsize=8, color=MUTED)
    save(fig, "F1_시연모델_재현율.png")


FAMILIES = [   # (파일, 제목, 무리, 기준 설정, 행 설정)
    ("F2a_판정_버튼.png", "버튼 — 기준 B-full-base(시연 설정)와 견줌", "button", "B-full-base",
     ["B-full-base", "B-early-base", "B-full-color", "B-full-noflip", "B-full-cutmix03", "B-full-blur"]),
    ("F2b_판정_공구_판A.png", "공구(판 A) — 기준 T-full-base 와 견줌", "tool", "T-full-base",
     ["T-full-base", "T-early-base", "T-full-in1024", "T-full-lr0005", "T-full-in1024lr0005",
      "T-full-S1t000", "T-full-S1t002", "T-full-S1t016", "T-full-cutmix03", "T-full-sgd"]),
    ("F2c_판정_공구_판B.png", "공구(판 B) — 기준 T-full-base-albu(시연 설정)와 견줌", "tool", "T-full-base-albu",
     ["T-full-base-albu", "T-full-base", "T-full-blur", "T-full-half", "T-full-b010"]),
]


def f2(J):
    """판정 — 지표마다 작은 그림 · 행 = 설정 · 점 = 시드 3개 · 파랑 띠 = 기준 시드 최저~최고(이 띠 밖이면 갈림)."""
    verdict = {(c["후보"], c["기준"]): c["지표"] for c in J["비교"]}
    for fname, title, g, base, rows in FAMILIES:
        keys = [k for k, _f in ledger.KEYS[g]]
        ncol = 3 if g == "button" else 2
        nrow = -(-len(keys) // ncol)
        fig, axes = plt.subplots(nrow, ncol, figsize=(4.8 * ncol, 0.38 * len(rows) * nrow + 1.6), sharey=True, squeeze=False)
        fig.subplots_adjust(wspace=0.55, hspace=0.45)
        for ax, k in zip(axes.flat, keys):
            bv = [value(J["모델요약"]["c001"][i], k) for i in C.setting(base)[2]]
            ax.axvspan(min(bv), max(bv), color=ACCENT, alpha=0.10, linewidth=0)
            allv = []
            for r, s in enumerate(rows):
                y = len(rows) - 1 - r
                vs = [value(J["모델요약"]["c001"][i], k) for i in C.setting(s)[2]]
                allv += vs
                col = ACCENT if s == base else MUTED
                ax.plot([min(vs), max(vs)], [y, y], color=col, linewidth=2, solid_capstyle="round")
                ax.scatter(vs, [y] * 3, s=40, color=col, edgecolors=SURF, linewidths=2, zorder=3, clip_on=False)
                v = verdict.get((s, base), {}).get(k)
                if v in ("위로 갈림", "아래로 갈림"):
                    ax.text(1.02, y, "▲ 위로" if v == "위로 갈림" else "▼ 아래로", transform=ax.get_yaxis_transform(),
                            va="center", fontsize=8.5, color=INK, clip_on=False)
            pad = max(0.01, (max(allv) - min(allv)) * 0.15)
            ax.set_xlim(min(allv) - pad, max(allv) + pad)
            ax.set_yticks(range(len(rows)))
            ax.set_yticklabels([s + (" (초벌 편향)" if s in C.DRAFT_BIASED else "") for s in rows][::-1])
            ax.set_title("정밀도(전체)" if k == "P" else f"{kn(k)} 재현율", loc="left", fontsize=10)
            style(ax)
        for ax in list(axes.flat)[len(keys):]:
            ax.axis("off")
        fig.legend(handles=[Line2D([], [], marker="o", color=ACCENT, linewidth=2, markersize=7, label="기준 설정 · 시드 3개"),
                            Line2D([], [], marker="o", color=MUTED, linewidth=2, markersize=7, label="견준 설정 · 시드 3개"),
                            Patch(color=ACCENT, alpha=0.10, label="기준 시드 최저~최고(이 밖 = 갈림)")],
                   loc="upper left", bbox_to_anchor=(0.01, 0.995), ncol=3, frameon=False, fontsize=9)
        fig.suptitle(f"c001 판정 — {title}", x=0.01, y=1.04, ha="left", fontsize=13, fontweight="semibold")
        fig.text(0.01, -0.02, CITE + " · ▲▼ = 채택 판정 규칙(시드 3개 모두 한쪽) · Q4 후보는 표시만(채택 아님)", fontsize=8, color=MUTED)
        save(fig, fname)


def f3(J):
    """변환 손실 — 지표마다 .pt 시드 3개(회색 점·선)와 HEF(파랑 마름모)."""
    fig, axes = plt.subplots(1, 4, figsize=(17, 4.6), squeeze=False)
    fig.subplots_adjust(wspace=0.75, top=0.72)
    for ax, v in zip(axes.flat, J["변환"]):
        hd = next(h for h in C.HEFS if h[0] == v["hef"])
        keys = [k for k, _f in ledger.KEYS[hd[2]]]
        for r, k in enumerate(keys):
            y = len(keys) - 1 - r
            vs = [value(J["모델요약"]["c001"][i], k) for i in C.setting(hd[4])[2]]
            ax.plot([min(vs), max(vs)], [y, y], color=MUTED, linewidth=2, solid_capstyle="round")
            ax.scatter(vs, [y] * 3, s=40, color=MUTED, edgecolors=SURF, linewidths=2, zorder=3, clip_on=False)
            ax.scatter([v["지표"][k]["hef"]], [y], s=80, marker="D", color=ACCENT, edgecolors=SURF, linewidths=2, zorder=4, clip_on=False)
            if v["지표"][k]["판정"] != "같은 수준":
                ax.text(1.02, y, "손실 의심", transform=ax.get_yaxis_transform(), va="center", fontsize=8.5, clip_on=False)
        ax.set_yticks(range(len(keys)))
        ax.set_yticklabels([kn(k) for k in keys][::-1])
        ax.set_title(f"{v['hef']}\n↔ .pt {hd[4]}", loc="left", fontsize=9.5)
        style(ax)
    fig.legend(handles=[Line2D([], [], marker="o", color=MUTED, linewidth=2, markersize=7, label=".pt 시드 3개(파이 CPU)"),
                        Line2D([], [], marker="D", color=ACCENT, linestyle="none", markersize=8, label="HEF(파이 Hailo-8 · 시연 검출기)")],
               loc="upper left", bbox_to_anchor=(0.01, 0.93), ncol=2, frameon=False, fontsize=9)
    fig.suptitle("c001 변환 손실 — HEF 가 같은 설정 .pt 의 시드 범위 안인가(재현율 · 정밀도)", x=0.01, y=0.99, ha="left", fontsize=13, fontweight="semibold")
    fig.text(0.01, -0.05, CITE + " · 「같은 수준」 = 시드 범위 안 또는 짝 .pt 와 1개 차이 이내(설계 §5.4)", fontsize=8, color=MUTED)
    save(fig, "F3_변환손실.png")


def f4(E):
    """오류 분석 — 시연 HEF 의 놓침 비율을 축마다 · 🔴 사후 층화(원인 분석용 · 성능 수치 아님)."""
    for fname, sname in (("F4a_오류분석_버튼.png", "B-full-base"), ("F4b_오류분석_공구.png", "T-full-base-albu")):
        miss = E[sname]["c001"]["놓침"]
        axes_names = [a for a in ("장면", "밝기", "크기", "끝", "쥠/놓임") if a in miss and len(miss[a]) > 1]
        one = [f"{a} = {next(iter(miss[a]))}" for a in ("장면", "밝기") if a in miss and len(miss[a]) == 1]
        fig, axes = plt.subplots(1, len(axes_names), figsize=(3.7 * len(axes_names), 3.4), squeeze=False)
        fig.subplots_adjust(wspace=0.9)
        for ax, a in zip(axes.flat, axes_names):
            cells = sorted(miss[a].items(), key=lambda kv: cell_key(kv[0]))
            ys = list(range(len(cells)))[::-1]
            rates = [c["놓침"][0] / c["정답"] for _v, c in cells]
            ax.barh(ys, rates, height=0.42, color=ACCENT)
            for y, (_v, c), r in zip(ys, cells, rates):
                ax.text(r + 0.01, y, f"{c['놓침'][0]}/{c['정답']}" + (" · 적음" if c["정답"] < 10 else ""),
                        va="center", color=INK2, fontsize=8.5)
            ax.set_yticks(ys)
            ax.set_yticklabels([v for v, _c in cells])
            ax.set_xlim(0, max(0.3, max(rates) * 1.6))
            ax.set_title(a, loc="left", fontsize=10)
            style(ax)
        hname = next(h[0] for h in C.HEFS if h[4] == sname)
        fig.suptitle(f"c001 놓침 비율 — {hname}(원인 분석용 · 사후 층화 · 성능 수치 아님)", x=0.01, y=1.06, ha="left", fontsize=12, fontweight="semibold")
        fig.text(0.01, -0.06, "칸 글자 = 놓침/정답 박스 · 「적음」 = 정답 10개 미만(비율을 읽지 않는다)"
                 + (f" · 칸이 하나뿐이라 뺀 축: {', '.join(one)}" if one else "") + " · " + CITE, fontsize=8, color=MUTED)
        save(fig, fname)


def f5(P):
    """학습 사진 구성 ↔ c001 — 종류별 박스 구성비(100% 쌓은 막대 · 2px 바탕 틈)."""
    comp = P["학습구성"]
    groups = [("button", [("B-full-base 외 4(학습 {n:,}장)", comp["B-full-base"]), ("B-early-base(학습 {n:,}장)", comp["B-early-base"])]),
              ("tool", [("T-full-base-albu 외(학습 {n:,}장)", comp["T-full-base-albu"]), ("T-full-half(학습 {n:,}장)", comp["T-full-half"]),
                        ("T-full-b010(학습 {n:,}장)", comp["T-full-b010"])])]
    fig, axes = plt.subplots(2, 1, figsize=(10, 4.6), gridspec_kw={"height_ratios": [3, 4]})
    fig.subplots_adjust(hspace=0.8)
    for ax, (g, rows) in zip(axes, groups):
        names = C.NAMES[g]
        data = [(lab.format(n=c["학습"]), c["박스"]) for lab, c in rows] + [("c001(194장)", {k: C.C001_BOXES[k] for k in names})]
        ys = list(range(len(data)))[::-1]
        for y, (lab, box) in zip(ys, data):
            tot, left = sum(box.values()), 0.0
            for i, n in enumerate(names):
                w = box[n] / tot
                ax.barh(y, w, left=left, height=0.5, color=SLOTS[i], edgecolor=SURF, linewidth=2)
                if w >= 0.09:
                    ax.text(left + w / 2, y, f"{n} {w:.0%}", ha="center", va="center", fontsize=8.5,
                            color="white" if SLOTS[i] in ON_DARK else INK)
                left += w
        ax.set_yticks(ys)
        ax.set_yticklabels([lab for lab, _b in data])
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
        ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
        ax.legend(handles=[Patch(color=SLOTS[i], label=n) for i, n in enumerate(names)], loc="lower left",
                  bbox_to_anchor=(0, 1.0), ncol=len(names), frameon=False, fontsize=9)
        style(ax)
    fig.suptitle("학습 사진(장소1)의 정답 박스 구성 ↔ c001(장소2)", x=0.01, y=1.04, ha="left", fontsize=13, fontweight="semibold")
    fig.text(0.01, -0.03, "학습 = 각 설정의 학습 몫(학습 중 검증·채점 몫 제외) · 같은 나눔을 쓰는 설정은 한 줄 · 출처 = prep.json 「학습구성」(설계 §3.4)", fontsize=8, color=MUTED)
    save(fig, "F5_학습구성.png")


def table_png(fname, title, header, rows, widths, note):
    h = 0.34 * (len(rows) + 1) + 1.0
    fig, ax = plt.subplots(figsize=(sum(widths), h))
    fig.subplots_adjust(left=0.01, right=0.99, top=1 - 0.6 / h, bottom=0.4 / h)
    ax.axis("off")
    t = ax.table(cellText=rows, colLabels=header, colWidths=[w / sum(widths) for w in widths], bbox=[0, 0, 1, 1], cellLoc="left")
    t.auto_set_font_size(False)
    t.set_fontsize(9)
    for (r, _c), cell in t.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_linewidth(0.8)
        cell.set_facecolor(HEAD if r == 0 else SURF)
        if r == 0:
            cell.get_text().set_fontweight("semibold")
    ax.set_title(title, loc="left", fontsize=12, fontweight="semibold")
    fig.text(0.01, 0.1 / h, note, fontsize=8, color=MUTED)
    save(fig, fname)


def tables(J, P):
    rows = [[c["묻는것"], f"{c['후보']} ↔ {c['기준']}", c["표시"].replace("**", "")] for c in J["비교"]]
    for v in J["변환"]:
        bad = [kn(k) for k, x in v["지표"].items() if x["판정"] != "같은 수준"]
        rows.append(["Q2", f"{v['hef']} ↔ .pt", "손실 의심: " + ", ".join(bad) if bad else "모든 지표 같은 수준"])
    table_png("T1_판정요약.png", "c001 판정 요약(규칙 = 설계 §5 · 채점 전 고정)", ["묻는 것", "비교", "판정"], rows, [0.8, 4.2, 6.5],
              CITE + " · Q4 = 2단계 재시험 후보 표시(채택 아님)")
    rows = []
    for name in C.DEMO_HEFS:
        sc = J["모델요약"]["c001"][name]
        for n in C.NAMES["button" if name.startswith("B") else "tool"]:
            c = sc["클래스"][n]
            rows.append([name, n, c["tp"], c["fp"], c["fn"], f"{c['precision']:.3f}", f"{c['recall']:.3f}"])
        rows.append([name, "전체", sc["전체"]["tp"], sc["전체"]["fp"], sc["전체"]["fn"],
                     f"{sc['전체']['precision']:.3f}", f"{sc['전체']['recall']:.3f}"])
    table_png("T2_시연모델.png", "시연 모델(HEF) — 처음 보는 장소2 c001", ["모델", "종류", "맞게 찾음", "잘못 찾음", "놓침", "정밀도", "재현율"],
              rows, [3.0, 0.9, 1.0, 1.0, 0.8, 0.9, 0.9], CITE)
    rows = []
    for name, c in P["학습구성"].items():
        tot = sum(c["박스"].values())
        rows.append([name, c["나눔"], f"{c['학습']:,}({c['배경'] / c['학습']:.1%})", c["학습중검증"],
                     f"{c['채점']}" + (f"+{c['세션채점']}" if c["세션채점"] else ""), f"{c['학습'] / 194:.1f}배",
                     " · ".join(f"{k} {v / tot:.0%}" for k, v in c["박스"].items()), c["라벨확인"]])
    for g in C.NAMES:
        tot = sum(C.C001_BOXES[k] for k in C.NAMES[g])
        rows.append([f"c001 {'버튼' if g == 'button' else '공구'}", "장소2", "194", "—", "—", "1", " · ".join(f"{k} {C.C001_BOXES[k] / tot:.0%}" for k in C.NAMES[g]), "—"])
    table_png("T3_학습사진.png", "모델마다 학습 사진 수·비율 ↔ c001", ["설정", "나눔", "학습(배경 %)", "학습 중 검증", "장소1 채점", "학습÷c001", "박스 구성", "라벨 확인"],
              rows, [2.0, 1.3, 1.3, 1.0, 1.0, 0.9, 4.8, 0.9], "학습 사진은 모두 장소1(2026-09-23) · 라벨 확인 = 학습 때 라벨 지문과 지금 사본이 같은가(기록 전 = 지문 기록 이전 학습)")


def main():
    J = C.load_json(C.HERE / "판정.json")
    E = C.load_json(C.HERE / "오류분석.json")
    P = C.load_json(C.W / "prep.json")
    f1(J)
    f2(J)
    f3(J)
    f4(E)
    f5(P)
    tables(J, P)


if __name__ == "__main__":
    main()
