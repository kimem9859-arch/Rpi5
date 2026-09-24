"""실제 시연 프로그램(Rpi5/Demo 최상위 모듈) 함수 지도 자동 추출 — 파악용 임시 스크립트."""
import ast, glob, os, json, sys, collections
DEMO = "/home/pi/sop-project/Rpi5/Demo"
SKIP = {"demo_postprocess.py"}
mods = {os.path.basename(p)[:-3]: p for p in sorted(glob.glob(f"{DEMO}/*.py")) if os.path.basename(p) not in SKIP}
CONFIG_NAMES = set()
cfg = ast.parse(open(mods["config"], encoding="utf-8").read())
for n in cfg.body:
    for t in (n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []):
        if isinstance(t, ast.Name): CONFIG_NAMES.add(t.id)
funcs = {}          # qual -> info
class V(ast.NodeVisitor):
    def __init__(s, mod, imports, from_imports, cfg_from):
        s.mod, s.stack, s.imports, s.fi, s.cfg_from = mod, [], imports, from_imports, cfg_from
    def visit_ClassDef(s, n):
        s.stack.append(n.name); s.generic_visit(n); s.stack.pop()
    def _fn(s, n):
        qual = f"{s.mod}." + ".".join(s.stack + [n.name])
        doc = (ast.get_docstring(n) or "").strip().splitlines()
        info = funcs[qual] = dict(mod=s.mod, name=n.name, cls=s.stack[-1] if s.stack and s.stack[-1][0].isupper() else None,
                                  line=n.lineno, end=n.end_lineno, doc=doc[0].strip() if doc else "",
                                  calls=set(), cfg=set(), connects=set())
        for c in ast.walk(n):
            if isinstance(c, ast.Call):
                f = c.func
                if isinstance(f, ast.Name):
                    if f.id in s.fi: info["calls"].add(f"{s.fi[f.id]}.{f.id}")
                    else: info["calls"].add(f"{s.mod}.{f.id}")
                elif isinstance(f, ast.Attribute):
                    v = f.value
                    if isinstance(v, ast.Name) and v.id in ("self", "cls") and s.stack:
                        info["calls"].add(f"{s.mod}.{s.stack[0]}.{f.attr}")
                    elif isinstance(v, ast.Name) and v.id in s.imports:
                        info["calls"].add(f"{s.imports[v.id]}.{f.attr}")
                    if f.attr == "connect" and c.args:
                        a = c.args[0]
                        if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) and a.value.id == "self" and s.stack:
                            info["connects"].add(f"{s.mod}.{s.stack[0]}.{a.attr}")
            if isinstance(c, ast.Attribute) and isinstance(c.value, ast.Name) and c.value.id == "config":
                info["cfg"].add(c.attr)
            if isinstance(c, ast.Name) and c.id in s.cfg_from:
                info["cfg"].add(c.id)
        s.stack.append(n.name); s.generic_visit(n); s.stack.pop()
    visit_FunctionDef = visit_AsyncFunctionDef = _fn
lines_of = {}
for m, p in mods.items():
    src = open(p, encoding="utf-8").read(); t = ast.parse(src)
    imports, fi, cfg_from = {}, {}, set()
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in mods: imports[a.asname or a.name] = a.name
        if isinstance(n, ast.ImportFrom) and n.module in mods:
            for a in n.names:
                fi[a.asname or a.name] = n.module
                if n.module == "config": cfg_from.add(a.asname or a.name)
    V(m, imports, fi, cfg_from).visit(t)
# 호출 관계 해석: 클래스 메서드 이름 매칭 보강
names = collections.defaultdict(list)
for q, i in funcs.items(): names[(i["mod"], i["name"])].append(q)
called_by = collections.defaultdict(set)
for q, i in funcs.items():
    for c in i["calls"] | i["connects"]:
        if c in funcs: called_by[c].add(q); continue
        parts = c.split(".")
        # mod.Class.method 이 부모 클래스 등에서 못 찾으면 같은 모듈 같은 이름
        cand = [x for x in names.get((parts[0], parts[-1]), [])]
        if len(cand) == 1: called_by[cand[0]].add(q)
out = []
for q, i in funcs.items():
    out.append(dict(q=q, **{k: (sorted(v) if isinstance(v, set) else v) for k, v in i.items()},
                    called_by=sorted(called_by.get(q, []))))
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
nodoc = [o for o in out if not o["doc"]]
nocaller = [o for o in out if not o["called_by"]]
print("함수", len(out), "· 설명 없음", len(nodoc), "· 부르는 곳 못 찾음", len(nocaller))
