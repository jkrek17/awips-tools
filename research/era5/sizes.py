import sys; sys.path.insert(0,'.')
import urllib.request, datetime, numpy as np, json
from era5lib import tidx
V3="https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
W13="https://storage.googleapis.com/gcp-public-data-arco-era5/ar/1959-2022-wb13-6h-0p25deg-chunk-1.zarr-v2"
def head(u):
    r=urllib.request.Request(u,method='HEAD'); 
    with urllib.request.urlopen(r,timeout=60) as x: return int(x.headers['Content-Length'])
vars_=['mean_sea_level_pressure','10m_u_component_of_wind','10m_v_component_of_wind','instantaneous_10m_wind_gust','sea_surface_temperature']
print('v3 hourly store, per-chunk compressed MB (HEAD content-length); 5 sample times each era')
tot={v:[] for v in vars_}
for ts in [1979010100,1985070112,1992011518,2000010100,2010120106,2022020812,2024010100]:
    row=[]
    for v in vars_:
        try: s=head(f"{V3}/{v}/{tidx(ts)}.0.0")/1e6
        except Exception as e: s=float('nan')
        tot[v].append(s); row.append(round(s,2))
    print(ts,row)
print('mean MB',{v:round(np.nanmean(x),2) for v,x in tot.items()})
for ts in [1979010100,2000010100,2020010100]:
    t6=tidx(ts)-tidx(1959010100); assert t6%6==0
    try: print('wb13 6h geopotential(13 lev) MB', ts, round(head(f"{W13}/geopotential/{t6//6}.0.0.0")/1e6,1))
    except Exception as e: print('wb13 err',e)
for ts in [2000010100,2020010100,2024010100]:
    try: print('v3 hourly geopotential(37 lev) MB', ts, round(head(f"{V3}/geopotential/{tidx(ts)}.0.0.0")/1e6,1))
    except Exception as e: print('v3 geopot err',e)
