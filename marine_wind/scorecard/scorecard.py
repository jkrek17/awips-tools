"""Model scorecard for the marine wind page: how GFS, ECMWF and AIFS have handled
the pattern lately, for the North Atlantic and the North Pacific. For awareness
only; it does not feed the blend (a winter 2025-26 hindcast found that a model's
recent skill adds nothing beyond its season-long ranking).

For one 12 UTC valid day it fetches the GFS and IFS analyses and the 12 UTC runs
of each model from 1 to 5 days earlier (AWS open-data mirrors), and scores, by
basin, model and lead:

  sea-level pressure (the high-seas box the blend was tested on, 30-67N, 0.25 deg;
               not the page's wider OPC chart area, so it stays comparable with the
               winter hindcast; truth = mean of the GFS and IFS analyses)
    msl_rmse   cos-latitude weighted RMSE, hPa
    lows       each analysed low < 1000 hPa is matched to the nearest forecast low
               within 800 km: low_n analysed, low_hit matched, pos_sum km and
               dp_sum hPa (forecast minus analysed central pressure) over matches
    h/f/m34,48 10 m wind hits, false alarms and misses at 34 and 48 kt, open
               ice-free water, against the same analysis mean
  500 mb height (basin plus upstream, 1.5 deg)
    z_acc      anomaly correlation (centred, cos-latitude weighted) against the
               ERA5 1990-2019 climatology in z500_clim.npz
    z_rmse     RMSE, m

    python3 scorecard.py --valid 20261013 --scores scores.json   # add one day
    python3 scorecard.py --backfill 30 --scores scores.json      # the last 30 days
scores.json keeps the newest KEEP_DAYS valid days.
"""
import argparse
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import eccodes
import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "pipeline"))
import fetch  # noqa: E402  (get, _ec_base, _ec_records, gfs_url)

KT = 1.94384
MODELS = ["GFS", "ECMWF", "AIFS"]
LEADS = [24, 48, 72, 96, 120]
KEEP_DAYS = 60
COLS = ["valid", "basin", "model", "lead", "msl_rmse", "z_acc", "z_rmse", "low_n", "low_hit",
        "pos_sum", "dp_sum", "h34", "f34", "m34", "h48", "f48", "m48"]

# Surface fields are kept for a 30-67N band (0.25 deg, all longitudes); 500 mb at
# 1.5 deg for the climatology's 18-82N band.
MSL_N, MSL_S = 67.0, 30.0
BAND = slice(int((90 - MSL_N) * 4), int((90 - MSL_S) * 4) + 1)
CLIM = np.load(os.path.join(HERE, "z500_clim.npz"))
ZLAT = CLIM["lat"]
ZROWS = ((90 - ZLAT) * 4).round().astype(int)          # 0.25 deg rows of the 1.5 deg grid
ZCOLS = np.arange(0, 1440, 6)

BASINS = {
    # sea-level pressure box (west, east, degrees east, kept continuous); 500 mb box
    "natl": dict(msl=(285.0, 359.75), z=(25.5, 75.0, 228.0, 370.5)),
    "npac": dict(msl=(160.0, 245.0), z=(25.5, 75.0, 99.0, 250.5)),
}

# Winter 2025-26 hindcast, North Atlantic, same box, truth and metric (151 runs):
# shown on the page as a reference line for the sea-level pressure error.
REFERENCE = {"natl": {"label": "Winter 2025-26 hindcast (151 runs)",
                      "msl_rmse": {"GFS": [0.92, 1.67, 2.68, 4.01, 5.48],
                                   "ECMWF": [0.79, 1.36, 2.26, 3.34, 4.75],
                                   "AIFS": [0.73, 1.25, 2.01, 2.94, 4.14]}}}


