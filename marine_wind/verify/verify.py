"""Daily verification of the marine wind blend, North Atlantic and North Pacific.

For one 12 UTC valid time (default: today's), the forecasts from the 12 UTC runs 1 to 5 days
earlier (+24 to +120 h) are rebuilt from the AWS open-data mirrors and scored against
  - the GFS + ECMWF IFS analysis mean, and the IFS analysis alone (open, ice-free water)
  - moored buoys, and ships + buoys (GDAS marine monitoring file: 06Z first guess + O-B,
    buoys raised from ~4 m to 10 m, ships scaled 0.88 onto the buoy basis)

Methods scored:
  mean3      plain mean of GFS, ECMWF IFS and AIFS 10 m speeds
  blend      the page: models weighted by member support + min(k x GEFS/ENS spread, 5 kt),
             k = 0.15 at +24 h, 0.25 after (PR #88)
  blend_eq   equal-weight mean + the same boost (the page before PR #88)
  gfs, ecmwf, aifs
Chances P34/P48/P64 from GEFS + ENS + AIFS ENS members are scored with the Brier score.

One CSV row per (valid, basin, lead, method, referee). Usage:
  python3 verify.py --out scores_new.csv [--valid YYYYMMDD]
  python3 verify.py --summary scores.csv --md summary.md
"""
import argparse, csv, collections, datetime as dt, io, json, os, sys, time
import numpy as np
import requests

KT = 1.943844
STEPS = [24, 48, 72, 96, 120]
CAP_KT, SUPPORT_KT = 5.0, 5.0
HERE = os.path.dirname(os.path.abspath(__file__))
GFS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GEFS = "https://noaa-gefs-pds.s3.amazonaws.com"
EC = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
# the page's boxes (pipeline/domain.py); longitudes run on past 360 across the prime meridian
DOMS = {"natl": (67.0, 18.0, 265.0, 370.0), "npac": (67.0, 18.0, 135.0, 245.0)}
CROP = {k: (slice(int((90 - n) * 4), int((90 - s) * 4) + 1), np.arange(int(w * 4), int(e * 4) + 1) % 1440) for k, (n, s, w, e) in DOMS.items()}
LATS = {k: np.linspace(DOMS[k][0], DOMS[k][1], CROP[k][0].stop - CROP[k][0].start) for k in DOMS}
LONS = {k: np.arange(int(DOMS[k][2] * 4), int(DOMS[k][3] * 4) + 1) * 0.25 for k in DOMS}
S = requests.Session()
S.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))


def k_for(step):
    return 0.15 if step <= 24 else 0.25


# ------------------------------------------------------------------ fetch
def get(url, rng=None, tries=7):
    for i in range(tries):
        try:
            h = {"Range": "bytes=%d-%s" % (rng[0], "" if rng[1] is None else rng[1])} if rng else None
            r = S.get(url, headers=h, timeout=120)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (403, 404):
                return None
        except requests.RequestException:
            pass
        time.sleep(min(2 ** i, 20))
    raise RuntimeError("fetch failed " + url)


