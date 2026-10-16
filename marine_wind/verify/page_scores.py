"""Scores for the verification page (/verification/): how each model and each of our blends
did against every truth source we use, one basin and one valid time per run.

    --hour 00, 06, 12 or 18 (default: HOUR[basin], North Atlantic 12 and North Pacific 00, which
    were the only hours scored before mid-October 2026): valid at that UTC hour, forecasts from the
    same-hour runs 1 to 5 days earlier. The page scores all four hours of both basins.

Forecasts come from the page job's forecast record (pipeline/record.py), else are rebuilt with the page's
own pipeline (build.step_values), so the blends are exactly what the page showed (or would have shown):

    windcore      Core Lifted (the page's main wind): the blend + 5 kt where the core likelihood is 35%+
    blend         the blend before the core lift: support-weighted 3 models + min(k x spread, 5 kt)
    nomem         deterministic blend (no members; the GFE candidate)
    mean3         plain average of GFS, ECMWF and AIFS
    gfs, ecmwf, aifs
    gefs_mean, ens_mean, aifsens_mean   each ensemble's mean wind (speed of the members' mean
                  u and v, as AWIPS shows it); the AIFS ensemble is on AWS from Aug 2025

Truth sources (open, ice-free water in the OPC chart box):

    analysis      mean of the GDAS and ECMWF IFS analyses
    gdas, ifs     each analysis alone
    ascat         Metop-B/C ASCAT within 90 min (RSS bytemaps), rain-flagged cells dropped,
                  equivalent-neutral wind turned into real 10 m wind with the analysed
                  air-minus-sea temperature, as in the storm study (storm_verify.py)
    buoys         moored buoys, ships+buoys: the GDAS marine monitoring file (first guess
                  + O-B), buoys raised to 10 m (Charnock profile), ships scaled 0.88

Four CSVs per run (DIR/scores_*.csv, chances_*.csv, lowbins_*.csv, storm_*.csv; names end _BASIN_HH):

  scores   per (lead, method, referee): n, ae, bias, se over all points; n25, ae25, bias25
           where forecast or truth is 25+ kt; h/f/m34,48,64 hits, false alarms, misses by
           cell or ob; on the gridded truths also 5 x 5 degree tiles (150+ scored cells):
           t{34,48,64}{h,m,f} peak caught/missed/false by tile ("any cell at the threshold"),
           and pk_n, pk_sum, pk_abs: tile highest-wind error (forecast max - truth max) over
           tiles where either reaches 34 kt
  chances  per (lead, referee, threshold): the page's P34, P48, P64 (P48/P64 recalibrated):
           n, events, Brier sum, and 10 reliability bins (count, events, sum of chances).
           Extra thr labels: "48raw", "64raw" (the members' own shares, before recalibration, same
           events as 48 and 64) and "core" (the storm core likelihood, ASCAT only: event = ASCAT
           48+ kt within about 50 km, the model's training target, see core_event; scored on the
           model's candidate cells only: blend 28+ kt or a model 34+ kt)
  lowbins  the same counts for the chances under 10% in finer bins [0,1), [1,2), [2,5), [5,10) %:
           per (lead, referee, thr) n0-n3, e0-e3, p0-p3
  storm    the storm layers (hazard lines, peaks, low track), storm_verify.py's rows

    python3 page_scores.py --basin natl --valid 20261012 [--hour 18] --out DIR
"""
import argparse, collections, csv, datetime as dt, gzip, io, os, sys, time, urllib.error, urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "..", "pipeline")
KT = 1.943844

STEPS = [24, 48, 72, 96, 120]
HOUR = {"natl": 12, "npac": 0}      # the hours scored before mid-October 2026 (the default of --hour)
HOURS = (0, 6, 12, 18)
LOW_EDGES = (0.0, 1.0, 2.0, 5.0, 10.0)   # percent
METHODS = ["windcore", "blend", "nomem", "mean3", "gfs", "ecmwf", "aifs", "gefs_mean", "ens_mean", "aifsens_mean"]
GRID_REFS = ["analysis", "gdas", "ifs"]
TILE_MIN = 150
MAX_DT = 90
ASCAT_URL = "https://data.remss.com/ascat/metop{s}/bmaps_v02.1/y{y}/m{m}/ascat{s}_{d}_v02.1.gz"
SCORE_FIELDS = (["valid", "basin", "hour", "lead", "method", "referee", "n", "ae", "bias", "se", "n25", "ae25", "bias25"]
                + ["%s%d" % (k, t) for t in (34, 48, 64) for k in "hfm"]
                + ["t%d%s" % (t, k) for t in (34, 48, 64) for k in "hmf"] + ["pk_n", "pk_sum", "pk_abs"])
