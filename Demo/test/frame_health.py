"""깨진 프레임(h264 디코딩 실패)을 찾아 후보 목록을 낸다 — 촬영 직후·업로드 전.

왜 필요한가:
    2026-09-05 시연영상 추출분에서 세 형태가 나왔다 — **형광 초록 뭉갬** · **색이 어긋난
    띠**(분홍·파랑) · **흰색으로 날아감**. 라벨링 전에 빼지 않으면 사람이 없는 물체를
    찾느라 시간을 쓰고, 남으면 학습이 그 화면을 배경으로 배운다.

    🔴 **밝기 지표로는 정상과 갈리지 않는다** — 어두운 콘솔과 밝은 배경의 경계가 찢김처럼
    잡혀 오탐이 났다(`165513_f00029`). 밝기를 뺀 **색조**가 갈라 준다. 다만 흰색으로
    날아간 형태는 색조가 멀쩡하므로 **평탄한 흰 블록 비율**을 함께 본다.

사용법:
    python3 test/frame_health.py <폴더> [<폴더> ...] --out cand.txt

판정(둘 중 하나면 후보):
    ① 색조 이음매 > --seam(기본 0.02)   — 열 평균색을 밝기로 나눈 뒤 이웃 열과의 차
    ② 흰 뭉갬 비율 > --washed(기본 0.25) — 밝고(평균>200) 평탄한(표준편차<4) 8x8 블록 비율

🔴 자동 삭제하지 않는다 — 목록을 사람이 본다(얼굴 후보 91장이 전부 오탐이었던 전례).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

EXT = {".png", ".jpg", ".jpeg"}


def metrics(path: Path) -> tuple[float, float]:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) + 1.0
    col = rgb.mean(axis=0)                                  # 열 평균색
    chrom = col / col.sum(axis=1, keepdims=True)            # 밝기를 뺀 색조
    seam = float(np.abs(np.diff(chrom, axis=0)).sum(axis=1).max())
    # 🔑 밝기는 루마(사람 눈 가중치)다 — RGB 평균을 쓰면 형광 초록(200,255,0)이
    #    평균 152 로 어두워져 「흰 뭉갬」에서 빠진다(2026-09-21 대조에서 드러남).
    g = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114
    h, w = g.shape[0] // 8 * 8, g.shape[1] // 8 * 8
    blk = g[:h, :w].reshape(h // 8, 8, w // 8, 8)
    washed = float(((blk.mean(axis=(1, 3)) > 200) & (blk.std(axis=(1, 3)) < 4)).mean())
    return seam, washed


def scan(roots: list[Path], seam_max: float = 0.02, washed_max: float = 0.25) -> list[dict]:
    rows = []
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() not in EXT:
                continue
            s, w = metrics(p)
            # 🔑 이름은 root 기준 상대경로다 — 영상 폴더마다 f00001.png 가 따로 있어
            #    파일명만 쓰면 어느 영상인지 구분되지 않는다(2026-09-21 실행에서 드러남).
            rows.append({"file": str(p.relative_to(root)), "path": str(p), "seam": s,
                         "washed": w, "suspect": bool(s > seam_max or w > washed_max)})
    return rows


def _selftest() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        a = np.zeros((64, 64, 3), np.uint8)
        a[:, :, :] = 90                                      # 평범한 회색 = 정상
        Image.fromarray(a).save(root / "ok.png")
        b = a.copy()
        b[:, :32] = (200, 255, 0)                            # 왼쪽 절반 형광 초록
        Image.fromarray(b).save(root / "tint.png")
        c = a.copy()
        c[:, :48] = 250                                      # 왼쪽이 평탄한 흰색
        Image.fromarray(c).save(root / "washed.png")
        r = {x["file"]: x for x in scan([root])}
    assert r["tint.png"]["suspect"], r["tint.png"]
    assert r["washed.png"]["suspect"], r["washed.png"]
    assert not r["ok.png"]["suspect"], r["ok.png"]
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="*", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--seam", type=float, default=0.02)
    ap.add_argument("--washed", type=float, default=0.25)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.roots:
        ap.error("폴더를 주거나 --selftest 를 쓴다")
    rows = scan(a.roots, a.seam, a.washed)
    bad = [r for r in rows if r["suspect"]]
    print(f"사진 {len(rows)}장 · 깨짐 후보 {len(bad)}장 ({len(bad)/max(len(rows),1):.1%})")
    for r in sorted(bad, key=lambda r: -r["seam"])[:20]:
        print(f"  {r['file']} 색조이음매 {r['seam']:.4f} · 흰뭉갬 {r['washed']:.2f}")
    if a.out:
        a.out.write_text("\n".join(r["file"] for r in bad) + "\n", encoding="utf-8")
        print(f"목록 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
