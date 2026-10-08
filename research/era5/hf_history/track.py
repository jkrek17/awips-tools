"""Link ERA5 6-hourly lows into tracks, tag basin, and summarise each track.

Reads lows/*.csv, writes tracks_points.csv (one row per fix with track id)
and tracks.csv (one row per track).
"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("ERA5_WORK", os.path.join(HERE, "work"))

import glob, sys
import numpy as np, pandas as pd

RE = 6371.0
MAXD = 900.0      # km per 6 h (about 80 kt), tested against a motion-extrapolated guess
MIN_LEN = 4       # fixes (24 h)


def basin(lat, lon):
    if 30 <= lat <= 67 and (lon >= 262 or lon <= 10):
        return "atl"
    if 27 <= lat <= 67 and 135 <= lon <= 240:
        return "pac"
    return ""


def dist(la1, lo1, la2, lo2):
    la1, lo1, la2, lo2 = map(np.radians, (la1, lo1, la2, lo2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * RE * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def season(t):
    y, m = int(t[:4]), int(t[4:6])
    return y if m >= 6 else y - 1


def link(df):
    df = df.sort_values("time").reset_index(drop=True)
    times = sorted(df.time.unique())
    groups = {t: g for t, g in df.groupby("time")}
    tid = np.full(len(df), -1)
    active = {}            # track id -> (row idx, prev row idx or None)
    nxt = 0
    for t in times:
        g = groups[t]
        idx = g.index.values
        la, lo = g.lat.values, g.lon.values
        cand = []
        for k, (i, ip) in active.items():
            pla, plo = df.lat[i], df.lon[i]
            if ip is not None:     # half-weight persistence of the last motion
                dla = df.lat[i] - df.lat[ip]
                dlo = ((df.lon[i] - df.lon[ip] + 180) % 360) - 180
                pla, plo = pla + 0.5 * dla, (plo + 0.5 * dlo) % 360
            d = dist(pla, plo, la, lo)
            d0 = dist(df.lat[i], df.lon[i], la, lo)
            for j in range(len(idx)):
                if d[j] < MAXD and d0[j] < 1200:
                    cand.append((d[j] + 2.0 * abs(df.msl[i] - g.msl.values[j]), k, j))
        cand.sort()
        used_k, used_j, new_active = set(), set(), {}
        for c, k, j in cand:
            if k in used_k or j in used_j:
                continue
            used_k.add(k); used_j.add(j)
            tid[idx[j]] = k
            new_active[k] = (idx[j], active[k][0])
        for j in range(len(idx)):
            if j not in used_j:
                tid[idx[j]] = nxt
                new_active[nxt] = (idx[j], None)
                nxt += 1
        active = new_active
    df["track"] = tid
    return df


if __name__ == "__main__":
    a, b, out = sys.argv[1], sys.argv[2], sys.argv[3]
    files = [f for f in sorted(glob.glob(os.path.join(WORK, "lows", "*.csv"))) if a <= f[-10:-4] <= b]
    df = pd.concat([pd.read_csv(f, dtype={"time": str}) for f in files], ignore_index=True)
    df = df[(df.lat >= 20) & (df.lat <= 75)]
    df = link(df)
    n = df.groupby("track").size()
    df = df[df.track.isin(n[n >= MIN_LEN].index)].copy()
    df["basin"] = [basin(a, b) for a, b in zip(df.lat, df.lon)]
    df["season"] = [season(t) for t in df.time]
    df.to_csv(out, index=False)
    print(len(df), "fixes", df.track.nunique(), "tracks")
