import json, math, sys, collections, statistics as st
sys.path.insert(0,'.')
import numpy as np
from era5lib import tidx
KT=1.94384
d=json.load(open('/home/user/awips-tools/docs/data/hf-lows.json'))
F=d['lowFields'];FF=d['fixFields']
events={}
for r in d['lows']:
    l=dict(zip(F,r)); l['key']=l['basin']+':'+l['id']; l['fixes']=[dict(zip(FF,f)) for f in l['fixes']]; events[l['key']]=l
def hav(la1,lo1,la2,lo2):
    p1,p2=math.radians(la1),math.radians(la2); dl=math.radians(lo2-lo1)
    h=math.sin((p1-p2)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*6371*math.asin(math.sqrt(h))
def analyse(ym, verbose=True):
    C=json.load(open(f'cand_{ym}.json'))
    y,mo=int(ym[:4]),int(ym[4:])
    res={}
    for dom,steps in C.items():
        steps={int(k):v for k,v in steps.items()}
        times=sorted(steps)
        # linking
        tracks=[]; active=[]
        for t in times:
            cs=steps[t]; used=set(); newactive=[]
            for tr in active:
                if tr['pts'][-1]['t']!=t-6: continue
                best=None
                for i,c in enumerate(cs):
                    if i in used: continue
                    dd=hav(tr['pts'][-1]['lat'],tr['pts'][-1]['lon'],c['lat'],c['lon'])
                    if dd<=700 and (best is None or dd<best[0]): best=(dd,i)
                if best: used.add(best[1]); tr['pts'].append(cs[best[1]]); newactive.append(tr)
            for i,c in enumerate(cs):
                if i not in used:
                    tr={'pts':[c]}; tracks.append(tr); newactive.append(tr)
            active=newactive
        # archive fixes in this domain in the month
        box={'atl':(25,70,-80,15),'pac':(25,65,None,None)}
        fixes=[]
        for e in events.values():
            if e['basin']!=dom and False: pass
            for f in e['fixes']:
                dt=f['date']
                if dt//1000000!=y or (dt//10000)%100!=mo: continue
                lo=f['lon']
                inside = (25<=f['lat']<=(70 if dom=='atl' else 65)) and ((-80<=lo<=15) if dom=='atl' else (lo>=130 or lo<=-120))
                if inside and e['basin']==dom: fixes.append((e['key'],tidx(dt),f))
        # match fix -> candidate at same time within 400 km
        cand_at={t:steps[t] for t in times}
        matched_cand=set(); fixres=[]
        for key,t,f in fixes:
            best=None
            for ci,c in enumerate(cand_at.get(t,[])):
                dd=hav(f['lat'],f['lon'],c['lat'],c['lon'])
                if dd<=400 and (best is None or dd<best[0]): best=(dd,ci)
            if best:
                matched_cand.add((t,best[1])); fixres.append((key,t,f,cand_at[t][best[1]]))
            else: fixres.append((key,t,f,None))
        # also mark any candidate within 600km of any archive fix at that time as 'covered'
        covered=set()
        for key,t,f in fixes:
            for ci,c in enumerate(cand_at.get(t,[])):
                if hav(f['lat'],f['lon'],c['lat'],c['lon'])<=600: covered.add((t,ci))
        # tracks
        for tr in tracks:
            tr['n']=len(tr['pts']); tr['minp']=min(p['p'] for p in tr['pts']); tr['maxws']=max(p['ws300'] for p in tr['pts'])*KT
            tr['maxg']=max(p['g300'] for p in tr['pts'])*KT; tr['maxdepth']=max(p['depth'] for p in tr['pts'])
            tr['hit']=False
            for p in tr['pts']:
                for ci,c in enumerate(cand_at[p['t']]):
                    if c is p and (p['t'],ci) in covered: tr['hit']=True
        res[dom]=dict(tracks=tracks,fixres=fixres,nfix=len(fixes))
    return res
if __name__=='__main__':
    for ym in sys.argv[1:]:
        R=analyse(ym)
        for dom,x in R.items():
            fr=x['fixres']; hf=[r for r in fr if r[2]['cat']=='HF']
            det=[r for r in hf if r[3] is not None]
            print(ym,dom,'archive fixes',x['nfix'],'HF fixes',len(hf),'ERA5 centre found within 400km (depth>=4hPa):',len(det),'tracks',len(x['tracks']))