CHANCE_FIELDS = (["valid", "basin", "hour", "lead", "referee", "thr", "n", "events", "bs"]
                 + ["n%d" % i for i in range(10)] + ["e%d" % i for i in range(10)] + ["p%d" % i for i in range(10)])

LOWBIN_FIELDS = (["valid", "basin", "hour", "lead", "referee", "thr"] + ["n%d" % i for i in range(4)]
                 + ["e%d" % i for i in range(4)] + ["p%d" % i for i in range(4)])

# WMO buoy blocks: a 5-digit station in one of these is a buoy, any other 5-digit one a ship or platform
BUOY_BLOCKS = {"13", "15", "21", "22", "23", "31", "32", "41", "42", "44", "45", "46", "48", "51", "52", "61", "62", "63", "64"}


def charnock(spd_ms, z_from, z_to=10.0, alpha=0.011, nu=1.5e-5, k=0.4, g=9.81):
    """Factor taking a wind measured at z_from metres to z_to (log profile, Charnock roughness)."""
    s = np.maximum(spd_ms, 0.5)
    us = s * k / np.log(z_from / 1e-4)
    for _ in range(20):
        z0 = alpha * us ** 2 / g + 0.11 * nu / us
        us = s * k / np.log(z_from / z0)
    return np.log(z_to / z0) / np.log(z_from / z0)


# ------------------------------------------------------------------ truth
def ascat_at(valid):
    """Metop-B/C cells within MAX_DT of the valid time: lat, lon (0-360), ENW kt, |dt| min.
    Cells near 00 UTC come from the end of the day before and the start of the day."""
    lo, hi = valid - dt.timedelta(minutes=MAX_DT), valid + dt.timedelta(minutes=MAX_DT)
    days = sorted({lo.date(), hi.date()})
    parts = []
    for day in days:
        ymd = day.strftime("%Y%m%d")
        t0 = dt.datetime.combine(day, dt.time())
        for s in ("b", "c"):
            u = ASCAT_URL.format(s=s, y=ymd[:4], m=ymd[4:6], d=ymd)
            a = None
            for k in range(6):
                try:
                    with urllib.request.urlopen(u, timeout=120) as r:
                        a = np.frombuffer(gzip.decompress(r.read()), np.uint8).reshape(2, 5, 720, 1440)
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        break
                    time.sleep(2 ** k)
                except Exception:
                    time.sleep(2 ** k)
            if a is None:
                continue
            for p in range(2):
                t, w, rn = a[p, 0], a[p, 1], a[p, 3]
                mins = (t0 - valid).total_seconds() / 60 + t.astype(np.float32) * 6
                ok = (t <= 240) & (w <= 250) & (np.abs(mins) <= MAX_DT) & ((rn & 1) == 0) & ((rn >> 2) < 2)
                iy, ix = np.nonzero(ok)
                parts.append(np.stack([-89.875 + 0.25 * iy, 0.125 + 0.25 * ix, w[iy, ix] * 0.2 * KT, np.abs(mins[iy, ix])], 1))
    return np.concatenate(parts) if parts else None


def gdas_url(ymd, hh, fh):
    import fetch
    return "%s/gdas.%s/%s/atmos/gdas.t%sz.pgrb2.0p25.f%03d" % (fetch.GFS, ymd, hh, hh, fh)


