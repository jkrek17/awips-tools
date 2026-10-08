"""Cyclone-level feature table for the ERA5 hurricane-force transfer test.

What this builds
----------------
For every sampled season, every 6-hourly time step from 1 Sep to 31 May, in the
archive's two domains (Atlantic 30-70N 80W-10E; Pacific 30-67N 160E-120W):

  1. find candidate cyclone centres in ERA5 mean sea level pressure (the pilot's
     detector from month.py: 5x5 smoothing, 17x17 minimum filter, centre below
     1005 hPa, at least 4 hPa deeper than the 450-650 km ring around it);
  2. compute the features a wind criterion would key on, from the GUST field
     (`instantaneous_10m_wind_gust`), not sustained wind - the pilot found 0 of
     103 archive events reach 64 kt in ERA5 10 m wind;
  3. cache the lot to one CSV per season (resumable; a finished season is
     never refetched).

`label()` then joins the candidates to the archive (docs/data/hf-lows.json):

  pos   candidate within 400 km, at the same valid time, of an archive fix
        whose category is HF. Fix category HF only: DHF/S/DS fixes are
        deliberately NOT positives, and they are not removed from the
        negatives either, because the archive began logging them around HF
        events in 2013-14 (Pacific) and 2017-18 (Atlantic). Letting them
        shape the negative set would make the labels depend on a recording
        practice that changed inside the study window.
  neg   a candidate on a linked track (700 km / 6 h greedy, as matchmonth.py)
        that NEVER matches an HF fix. These are cyclones that did not reach
        hurricane force, which is the point: the comparison is between HF
        moments and non-HF cyclones, not between storms and empty ocean.
  gray  a candidate that is not itself a positive but either sits on a track
        that DOES reach HF at some other time (pre-deepening, post-peak), or lies
        within 400 km of an archive HF fix whose event class is tipjet/nocentre
        (no analysed cyclone centre, so the HF wind is not attributable to this
        cyclone). Only archive class 'low' HF fixes create positives. Gray is
        excluded from the primary fit; reported, and used in one pre-specified
        sensitivity.

Usage
-----
    python event_fields.py fetch 2004 2005 2021 2022 2023 2024 2025
    python event_fields.py label            # writes event_fields.csv

Concurrency is a ThreadPoolExecutor of 6, as in stationarity2.py. Do not raise
it: another job may be streaming the same store.

numpy and numcodecs only (no scipy; the filters are separable and written
directly).
"""
import csv
import datetime
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from numpy.lib.stride_tricks import sliding_window_view

import numcodecs
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(HERE, "..", "..", "docs", "data", "hf-lows.json")
B = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
     "full_37-1h-0p25deg-chunk-1.zarr-v3")
T0 = datetime.datetime(1900, 1, 1)
CODEC = numcodecs.Blosc()
BYTES = [0]
KT = 1.94384
RK = 6371.0
WORKERS = 6

# Core domains (where a centre may lie) and the extended window the neighbourhood
# is read from: 6 degrees of latitude and 20 of longitude of margin, so a 650 km
# ring around a centre on the domain edge is still inside the array.
BASINS = {
    "atl": dict(lat=(70.0, 30.0), lon=(-80.0, 10.0),
                xlat=(76.0, 24.0), xlon=(-100.0, 30.0)),
    "pac": dict(lat=(67.0, 30.0), lon=(160.0, 240.0),
                xlat=(73.0, 24.0), xlon=(140.0, 260.0)),
}

R_GUST = 500.0       # km: gust maximum, gust areas, gradient maximum
R_MIN = 150.0        # km: raw minimum pressure
MATCH_KM = 400.0     # km: candidate to archive fix, as the pilot
LINK_KM = 700.0      # km per 6 h: track linking, as matchmonth.py
HF_MS = 64 * 0.514444
SF_MS = 50 * 0.514444

COLS = ["t", "basin", "lat", "lon", "p", "pmin", "depth", "lap", "g300", "g500",
        "a64", "a50", "gradmax"]


def tidx(t):
    return int((t - T0).total_seconds() // 3600)


def idx_to_dt(i):
    return T0 + datetime.timedelta(hours=int(i))


def season_of(dt):
    return dt.year if dt.month >= 6 else dt.year - 1


def field(var, idx, tries=4):
    url = "%s/%s/%d.0.0" % (B, var, idx)
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=150) as r:
                raw = r.read()
            BYTES[0] += len(raw)
            return np.frombuffer(CODEC.decode(raw), dtype="<f4").reshape(721, 1440)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


