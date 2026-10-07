import json, random, collections
d=json.load(open('/home/user/awips-tools/docs/data/hf-lows.json'))
F=d['lowFields']; FF=d['fixFields']
lows=[dict(zip(F,r)) for r in d['lows']]
for l in lows: l['fixes']=[dict(zip(FF,f)) for f in l['fixes']]
for l in lows: l['key']=l['basin']+':'+l['id']
named=['atl:2019202032','pac:2020202120','pac:2014201507','pac:2015201616','atl:2006200718',
       'atl:2014201534','pac:2006200701','atl:2016201701','pac:2009201003']                 # marginal single fix 975
tips=['atl:2021202219','atl:2017201825','atl:2020202125','atl:2011201225','atl:2012201311','atl:2015201623','atl:2024202533','atl:2004200531']
random.seed(7)
pool=[l for l in lows if l['cls']=='low' and l['key'] not in named and l['season']>=2004]
rnd=random.sample(pool,30)
sel=[]
for i in named: sel.append((i,'named'))
for i in tips: sel.append((i,'tipjet'))
for l in rnd: sel.append((l['key'],'random'))
json.dump(sel,open('selection.json','w'))
print(len(sel))
print(collections.Counter(l['season'] for l in rnd))