def sample(grid, lats, lons, lat, lon):
    """Bilinear value of a north-first grid at points (lon in any convention)."""
    fy = (lats[0] - np.asarray(lat, float)) / 0.25
    fx = ((np.asarray(lon, float) - lons[0]) % 360) / 0.25
    ny, nx = grid.shape
    y0 = np.clip(np.floor(fy).astype(int), 0, ny - 2); x0 = np.clip(np.floor(fx).astype(int), 0, nx - 2)
    wy = np.clip(fy - y0, 0, 1); wx = np.clip(fx - x0, 0, 1)
    return ((1 - wy) * (1 - wx) * grid[y0, x0] + (1 - wy) * wx * grid[y0, x0 + 1]
            + wy * (1 - wx) * grid[y0 + 1, x0] + wy * wx * grid[y0 + 1, x0 + 1])


def observations(valid, lats, lons, mask):
    """{'buoys': [n, 3], 'ships+buoys': [n, 3]} (lat, lon, kt) within 1 h of the valid time, or None."""
    import pandas as pd
    import fetch
    ymd, hh = valid.strftime("%Y%m%d"), valid.strftime("%H")
    r = fetch.get("%s/gdas.%s/%s/atmos/wdqms/gdas.t%sz.marine.csv" % (fetch.GFS, ymd, hh, hh))
    if r is None:
        return None
    fg = valid - dt.timedelta(hours=6)
    U, V = [], []
    for fh in range(3, 10):
        b = fetch._ncep(gdas_url(fg.strftime("%Y%m%d"), fg.strftime("%H"), fh), fetch.UV)
        if b is None:
            return None
        U.append(b["u"]); V.append(b["v"])
    bl = {l.split()[0] for l in open(os.path.join(HERE, "obs_blacklist.txt")) if l.strip() and not l.startswith("#")}
    d0 = pd.read_csv(io.StringIO(r.text), comment="#", dtype={"Station_id": str})
    d0 = d0[d0.var_id.isin([41, 42]) & (d0.StatusFlag == 0)]
    key = ["Station_id", "yyyymmdd", "HHMMSS", "latitude", "Longitude"]
    d0 = d0.drop_duplicates(key + ["var_id"])
    m = d0[d0.var_id == 41].set_index(key)[["Bg_dep"]].join(d0[d0.var_id == 42].set_index(key)[["Bg_dep"]], how="inner",
                                                             lsuffix="_u", rsuffix="_v").reset_index()
    t = pd.to_datetime(m.yyyymmdd.astype(str) + m.HHMMSS.astype(int).map("{:06d}".format), format="%Y%m%d%H%M%S")
    dth = ((t - valid).dt.total_seconds() / 3600).to_numpy()
    keep = np.abs(dth) <= 1.0
    m, dth = m[keep], dth[keep]
    lat, lon = m.latitude.to_numpy(float), m.Longitude.to_numpy(float)
    fy = (lats[0] - lat) / 0.25; fx = ((lon - lons[0]) % 360) / 0.25
    inside = (fy >= 0) & (fy <= len(lats) - 1) & (fx >= 0) & (fx <= len(lons) - 1)
    lat, lon, h = lat[inside], lon[inside], dth[inside]
    sid = m.Station_id.astype(str).to_numpy()[inside]
    sid = np.array([x[:2] + x[4:] if (len(x) == 7 and x.isdigit() and x[2:4] == "00") else x for x in sid])
    fh = np.clip(h + 3, 0, 6); i0 = np.clip(np.floor(fh).astype(int), 0, 5); wt = fh - i0
    bu = np.array([(1 - wt[j]) * sample(U[i0[j]], lats, lons, lat[j], lon[j]) + wt[j] * sample(U[i0[j] + 1], lats, lons, lat[j], lon[j]) for j in range(len(lat))])
    bv = np.array([(1 - wt[j]) * sample(V[i0[j]], lats, lons, lat[j], lon[j]) + wt[j] * sample(V[i0[j] + 1], lats, lons, lat[j], lon[j]) for j in range(len(lat))])
    ou, ov = bu + m.Bg_dep_u.to_numpy()[inside], bv + m.Bg_dep_v.to_numpy()[inside]
    sea = sample(mask.astype(np.float32), lats, lons, lat, lon) >= 0.99 if len(lat) else np.zeros(0, bool)
    recs = collections.defaultdict(list)
    for j in range(len(lat)):
        if sea[j] and sid[j] not in bl and np.isfinite(ou[j]):
            recs[sid[j]].append(j)
    res = {"buoys": [], "ships+buoys": []}
    for st, jj in recs.items():
        moving = np.ptp(lat[jj]) > 0.05 or np.ptp(lon[jj]) > 0.05
        buoy = st.isdigit() and (len(st) == 7 or st[:2] in BUOY_BLOCKS)
        if st.isdigit() and not buoy:
            continue
        sp = np.hypot(ou[jj].mean(), ov[jj].mean()) * (1.0 if buoy else 0.88)
        rec = (lat[jj].mean(), lon[jj].mean(), sp * charnock(sp, 4.0) * KT)
        res["ships+buoys"].append(rec)
        if buoy and not moving:
            res["buoys"].append(rec)
    return {k: np.array(v).reshape(-1, 3) for k, v in res.items()}