# --- grid helpers -----------------------------------------------------------

def _window(spec):
    r0 = int(round((90 - spec["xlat"][0]) / 0.25))
    r1 = int(round((90 - spec["xlat"][1]) / 0.25)) + 1
    c0 = int(round((spec["xlon"][0] % 360) / 0.25))
    ncol = int(round((spec["xlon"][1] - spec["xlon"][0]) / 0.25)) + 1
    cols = (c0 + np.arange(ncol)) % 1440
    return slice(r0, r1), cols


def _prep():
    out = {}
    for b, spec in BASINS.items():
        rs, cols = _window(spec)
        lat = 90 - 0.25 * np.arange(rs.start, rs.stop)
        lon = cols * 0.25
        lon = np.where(lon > 180, lon - 360, lon) if b == "atl" else lon
        # core-domain mask on the extended grid (Pacific lon stays 0..360)
        core = (lat[:, None] <= spec["lat"][0]) & (lat[:, None] >= spec["lat"][1])
        lo = lon[None, :]
        core = core & (lo >= spec["lon"][0]) & (lo <= spec["lon"][1])
        out[b] = dict(rs=rs, cols=cols, lat=lat, lon=lon, core=core)
    return out


GRID = _prep()


def box(a, n):
    """Edge-padded n x n mean (n odd)."""
    h = n // 2
    p = np.pad(a, h, mode="edge")
    c = np.cumsum(np.cumsum(np.pad(p, ((1, 0), (1, 0))), 0), 1)
    return (c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)


def minfilt(a, n):
    h = n // 2
    p = np.pad(a, h, mode="edge")
    m = sliding_window_view(p, n, axis=0).min(-1)
    return sliding_window_view(m, n, axis=1).min(-1)


