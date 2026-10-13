#!/usr/bin/env bash
# 시연 UI 성능 관문 — 같은 녹화를 가짜 카메라로 흘려 [FPS] 로그 중앙값을 낸다(설계 2026-10-13 §7).
# 🔴 가짜 카메라를 초당 40장으로 보낸다 — 19.5장이면 처리 FPS 가 입력 천장에 붙어 회차마다 14~19 로 흔들렸다(10/14 기준값 1차).
# 사용: bash tools/ui_perf.sh <이름표> [번수=5] [초=60]
set -u
cd "$(dirname "$0")/.." || exit 1
TAG=$1; N=${2:-5}; SEC=${3:-60}
VID=recordings/시연영상/촬영본/20261006_212651_정상_오버레이켬/20261006_212651_정상_1인칭풀_오버레이끔.mp4
OUT=$HOME/lab/ui-perf; mkdir -p "$OUT"
export DISPLAY=${DISPLAY:-:0} XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}
for i in $(seq 1 "$N"); do
  PYTHONPATH=$PWD python3 test/fake_camera.py "$VID" --unorient --fps 40 --seconds $((SEC + 200)) > "$OUT/cam_${TAG}_$i.out" 2>&1 &
  cam=$!
  for _ in $(seq 1 150); do (exec 3<>/dev/tcp/127.0.0.1/8888) 2>/dev/null && break; sleep 1; done
  SOP_VOICE=0 SOP_INFER_MODEL=1 SOP_CAMERA_HOST=127.0.0.1 timeout $((SEC + 30)) python3 main.py > "$OUT/stdout_${TAG}_$i.out" 2>&1
  cp "$(ls -t logs/*_log.txt | head -1)" "$OUT/main_${TAG}_$i.out"    # [FPS] 는 로그 파일에만 남는다
  kill $cam 2>/dev/null; wait $cam 2>/dev/null
  sleep 2
done
python3 - "$OUT" "$TAG" <<'PY'
import glob, os, re, statistics, sys
out, tag = sys.argv[1], sys.argv[2]
meds = []
files = sorted(glob.glob(f"{out}/main_{tag}_*.out"), key=lambda f: int(re.search(r"_(\d+)\.out$", f).group(1)))
for k, f in enumerate(files):
    v = [float(x) for x in re.findall(r"\[FPS\] ([\d.]+)", open(f, encoding="utf-8", errors="replace").read())][1:]
    if v and k > 0:                       # 🔴 첫 회는 예열로 버린다 — 10/14 기준값에서 1회만 16.7(2~5회 18.6~18.8)
        meds.append(statistics.median(v))
    print(os.path.basename(f), "n=%d" % len(v), ("중앙값=%.2f" % statistics.median(v)) if v else "값 없음")
if meds:
    print("기준 중앙값(첫 회 버림)=%.2f · 범위 %.2f~%.2f" % (statistics.median(meds), min(meds), max(meds)))
PY
