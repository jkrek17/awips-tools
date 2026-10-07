import sys,json,math
sys.path.insert(0,'.')
from era5lib import *
d=json.load(open('/home/user/awips-tools/docs/data/hf-lows.json'))
F=d['lowFields'];FF=d['fixFields']
L={}
for r in d['lows']:
    l=dict(zip(F,r)); L[l['basin']+':'+l['id']]=l
for key in ['atl:2006200703','pac:2009201003','atl:2006200724']:
    l=L[key]; print('==',key,'minP',l['minP'],'n',l['n'],'idOk',l['idOk'],'split',l['split'],'timesSuspect',l['timesSuspect'],'spd',l['spdKt'],l['spdMaxKt'])
    for f in l['fixes']:
        fx=dict(zip(FF,f)); print('  ',fx)
    for f in l['fixes'][:5]:
        fx=dict(zip(FF,f)); i=tidx(fx['date']); m=field('mean_sea_level_pressure',i)/100
        # global-ish search: lowest pressure in +-15 deg box
        la0=fx['lat']; lo0=fx['lon']%360
        j0=int((90-la0-12)/0.25); j1=int((90-la0+12)/0.25); k0=int((lo0-20)/0.25); k1=int((lo0+20)/0.25)
        ks=np.arange(k0,k1)%1440
        sub=m[j0:j1][:,ks]; jj,kk=np.unravel_index(np.argmin(sub),sub.shape)
        print('   ',fx['date'],'analysed',fx['lat'],fx['lon'],fx['pres'],'| ERA5 lowest in +-12lat/+-20lon:',round(float(sub[jj,kk]),1),'at',90-0.25*(j0+jj),(0.25*ks[kk]+180)%360-180)
