# 일회용 — LLM 한 번 호출: 클라이언트 벽시계 vs 서버 total_duration → 차이 = 네트워크·HTTP 몫
import json, sys, time, urllib.request
host = sys.argv[1]; tag = sys.argv[2]
body = json.dumps({"model": "gemma4:e2b-it-qat", "prompt": "작업 2단계에서 다음에 누를 버튼을 한 문장으로 말해 줘.",
                   "stream": False, "options": {"num_predict": 40, "num_ctx": 2048, "temperature": 0}, "think": False}).encode()
t = time.monotonic()
r = json.load(urllib.request.urlopen(urllib.request.Request(f"http://{host}:11434/api/generate", body,
                                     {"Content-Type": "application/json"}), timeout=180))
wall = time.monotonic() - t
srv = r["total_duration"] / 1e9
print(f"{tag}: 전체 {wall:.3f}s · 서버 {srv:.3f}s(적재 {r.get('load_duration',0)/1e9:.2f}s) · 차이 {1000*(wall-srv):.1f}ms · 답 {r['response'][:40]!r}")
