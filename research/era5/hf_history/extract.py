"""Extract ERA5 low centres and the gust field around them, 6-hourly.

For every 6-hourly time: find MSLP minima over 20-75N, then assign every ocean
grid point with an instantaneous 10 m gust >= 17 m/s to its nearest low
(within 1200 km) and summarise the gust field each low owns.

Output: one CSV per month in OUT/, resumable.
"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("ERA5_WORK", os.path.join(HERE, "work"))

import os, sys, json, time
import numpy as np, numcodecs, gcsfs
from scipy import ndimage
from scipy.spatial import cKDTree
from multiprocessing import Pool

ROOT = "gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
OUT = os.path.join(WORK, "lows")
T0 = np.datetime64("1900-01-01T00")
R0, R1 = 60, 281                    # rows for 75N .. 20N
LAT = 90 - 0.25 * np.arange(R0, R1)
LON = 0.25 * np.arange(1440)
RE = 6371.0
KT = 1 / 0.514444

_fs = None
_codec = numcodecs.Blosc(cname="lz4", clevel=5, shuffle=1)
LSM_PATH = os.path.join(WORK, "lsm.npy")
if not os.path.exists(LSM_PATH):
    os.makedirs(WORK, exist_ok=True)
    _b = gcsfs.GCSFileSystem(token="anon").cat(f"{ROOT}/land_sea_mask/876576.0.0")    # 2000-01-01 00Z
    np.save(LSM_PATH, np.frombuffer(_codec.decode(_b), "<f4").reshape(721, 1440))
LSM = np.load(LSM_PATH)[R0:R1] < 0.5          # ocean
LA2, LO2 = np.meshgrid(np.radians(LAT), np.radians(LON), indexing="ij")
XYZ = np.stack([np.cos(LA2) * np.cos(LO2), np.cos(LA2) * np.sin(LO2), np.sin(LA2)], -1)


def fs():
    global _fs
    if _fs is None:
        _fs = gcsfs.GCSFileSystem(token="anon")
    return _fs


def get(var, ti):
    for k in range(5):
        try:
            b = fs().cat(f"{ROOT}/{var}/{ti}.0.0")
            return np.frombuffer(_codec.decode(b), "<f4").reshape(721, 1440)[R0:R1]
        except Exception:
            time.sleep(2 ** k)
    raise RuntimeError(f"fetch failed {var} {ti}")


def lows_at(ti):
    msl = get("mean_sea_level_pressure", ti) / 100.0
    gust = get("instantaneous_10m_wind_gust", ti)
    sm = ndimage.gaussian_filter(msl, 2, mode=["nearest", "wrap"])
    mn = ndimage.minimum_filter(sm, size=(21, 21), mode=["nearest", "wrap"])
    r, c = np.where((sm == mn) & (sm < 1010.0))
    keep = (r > 2) & (r < len(LAT) - 3)
    r, c = r[keep], c[keep]
    if len(r) == 0:
        return []
    # refine to the raw minimum in a 5x5 box, then drop lows within 400 km of a deeper one
    pts = []
    for i, j in zip(r, c):
        rr = slice(max(i - 2, 0), i + 3)
        cols = np.arange(j - 2, j + 3) % 1440
        box = msl[rr][:, cols]
        a, b = np.unravel_index(np.argmin(box), box.shape)
        pts.append((box[a, b], max(i - 2, 0) + a, cols[b]))
    pts.sort()
    sel = []
    for p, i, j in pts:
        v = XYZ[i, j]
        if all(np.arccos(np.clip(v @ XYZ[a, b], -1, 1)) * RE > 400 for _, a, b in sel):
            sel.append((p, i, j))
    cen = np.array([XYZ[i, j] for _, i, j in sel])
    tree = cKDTree(cen)
    m = LSM & (gust >= 17.0)
    gi = np.where(m)
    g = gust[gi]
    out = []
    stats = [dict(g500=0.0, g800=0.0, g1200=0.0, n33_800=0, n33_1200=0, n25_800=0) for _ in sel]
    if len(g):
        d, k = tree.query(XYZ[gi], k=1)
        dkm = 2 * np.arcsin(np.clip(d / 2, 0, 1)) * RE
        n = len(sel)
        for rad, key in ((500, "g500"), (800, "g800"), (1200, "g1200")):
            acc = np.zeros(n); w = dkm <= rad
            np.maximum.at(acc, k[w], g[w])
            for kk in range(n): stats[kk][key] = acc[kk]
        for rad, thr, key in ((800, 32.9, "n33_800"), (1200, 32.9, "n33_1200"), (800, 24.5, "n25_800")):
            cnt = np.bincount(k[(dkm <= rad) & (g >= thr)], minlength=n)
            for kk in range(n): stats[kk][key] = cnt[kk]
    # also the full-disc 800 km max ignoring ownership (for diagnostics)
    for (p, i, j), s in zip(sel, stats):
        out.append((LAT[i], LON[j], round(float(p), 1), round(s["g500"] * KT, 1), round(s["g800"] * KT, 1),
                    round(s["g1200"] * KT, 1), int(s["n33_800"]), int(s["n33_1200"]), int(s["n25_800"])))
    return out


def month(ym):
    y, m = ym
    path = f"{OUT}/{y}{m:02d}.csv"
    if os.path.exists(path):
        return ym
    a = np.datetime64(f"{y}-{m:02d}-01T00")
    b = np.datetime64(f"{y + (m == 12)}-{m % 12 + 1:02d}-01T00")
    rows = []
    t = a
    while t < b:
        ti = int((t - T0) / np.timedelta64(1, "h"))
        stamp = str(t).replace("-", "").replace("T", "")[:10]
        for r in lows_at(ti):
            rows.append((stamp,) + r)
        t += np.timedelta64(6, "h")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("time,lat,lon,msl,g500,g800,g1200,n33_800,n33_1200,n25_800\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    os.replace(tmp, path)
    return ym


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    y0, y1 = int(sys.argv[1]), int(sys.argv[2])     # season start years, Jun y0 .. May y1+1
    months = [(y, m) for y in range(y0, y1 + 2) for m in range(1, 13)
              if (y, m) >= (y0, 6) and (y, m) <= (y1 + 1, 5)]
    months.sort(key=lambda ym: -ym[0])     # newest first: calibration period lands first
    t = time.time()
    with Pool(int(os.environ.get("NPROC", 12))) as p:
        for i, ym in enumerate(p.imap_unordered(month, months)):
            print(f"{ym} {i + 1}/{len(months)} {time.time() - t:.0f}s", flush=True)
