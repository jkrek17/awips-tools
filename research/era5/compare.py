import sys, json, math
sys.path.insert(0,'.')
from era5lib import *
from concurrent.futures import ThreadPoolExecutor
d=json.load(open('/home/user/awips-tools/docs/data/hf-lows.json'))
F=d['lowFields']; FF=d['fixFields']
lows={}
for r in d['lows']:
    l=dict(zip(F,r)); l['key']=l['basin']+':'+l['id']; l['fixes']=[dict(zip(FF,f)) for f in l['fixes']]; lows[l['key']]=l
sel=json.load(open('selection.json'))
jobs=[]
for eid,kind in sel:
    l=lows[eid]; fx=l['fixes']
    if l['cls']=='tipjet':
        step=max(1,len(fx)//3); pick=fx[::step][:3]
    else:
        hf=[f for f in fx if f['cat']=='HF']
        mn=[f for f in fx if f['pres'] is not None and f['pres']==l['minP']][:1]
        pick=[]
        for f in mn+hf+fx:
            if f not in pick: pick.append(f)
        pick=pick[:4]
    for f in pick: jobs.append((eid,kind,l['cls'],l['season'],f))
print(len(jobs),'timesteps',flush=True)
R=6371.0
def box(a,lat0,lon0,rkm):
    dlat=rkm/111.19+0.5; dlon=min(180,dlat/max(0.1,math.cos(math.radians(lat0))))
    j0=max(0,int((90-(lat0+dlat))/0.25)); j1=min(720,int((90-(lat0-dlat))/0.25)+1)
    ks=np.arange(int((lon0-dlon)/0.25)-1,int((lon0+dlon)/0.25)+2)%1440
    return j0,j1,ks
def dist(la,lo,lat0,lon0):
    p1=np.radians(la)[:,None]; p2=math.radians(lat0)
    dl=np.radians(lo)[None,:]-math.radians(lon0)
    h=np.sin((p1-p2)/2)**2+np.cos(p1)*math.cos(p2)*np.sin(dl/2)**2
    return 2*R*np.arcsin(np.sqrt(h))
def work(job):
    eid,kind,cls,season,f=job
    i=tidx(f['date']); lat0=f['lat']; lon0=f['lon']%360
    m=field('mean_sea_level_pressure',i)/100; u=field('10m_u_component_of_wind',i); v=field('10m_v_component_of_wind',i)
    l=lows[eid]; out=dict(timesSuspect=l['timesSuspect'],idOk=l['idOk'],id=eid,kind=kind,cls=cls,season=season,date=f['date'],cat=f['cat'],lat=lat0,lon=f['lon'],pres=f['pres'])
    j0,j1,ks=box(m,lat0,lon0,700)
    la=lat[j0:j1]; lo=lon[ks]
    D=dist(la,lo,lat0,lon0)
    M=m[j0:j1][:,ks]; WS=np.hypot(u[j0:j1][:,ks],v[j0:j1][:,ks])
    for r in (300,600):
        msk=D<=r
        Mm=np.where(msk,M,np.inf); jj,kk=np.unravel_index(np.argmin(Mm),Mm.shape)
        out[f'mslp{r}']=float(Mm[jj,kk]); out[f'mslp{r}_off']=float(D[jj,kk])
        W=np.where(msk,WS,-1); out[f'ws{r}']=float(W.max())
        jj,kk=np.unravel_index(np.argmax(W),W.shape); out[f'ws{r}_at']=(float(la[jj]),float(((lo[kk]+180)%360)-180))
    return out
with ThreadPoolExecutor(6) as ex: res=list(ex.map(work,jobs))
json.dump(res,open('compare_out.json','w'))
print('bytes fetched MB',BYTES[0]/1e6)
