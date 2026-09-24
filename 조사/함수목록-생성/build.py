"""함수목록.md 조립 — map3.json(기계 추출) + desc_*.json(한 줄 설명) + head.md + tail.md."""
import json, os, sys
D = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(f"{D}/map3.json", encoding="utf-8"))
desc = {}
for g in "ABCD":
    desc.update(json.load(open(f"{D}/desc_{g}.json", encoding="utf-8")))
missing = [d["q"] for d in data if d["q"] not in desc]
extra = [k for k in desc if k not in {d["q"] for d in data}]
if missing or extra:
    sys.exit(f"설명 누락 {len(missing)} {missing[:5]} · 여분 {len(extra)} {extra[:5]}")

ORDER = ["main", "config", "camera_thread", "gpio_input", "serial_ports", "detector", "hailo_device",
         "hand_tracker", "frame_orient", "roi_zones", "tool_gate", "tool_worker", "tool_state", "fsm",
         "recipe", "sub_task", "interlock", "safety_console", "overlay", "overlay_menu", "overlay_result",
         "anim", "theme", "precheck", "session_stats", "fps", "state_publisher", "demo_recorder",
         "demo_ffmpeg", "voice_assistant", "voice_lib", "voice_card", "voice_llm", "voice_tts"]
assert set(ORDER) == {d["mod"] for d in data}, set(ORDER) ^ {d["mod"] for d in data}

def short(q, mod):
    return q[len(mod) + 1:] if q.startswith(mod + ".") else q

def callers(d):
    m = d["mod"]
    parts = []
    direct = sorted(set(d["called_by"]) - {d["q"]})
    if direct:
        parts.append("직접 " + " · ".join(f"`{short(x, m)}`" for x in direct[:3]) + (f" 외 {len(direct)-3}" if len(direct) > 3 else ""))
    refs = sorted(set(d["refs"]) - set(direct) - {d["q"]})
    if refs:
        parts.append("연결 " + " · ".join(f"`{short(x, m)}`" for x in refs[:2]) + (f" 외 {len(refs)-2}" if len(refs) > 2 else ""))
    uu = sorted(set(d["uses_unique"]) - set(direct) - set(refs))
    if uu:
        parts.append("직접 " + " · ".join(f"`{short(x, m)}`" for x in uu[:2]) + (f" 외 {len(uu)-2}" if len(uu) > 2 else ""))
    if not parts and d["uses_ambig"]:
        parts.append("이름 후보 " + " · ".join(f"`{short(x, m)}`" for x in d["uses_ambig"][:2]) + (f" 외 {len(d['uses_ambig'])-2}" if len(d["uses_ambig"]) > 2 else ""))
    if not parts and d["qt"]:
        parts.append("Qt")
    if not parts and d["main"]:
        parts.append("객체 생성·파이썬")
    return " / ".join(parts) or "**없음**"

out = [open(f"{D}/head.md", encoding="utf-8").read().rstrip() + "\n"]
notes = []
for m in ORDER:
    rows = sorted([d for d in data if d["mod"] == m], key=lambda d: d["line"])
    out.append(f"\n### `{m}.py` ({len(rows)}개)\n\n| 함수 | 줄 | 하는 일 | 부르는 곳 | 쓰는 설정값 |\n|---|---|---|---|---|")
    for d in rows:
        e = desc[d["q"]]
        cfg = " ".join(f"`{c}`" for c in d["cfg"][:4]) + (f" 외 {len(d['cfg'])-4}" if len(d["cfg"]) > 4 else "")
        name = short(d["q"], m)
        flag = " ⚠️" if e.get("note") else ""
        out.append(f"| `{name}`{flag} | {d['line']} | {e['desc'].replace('|', '/')} | {callers(d)} | {cfg or '—'} |")
        if e.get("note"):
            notes.append((m, name, d["line"], e["note"].replace("\n", " ")))
out.append(open(f"{D}/tail.md", encoding="utf-8").read().rstrip() + "\n")
out.append("\n### 4.4 함수별 메모 (3절에서 ⚠️ 가 붙은 함수 — 코드를 읽으며 적은 것 · 재확인 전)\n\n| 모듈 | 함수 | 줄 | 메모 |\n|---|---|---|---|")
for m, n, l, t in notes:
    out.append(f"| `{m}` | `{n}` | {l} | {t.replace('|', '/')} |")
open(sys.argv[1], "w", encoding="utf-8").write("\n".join(out) + "\n")
print("함수", len(data), "· 메모", len(notes), "·", sys.argv[1])
