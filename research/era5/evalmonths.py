import sys, collections, statistics as st, json
sys.path.insert(0,'.')
from matchmonth import *
yms=['201801','201312','201804']
allfix=[]; alltr=[]
for ym in yms:
    R=analyse(ym)
    for dom,x in R.items():
        for key,t,f,c in x['fixres']:
            e=events[key]; allfix.append(dict(ym=ym,dom=dom,key=key,cls=e['cls'],cat=f['cat'],c=c))
        for tr in x['tracks']: tr['ym']=ym; tr['dom']=dom; alltr.append(tr)
# --- centre detection at fixes
print('FIX-LEVEL centre detection (ERA5 closed low >=4 hPa deep within 400 km of analysed position, same time)')
for cls in ('low','tipjet','nocentre'):
    for cat in ('HF','S'):
        s=[a for a in allfix if a['cls']==cls and a['cat']==cat]
        if s: print(f'  {cls:9s} {cat:2s} n={len(s):3d} found={sum(a["c"] is not None for a in s):3d}  ({100*sum(a["c"] is not None for a in s)/len(s):.0f}%)')
# --- wind at matched centres
hf=[a for a in allfix if a['cls']=='low' and a['cat']=='HF' and a['c']]
w=[a['c']['ws300']*KT for a in hf]; g=[a['c']['g300']*KT for a in hf]
print('HF low fixes with ERA5 centre n',len(hf),'ws300 kt median',round(st.median(w)),'p10/p90',round(np.percentile(w,10)),round(np.percentile(w,90)),'max',round(max(w)),'| gust300 median',round(st.median(g)),'p10/p90',round(np.percentile(g,10)),round(np.percentile(g,90)),'max',round(max(g)),'frac gust>=64',round(sum(x>=64 for x in g)/len(g),2),'frac ws>=64',round(sum(x>=64 for x in w)/len(w),2))
# --- track-level discrimination: restrict to 'real' cyclone tracks: n>=3 (12h), minp<=990
T=[t for t in alltr if t['n']>=3 and t['minp']<=990]
pos=[t for t in T if t['hit']]; neg=[t for t in T if not t['hit']]
print('\nTRACKS n>=3 pts, min smoothed MSLP<=990:',len(T),' matched to an archive fix:',len(pos),' unmatched:',len(neg))
def auc(feat):
    p=[feat(t) for t in pos]; n=[feat(t) for t in neg]
    s=0
    for a in p:
        for b in n: s+= 1 if a>b else (0.5 if a==b else 0)
    return s/(len(p)*len(n))
for name,fn in [('max 10m wind (300km)',lambda t:t['maxws']),('max gust (300km)',lambda t:t['maxg']),('min MSLP (lower=more extreme)',lambda t:-t['minp']),('max depth',lambda t:t['maxdepth']),('lifetime pts',lambda t:t['n'])]:
    print(f'  AUC {name:32s} {auc(fn):.2f}')
print('\nThreshold sweep on track max 10m wind (300 km), kt:  recall of matched tracks / unmatched tracks passing / precision')
for X in (40,45,48,50,52,55,58,60,64):
    tp=sum(t['maxws']>=X for t in pos); fp=sum(t['maxws']>=X for t in neg)
    print(f'  >= {X} kt: matched {tp}/{len(pos)} ({100*tp/len(pos):.0f}%), unmatched {fp}/{len(neg)}, precision {tp/max(1,tp+fp):.2f}')
print('\nThreshold sweep on track max gust (300 km), kt')
for X in (50,55,60,64,68,72,76,80):
    tp=sum(t['maxg']>=X for t in pos); fp=sum(t['maxg']>=X for t in neg)
    print(f'  >= {X} kt: matched {tp}/{len(pos)} ({100*tp/len(pos):.0f}%), unmatched {fp}/{len(neg)}, precision {tp/max(1,tp+fp):.2f}')
print('\nThreshold sweep on track min MSLP')
for X in (990,980,975,970,965,960,955,950):
    tp=sum(t['minp']<=X for t in pos); fp=sum(t['minp']<=X for t in neg)
    print(f'  <= {X}: matched {tp}/{len(pos)}, unmatched {fp}/{len(neg)}, precision {tp/max(1,tp+fp):.2f}')
# event-level recall: archive events (cls low) in months, found by any track?
ev=collections.defaultdict(lambda:[0,0])
for a in allfix:
    if a['cat']=='HF': ev[(a['key'],a['cls'])][0]+=1; ev[(a['key'],a['cls'])][1]+= a['c'] is not None
n=collections.Counter(); f=collections.Counter()
for (k,cls),(a,b) in ev.items(): n[cls]+=1; f[cls]+= b>0
print('\nEVENT-LEVEL (events with >=1 HF fix inside the domain boxes, 3 months): detected = >=1 HF fix with ERA5 centre in 400 km',{c:(f[c],n[c]) for c in n})
# monthly tallies
for ym in yms:
    nt=[t for t in T if t['ym']==ym]; print(ym,'tracks(>=12h, <=990)',len(nt),'matched',sum(t['hit'] for t in nt),'archive events w HF fix',len({k for (k,c) in ev if True and any(True for _ in [0])}) if False else '')