# ------------------------------------------------------------------ fetching
def decode(blob):
    """GRIB2 message -> global 0.25 deg array, north first, lon 0..359.75."""
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
    if lon0 > 100:   # ECMWF open data starts at -180
        v = np.roll(v, ni // 2, axis=1)
    return v


def keep(name, g):
    """Trim a global field to what is scored."""
    if name == "z":
        return g[ZROWS][:, ZCOLS]
    return g[BAND]


def gfs(ymd, fh, land=False):
    url = fetch.gfs_url(ymd, "12", fh)
    r = fetch.get(url + ".idx")
    if r is None:
        return None
    lines = [l.split(":") for l in r.text.splitlines() if l.strip()]
    idx = {}
    for i, f in enumerate(lines):
        end = int(lines[i + 1][1]) - 1 if i + 1 < len(lines) else None
        idx.setdefault(f[3] + ":" + f[4], (int(f[1]), end))
    want = {"PRMSL:mean sea level": "msl", "HGT:500 mb": "z", "UGRD:10 m above ground": "u",
            "VGRD:10 m above ground": "v"}
    if land:
        want.update({"LAND:surface": "land", "ICEC:surface": "ice"})
    out = {}
    for key, name in want.items():
        if key not in idx:
            return None
        out[name] = keep(name, decode(fetch.get(url, idx[key]).content))
    return out


def ec(model, ymd, step):
    base = fetch._ec_base(model, "oper", "fc", ymd, "12", step)
    recs = fetch._ec_records(base)
    if recs is None:
        return None
    pick = {("sfc", "msl"): "msl", ("sfc", "10u"): "u", ("sfc", "10v"): "v", ("pl", "gh"): "z"}
    if not any(r["param"] == "gh" and r.get("levelist") == "500" for r in recs):
        pick[("pl", "z")] = "z"          # older AIFS runs carry geopotential only
    out = {}
    for r in recs:
        k = (r.get("levtype"), r["param"])
        if k in pick and (k[0] == "sfc" or r.get("levelist") == "500"):
            v = decode(fetch.get(base + ".grib2", (r["_offset"], r["_offset"] + r["_length"] - 1)).content)
            out[pick[k]] = keep(pick[k], v / 9.80665 if r["param"] == "z" else v)
    return out if len(out) == 4 else None


def model_run(model, ymd, step):
    if model == "GFS":
        return gfs(ymd, step)
    return ec("ifs" if model == "ECMWF" else "aifs-single", ymd, step)


# ------------------------------------------------------------------ scoring
def cols(lon0, lon1, res):
    """Column indices (into a 0..360 grid of spacing res) for lon0..lon1, wrapping."""
    return (np.round(np.arange(lon0, lon1 + res / 2, res) / res).astype(int)) % int(round(360 / res))


def hav(la1, lo1, la2, lo2):
    p1, p2 = np.deg2rad(la1), np.deg2rad(la2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.deg2rad(lo2 - lo1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def lows(msl, lats, lons, thr):
    """Minima of lightly smoothed MSLP below thr, at least ~500 km apart, away from the edge."""
    s = ndimage.gaussian_filter(msl, 1.5)
    yy, xx = np.where((s == ndimage.minimum_filter(s, size=19, mode="nearest")) & (s < thr))
    k = (yy > 3) & (yy < s.shape[0] - 4) & (xx > 3) & (xx < s.shape[1] - 4)
    return [(lats[y], lons[x], float(msl[max(y - 2, 0):y + 3, max(x - 2, 0):x + 3].min())) for y, x in zip(yy[k], xx[k])]


def tri(fc, ob, th, mask):
    f, o = (fc >= th) & mask, (ob >= th) & mask
    return int(np.sum(f & o)), int(np.sum(f & ~o)), int(np.sum(~f & o))


def score_basin(basin, fc, an, mask):
    B = BASINS[basin]
    c = cols(B["msl"][0], B["msl"][1], 0.25)
    lats = np.linspace(MSL_N, MSL_S, BAND.stop - BAND.start)
    lons = np.arange(B["msl"][0], B["msl"][1] + 0.125, 0.25)
    w = np.cos(np.deg2rad(lats))[:, None] * np.ones(len(c))
    fm, am = fc["msl"][:, c] / 100.0, an["msl"][:, c] / 100.0
    row = dict(msl_rmse=float(np.sqrt(np.sum(w * (fm - am) ** 2) / w.sum())))

    al, fl = lows(am, lats, lons, 1000.0), lows(fm, lats, lons, 1012.0)
    row.update(low_n=len(al), low_hit=0, pos_sum=0.0, dp_sum=0.0)
    for la, lo, p in al:
        if not fl:
            break
        d = np.array([hav(la, lo, a, b) for a, b, _ in fl])
        j = int(np.argmin(d))
        if d[j] <= 800:
            row["low_hit"] += 1; row["pos_sum"] += float(d[j]); row["dp_sum"] += fl[j][2] - p

    fs = np.hypot(fc["u"][:, c], fc["v"][:, c]) * KT
    asp = np.hypot(an["u"][:, c], an["v"][:, c]) * KT
    m = mask[:, c]
    row["h34"], row["f34"], row["m34"] = tri(fs, asp, 34, m)
    row["h48"], row["f48"], row["m48"] = tri(fs, asp, 48, m)

    s, n, w0, e0 = B["z"]
    ry = np.where((ZLAT <= n + 0.01) & (ZLAT >= s - 0.01))[0]
    cz = cols(w0, e0, 1.5)
    doy = min(int(dt.datetime.strptime(an["valid"], "%Y%m%d").strftime("%j")), 366)
    clim = CLIM["z"][doy - 1][ry][:, cz].astype(np.float32)
    fz, az = fc["z"][ry][:, cz], an["z"][ry][:, cz]
    wz = np.cos(np.deg2rad(ZLAT[ry]))[:, None] * np.ones(len(cz))
    fa, aa = fz - clim, az - clim
    fa = fa - np.sum(wz * fa) / wz.sum(); aa = aa - np.sum(wz * aa) / wz.sum()
    row["z_acc"] = float(np.sum(wz * fa * aa) / np.sqrt(np.sum(wz * fa * fa) * np.sum(wz * aa * aa)))
    row["z_rmse"] = float(np.sqrt(np.sum(wz * (fz - az) ** 2) / wz.sum()))
    return row


def day(valid):
    """All rows for one 12 UTC valid day, or [] if the analyses are not out yet."""
    g, e = gfs(valid, 0, land=True), ec("ifs", valid, 0)
    if g is None or e is None:
        print("no analyses for", valid, flush=True)
        return []
    an = {k: (g[k] + e[k]) / 2 for k in ("msl", "z", "u", "v")}
    an["valid"] = valid
    mask = (g["land"] < 0.01) & ~(np.nan_to_num(g["ice"]) > 0.15)
    vd = dt.datetime.strptime(valid, "%Y%m%d")
    jobs = [(m, (vd - dt.timedelta(hours=L)).strftime("%Y%m%d"), L) for m in MODELS for L in LEADS]
    with ThreadPoolExecutor(6) as ex:
        runs = list(ex.map(lambda j: model_run(*j), jobs))
    rows = []
    for (m, _, L), fc in zip(jobs, runs):
        if fc is None:
            print("missing", m, L, "for", valid, flush=True)
            continue
        for basin in BASINS:
            r = dict(valid=valid, basin=basin, model=m, lead=L)
            r.update(score_basin(basin, fc, an, mask))
            rows.append(r)
    return rows


# ------------------------------------------------------------------ the file
def load(path):
    if path and os.path.exists(path):
        d = json.load(open(path))
        return [dict(zip(d["cols"], r)) for r in d["rows"]]
    return []


def save(path, rows):
    days = sorted({r["valid"] for r in rows})[-KEEP_DAYS:]
    rows = sorted((r for r in rows if r["valid"] in days),
                  key=lambda r: (r["valid"], r["basin"], MODELS.index(r["model"]), r["lead"]))
    rnd = lambda v: round(v, 3) if isinstance(v, float) else v
    out = dict(updated=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
               models=MODELS, leads=LEADS, basins=list(BASINS), reference=REFERENCE,
               cols=COLS, rows=[[rnd(r[c]) for c in COLS] for r in rows])
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("wrote", path, len(rows), "rows,", len(days), "days", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--valid", help="YYYYMMDD (12 UTC) to score; default today")
    ap.add_argument("--backfill", type=int, help="score this many days ending at --valid")
    ap.add_argument("--scores", required=True, help="scores.json to update (created if missing)")
    a = ap.parse_args()
    end = dt.datetime.strptime(a.valid, "%Y%m%d") if a.valid else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    days = [(end - dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((a.backfill or 1) - 1, -1, -1)]
    rows = load(a.scores)
    for d in days:
        new = day(d)
        if new:
            rows = [r for r in rows if r["valid"] != d] + new
            print(d, len(new), "rows", flush=True)
    if rows:
        save(a.scores, rows)


if __name__ == "__main__":
    main()
