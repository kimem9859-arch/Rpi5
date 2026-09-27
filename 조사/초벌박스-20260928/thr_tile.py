import os
import statistics as st
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fit_spike.py')).read().split('res = {m:')[0])
src=open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'box_fit.py')).read().split("if __name__")[0]
fits={}
for thr in (20,30,45):
    ns={}; exec(src.replace('> 45', f'> {thr}'), ns); fits[thr]=ns['fit']
out={(m,t):([],[]) for m in ('base','tile') for t in fits}
for scene,p in FRAMES:
    if scene!='정지': continue
    img=cv2.imread(p)
    for m,ds in (('base',run(img)),('tile',tile(img))):
        for n,s,b in ds:
            if n=='B4': continue
            for t,f in fits.items():
                r=f(img,b)
                if r: out[(m,t)][0].append((b[2]-b[0])/r[0]); out[(m,t)][1].append((b[3]-b[1])/r[1])
for (m,t),(rw,rh) in out.items():
    print(f'{m:5} 문턱 {t}: 폭비 {st.median(rw):.2f} · 높이비 {st.median(rh):.2f}')
