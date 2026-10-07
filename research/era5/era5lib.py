import urllib.request, json, datetime, math, time, ssl, os
import numpy as np, numcodecs
B="https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
T0=datetime.datetime(1900,1,1)
codec=numcodecs.Blosc()
def tidx(yyyymmddhh):
    s=str(yyyymmddhh); t=datetime.datetime(int(s[:4]),int(s[4:6]),int(s[6:8]),int(s[8:10]))
    return int((t-T0).total_seconds()//3600)
BYTES=[0]
def field(var,idx):
    url=f"{B}/{var}/{idx}.0.0"
    for k in range(3):
        try:
            with urllib.request.urlopen(url,timeout=120) as r: raw=r.read()
            break
        except Exception as e:
            if k==2: raise
            time.sleep(2)
    BYTES[0]+=len(raw)
    a=np.frombuffer(codec.decode(raw),dtype='<f4').reshape(721,1440)
    return a
lat=90-0.25*np.arange(721)   # verified below against latitude array
lon=0.25*np.arange(1440)     # 0..359.75
