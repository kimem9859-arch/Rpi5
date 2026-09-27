import sys, math
sys.argv=['x']
sys.path.insert(0,'/home/pi/sop-project/Rpi5/조사/기계검토-20260928')
import machine_review as M, cv2, numpy as np
from detector import create_detector
M.DET=create_detector()
def snap_soft(img, box, frac):
    """오츠로 버튼 속을 찾은 뒤, 버튼 속 색 거리 중앙값의 frac 배를 문턱으로 다시 갈라 그늘진 가장자리까지 넣는다."""
    x1,y1,x2,y2=box; w,h=x2-x1,y2-y1; m=int(0.4*max(w,h)); H,W=img.shape[:2]
    X1,Y1,X2,Y2=max(0,x1-m),max(0,y1-m),min(W,x2+m),min(H,y2+m); crop=img[Y1:Y2,X1:X2]
    lab=cv2.cvtColor(crop,cv2.COLOR_BGR2LAB).astype(np.float32)
    ring=np.ones(crop.shape[:2],bool); ring[max(0,y1-Y1):y2-Y1,max(0,x1-X1):x2-X1]=False
    d=np.linalg.norm(lab-np.median(lab[ring],axis=0),axis=2)
    d8=np.clip(d*255/max(float(d.max()),1),0,255).astype(np.uint8)
    t,core=cv2.threshold(d8,0,1,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    thr=frac*float(np.median(d8[core>0])); mask=(d8>thr).astype(np.uint8)
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    n,labm,st,_=cv2.connectedComponentsWithStats(mask,8)
    inner=np.zeros(mask.shape,bool); inner[max(0,y1-Y1):y2-Y1,max(0,x1-X1):x2-X1]=True
    best=max(range(1,n),key=lambda k:((labm==k)&inner).sum(),default=None)
    if best is None: return None
    bx,by,bw,bh,_=st[best]; return [X1+bx,Y1+by,X1+bx+bw,Y1+by+bh]
cases=[('20260923_184732_esp32_xga-rt-s1-r2_console_v2',151),('20260923_184922_esp32_xga-rt-s2-r1_console_v2',212)]
tiles=[]
for sess,fr in cases:
    img=cv2.imread(f'/home/pi/sop-project/Rpi5/Demo/test/raw/{sess}/f{fr:05d}.png')
    for n,s,b in M.tile(img):
        if n=='B4': continue
        x1,y1,x2,y2=b; m=20; ox,oy=max(0,x1-m),max(0,y1-m)
        c=img[oy:y2+m, ox:x2+m].copy(); Z=5
        c=cv2.resize(c,(c.shape[1]*Z,c.shape[0]*Z),interpolation=cv2.INTER_NEAREST)
        for bb,col in ((b,(255,255,0)),(snap_soft(img,b,0.35),(0,255,0)),(snap_soft(img,b,0.2),(0,0,255))):
            if bb: cv2.rectangle(c,((bb[0]-ox)*Z,(bb[1]-oy)*Z),((bb[2]-ox)*Z,(bb[3]-oy)*Z),col,2)
        cv2.putText(c,n,(4,20),cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,255),2); tiles.append(c)
h=max(t.shape[0] for t in tiles)
tiles=[cv2.copyMakeBorder(t,0,h-t.shape[0],0,4,cv2.BORDER_CONSTANT) for t in tiles]
rows=[np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]
w=max(r.shape[1] for r in rows); rows=[cv2.copyMakeBorder(r,0,4,0,w-r.shape[1],cv2.BORDER_CONSTANT) for r in rows]
cv2.imwrite('/home/pi/sop-project/Rpi5/조사/기계검토-20260928/edge_compare.jpg',np.vstack(rows))