def hav(la, lo, la0, lo0):
    p1 = np.radians(la)[:, None]
    p2 = math.radians(la0)
    dl = np.radians(lo)[None, :] - math.radians(lo0)
    h = np.sin((p1 - p2) / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * RK * np.arcsin(np.sqrt(h))


def hav1(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    dl = math.radians(lo2 - lo1)
    h = math.sin((p1 - p2) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RK * math.asin(min(1.0, math.sqrt(h)))


# --- one time step -----------------------------------------------------------

def step(idx):
    """All candidates and their features, both basins, for one valid time."""
    mfull = field("mean_sea_level_pressure", idx)
    gfull = field("instantaneous_10m_wind_gust", idx)
    out = []
    for b, G in GRID.items():
        m = mfull[G["rs"]][:, G["cols"]].astype(np.float64) / 100.0
        g = gfull[G["rs"]][:, G["cols"]].astype(np.float64)
        la, lo = G["lat"], G["lon"]
        ms = box(m, 5)
        mn = minfilt(ms, 17)
        cand = np.argwhere((ms == mn) & (ms < 1005) & G["core"])
        if not len(cand):
            continue
        # pressure gradient magnitude, hPa per 100 km, from the raw field
        dy = 0.25 * math.radians(1) * RK * 2          # km across two rows
        dpdy = np.zeros_like(m)
        dpdy[1:-1] = (m[:-2] - m[2:]) / dy * 100
        dx = (0.25 * math.radians(1) * RK * np.cos(np.radians(la)) * 2)[:, None]
        dpdx = np.zeros_like(m)
        dpdx[:, 1:-1] = (m[:, 2:] - m[:, :-2]) / dx[:, :] * 100
        grad = np.hypot(dpdx, dpdy)
        cellarea = (0.25 * math.radians(1) * RK) ** 2 * np.cos(np.radians(la))[:, None]
        for a, c in cand:
            pad = 28
            padc = int(min(150, math.ceil(pad / max(0.3, math.cos(math.radians(la[a]))))))
            a0, a1 = max(0, a - pad), min(m.shape[0], a + pad + 1)
            c0, c1 = max(0, c - padc), min(m.shape[1], c + padc + 1)
            if a - a0 < pad or a1 - a < pad + 1 or c - c0 < padc or c1 - c < padc + 1:
                continue
            Dk = hav(la[a0:a1], lo[c0:c1], la[a], lo[c])
            ring = (Dk >= 450) & (Dk <= 650)
            depth = float(ms[a0:a1, c0:c1][ring].mean() - ms[a, c])
            if depth < 4:
                continue
            r3 = (Dk >= 250) & (Dk <= 350)
            lap = 4 * float(ms[a0:a1, c0:c1][r3].mean() - ms[a, c]) / 9.0  # hPa/(100 km)^2
            near = Dk <= R_MIN
            rg = Dk <= R_GUST
            gg = g[a0:a1, c0:c1]
            ca = cellarea[a0:a1]
            out.append((idx, b, float(la[a]), float(lo[c]), float(ms[a, c]),
                        float(m[a0:a1, c0:c1][near].min()), depth, lap,
                        float(gg[Dk <= 300].max()) * KT, float(gg[rg].max()) * KT,
                        float((ca * (gg >= HF_MS) * rg).sum()),
                        float((ca * (gg >= SF_MS) * rg).sum()),
                        float(grad[a0:a1, c0:c1][rg].max())))
    return out


def _safe(idx):
    try:
        return idx, step(idx)
    except Exception as e:  # a gap in the sample, not a dead run
        print("# step %d failed: %r" % (idx, e), file=sys.stderr, flush=True)
        return idx, None


def season_steps(season):
    t = datetime.datetime(season, 9, 1)
    end = datetime.datetime(season + 1, 6, 1)
    out = []
    while t < end:
        out.append(tidx(t))
        t += datetime.timedelta(hours=6)
    return out


def raw_path(season):
    return os.path.join(HERE, "event_fields_%d.csv" % season)


STEPS_CSV = os.path.join(HERE, "event_fields_steps.csv")


def fetch_season(season, pool):
    path = raw_path(season)
    if os.path.exists(path):
        print("season %d cached" % season, flush=True)
        return
    t0 = time.time()
    idxs = season_steps(season)
    res = list(pool.map(_safe, idxs))
    ok = sum(r is not None for _, r in res)
    tmp = path + ".part"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for _, r in res:
            for row in (r or []):
                w.writerow([row[0], row[1]] + ["%.3f" % v if i < 2 else "%.2f" % v
                                               for i, v in enumerate(row[2:])])
    new = not os.path.exists(STEPS_CSV)
    with open(STEPS_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["season", "t", "ok"])
        for i, r in res:
            w.writerow([season, i, int(r is not None)])
    os.replace(tmp, path)
    print("season %d: %d/%d steps ok, %d candidates, %.1f GB total, %.0f s" % (
        season, ok, len(idxs), sum(len(r or []) for _, r in res), BYTES[0] / 1e9,
        time.time() - t0), flush=True)


# --- archive and labels -------------------------------------------------------

def load_archive():
    d = json.load(open(ARCHIVE))
    F, FF = d["lowFields"], d["fixFields"]
    fixes = []
    for r in d["lows"]:
        low = dict(zip(F, r))
        for f in low["fixes"]:
            x = dict(zip(FF, f))
            s = str(x["date"])
            dt = datetime.datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]))
            lo = x["lon"]
            if low["basin"] == "atl":
                inside = (30 <= x["lat"] <= 70) and (-80 <= lo <= 10)
            else:
                inside = (30 <= x["lat"] <= 67) and (lo >= 160 or lo <= -120)
                lo = lo % 360
            fixes.append(dict(key=low["basin"] + ":" + low["id"], basin=low["basin"],
                              t=tidx(dt), lat=x["lat"], lon=lo, cat=x["cat"],
                              inside=inside, season=season_of(dt), cls=low["cls"]))
    return fixes


def read_raw(seasons):
    rows = []
    for s in seasons:
        with open(raw_path(s)) as f:
            for r in csv.DictReader(f):
                r["season"] = s
                rows.append(r)
    return rows


def link_tracks(cands):
    """Greedy nearest-neighbour linking per basin, as matchmonth.py."""
    byt = {}
    for c in cands:
        byt.setdefault((c["basin"], c["t"]), []).append(c)
    n = 0
    for basin in BASINS:
        times = sorted(t for (b, t) in byt if b == basin)
        active = []
        for t in times:
            cs = byt[(basin, t)]
            used, new_active = set(), []
            for tr in active:
                if tr["last_t"] != t - 6:
                    continue
                best = None
                for i, c in enumerate(cs):
                    if i in used:
                        continue
                    dd = hav1(tr["last"]["lat"], tr["last"]["lon"], c["lat"], c["lon"])
                    if dd <= LINK_KM and (best is None or dd < best[0]):
                        best = (dd, i)
                if best:
                    used.add(best[1])
                    c = cs[best[1]]
                    c["track"] = tr["id"]
                    tr["last"], tr["last_t"] = c, t
                    new_active.append(tr)
            for i, c in enumerate(cs):
                if i not in used:
                    n += 1
                    tr = dict(id=n, last=c, last_t=t)
                    c["track"] = n
                    new_active.append(tr)
            active = new_active


