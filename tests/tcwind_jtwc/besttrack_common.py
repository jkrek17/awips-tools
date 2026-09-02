"""Shared IBTrACS WestPac loading/record-building for the tcwind_jtwc
verification scripts (verify_besttrack_rmax.py, verify_besttrack_roci.py,
verify_besttrack_holland.py, prep_besttrack_data.py, fit_westpac_rmax.py).
See README.md for what each of those actually checks.
"""
import calendar
import csv
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                 "GFE", "procedures"))
import TCWind_JTWC as tc  # noqa: E402  (needs the sys.path insert above)

IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-"
               "archive-for-climate-stewardship-ibtracs/v04r01/access/csv/"
               "ibtracs.WP.list.v04r01.csv")
CACHE = ("/tmp/claude-0/-home-user-awips-tools/"
         "738f763c-b8e3-58a4-9745-13d9f53ffc1b/scratchpad/ibtracs_wp_full.csv")

QUADS = ["NE", "SE", "SW", "NW"]


def load_rows(path):
    if not os.path.exists(path):
        print("Downloading %s ..." % IBTRACS_URL, file=sys.stderr)
        urllib.request.urlretrieve(IBTRACS_URL, path)
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        next(r)  # units row
        for row in r:
            yield row


def to_float(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def quad_radii(row, thresh):
    """{NE,SE,SW,NW} at one threshold, or None if none of the four were
    reported at all (as opposed to genuinely 0, meaning reported-but-not-
    reached)."""
    vals = {}
    any_present = False
    for q in QUADS:
        v = to_float(row["USA_R%d_%s" % (thresh, q)])
        if v is not None:
            any_present = True
        vals[q] = v or 0.0
    return vals if any_present else None


def quad_stat(row, thresh, fn):
    q = quad_radii(row, thresh)
    if not q:
        return None
    nz = [v for v in q.values() if v > 0]
    return fn(nz) if nz else None


def quad_mean(row, thresh):
    return quad_stat(row, thresh, lambda nz: sum(nz) / len(nz))


def quad_min(row, thresh):
    return quad_stat(row, thresh, min)


class _Pt(object):
    """Minimal duck-typed stand-in for a Tau, for tc._bearing_speed()."""
    def __init__(self, lat, lon, epoch):
        self.lat, self.lon, self.epoch = lat, lon, epoch


def build_storm_records(rows):
    """One storm's IBTrACS rows (already time-sorted) -> a list of record
    dicts: iso, epoch, lat, lon, vmax, rmw, roci, pres, radii (full
    per-quadrant dict per threshold reported), motionDir/motionSpd (filled
    in from consecutive positions, same convention parseJTWC() uses: the
    last point inherits the previous motion), nature (IBTrACS' own storm-
    type flag - "TS" tropical, "ET" extratropical transition, "SS"
    subtropical, "MX" mixture, "DS" disturbance, "NR" not reported) and
    dist2land (km to the nearest coastline, IBTrACS' own field - used to
    check whether the tool's accuracy holds up for landfalling/near-shore
    storms, which is not tested anywhere else in this suite)."""
    recs = []
    for row in rows:
        lat = to_float(row["USA_LAT"]) or to_float(row["LAT"])
        lon = to_float(row["USA_LON"]) or to_float(row["LON"])
        vmax = to_float(row["USA_WIND"])
        if lat is None or lon is None or vmax is None:
            continue
        radii = {}
        for thresh in (64, 50, 34):
            q = quad_radii(row, thresh)
            if q:
                radii[thresh] = q
        epoch = calendar.timegm(
            time.strptime(row["ISO_TIME"], "%Y-%m-%d %H:%M:%S"))
        recs.append({
            "iso": row["ISO_TIME"], "epoch": epoch,
            "lat": lat, "lon": lon, "vmax": vmax,
            "rmw": to_float(row["USA_RMW"]),
            "roci": to_float(row["USA_ROCI"]),
            "pres": to_float(row["USA_PRES"]),
            "radii": radii,
            "nature": (row.get("NATURE") or "").strip(),
            "dist2land": to_float(row.get("DIST2LAND")),
        })

    for i, rec in enumerate(recs):
        if i + 1 < len(recs):
            p1 = _Pt(rec["lat"], rec["lon"], rec["epoch"])
            p2 = _Pt(recs[i + 1]["lat"], recs[i + 1]["lon"], recs[i + 1]["epoch"])
            brg, spd = tc._bearing_speed(p1, p2)
            rec["motionDir"], rec["motionSpd"] = brg, spd
        elif i > 0:
            rec["motionDir"] = recs[i - 1]["motionDir"]
            rec["motionSpd"] = recs[i - 1]["motionSpd"]
        else:
            rec["motionDir"], rec["motionSpd"] = 0.0, 0.0
    return recs


def iter_storms(path, agency="jtwc_wp"):
    """Yields (sid, name, season, rows) - rows grouped by SID, storms in
    file order (which is already time order within IBTrACS)."""
    from collections import OrderedDict
    by_sid = OrderedDict()
    names, seasons = {}, {}
    for row in load_rows(path):
        if row["USA_AGENCY"].strip() != agency:
            continue
        sid = row["SID"]
        by_sid.setdefault(sid, []).append(row)
        names[sid] = row["NAME"]
        seasons[sid] = row["SEASON"]
    for sid, rows in by_sid.items():
        yield sid, names[sid], seasons[sid], rows


def snapshot_from_record(rec):
    """A tc.Snapshot for resolveRmax()/buildVortex(), from one record dict."""
    snap = tc.Snapshot()
    snap.lat, snap.lon, snap.vmax = rec["lat"], rec["lon"], rec["vmax"]
    snap.radii = rec["radii"]
    snap.motionDir = rec.get("motionDir", 0.0) or 0.0
    snap.motionSpd = rec.get("motionSpd", 0.0) or 0.0
    return snap


def stats(pairs):
    """pairs: list of (estimate, truth). Returns bias, MAE, RMSE, r."""
    import math
    n = len(pairs)
    if n == 0:
        return None
    errs = [e - t for e, t in pairs]
    bias = sum(errs) / n
    mae = sum(abs(e) for e in errs) / n
    rmse = math.sqrt(sum(e * e for e in errs) / n)
    ex = [e for e, _ in pairs]
    tx = [t for _, t in pairs]
    mex, mtx = sum(ex) / n, sum(tx) / n
    cov = sum((e - mex) * (t - mtx) for e, t in pairs)
    sde = math.sqrt(sum((e - mex) ** 2 for e in ex))
    sdt = math.sqrt(sum((t - mtx) ** 2 for t in tx))
    r = cov / (sde * sdt) if sde > 0 and sdt > 0 else float("nan")
    return {"n": n, "bias": bias, "mae": mae, "rmse": rmse, "r": r}


def fmt(label, s):
    if s is None:
        print("  %-30s (no records)" % label)
        return
    print("  %-30s n=%-5d bias=%+6.1f nm  MAE=%5.1f nm  RMSE=%5.1f nm  r=%.2f"
          % (label, s["n"], s["bias"], s["mae"], s["rmse"], s["r"]))


def category(vmax):
    if vmax < 34:
        return "TD (<34kt)"
    if vmax < 64:
        return "TS (34-63kt)"
    return "TY+ (64kt+)"
