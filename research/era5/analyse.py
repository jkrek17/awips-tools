import json, statistics as st, collections
R=json.load(open('compare_out.json'))
KT=1.94384
print('key cls date cat anlP | era5 minP300 bias off | ws300 kt ws600 kt | susp idOk')
for r in sorted(R,key=lambda r:(r['kind'],r['id'],r['date'])):
    bias=(r['mslp300']-r['pres']) if r['pres'] else None
    print(r['id'],r['cls'][:3],r['date'],r['cat'].ljust(3),r['pres'],'|',round(r['mslp300'],1),None if bias is None else round(bias,1),round(r['mslp300_off']),'|',round(r['ws300']*KT),round(r['ws600']*KT),'|',r['timesSuspect'],r['idOk'])
print()
lw=[r for r in R if r['cls']=='low' and r['pres']]
b=[r['mslp300']-r['pres'] for r in lw]
print('pressure bias, all fixes n',len(b),'mean',round(st.mean(b),2),'median',round(st.median(b),2),'sd',round(st.pstdev(b),2))
print('  |bias|<=5 hPa frac',round(sum(abs(x)<=5 for x in b)/len(b),2),' ERA5 shallower (bias>0) frac',round(sum(x>0 for x in b)/len(b),2))
print('  offset km median',round(st.median([r['mslp300_off'] for r in lw])))
# exclude fixes where min is at the search edge (>=250 km): likely no matching low
core=[r for r in lw if r['mslp300_off']<250]
cb=[r['mslp300']-r['pres'] for r in core]
print('fixes with ERA5 min within 250km:',len(core),'of',len(lw),'; bias mean',round(st.mean(cb),2),'median',round(st.median(cb),2),'sd',round(st.pstdev(cb),2))
byev=collections.defaultdict(list)
for r in lw: byev[r['id']].append(r)
ev=[min(v,key=lambda r:r['pres']) for v in byev.values()]
eb=[r['mslp300']-r['pres'] for r in ev]; print('event minP-fix bias n',len(eb),'mean',round(st.mean(eb),2),'median',round(st.median(eb),2))
for lo,hi in [(0,950),(950,965),(965,980),(980,1100)]:
    x=[r['mslp300']-r['pres'] for r in core if lo<=r['pres']<hi]
    if x: print('analysed P',lo,hi,'n',len(x),'mean bias',round(st.mean(x),2),'median',round(st.median(x),2))
cat=collections.defaultdict(list)
for r in R: cat[(r['cls']=='tipjet',r['cat'])].append(r['ws300']*KT)
for k,v in sorted(cat.items()):
    v.sort(); print('tipjet' if k[0] else 'low   ',k[1],'n',len(v),'ERA5 max ws300 kt: median',round(st.median(v)),'p10',round(v[int(.1*(len(v)-1))]),'p90',round(v[int(.9*(len(v)-1))]),'max',round(max(v)),'frac>=64',round(sum(x>=64 for x in v)/len(v),2),'frac>=48',round(sum(x>=48 for x in v)/len(v),2))
hf=[r for r in R if r['cat']=='HF' and r['cls']=='low']
w=[r['ws300']*KT for r in hf]; print('HF low fixes ws300 mean',round(st.mean(w),1),'-> deficit vs 64:',round(64-st.mean(w),1),'kt;  mean ratio',round(st.mean(w)/64,2))
w6=[r['ws600']*KT for r in hf]; print('ws600 median',round(st.median(w6)),'frac>=64',round(sum(x>=64 for x in w6)/len(w6),2))
# event level: max over fixes of ws300
evmax=collections.defaultdict(float)
for r in R:
    if r['cat']=='HF': evmax[r['id']]=max(evmax[r['id']],r['ws300']*KT)
print('event-level (max over sampled HF fixes) n',len(evmax),'>=64kt:',sum(v>=64 for v in evmax.values()),' >=55:',sum(v>=55 for v in evmax.values()),' >=50:',sum(v>=50 for v in evmax.values()),' median',round(st.median(evmax.values())))