def decode(blob):
    import eccodes
    h = eccodes.codes_new_from_message(blob)
    try:
        ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
        v = eccodes.codes_get_values(h).reshape(nj, ni).astype(np.float32)
        lat0 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
        lon0 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
    finally:
        eccodes.codes_release(h)
    if lat0 < 0:
        v = v[::-1]
    if lon0 > 100:
        v = np.roll(v, ni // 2, axis=1)
    return {k: v[iy, ix].copy() for k, (iy, ix) in CROP.items()}


def ncep(url, keys):
    r = get(url + ".idx")
    if r is None:
        return None
    lines = [l.split(":") for l in r.text.splitlines() if l.strip()]
    idx = {}
    for i, f in enumerate(lines):
        idx.setdefault(f[3] + ":" + f[4], (int(f[1]), int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else None))
    out = {}
    for k, name in keys.items():
        if k not in idx:
            return None
        b = get(url, idx[k])
        if b is None:
            return None
        out[name] = decode(b.content)
    return out


UV = {"UGRD:10 m above ground": "u", "VGRD:10 m above ground": "v"}


def ec(model, stream, typ, ymd, step, params=("10u", "10v")):
    """[(member, 'u'|'v'|..., {dom: arr})] or None."""
    base = "%s/%s/12z/%s/0p25/%s/%s120000-%dh-%s-%s" % (EC, ymd, model, stream, ymd, step, stream, typ)
    r = get(base + ".index")
    if r is None:
        return None
    recs = [json.loads(l) for l in r.text.splitlines() if l.strip().startswith("{")]
    recs = [x for x in recs if x.get("levtype") == "sfc" and x["param"] in params]
    from concurrent.futures import ThreadPoolExecutor
    def one(x):
        b = get(base + ".grib2", (x["_offset"], x["_offset"] + x["_length"] - 1))
        return None if b is None else (int(x.get("number", 0)), {"10u": "u", "10v": "v"}.get(x["param"], x["param"]), decode(b.content))
    with ThreadPoolExecutor(12) as ex:
        out = list(ex.map(one, recs))
    return None if any(o is None for o in out) else out


def members_uv(rows):
    d = collections.defaultdict(dict)
    for m, n, a in rows:
        d[m][n] = a
    return [d[k] for k in sorted(d)]


def spd(x):
    return {dom: np.hypot(x["u"][dom], x["v"][dom]) * KT for dom in DOMS}


def forecast(cyc, step):
    """{dom: {'speeds': [3,y,x], 'ge': [n,y,x], 'all': [n,y,x]}} or None if incomplete."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        g = ex.submit(ncep, "%s/gfs.%s/12/atmos/gfs.t12z.pgrb2.0p25.f%03d" % (GFS, cyc, step), UV)
        gm = [ex.submit(ncep, "%s/gefs.%s/12/atmos/pgrb2sp25/ge%s.t12z.pgrb2s.0p25.f%03d" % (GEFS, cyc, m, step), UV)
              for m in ["c00"] + ["p%02d" % i for i in range(1, 31)]]
        e = ec("ifs", "oper", "fc", cyc, step)
        a = ec("aifs-single", "oper", "fc", cyc, step)
        ens = ec("ifs", "enfo", "ef", cyc, step)
        aens = (ec("aifs-ens", "enfo", "cf", cyc, step) or []) + (ec("aifs-ens", "enfo", "pf", cyc, step) or [])
        g = g.result(); gm = [x.result() for x in gm]
    if g is None or e is None or a is None or ens is None:
        return None
    gm = [x for x in gm if x is not None]
    if len(gm) < 20:
        return None
    dets = [spd(g), spd(members_uv(e)[0]), spd(members_uv(a)[0])]
    ge = [spd(x) for x in gm] + [spd(x) for x in members_uv(ens)]
    ae = [spd(x) for x in members_uv(aens)]
    out = {}
    for dom in DOMS:
        out[dom] = {"speeds": np.array([d[dom] for d in dets]), "ge": np.array([m[dom] for m in ge])}
        out[dom]["all"] = np.concatenate([out[dom]["ge"], np.array([m[dom] for m in ae])]) if ae else out[dom]["ge"]
        out[dom]["n_aifs_ens"] = len(ae)
    return out


def analysis(ymd):
    g = ncep("%s/gfs.%s/12/atmos/gfs.t12z.pgrb2.0p25.f000" % (GFS, ymd), dict(UV, **{"LAND:surface": "land", "ICEC:surface": "ice"}))
    e = ec("ifs", "oper", "fc", ymd, 0)
    if g is None or e is None:
        return None
    gs, es = spd(g), spd(members_uv(e)[0])
    return {dom: dict(truth=(gs[dom] + es[dom]) / 2, truth_ifs=es[dom],
                      mask=(g["land"][dom] < 0.01) & ~(np.nan_to_num(g["ice"][dom]) > 0.15)) for dom in DOMS}


# ------------------------------------------------------------------ obs
def sample(grid, dom, lat, lon):
    lon = np.asarray(lon, float) % 360
    fy = (LATS[dom][0] - np.asarray(lat, float)) / 0.25; fx = ((lon - LONS[dom][0]) % 360) / 0.25
    ny, nx = grid.shape
    y0 = np.clip(np.floor(fy).astype(int), 0, ny - 2); x0 = np.clip(np.floor(fx).astype(int), 0, nx - 2)
    wy = np.clip(fy - y0, 0, 1); wx = np.clip(fx - x0, 0, 1)
    return ((1 - wy) * (1 - wx) * grid[y0, x0] + (1 - wy) * wx * grid[y0, x0 + 1]
            + wy * (1 - wx) * grid[y0 + 1, x0] + wy * wx * grid[y0 + 1, x0 + 1])


BUOY_BLOCKS = {"13", "21", "22", "31", "32", "41", "42", "44", "45", "46", "48", "61", "62", "63", "64"}


def charnock(spd_ms, z_from, z_to=10.0, alpha=0.011, nu=1.5e-5, k=0.4, g=9.81):
    s = np.maximum(spd_ms, 0.5)
    us = s * k / np.log(z_from / 1e-4)
    for _ in range(20):
        z0 = alpha * us ** 2 / g + 0.11 * nu / us
        us = s * k / np.log(z_from / z0)
    return np.log(z_to / z0) / np.log(z_from / z0)


def observations(ymd):
    """{dom: {'buoys': (lat, lon, kt), 'ships+buoys': (...)}}; status 0, +-1 h, open water, one per station."""
    import pandas as pd
    r = get("%s/gdas.%s/12/atmos/wdqms/gdas.t12z.marine.csv" % (GFS, ymd))
    if r is None:
        return None
    bl = {l.split()[0] for l in open(os.path.join(HERE, "obs_blacklist.txt")) if l.strip() and not l.startswith("#")}
    U, V, L = {d: [] for d in DOMS}, {d: [] for d in DOMS}, {}
    for fh in range(3, 10):
        k = dict(UV, **({"LAND:surface": "land"} if fh == 3 else {}))
        b = ncep("%s/gdas.%s/06/atmos/gdas.t06z.pgrb2.0p25.f%03d" % (GFS, ymd, fh), k)
        if b is None:
            return None
        for d in DOMS:
            U[d].append(b["u"][d]); V[d].append(b["v"][d])
            if "land" in b:
                L[d] = b["land"][d]
    d0 = pd.read_csv(io.StringIO(r.text), comment="#", dtype={"Station_id": str})
    d0 = d0[d0.var_id.isin([41, 42]) & (d0.StatusFlag == 0)]
    key = ["Station_id", "yyyymmdd", "HHMMSS", "latitude", "Longitude"]
    d0 = d0.drop_duplicates(key + ["var_id"])
    m = d0[d0.var_id == 41].set_index(key)[["Bg_dep"]].join(d0[d0.var_id == 42].set_index(key)[["Bg_dep"]], how="inner", lsuffix="_u", rsuffix="_v").reset_index()
    t = pd.to_datetime(m.yyyymmdd.astype(str) + m.HHMMSS.astype(int).map("{:06d}".format), format="%Y%m%d%H%M%S")
    dth = ((t - (dt.datetime.strptime(ymd, "%Y%m%d") + dt.timedelta(hours=12))).dt.total_seconds() / 3600).to_numpy()
    m = m[np.abs(dth) <= 1.0]; dth = dth[np.abs(dth) <= 1.0]
    out = {}
    for dom, (n, s, w, e) in DOMS.items():
        lat, lon = m.latitude.to_numpy(float), m.Longitude.to_numpy(float) % 360
        k = (lat >= s) & (lat <= n) & ((lon - w) % 360 <= e - w)
        lat, lon, h = lat[k], lon[k], dth[k]
        sid = m.Station_id.astype(str).to_numpy()[k]
        sid = np.array([x[:2] + x[4:] if (len(x) == 7 and x.isdigit() and x[2:4] == "00") else x for x in sid])
        fh = np.clip(h + 3, 0, 6); i0 = np.clip(np.floor(fh).astype(int), 0, 5); wt = fh - i0
        bu = np.array([(1 - wt[j]) * sample(U[dom][i0[j]], dom, lat[j:j + 1], lon[j:j + 1])[0] + wt[j] * sample(U[dom][i0[j] + 1], dom, lat[j:j + 1], lon[j:j + 1])[0] for j in range(len(lat))])
        bv = np.array([(1 - wt[j]) * sample(V[dom][i0[j]], dom, lat[j:j + 1], lon[j:j + 1])[0] + wt[j] * sample(V[dom][i0[j] + 1], dom, lat[j:j + 1], lon[j:j + 1])[0] for j in range(len(lat))])
        ou, ov = bu + m.Bg_dep_u.to_numpy()[k], bv + m.Bg_dep_v.to_numpy()[k]
        land = sample(L[dom], dom, lat, lon)
        recs = collections.defaultdict(list)
        for j in range(len(lat)):
            if land[j] <= 0 and sid[j] not in bl and np.isfinite(ou[j]):
                recs[sid[j]].append(j)
        res = {"buoys": [], "ships+buoys": []}
        for st, jj in recs.items():
            moving = np.ptp(lat[jj]) > 0.05 or np.ptp(lon[jj]) > 0.05
            buoy = st.isdigit() and (len(st) == 7 or st[:2] in BUOY_BLOCKS)
            if st.isdigit() and not buoy:
                continue
            u, v = ou[jj].mean(), ov[jj].mean()
            f = 1.0 if buoy else 0.88
            sp = np.hypot(u, v) * f
            sp = sp * charnock(sp, 4.0) * KT
            rec = (lat[jj].mean(), lon[jj].mean(), sp)
            res["ships+buoys"].append(rec)
            if buoy and not moving:
                res["buoys"].append(rec)
        out[dom] = {k: np.array(v).reshape(-1, 3) for k, v in res.items()}
    return out


# ------------------------------------------------------------------ methods and scores
def methods(f, step):
    sp, ge = f["speeds"], f["ge"]
    w = np.array([np.exp(-0.5 * ((ge - s[None]) / SUPPORT_KT) ** 2).mean(0) for s in sp]) + 1e-6
    boost = np.minimum(k_for(step) * ge.std(0), CAP_KT)
    m3 = sp.mean(0)
    return {"blend": (w * sp).sum(0) / w.sum(0) + boost, "blend_eq": m3 + boost, "mean3": m3,
            "gfs": sp[0], "ecmwf": sp[1], "aifs": sp[2]}


FIELDS = ["valid", "basin", "lead", "method", "referee", "n", "n25", "ae25", "bias25", "se",
          "h34", "f34", "m34", "h48", "f48", "m48", "h64", "f64", "m64", "bs34", "bs48", "bs64"]


def score_row(fc, ob, probs):
    m25 = (fc >= 25) | (ob >= 25)
    d = fc - ob
    r = dict(n=int(d.size), n25=int(m25.sum()), ae25=float(np.abs(d[m25]).sum()), bias25=float(d[m25].sum()), se=float((d ** 2).sum()))
    for t in (34, 48, 64):
        a, b = fc >= t, ob >= t
        r["h%d" % t], r["f%d" % t], r["m%d" % t] = int((a & b).sum()), int((a & ~b).sum()), int((~a & b).sum())
        r["bs%d" % t] = "" if probs is None else float(((probs[t] - b) ** 2).sum())
    return r


def run(valid):
    vt = dt.datetime.strptime(valid, "%Y%m%d")
    an = analysis(valid)
    if an is None:
        raise SystemExit("analyses for %s 12Z not on AWS yet" % valid)
    obs = observations(valid)
    rows = []
    for step in STEPS:
        cyc = (vt - dt.timedelta(hours=step)).strftime("%Y%m%d")
        f = forecast(cyc, step)
        if f is None:
            print("skip +%dh (run %s 12Z incomplete)" % (step, cyc), flush=True)
            continue
        for dom in DOMS:
            ms = methods(f[dom], step)
            P = {t: (f[dom]["all"] >= t).mean(0) for t in (34, 48, 64)}
            msk = an[dom]["mask"]
            for name, fc in ms.items():
                for ref in ("analysis", "ifs_analysis"):
                    ob = an[dom]["truth" if ref == "analysis" else "truth_ifs"]
                    rows.append(dict(valid=valid, basin=dom, lead=step, method=name, referee=ref,
                                     **score_row(fc[msk], ob[msk], {t: p[msk] for t, p in P.items()} if name == "blend" else None)))
                if obs is None:
                    continue
                for ref in ("buoys", "ships+buoys"):
                    o = obs[dom][ref]
                    if not len(o):
                        continue
                    fo = sample(fc, dom, o[:, 0], o[:, 1])
                    po = {t: sample(p, dom, o[:, 0], o[:, 1]) for t, p in P.items()} if name == "blend" else None
                    rows.append(dict(valid=valid, basin=dom, lead=step, method=name, referee=ref, **score_row(fo, o[:, 2], po)))
        print("+%dh done" % step, flush=True)
    return rows


# ------------------------------------------------------------------ summary
def summarize(path, md):
    rows = list(csv.DictReader(open(path)))
    if not rows:
        open(md, "w").write("No verification yet.\n")
        return
    last = max(r["valid"] for r in rows)
    lv = dt.datetime.strptime(last, "%Y%m%d")
    periods = [("last 7 days", (lv - dt.timedelta(days=6)).strftime("%Y%m%d")),
               ("last 30 days", (lv - dt.timedelta(days=29)).strftime("%Y%m%d")),
               ("all", "00000000")]
    names = {"natl": "North Atlantic", "npac": "North Pacific"}
    out = ["# Marine wind verification", "", "Through %s 12 UTC. Scores pooled over the period and leads +24 to +120 h unless shown by lead." % last,
           "MAE25: mean absolute error (kt) where forecast or truth is 25+ kt. CSI: hits / (hits + false alarms + misses).",
           "Brier skill: the blend's member chances against the period's base rate (1 perfect, 0 no skill).", ""]
    for dom in ("natl", "npac"):
        for plabel, start in periods:
            sel = [r for r in rows if r["basin"] == dom and r["valid"] >= start]
            if not sel:
                continue
            ndays = len({r["valid"] for r in sel})
            out += ["## %s, %s (%d days)" % (names[dom], plabel, ndays), "",
                    "| method | MAE25 vs analysis | CSI34 | CSI48 | CSI64 | MAE25 vs buoys | CSI34 ships+buoys |", "|---|---|---|---|---|---|---|"]
            for meth in ("blend", "blend_eq", "mean3", "gfs", "ecmwf", "aifs"):
                agg = {}
                for ref in ("analysis", "buoys", "ships+buoys"):
                    rr = [r for r in sel if r["method"] == meth and r["referee"] == ref]
                    agg[ref] = {k: sum(float(r[k]) for r in rr) for k in ("ae25", "n25", "h34", "f34", "m34", "h48", "f48", "m48", "h64", "f64", "m64")} if rr else None
                def csi(a, t):
                    if a is None:
                        return "-"
                    d = a["h%d" % t] + a["f%d" % t] + a["m%d" % t]
                    return "%.3f" % (a["h%d" % t] / d) if d else "-"
                def mae(a):
                    return "%.2f" % (a["ae25"] / a["n25"]) if a and a["n25"] else "-"
                out.append("| %s | %s | %s | %s | %s | %s | %s |" % (meth, mae(agg["analysis"]), csi(agg["analysis"], 34), csi(agg["analysis"], 48),
                                                                   csi(agg["analysis"], 64), mae(agg["buoys"]), csi(agg["ships+buoys"], 34)))
            bss = []
            for t in (34, 48, 64):
                rr = [r for r in sel if r["method"] == "blend" and r["referee"] == "analysis" and r["bs%d" % t] != ""]
                n = sum(float(r["n"]) for r in rr)
                if not n:
                    continue
                base = sum(float(r["h%d" % t]) + float(r["m%d" % t]) for r in rr) / n
                bs = sum(float(r["bs%d" % t]) for r in rr) / n
                bss.append("P%d %.2f" % (t, 1 - bs / (base * (1 - base))) if 0 < base < 1 else "P%d -" % t)
            out += ["", "Brier skill of the chances vs the analysis: " + ", ".join(bss), ""]
    open(md, "w").write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valid", help="YYYYMMDD (12 UTC); default today UTC")
    ap.add_argument("--out", help="CSV to write this day's rows to")
    ap.add_argument("--summary", help="CSV of all rows to summarize")
    ap.add_argument("--md", default="summary.md")
    a = ap.parse_args()
    if a.summary:
        summarize(a.summary, a.md)
        return
    valid = a.valid or dt.datetime.utcnow().strftime("%Y%m%d")
    rows = run(valid)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(len(rows), "rows for", valid)


if __name__ == "__main__":
    main()