def label(seasons, ok_steps=None):
    """Return the labelled candidate list (list of dicts)."""
    rows = read_raw(seasons)
    cands = []
    for r in rows:
        c = dict(t=int(r["t"]), basin=r["basin"], season=r["season"])
        for k in COLS[2:]:
            c[k] = float(r[k])
        c["lon"] = c["lon"] % 360 if c["basin"] == "pac" else c["lon"]
        cands.append(c)
    link_tracks(cands)
    byt = {}
    for c in cands:
        c["pos"], c["other"], c["amb"], c["key"] = 0, 0, 0, ""
        byt.setdefault((c["basin"], c["t"]), []).append(c)
    for f in load_archive():
        if not f["inside"] or f["season"] not in seasons:
            continue
        best = None
        for c in byt.get((f["basin"], f["t"]), []):
            dd = hav1(f["lat"], f["lon"], c["lat"], c["lon"])
            if dd <= MATCH_KM and (best is None or dd < best[0]):
                best = (dd, c)
        if best:
            if f["cat"] == "HF" and f["cls"] == "low":
                best[1]["pos"] = 1
                best[1]["key"] = f["key"]
            elif f["cat"] == "HF":
                # terrain-forced / no-centre archive HF: the wind is not tied
                # to this cyclone, so the candidate is neither pos nor neg
                best[1]["amb"] = 1
            else:
                best[1]["other"] = 1
    hf_tracks = {(c["basin"], c["track"]) for c in cands if c["pos"]}
    for c in cands:
        if c["pos"]:
            c["cls"] = "pos"
        elif (c["basin"], c["track"]) in hf_tracks:
            c["cls"] = "gray"
        else:
            c["cls"] = "gray" if c["amb"] else "neg"
        c["track"] = "%s%d" % (c["basin"], c["track"])
    return cands


def detection(seasons):
    """Archive HF fixes inside the domains that have an ERA5 candidate within
    400 km at the same valid time. Returns per-season-basin counts and the
    event-level tally, split by the archive's event class (low / tipjet /
    nocentre). Time steps ERA5 failed to serve are excluded."""
    okt = set()
    with open(STEPS_CSV) as f:
        for r in csv.DictReader(f):
            if r["ok"] == "1":
                okt.add(int(r["t"]))
    rows = read_raw(seasons)
    byt = {}
    for r in rows:
        byt.setdefault((r["basin"], int(r["t"])), []).append(
            (float(r["lat"]), float(r["lon"]) % 360 if r["basin"] == "pac" else float(r["lon"]),
             float(r["p"])))
    res = {}
    ev = {}
    for f in load_archive():
        if f["cat"] != "HF" or not f["inside"] or f["season"] not in seasons or f["t"] not in okt:
            continue
        hit = None
        for la, lo, p in byt.get((f["basin"], f["t"]), []):
            dd = hav1(f["lat"], f["lon"], la, lo)
            if dd <= MATCH_KM and (hit is None or dd < hit[0]):
                hit = (dd, p)
        k = (f["season"], f["basin"], f["cls"])
        a = res.setdefault(k, [0, 0, 0])
        a[0] += 1
        a[1] += hit is not None
        a[2] += hit is not None and hit[1] <= 990
        e = ev.setdefault((f["season"], f["basin"], f["key"], f["cls"]), [0, 0])
        e[0] += 1
        e[1] += hit is not None
    return res, ev


def write_labelled(seasons, path=None):
    cands = label(seasons)
    path = path or os.path.join(HERE, "event_fields.csv")
    cols = ["season", "basin", "t", "track", "cls", "pos", "other", "amb", "key"] + COLS[2:]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for c in sorted(cands, key=lambda c: (c["basin"], c["t"], c["lat"])):
            w.writerow([c[k] if not isinstance(c[k], float) else "%.3f" % c[k] for k in cols])
    return cands


def main():
    cmd = sys.argv[1]
    if cmd == "fetch":
        pool = ThreadPoolExecutor(max_workers=WORKERS)
        for s in map(int, sys.argv[2:]):
            fetch_season(s, pool)
    elif cmd == "label":
        seasons = sorted(int(f[13:17]) for f in os.listdir(HERE)
                         if f.startswith("event_fields_") and f.endswith(".csv")
                         and f[13:17].isdigit())
        c = write_labelled(seasons)
        print("wrote event_fields.csv, %d candidates, seasons %s" % (len(c), seasons))


if __name__ == "__main__":
    main()
