import sys,json,math,time,urllib.request
sys.path.insert(0,'.')
from era5lib import *
W13="https://storage.googleapis.com/gcp-public-data-arco-era5/ar/1959-2022-wb13-6h-0p25deg-chunk-1.zarr-v2"
lv=np.frombuffer(codec.decode(urllib.request.urlopen(f"{W13}/level/0").read()),dtype='<i8'); print('levels',lv)
i500=int(np.where(lv==500)[0][0])
d=json.load(open('/home/user/awips-tools/docs/data/hf-lows.json')); F=d['lowFields'];FF=d['fixFields']
L={}
for r in d['lows']:
    l=dict(zip(F,r)); L[l['basin']+':'+l['id']]=l
keys=['atl:2006200718','pac:2014201507','pac:2015201616','atl:2005200617','pac:2012201309','atl:2013201415']
t59=tidx(1959010100)
t=time.time(); b0=BYTES[0]
for k in keys:
    l=L[k]; f=dict(zip(FF,l['fixes'][0])); i=tidx(f['date'])
    raw=urllib.request.urlopen(f"{W13}/geopotential/{(i-t59)//6}.0.0.0").read(); BYTES[0]+=len(raw)
    z=np.frombuffer(codec.decode(raw),dtype='<f4').reshape(13,721,1440)[i500]/9.80665
    sst=field('sea_surface_temperature',i)
    lat0=f['lat']; lon0=f['lon']%360; j=int(round((90-lat0)/0.25)); kk=int(round(lon0/0.25))
    sub=sst[j-8:j+9,kk-8:kk+9]; 
    gy,gx=np.gradient(np.where(np.isnan(sub),np.nan,sub))
    gmag=np.hypot(gy/(0.25*111.19),gx/(0.25*111.19*math.cos(math.radians(lat0))))*100  # K per 100 km
    print(k,f['date'],'genesis-fix at',lat0,f['lon'],'| Z500 at fix %.0f m'%z[j,kk],'| SST at fix %s K'%(None if np.isnan(sst[j,kk]) else round(float(sst[j,kk]),1)),'| max SST grad +-2deg %.2f K/100km'%np.nanmax(gmag) if not np.isnan(gmag).all() else 'sst nan')
print('MB read',(BYTES[0]-b0)/1e6,'sec',round(time.time()-t,1))
