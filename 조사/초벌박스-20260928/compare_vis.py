import os
import sys
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fit_spike.py')).read().split('res = {m:')[0])
from collections import Counter
COL={'B1':(0,210,255),'B2':(255,200,0),'B3':(180,105,255),'B4':(255,90,60),'EMO':(30,30,255)}   # BGR
def draw(img,ds,title):
    im=img.copy()
    for n,s,(x1,y1,x2,y2) in ds:
        cv2.rectangle(im,(x1,y1),(x2,y2),COL[n],3); cv2.rectangle(im,(x1,y1-26),(x1+105,y1),(0,0,0),-1)
        cv2.putText(im,f'{n} {s:.2f}',(x1+3,y1-6),cv2.FONT_HERSHEY_SIMPLEX,0.65,COL[n],2)
    cv2.rectangle(im,(0,0),(768,44),(0,0,0),-1); cv2.putText(im,title,(10,32),cv2.FONT_HERSHEY_SIMPLEX,1.0,(255,255,255),2)
    return im
picks=[]
for scene,p in FRAMES:
    if scene!='좌우이동': continue
    img=cv2.imread(p); b=run(img)
    if Counter(n for n,_,_ in b)['EMO']>1: picks.append((p,img,b))
    if len(picks)==3: break
rows=[np.hstack([draw(img,b,'now (whole frame)'),draw(img,tile(img),'tile (training shape)')]) for p,img,b in picks]
out=np.vstack(rows); out=cv2.resize(out,(out.shape[1]//2,out.shape[0]//2))
cv2.imwrite(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tile_vs_now.jpg'),out,[cv2.IMWRITE_JPEG_QUALITY,88])
print([p.split('/')[-1] for p,_,_ in picks], out.shape)
