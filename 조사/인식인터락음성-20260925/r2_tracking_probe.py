"""R2(두 프레임 확정)의 판정 영향 — 옛 데이터 거울 재생. 읽기 전용 · 일회성 분석(측정 도구 아님).

실행: cd Rpi5/Demo && python3 ../조사/인식인터락음성-20260925/r2_tracking_probe.py
- 추적 = R2 전(Rpi5 bc95c75 의 camera_thread — git show 로 꺼냄) · 지금(Demo/camera_thread.py) 의 **실제 코드** ·
  변형(다른 클래스 확정 박스와 겹칠 때만 두 프레임 — 이 파일 안의 재구현)
- 거울 = 조사/런타임-도구-대조-추적재생.py 와 같다: rawdet(≥0.50) → 추적 → 손끝(palm_frames · palm_thresh 0.5 · flag≥0.2)
  → roi_zones → 지금의 SafetyFSM · 시뮬레이션 정책 4종(경고·차단 즉시 해제 · 기대단계 DB 주입 · IDLE 시 자동 다음 주기)
- 조건 = hoi.db 22세션(2026-07 모조 콘솔 VGA · 매 프레임 PNG 저장 중 9.1fps — 한 프레임 약 0.11초). 실제 GUI 운용과 다르다.
- 발견 = ③ 최종 리뷰 I-2(2026-09-25) · 결과 = 같은 폴더 r2_tracking_probe.txt
"""
import csv, os, sys, types, collections, importlib.util
D = "/home/pi/sop-project/Rpi5/Demo"; T = D + "/test"; HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D); sys.path.insert(0, T)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
fake = types.ModuleType("detector"); fake.create_detector = lambda: None; sys.modules["detector"] = fake
import config; config.HAND_ENABLED = False; config.TOOL_ENABLED = False
import roi_zones, hoi_metrics
from fsm import SafetyFSM, State
from roi_zones import INSIDE
import subprocess, tempfile
_tmp = tempfile.mkdtemp()
open(f"{_tmp}/ct_before.py", "w", encoding="utf-8").write(
    subprocess.check_output(["git", "-C", os.path.dirname(D), "show", "bc95c75:Demo/camera_thread.py"], text=True))
def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
before, after = load_path("ct_before", f"{_tmp}/ct_before.py"), load_path("ct_after", f"{D}/camera_thread.py")
NAMES = ["B1", "B2", "B3", "B4", "EMO"]
def labeled(tracks):   # 판정에 쓰는 박스 — 확정 트랙만(옛 코드는 전부 확정)
    return [(NAMES[t['cls']], *t['box']) for t in tracks if t.get('confirmed', True)]
def upd_variant(tracks, dets):
    """변형(재구현): 새 박스가 **다른 클래스 확정 트랙과 겹칠 때만** 두 프레임 확정, 아니면 즉시."""
    n0 = len(tracks)
    after._update_tracks(tracks, dets)
    for t in tracks:
        if not t['confirmed'] and t.get('hits', 1) == 1:
            over = any(o is not t and o['confirmed'] and o['cls'] != t['cls']
                       and after._iou(o['box'], t['box']) > 0 for o in tracks) if hasattr(after, "_iou") else True
            if not over:
                t['confirmed'] = True
    tracks[:] = after._one_per_class(tracks)
    return tracks
TRACKERS = {"R2 전": before._update_tracks, "R2 지금": after._update_tracks, "변형(겹칠 때만)": upd_variant}
con = hoi_metrics.connect()
res = {}
for tname, upd in TRACKERS.items():
    agg = collections.Counter()
    for sid in hoi_metrics.session_ids(con):
        raw = collections.defaultdict(list)
        for r in csv.DictReader(open(f"{T}/logs/{sid}_rawdet_log.csv")):
            raw[int(r["frame"])].append((NAMES.index(r["cls_name"]), float(r["score"]), int(r["x1"]), int(r["y1"]), int(r["x2"]), int(r["y2"])))
        pf = {r["frame"]: dict(r) for r in con.execute("SELECT * FROM palm_frames WHERE session_id=? AND palm_thresh=0.5", (sid,))}
        maxf = max(max(raw, default=0), max(pf, default=0))
        tracks = []; boxes = {}
        for f in range(1, maxf + 1):
            upd(tracks, raw.get(f, [])); boxes[f] = labeled(tracks)
        ser = {}; lvl = {}
        for f, r in pf.items():
            if r["tip_x"] is None: ser[f] = None; lvl[f] = None; continue
            lab, lv = roi_zones.zone_at_point(r["tip_x"], r["tip_y"], boxes.get(f, []), r["ring_px"])
            ser[f] = lab if (r["flag"] is not None and r["flag"] >= 0.2) else None; lvl[f] = lv
        pr = hoi_metrics.load_presses(con, sid)
        h, n = hoi_metrics.capability_rate({f: (v if v else None) for f, v in ser.items()}, pr); agg["cap_h"] += h; agg["cap_n"] += n
        agg["zone_frames"] += sum(1 for v in ser.values() if v)
        times = {f: r["ts"] for f, r in pf.items()}
        fsm = SafetyFSM(); fsm.load_recipe(); pa = {p["frame"]: p for p in pr}; nxt = 0
        if pr and pr[0]["expected_button"]: fsm.expected_step = int(pr[0]["expected_button"][1:])
        mh = bl = vi = warns = 0
        for f in sorted(ser):
            ts = times.get(f)
            if ts is None: continue
            b = fsm.state; fsm.update_vision(ser[f], ts, lvl.get(f) or INSIDE)
            fired = fsm.state == State.WARNING and b != State.WARNING
            warns += fired
            p = pa.get(f)
            if p:
                mh += fsm.last_roi == p["button"]
                if p["is_violation"] == 1:
                    vi += 1; bl += (fsm.state == State.WARNING or fired)
                fsm.release_warning(); fsm.release_block(); fsm.press_button(p["button"], ts)
                fsm.release_warning(); fsm.release_block()
                if fsm.state == State.IDLE: fsm.load_recipe()
                nxt += 1
                if nxt < len(pr) and pr[nxt]["expected_button"]: fsm.expected_step = int(pr[nxt]["expected_button"][1:])
        agg["mir_h"] += mh; agg["blk"] += bl; agg["vio"] += vi
        if vi == 0:
            agg["norm_sessions"] += 1; agg["norm_warns"] += warns; agg["norm_sessions_warned"] += warns > 0
    res[tname] = agg
    print(f"{tname:12} 사전 차단 {agg['blk']}/{agg['vio']} · 정상 세션 경고 {agg['norm_warns']}건 · 경고 난 정상 세션 {agg['norm_sessions_warned']}/{agg['norm_sessions']} · 역량 {agg['cap_h']}/{agg['cap_n']} · 거울 적중 {agg['mir_h']} · 구역 프레임 {agg['zone_frames']}")