# ------------------------------------------------------------------ scores
def point_scores(fc, ob):
    d = fc - ob
    m25 = (fc >= 25) | (ob >= 25)
    r = dict(n=int(d.size), ae=round(float(np.abs(d).sum()), 2), bias=round(float(d.sum()), 2), se=round(float((d ** 2).sum()), 2),
             n25=int(m25.sum()), ae25=round(float(np.abs(d[m25]).sum()), 2), bias25=round(float(d[m25].sum()), 2))
    for t in (34, 48, 64):
        a, b = fc >= t, ob >= t
        r["h%d" % t], r["f%d" % t], r["m%d" % t] = int((a & b).sum()), int((a & ~b).sum()), int((~a & b).sum())
    return r


class Tiles:
    """5 x 5 degree tiles of a set of scored cells; tiles with fewer than TILE_MIN cells drop out."""

    def __init__(self, lats, lons, r, c):
        key = (np.floor(lats[r] / 5) * 1000 + np.floor((lons[c] % 360) / 5)).astype(int)
        _, self.inv = np.unique(key, return_inverse=True)
        self.nt = self.inv.max() + 1 if len(self.inv) else 0
        self.ok = np.bincount(self.inv, minlength=self.nt) >= TILE_MIN

    def tmax(self, v):
        out = np.full(self.nt, -np.inf)
        np.maximum.at(out, self.inv, v)
        return out[self.ok]

    def scores(self, fc, ob):
        fm, om = self.tmax(fc), self.tmax(ob)
        r = {}
        for t in (34, 48, 64):
            a, b = fm >= t, om >= t
            r["t%dh" % t], r["t%dm" % t], r["t%df" % t] = int((a & b).sum()), int((~a & b).sum()), int((a & ~b).sum())
        k = (fm >= 34) | (om >= 34)
        r.update(pk_n=int(k.sum()), pk_sum=round(float((fm - om)[k].sum()), 2), pk_abs=round(float(np.abs(fm - om)[k].sum()), 2))
        return r


def core_event(r, c, kt, shape):
    """Where ASCAT sees 48+ kt within about 50 km of each scored ASCAT cell (r, c, real 10 m kt): the core
    model's training target (research core/code/ascat_target.py: ASCAT on the grid, -1 where unseen, then
    maximum_filter(size=(5, 7)) >= 48 at the cells ASCAT saw). Returns a bool per cell."""
    from scipy import ndimage
    A = np.full(shape, -1.0, np.float32)
    A[r, c] = kt
    return ndimage.maximum_filter(A, size=(5, 7))[r, c] >= 48


def chance_rows(base, items):
    """items: {thr label: (chance 0-1 at the scored points, event bool at those points)}."""
    out = []
    for t, (pp, e) in items.items():
        pp, e = np.asarray(pp, float), np.asarray(e, bool)
        b = np.minimum((pp * 10).astype(int), 9)
        row = dict(base, thr=t, n=int(e.size), events=int(e.sum()), bs=round(float(((pp - e) ** 2).sum()), 3))
        for i in range(10):
            s = b == i
            row["n%d" % i], row["e%d" % i], row["p%d" % i] = int(s.sum()), int(e[s].sum()), round(float(pp[s].sum()), 3)
        out.append(row)
    return out


