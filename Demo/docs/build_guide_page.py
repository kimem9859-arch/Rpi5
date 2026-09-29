"""라벨링 안내서 페이지 생성기 — 원본 md(labeling_guide.md) → 아티팩트 HTML 한 파일.

실행(Demo/ 에서, 시스템 python3 · markdown 3.x): python3 docs/build_guide_page.py docs/labeling_guide.md <출력 html>
정본 설계 = 상위 sop-project docs/superpowers/specs/2026-09-29-라벨링안내서-design.md §3
🔴 문구는 원본 md 에만 쓴다 — 이 파일에는 페이지 틀(모양)만 둔다. 그림은 data URI 로 품어 파일 하나로 낸다.
   원본 쓰는 법: 절 = `## ` (목차가 된다) · 단축키 = <kbd>R</kbd> · 버튼 이름 = `B1` 처럼 코드 표기(실제 버튼 색 칩이 된다)
   · 그림 = <img src="labeling_guide_img/…" width="…%" alt="…"> (누르면 크게 보인다)
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import markdown

TITLE = "라벨링 검토 안내서"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
BUTTONS = ("B1", "B2", "B3", "B4", "EMO")

STYLE = """
/* 배치: 넓은 화면 = 왼쪽 목차(고정) + 본문 한 단(약 68자) · 폰 = 목차가 본문 위로 */
:root {
  --bg: #f4f6f9; --panel: #ffffff; --fg: #1b2230; --muted: #596377; --rule: #d8dde6;
  --accent: #2753c9; --accent-soft: #e6ecfb; --warn: #b3261e; --warn-soft: #fbeceb;
  --key-bg: #ffffff; --key-edge: #b9c1cf;
  --chip-b1: #f2c230; --chip-b2: #f7f7f2; --chip-b3: #e98aa6; --chip-b4: #2f5fd6; --chip-emo: #cf2f2f;
  --chip-ink-dark: #1b2230; --chip-ink-light: #ffffff;
  --f-body: "IBM Plex Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #11151c; --panel: #181e27; --fg: #e5e9f0; --muted: #9aa4b6; --rule: #2a323f;
    --accent: #86a6ff; --accent-soft: #1d2842; --warn: #ff8a80; --warn-soft: #3a1d1d;
    --key-bg: #222a36; --key-edge: #3c4757; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #11151c; --panel: #181e27; --fg: #e5e9f0; --muted: #9aa4b6; --rule: #2a323f;
  --accent: #86a6ff; --accent-soft: #1d2842; --warn: #ff8a80; --warn-soft: #3a1d1d;
  --key-bg: #222a36; --key-edge: #3c4757; color-scheme: dark;
}
body { background: var(--bg); color: var(--fg); font-family: var(--f-body); font-size: 16px; line-height: 1.7; }
.page { padding-inline: 16px; padding-block: 28px 64px; max-width: 1180px; margin: 0 auto; }
.masthead { display: grid; gap: 6px; padding-block: 8px 24px; border-bottom: 1px solid var(--rule); margin-bottom: 28px; }
.masthead .kicker { font-family: var(--f-mono); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0; }
.masthead h1 { font-size: clamp(28px, 5vw, 40px); line-height: 1.2; margin: 0; font-weight: 700; text-wrap: balance; }
.layout { display: grid; gap: 32px; }
@media (min-width: 960px) { .layout { grid-template-columns: 240px minmax(0, 1fr); } }
.toc { align-self: start; background: var(--panel); border: 1px solid var(--rule); border-radius: 10px; padding: 16px 18px; }
@media (min-width: 960px) { .toc { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px); max-height: calc(100vh - 32px); overflow: auto; } }
.toc p { margin: 0 0 8px; font-size: 12px; letter-spacing: .08em; color: var(--muted); font-family: var(--f-mono); }
.toc ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.toc a { display: block; padding: 5px 8px; border-radius: 6px; color: var(--fg); text-decoration: none; font-size: 14px; line-height: 1.45; }
.toc a:hover, .toc a:focus-visible { background: var(--accent-soft); color: var(--accent); outline: none; }
.content { min-width: 0; max-width: 72ch; }
.content h2 { font-size: 24px; line-height: 1.3; margin: 48px 0 12px; padding-top: 12px; border-top: 2px solid var(--fg); text-wrap: balance; scroll-margin-top: 16px; }
.content h2:first-child { margin-top: 0; }
.content h3 { font-size: 18px; margin: 28px 0 8px; text-wrap: balance; }
.content p, .content li { overflow-wrap: anywhere; }
.content ol, .content ul { padding-left: 1.4em; display: grid; gap: 4px; }
.content a { color: var(--accent); }
.content blockquote { margin: 16px 0; padding: 12px 16px; background: var(--accent-soft); border-radius: 8px; border: 1px solid var(--rule); }
.content blockquote p { margin: 4px 0; }
.content img { max-width: 100%; height: auto; border-radius: 6px; border: 1px solid var(--rule); cursor: zoom-in; vertical-align: top; }
.content img:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.content p:has(> img) { display: flex; flex-wrap: wrap; gap: 8px; }
.content hr { border: 0; border-top: 1px solid var(--rule); margin: 40px 0 16px; }
.table-wrap { overflow-x: auto; margin: 16px 0; border: 1px solid var(--rule); border-radius: 8px; background: var(--panel); }
.table-wrap table { border-collapse: collapse; width: 100%; font-size: 15px; }
.table-wrap th, .table-wrap td { text-align: left; vertical-align: top; padding: 9px 12px; border-bottom: 1px solid var(--rule); }
.table-wrap th { font-size: 13px; letter-spacing: .02em; color: var(--muted); font-weight: 600; background: var(--bg); }
.table-wrap tr:last-child td { border-bottom: 0; }
code { font-family: var(--f-mono); font-size: .9em; background: var(--panel); border: 1px solid var(--rule); border-radius: 4px; padding: 1px 5px; }
pre { overflow-x: auto; background: var(--panel); border: 1px solid var(--rule); border-radius: 8px; padding: 12px 14px; }
pre code { border: 0; padding: 0; background: none; }
kbd { font-family: var(--f-mono); font-size: .85em; font-weight: 500; background: var(--key-bg); border: 1px solid var(--key-edge); border-bottom-width: 3px; border-radius: 5px; padding: 1px 7px; white-space: nowrap; }
.chip { display: inline-block; font-family: var(--f-mono); font-size: .82em; font-weight: 600; line-height: 1.5; padding: 0 8px; border-radius: 999px; border: 1px solid var(--rule); white-space: nowrap; }
.chip.b1 { background: var(--chip-b1); color: var(--chip-ink-dark); }
.chip.b2 { background: var(--chip-b2); color: var(--chip-ink-dark); }
.chip.b3 { background: var(--chip-b3); color: var(--chip-ink-dark); }
.chip.b4 { background: var(--chip-b4); color: var(--chip-ink-light); }
.chip.emo { background: var(--chip-emo); color: var(--chip-ink-light); box-shadow: inset 0 0 0 2px var(--chip-ink-light); }
strong { font-weight: 700; }
dialog.zoom { border: 0; padding: 0; background: transparent; max-width: 96vw; max-height: 94vh; }
dialog.zoom::backdrop { background: rgba(8, 10, 14, .82); }
dialog.zoom img { display: block; max-width: 96vw; max-height: 88vh; border-radius: 6px; }
dialog.zoom p { margin: 8px 0 0; text-align: center; color: #e5e9f0; font-size: 14px; }
@media (prefers-reduced-motion: no-preference) { .toc a { transition: background .15s, color .15s; } }
"""

SCRIPT = """
(function () {
  var dlg = document.getElementById('zoom'); if (!dlg || !dlg.showModal) return;
  var big = dlg.querySelector('img');
  function open(im) { big.src = im.src; big.alt = im.alt || ''; try { dlg.showModal(); } catch (e) {} }
  document.querySelectorAll('.content img').forEach(function (im) {
    im.tabIndex = 0;
    im.addEventListener('click', function () { open(im); });
    im.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(im); } });
  });
  dlg.addEventListener('click', function () { dlg.close(); });
})();
"""


def _embed(text, base):
    """src="상대 경로" 그림을 data URI 로 — 없으면 FileNotFoundError(조용히 깨진 그림을 내지 않는다)."""
    def rep(m):
        src = m.group(1)
        if src.startswith(("http:", "https:", "data:")):
            return m.group(0)
        p = (base / src).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"그림이 없다: {src}")
        mime = MIME.get(p.suffix.lower(), "application/octet-stream")
        return f'src="data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"'
    return re.sub(r'src="([^"]+)"', rep, text)


def build(md_path, out_path, max_bytes=16_000_000):
    """원본 md → 페이지 HTML. 반환 = 쓴 바이트 수. 상한을 넘으면 ValueError(아티팩트 16MB)."""
    md_path, out_path = Path(md_path), Path(out_path)
    lines = md_path.read_text(encoding="utf-8").splitlines()
    k = next((i for i, l in enumerate(lines) if l.startswith("# ")), None)
    heading = lines[k][2:].strip() if k is not None else TITLE
    if k is not None:
        lines = lines[:k] + lines[k + 1:]
    body = markdown.markdown("\n".join(lines), extensions=["tables", "fenced_code"])

    toc, n = [], [0]

    def h2(m):
        n[0] += 1
        sid = f"s{n[0]}"
        toc.append((sid, re.sub(r"<[^>]+>", "", m.group(1)).strip()))
        return f'<h2 id="{sid}">{m.group(1)}</h2>'
    body = re.sub(r"<h2>(.*?)</h2>", h2, body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    body = re.sub(r"<code>(%s)</code>" % "|".join(BUTTONS), lambda m: f'<span class="chip {m.group(1).lower()}">{m.group(1)}</span>', body)
    body = _embed(body, md_path.parent)
    nav = "".join(f'<li><a href="#{sid}">{t}</a></li>' for sid, t in toc)
    page = (f"<title>{TITLE}</title>\n"
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600'
            '&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">\n'
            f"<style>{STYLE}</style>\n"
            '<div class="page">\n'
            f'<header class="masthead"><p class="kicker">X-AnyLabeling · 라벨링 묶음 검토</p><h1>{heading}</h1></header>\n'
            f'<div class="layout"><nav class="toc" aria-label="목차"><p>목차</p><ol>{nav}</ol></nav>\n'
            f'<main class="content">\n{body}\n</main></div>\n</div>\n'
            '<dialog class="zoom" id="zoom"><img alt=""><p>아무 곳이나 누르면 닫힙니다</p></dialog>\n'
            f"<script>{SCRIPT}</script>\n")
    data = page.encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError(f"페이지가 {len(data) / 1e6:.1f}MB — 상한 {max_bytes / 1e6:.1f}MB 를 넘는다(그림을 줄인다)")
    out_path.write_bytes(data)
    return len(data)


def main():
    if len(sys.argv) != 3:
        sys.exit("사용법: python3 docs/build_guide_page.py <원본 md> <출력 html>")
    n = build(sys.argv[1], sys.argv[2])
    print(f"페이지 {n / 1e6:.2f}MB → {sys.argv[2]}")


if __name__ == "__main__":
    main()
