import sys, json, math, datetime
sys.path.insert(0,'.')
from era5lib import *
from scipy import ndimage
from concurrent.futures import ThreadPoolExecutor
Rk=6371.0
DOM={'atl':dict(j=(80,261),k=np.r_[1120:1440,0:61]),   # 70N..25N, 80W..15E
     'pac':dict(j=(100,261),k=np.arange(520,961))}      # 65N..25N, 130E..240E
def hav(la,lo,la0,lo0):
    p1=np.radians(la)[:,None]; p2=math.radians(la0); dl=np.radians(lo)[None,:]-math.radians(lo0)
    h=np.sin((p1-p2)/2)**2+np.cos(p1)*math.cos(p2)*np.sin(dl/2)**2
    return 2*Rk*np.arcsin(np.sqrt(h))
def step(args):
    dom,idx=args
    D=DOM[dom]; j0,j1=D['j']; ks=D['k']
    ix=lambda a: a[j0:j1][:,ks]
    m=ix(field('mean_sea_level_pressure',idx))/100
    u=ix(field('10m_u_component_of_wind',idx)); v=ix(field('10m_v_component_of_wind',idx)); g=ix(field('instantaneous_10m_wind_gust',idx))
    ws=np.hypot(u,v); la=lat[j0:j1]; lo=lon[ks]
    ms=ndimage.uniform_filter(m,size=5,mode='nearest')
    mn=ndimage.minimum_filter(ms,size=17,mode='nearest')
    cand=np.argwhere((ms==mn)&(ms<1005))
    out=[]
    for a,b in cand:
        if a<8 or a>m.shape[0]-9 or b<8 or b>m.shape[1]-9: continue
        pad=40  # +-10 deg window
        a0,a1=max(0,a-pad),min(m.shape[0],a+pad+1); b0,b1=max(0,b-pad*2),min(m.shape[1],b+pad*2+1)
        Dk=hav(la[a0:a1],lo[b0:b1],la[a],lo[b])
        ring=(Dk>=450)&(Dk<=650)
        if ring.sum()==0: continue
        depth=float(ms[a0:a1,b0:b1][ring].mean()-ms[a,b])
        if depth<4: continue
        W=ws[a0:a1,b0:b1]; G=g[a0:a1,b0:b1]
        r={'t':idx,'lat':float(la[a]),'lon':float(((lo[b]+180)%360)-180),'p':float(ms[a,b]),'depth':depth}
        for R_ in (300,600):
            mk=Dk<=R_; r[f'ws{R_}']=float(W[mk].max()); r[f'g{R_}']=float(G[mk].max())
        out.append(r)
    return dom,idx,out
def run(year,month):
    t0=tidx(year*1000000+month*10000+100)
    n=(datetime.datetime(year+(month==12),month%12+1,1)-datetime.datetime(year,month,1)).days*4
    jobs=[(d,t0+6*i) for d in DOM for i in range(n)]
    with ThreadPoolExecutor(6) as ex: res=list(ex.map(step,jobs))
    C={d:{} for d in DOM}
    for dom,idx,out in res: C[dom][idx]=out
    json.dump(C,open(f'cand_{year}{month:02d}.json','w'))
    print(year,month,'steps',len(jobs),'cands',sum(len(o) for d in C.values() for o in d.values()),'MB',BYTES[0]/1e6,flush=True)
if __name__=='__main__':
    run(int(sys.argv[1]),int(sys.argv[2]))