def lowbin_rows(base, items):
    """The chances under 10% in bins [0,1), [1,2), [2,5), [5,10) percent: count, events, sum of chances (0-1)."""
    out = []
    for t, (pp, e) in items.items():
        pc, e = np.asarray(pp, float) * 100.0, np.asarray(e, bool)
        row = dict(base, thr=t)
        for i in range(4):
            s = (pc >= LOW_EDGES[i]) & (pc < LOW_EDGES[i + 1])
            row["n%d" % i], row["e%d" % i], row["p%d" % i] = int(s.sum()), int(e[s].sum()), round(float(pc[s].sum() / 100.0), 4)
        out.append(row)
    return out


def run(valid_ymd, basin, hour=None):
    os.environ["MARINE_DOMAIN"] = basin
    sys.path.insert(0, PIPE)
    sys.path.insert(0, HERE)
    import build, fetch, record, storm
    import storm_verify as sv
    from domain import LATS, LONS
    hour = HOUR[basin] if hour is None else int(hour)
    hh = "%02d" % hour
    valid = dt.datetime.strptime(valid_ymd + hh, "%Y%m%d%H")
    g = fetch._ncep(gdas_url(valid_ymd, hh, 0), dict(fetch.UVP, **{"LAND:surface": "land", "ICEC:surface": "ice",
                                                                 "TMP:2 m above ground": "t2", "TMP:surface": "skt"}))
    e = fetch.ec_det("ifs", valid_ymd, hh, 0)
    if g is None or e is None:
        raise SystemExit("analyses for %s %sZ not on AWS" % (valid_ymd, hh))
    truth = {"gdas": np.hypot(g["u"], g["v"]) * KT, "ifs": np.hypot(e["u"], e["v"]) * KT}
    truth["analysis"] = (truth["gdas"] + truth["ifs"]) / 2
    mask = (g["land"] < 0.01) & ~(np.nan_to_num(g["ice"]) > 0.15)
    anl_lows = storm.lows((g["msl"] + e["msl"]) / 200.0, 1005.0)
    ar, ac = np.nonzero(mask)
    tiles_grid = Tiles(LATS, LONS, ar, ac)
    asc = sv.ascat_on_grid(ascat_at(valid), LATS, LONS, mask, g["t2"] - g["skt"])
    tiles_asc = Tiles(LATS, LONS, asc[0], asc[1]) if asc is not None and len(asc[0]) else None
    try:
        obs = observations(valid, LATS, LONS, mask)
    except Exception as x:
        print("observations unavailable: %s" % x, flush=True)
        obs = None
    print("%s %sZ %s: ASCAT %d cells, buoys %s, ships+buoys %s, analysed lows %d" % (
        valid_ymd, hh, basin, 0 if asc is None else len(asc[0]), "-" if obs is None else len(obs["buoys"]),
        "-" if obs is None else len(obs["ships+buoys"]), len(anl_lows)), flush=True)

    scores, chances, lowbins, storms = [], [], [], []
    for lead in STEPS:
        cyc = valid - dt.timedelta(hours=lead)
        try:
            vals, stats, extra = record.load_or_build(cyc.strftime("%Y%m%d") + hh, lead)
        except Exception as ex:
            print("  +%dh: build failed (%s)" % (lead, ex), flush=True)
            continue
        fc = {"windcore": vals["windcore"], "blend": vals["wind"], "nomem": vals["nomem"],
              "mean3": (vals["gfs"] + vals["ecmwf"] + vals["aifs"]) / 3,
              "gfs": vals["gfs"], "ecmwf": vals["ecmwf"], "aifs": vals["aifs"]}
        fc.update({k: v for k, v in extra.items() if v is not None})
        if stats.get("nomem_runs", 0) < 9:      # as on the page, but scored only with all 9 runs, as tested
            fc.pop("nomem")
        # chance label -> (chance 0-1 grid, threshold kt of its event); "core" is handled apart (ASCAT only)
        P = {34: (vals["p34"] / 100.0, 34), 48: (vals["p48"] / 100.0, 48), 64: (vals["p64"] / 100.0, 64)}
        for t in (48, 64):
            if vals.get("p%draw" % t) is not None:
                P["%draw" % t] = (vals["p%draw" % t] / 100.0, t)
        core = vals["core"] / 100.0 if stats.get("core_model") and vals.get("core") is not None else None
        # as storm.core_grid: the model only runs where the blend is 28+ kt or a model 34+ kt (open water is already in the scored cells)
        cand = (vals["wind"] >= 28) | (np.maximum(np.maximum(vals["gfs"], vals["ecmwf"]), vals["aifs"]) >= 34)
        base = dict(valid=valid_ymd, basin=basin, hour=hour, lead=lead)
        refs = {k: (truth[k][ar, ac], ar, ac, tiles_grid) for k in GRID_REFS}
        if tiles_asc is not None:
            refs["ascat"] = (asc[2], asc[0], asc[1], tiles_asc)
        for ref, (ob, r, c, tl) in refs.items():
            for name in METHODS:
                if name in fc:
                    f = fc[name][r, c]
                    scores.append(dict(base, method=name, referee=ref, **point_scores(f, ob), **tl.scores(f, ob)))
            items = {t: (p[r, c], ob >= thr) for t, (p, thr) in P.items()}
            if ref == "ascat" and core is not None:     # defined against ASCAT only, on the model's candidate cells
                k = cand[r, c]
                items["core"] = (core[r, c][k], core_event(r, c, ob, core.shape)[k])
            chances += chance_rows(dict(base, referee=ref), items)
            lowbins += lowbin_rows(dict(base, referee=ref), items)
        for ref in ("buoys", "ships+buoys"):
            if obs is None or not len(obs[ref]):
                continue
            o = obs[ref]
            for name in METHODS:
                if name in fc:
                    scores.append(dict(base, method=name, referee=ref, **point_scores(sample(fc[name], LATS, LONS, o[:, 0], o[:, 1]), o[:, 2])))
            items = {t: (np.clip(sample(p, LATS, LONS, o[:, 0], o[:, 1]), 0, 1), o[:, 2] >= thr) for t, (p, thr) in P.items()}
            chances += chance_rows(dict(base, referee=ref), items)
            lowbins += lowbin_rows(dict(base, referee=ref), items)
        if stats.get("core_model"):
            f = {"wind": vals["wind"], "windcore": vals["windcore"], "hazard": vals["hazard"].astype(np.uint8)}
            if asc is not None:
                storms += sv.rows_for(valid_ymd, basin, lead, "ascat", asc[2], asc[0], asc[1], f, LATS, LONS)
            storms += sv.rows_for(valid_ymd, basin, lead, "analysis", truth["analysis"][ar, ac], ar, ac, f, LATS, LONS)
            storms.append(sv.track_row(valid_ymd, basin, lead, stats.get("lows", []), anl_lows, LATS, LONS, storm))
        print("  +%dh ok (%s)" % (lead, ", ".join(k for k in METHODS if k in fc)), flush=True)
    for r in storms:
        r["hour"] = hour
    return scores, chances, lowbins, storms


