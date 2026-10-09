import json, cv2, numpy as np
from pathlib import Path
S = Path.home()/"data/c001채점/sets/c001"
T = json.load(open("/home/pi/sop-project/Rpi5/조사/c001채점-20261008/쥠놓임.json", encoding="utf-8"))["표시"]
NAMES = ["driver", "wrench", "pliers"]
held = [k for k, v in T.items() if v == "쥠"]
OUT = Path("/tmp/claude-1000/-home-pi-sop-project/8572c720-a93c-4ce7-9c47-51f071c27109/scratchpad/glove")
tiles = []
for i, k in enumerate(held, 1):
    n, tool = k.split("|")
    im = cv2.imread(str(S/"orig"/f"{n}.png")); h, w = im.shape[:2]
    for line in (S/"labels_tool"/f"{n}.txt").read_text().splitlines():
        c, cx, cy, bw, bh = line.split()
        if NAMES[int(c)] != tool: continue
        cx, cy, bw, bh = map(float, (cx, cy, bw, bh))
        x1, y1, x2, y2 = (cx-bw/2)*w, (cy-bh/2)*h, (cx+bw/2)*w, (cy+bh/2)*h
        m = max(x2-x1, y2-y1)*0.8
        X1, Y1, X2, Y2 = max(0, int(x1-m)), max(0, int(y1-m)), min(w, int(x2+m)), min(h, int(y2+m))
        cr = im[Y1:Y2, X1:X2].copy()
        cv2.rectangle(cr, (int(x1)-X1, int(y1)-Y1), (int(x2)-X1, int(y2)-Y1), (0, 255, 0), 2)
        break
    s = 300/max(cr.shape[:2]); sm = cv2.resize(cr, (int(cr.shape[1]*s), int(cr.shape[0]*s)))
    t = np.full((330, 300, 3), 255, np.uint8); t[30:30+sm.shape[0], :sm.shape[1]] = sm
    cv2.putText(t, f"{i} {tool}", (4, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    tiles.append(t)
COLS, ROWS = 5, 4
for si in range(0, len(tiles), COLS*ROWS):
    chunk = tiles[si:si+COLS*ROWS]
    while len(chunk) < COLS*ROWS: chunk.append(np.full((330, 300, 3), 255, np.uint8))
    rows = [np.hstack(chunk[r*COLS:(r+1)*COLS]) for r in range(ROWS)]
    cv2.imwrite(str(OUT/f"sheet_{si//(COLS*ROWS)+1}.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
json.dump(held, open(OUT/"held.json", "w"), ensure_ascii=False)
print(len(held))
