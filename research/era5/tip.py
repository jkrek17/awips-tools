import sys,json,math
sys.path.insert(0,'.')
from era5lib import *
import urllib.request
raw=urllib.request.urlopen(f"{B}/land_sea_mask/1052994.0.0").read()
lsm=np.frombuffer(codec.decode(raw),dtype='<f4').reshape(721,1440)
d=json.load(open('/home/user/awips-tools/docs/data/hf-lows.json')); F=d['lowFields'];FF=d['fixFields']
L={}
for r in d['lows']:
    l=dict(zip(F,r)); L[l['basin']+':'+l['id']]=l
R=6371.
def hav(la,lo,la0,lo0):
    p1=np.radians(la)[:,None]; p2=math.radians(la0); dl=np.radians(lo)[None,:]-math.radians(lo0)
    h=np.sin((p1-p2)/2)**2+np.cos(p1)*math.cos(p2)*np.sin(dl/2)**2
    return 2*R*np.arcsin(np.sqrt(h))
rows=[]
for k in ['atl:2004200531','atl:2017201825','atl:2020202125','atl:2021202219','atl:2024202533','atl:2011201225','atl:2012201311']:
    l=L[k]; fx=[dict(zip(FF,f)) for f in l['fixes']]
    for f in fx[::max(1,len(fx)//3)][:3]:
        i=tidx(f['date']); lat0=f['lat']; lon0=f['lon']%360
        u=field('10m_u_component_of_wind',i); v=field('10m_v_component_of_wind',i); g=field('instantaneous_10m_wind_gust',i); m=field('mean_sea_level_pressure',i)/100
        j0=int((90-lat0-6)/0.25); j1=int((90-lat0+6)/0.25)+1; k0=int((lon0-12)/0.25); k1=int((lon0+12)/0.25)+1
        ks=np.arange(k0,k1)%1440
        Dk=hav(lat[j0:j1],lon[ks],lat0,lon0)
        ocean=(lsm[j0:j1][:,ks]<0.1)&(Dk<=300)
        ws=np.hypot(u,v)[j0:j1][:,ks]; gg=g[j0:j1][:,ks]
        jj,kk=np.unravel_index(np.argmax(np.where(ocean,ws,-1)),ws.shape)
        # pressure gradient: max |grad p| within 300km ocean
        gy,gx=np.gradient(m[j0:j1][:,ks]); gm=np.hypot(gy/(0.25*111.19),gx/(0.25*111.19*math.cos(math.radians(lat0))))*100
        rows.append((k,f['date'],f['cat'],round(float(ws[jj,kk]*KT) if False else float(ws[jj,kk])*1.94384),round(float(np.where(ocean,gg,-1).max())*1.94384),round(float(np.where(ocean,gm,-1).max()),1),round(float(lat[j0+jj]),1),round(float(((lon[ks[kk]]+180)%360)-180),1)))
for r in rows: print(*r)
import statistics as st
print('ocean-only ws300 kt median',st.median(r[3] for r in rows),'gust median',st.median(r[4] for r in rows),'frac gust>=64',sum(r[4]>=64 for r in rows)/len(rows), 'n',len(rows))
