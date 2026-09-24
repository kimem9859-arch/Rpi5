import sys; sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
from fsm import SafetyFSM, State
def mk():
    f = SafetyFSM(step_count=4, dwell_threshold=0.3, gap_fill=0.3)
    f.load_recipe(); return f
dt = 1/15
# 1) graze: wrong ROI B3 seen 2 frames, then hand outside any box
f = mk(); t=0
for roi in ["B3","B3"]+[None]*6:
    f.update_vision(roi, t); t+=dt
print("1 graze 2 frames(0.067s) ->", f.state)
# 2) correct press B1 then finger lingers 2 frames, then moves (no box)
f = mk(); t=0
for roi in ["B1"]*4: f.update_vision(roi,t); t+=dt
f.press_button("B1", t)
for roi in ["B1","B1"]+[None]*6:
    f.update_vision(roi,t); t+=dt
print("2 after correct B1 press, linger 2 frames ->", f.state, "expected", f.correct_roi)
# 3) stale dwell across frame gap (camera stall/reconnect)
f = mk(); t=0
f.update_vision("B3", t)       # single frame graze
t += 5.0                        # no frames for 5 s
f.update_vision("B3", t)       # first frame after reconnect, hand at B3 again
print("3 single frame + 5s gap + single frame ->", f.state)
# 4) EMO ROI dwell
f = mk(); t=0
for _ in range(7): f.update_vision("EMO", t); t+=dt
print("4 EMO roi dwell ->", f.state)
# 5) EMO in IDLE then release
f = SafetyFSM(step_count=4)
f.press_button("EMO"); print("5a", f.state); f.release_block(); print("5b EMO from IDLE, release ->", f.state, f.expected_step)
