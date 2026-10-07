import io, requests, h5py, numpy as np, time
class RangeFile(io.RawIOBase):
    def __init__(s,url):
        s.url=url; s.s=requests.Session(); r=s.s.head(url); s.size=int(r.headers['Content-Length']); s.pos=0; s.n=0; s.bytes=0
    def readable(s): return True
    def seekable(s): return True
    def tell(s): return s.pos
    def seek(s,o,w=0):
        s.pos = o if w==0 else (s.pos+o if w==1 else s.size+o); return s.pos
    def readinto(s,b):
        n=len(b)
        if n==0 or s.pos>=s.size: return 0
        end=min(s.pos+n,s.size)-1
        r=s.s.get(s.url,headers={'Range':f'bytes={s.pos}-{end}'}); d=r.content
        s.n+=1; s.bytes+=len(d)
        b[:len(d)]=d; s.pos+=len(d); return len(d)
url="https://nsf-ncar-era5.s3.amazonaws.com/e5.oper.an.sfc/198001/e5.oper.an.sfc.128_151_msl.ll025sc.1980010100_1980013123.nc"
f=RangeFile(url)
h=h5py.File(f,'r')
print(list(h.keys()))
v=h['MSL']; print(v.shape,v.dtype,v.chunks,v.compression,v.scaleoffset,v.shuffle)
print({k:(v.attrs[k] if not hasattr(v.attrs[k],'shape') or v.attrs[k].size<5 else '...') for k in v.attrs.keys()})
print('requests',f.n,'bytes',f.bytes)
t=time.time(); a=v[5]; print('read one step',a.shape,a.dtype,a.min(),a.max(),'requests',f.n,'bytes',f.bytes,time.time()-t)
print(h['time'][:3] if 'time' in h else h.keys(), h['latitude'][:3], h['longitude'][:3])
