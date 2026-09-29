"""build_guide_page — 원본 md 에서 아티팩트 페이지를 만드는 생성기를 고정한다.

실행: python3 Demo/selftest/test_guide_page.py
정본 설계: ../../docs/superpowers/specs/2026-09-29-라벨링안내서-design.md §3
"""
import os
import sys
import tempfile
from pathlib import Path

_DEMO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DEMO_DIR, "docs"))

import build_guide_page as G

_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def _src(d, body):
    (Path(d) / "img").mkdir(exist_ok=True)
    (Path(d) / "img" / "a.png").write_bytes(PNG)
    md = Path(d) / "g.md"; md.write_text(body, encoding="utf-8")
    return md


def test_없는_그림은_멈춤():
    print("[1] 🔴 원본이 없는 그림을 가리키면 조용히 깨진 그림이 아니라 FileNotFoundError")
    with tempfile.TemporaryDirectory() as d:
        md = _src(d, "# 제목\n\n## 하나\n\n<img src=\"img/없음.png\" width=\"40%\">\n")
        try:
            G.build(md, Path(d) / "out.html"); raised = False
        except FileNotFoundError:
            raised = True
        check(raised, "없는 그림 = FileNotFoundError")


def test_목차_주소는_영문():
    print("[2] 🔴 한국어 절 제목도 목차 링크가 통한다 — 절 id = s1, s2 … · 목차 href 가 그 id")
    with tempfile.TemporaryDirectory() as d:
        md = _src(d, "# 제목\n\n## 설치\n\n글\n\n## 검토 방법\n\n글\n")
        G.build(md, Path(d) / "out.html")
        h = (Path(d) / "out.html").read_text(encoding="utf-8")
        check('id="s1"' in h and 'id="s2"' in h and 'href="#s1"' in h and 'href="#s2"' in h, "s1·s2 id 와 목차 링크")
        check(">설치<" in h and ">검토 방법<" in h, "목차에 한국어 제목")


def test_표는_가로_스크롤_틀():
    print("[3] 폰에서 넓은 표가 페이지를 밀지 않게 — 표마다 가로 스크롤 틀로 감싼다 · 그림은 data URI 로 품는다")
    with tempfile.TemporaryDirectory() as d:
        md = _src(d, "# 제목\n\n## 표\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<img src=\"img/a.png\" width=\"40%\">\n")
        G.build(md, Path(d) / "out.html")
        h = (Path(d) / "out.html").read_text(encoding="utf-8")
        check('<div class="table-wrap"><table>' in h, "표 감쌈")
        check('src="data:image/png;base64,' in h and 'src="img/a.png"' not in h, "그림 품음")


def test_크기_상한():
    print("[4] 🔴 페이지가 상한을 넘으면 멈춘다(아티팩트 16MB)")
    with tempfile.TemporaryDirectory() as d:
        md = _src(d, "# 제목\n\n## 하나\n\n<img src=\"img/a.png\">\n")
        try:
            G.build(md, Path(d) / "out.html", max_bytes=100); raised = False
        except ValueError:
            raised = True
        check(raised, "상한 초과 = ValueError")


def test_페이지_규칙():
    print("[5] 아티팩트 페이지 규칙 — 앞머리 <title> · 두 테마 토큰 · <html>/<body> 태그 없음")
    with tempfile.TemporaryDirectory() as d:
        md = _src(d, "# 제목\n\n## 하나\n\n글\n")
        G.build(md, Path(d) / "out.html")
        h = (Path(d) / "out.html").read_text(encoding="utf-8")
        check("<title>라벨링 검토 안내서</title>" in h[:8000], "title")
        check("prefers-color-scheme: dark" in h and ':root[data-theme="dark"]' in h, "두 테마")
        check("<html" not in h and "<body" not in h, "skeleton 태그 없음")


if __name__ == "__main__":
    test_없는_그림은_멈춤()
    test_목차_주소는_영문()
    test_표는_가로_스크롤_틀()
    test_크기_상한()
    test_페이지_규칙()
    print()
    if _fails:
        print(f"❌ 실패 {len(_fails)}건")
        for m in _fails:
            print(f"   - {m}")
        sys.exit(1)
    print("✅ 안내서 페이지 생성기 검증 통과")
