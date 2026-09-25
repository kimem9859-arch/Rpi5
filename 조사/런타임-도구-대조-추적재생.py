"""Estimate: zone judged on rawdet boxes (tools) vs runtime-style tracks. Read-only."""
import csv, os, sys, sqlite3, collections
D="/home/pi/sop-project/Rpi5/Demo"; T=D+"/test"
sys.path.insert(0,D); sys.path.insert(0,T)
import roi_zones, hoi_metrics
from fsm import SafetyFSM, State
from roi_zones import INSIDE
CONF_HIGH, IOU, MAXMISS = 0.65, 0.3, 5
NAMES=["B1","B2","B3","B4","EMO"]
def _iou(a,b):
    ix1,iy1=max(a[0],b[0]),max(a[1],b[1]); ix2,iy2=min(a[2],b[2]),min(a[3],b[3])
    inter=max(0,ix2-ix1)*max(0,iy2-iy1)
    return 0.0 if inter==0 else inter/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
def upd(tracks,dets,opc=True):   # verbatim logic of camera_thread._update_tracks/_one_per_class — ⚠️ 2026-09-24 기준(③ R2 전: 두 프레임 확정·오래된 트랙 우선 없음)
    used=[False]*len(dets)
    for t in tracks:
        bi,bv=-1,IOU
        for i,d in enumerate(dets):
            if used[i] or d[0]!=t['cls']: continue
            v=_iou(t['box'],d[2:6])
            if v>bv: bv,bi=v,i
        if bi>=0:
            d=dets[bi]; t['box']=tuple(d[2:6]); t['score']=d[1]; t['miss']=0
            if d[1]>=CONF_HIGH: t['confirmed']=True
            used[bi]=True
        else: t['miss']+=1
    for i,d in enumerate(dets):
        if not used[i] and d[1]>=CONF_HIGH:
            tracks.append({'cls':d[0],'box':tuple(d[2:6]),'score':d[1],'miss':0,'confirmed':True})
    tracks[:]=[t for t in tracks if t['miss']<=MAXMISS and t['confirmed']]
    if opc:
        best={}
        for t in tracks:
            p=best.get(t['cls'])
            if p is None or (t['miss'],-t['score'])<(p['miss'],-p['score']): best[t['cls']]=t
        tracks[:]=[t for t in tracks if best[t['cls']] is t]
    return tracks
con=hoi_metrics.connect(); con2=sqlite3.connect(T+"/hoi.db")
agg=collections.Counter()
for sid in hoi_metrics.session_ids(con):
    raw=collections.defaultdict(list)
    for r in csv.DictReader(open(f"{T}/logs/{sid}_rawdet_log.csv")):
        raw[int(r["frame"])].append((NAMES.index(r["cls_name"]),float(r["score"]),int(r["x1"]),int(r["y1"]),int(r["x2"]),int(r["y2"])))
    pf={r["frame"]:dict(r) for r in con.execute("SELECT * FROM palm_frames WHERE session_id=? AND palm_thresh=0.5",(sid,))}
    maxf=max(max(raw,default=0),max(pf,default=0))
    tracks=[]; trk_boxes={}
    for f in range(1,maxf+1):
        upd(tracks,raw.get(f,[]))
        trk_boxes[f]=[(NAMES[t['cls']],*t['box']) for t in tracks]
    ser_tool={}; ser_rt={}; lvl_tool={}; lvl_rt={}; ser_rt_flag={}
    for f,r in pf.items():
        ser_tool[f]=r["zone_label"]; lvl_tool[f]=r["zone_level"]
        if r["tip_x"] is None: ser_rt[f]=None; lvl_rt[f]=None; ser_rt_flag[f]=None; continue
        lab,lv=roi_zones.zone_at_point(r["tip_x"],r["tip_y"],trk_boxes.get(f,[]),r["ring_px"])
        ser_rt[f]=lab; lvl_rt[f]=lv
        ser_rt_flag[f]=lab if (r["flag"] is not None and r["flag"]>=0.2) else None
    pr=hoi_metrics.load_presses(con,sid)
    for name,s in (("tool",ser_tool),("rt",ser_rt),("rt+flag",ser_rt_flag)):
        h,n=hoi_metrics.capability_rate(s,pr); agg[name+"_cap_h"]+=h; agg[name+"_cap_n"]+=n
    agg["zone_frames_tool"]+=sum(1 for v in ser_tool.values() if v); agg["zone_frames_rt"]+=sum(1 for v in ser_rt.values() if v)
    # mirror via real SafetyFSM, same policies as fsm_sim
    for name,s,lv in (("tool",ser_tool,lvl_tool),("rt",ser_rt_flag,lvl_rt)):
        times={f:r["ts"] for f,r in pf.items()}
        fsm=SafetyFSM(); fsm.load_recipe(); pa={p["frame"]:p for p in pr}; nxt=0
        if pr and pr[0]["expected_button"]: fsm.expected_step=int(pr[0]["expected_button"][1:])
        warn=[0]; mh=mt=bl=vi=0
        for f in sorted(s):
            ts=times.get(f)
            if ts is None: continue
            b=fsm.state; fsm.update_vision(s[f],ts,lv.get(f) or INSIDE)
            fired = fsm.state==State.WARNING and b!=State.WARNING
            p=pa.get(f)
            if p:
                mt+=1; mh+= fsm.last_roi==p["button"]
                if p["is_violation"]==1:
                    vi+=1; bl+= (fsm.state==State.WARNING or fired)
                fsm.release_warning(); fsm.release_block(); fsm.press_button(p["button"],ts)
                fsm.release_warning(); fsm.release_block()
                if fsm.state==State.IDLE: fsm.load_recipe()
                nxt+=1
                if nxt<len(pr) and pr[nxt]["expected_button"]: fsm.expected_step=int(pr[nxt]["expected_button"][1:])
        agg[name+"_mir_h"]+=mh; agg[name+"_mir_n"]+=mt; agg[name+"_blk"]+=bl; agg[name+"_vio"]+=vi
for k in sorted(agg): print(k, agg[k])