def write(path, fields, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valid", required=True, help="YYYYMMDD")
    ap.add_argument("--basin", required=True, choices=sorted(HOUR))
    ap.add_argument("--hour", type=int, choices=HOURS, help="valid hour UTC (default: the basin's HOUR, natl 12, npac 0)")
    ap.add_argument("--out", required=True, help="directory for the CSVs")
    a = ap.parse_args()
    t0 = time.time()
    hour = HOUR[a.basin] if a.hour is None else a.hour
    scores, chances, lowbins, storms = run(a.valid, a.basin, hour)
    if not scores:
        sys.exit("no forecasts scored for %s %s %02dZ" % (a.valid, a.basin, hour))
    os.makedirs(a.out, exist_ok=True)
    tag = "%s_%s_%02d" % (a.valid, a.basin, hour)
    write(os.path.join(a.out, "scores_%s.csv" % tag), SCORE_FIELDS, scores)
    write(os.path.join(a.out, "chances_%s.csv" % tag), CHANCE_FIELDS, chances)
    write(os.path.join(a.out, "lowbins_%s.csv" % tag), LOWBIN_FIELDS, lowbins)
    import storm_verify as sv
    write(os.path.join(a.out, "storm_%s.csv" % tag), sv.FIELDS[:3] + ["hour"] + sv.FIELDS[3:], storms)
    print("%s: %d score rows, %d chance rows, %d low-bin rows, %d storm rows in %.0f s" % (tag, len(scores), len(chances), len(lowbins), len(storms), time.time() - t0))


if __name__ == "__main__":
    main()
