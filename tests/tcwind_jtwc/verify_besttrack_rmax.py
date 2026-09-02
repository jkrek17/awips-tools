#!/usr/bin/env python3
"""Verify the tool's Rmax estimate against real JTWC best-track data.

TCWind_JTWC.py never gets an observed Rmax from a real-time warning -
JTWC doesn't report one operationally. The tool falls back to the
Willoughby (2006) regression, clamped below 0.7x the smallest reported
wind-radius quadrant whenever the storm's intensity exceeds a reported
threshold. The code's own comment is candid that this is a guess: "tuned
to Atlantic climatology and routinely disagrees with the radii in the
same bulletin for small WestPac systems." This script checks that claim
against something the real-time bulletin never has access to: JTWC's own
POST-SEASON best-track RMW, from IBTrACS.

This does not run the real parser - best-track records aren't warning
bulletins, so there is nothing to feed parseJTWC(). Instead it builds a
Snapshot directly from IBTrACS' own JTWC-sourced (agency "jtwc_wp")
position/intensity/wind-radii fields and calls resolveRmax()/
willoughbyRmax() exactly as the tool would, then compares to IBTrACS'
own USA_RMW for the same record. That is a genuine, independent check of
the tool's physical assumption - not a parser test, and not circular
(RMW is never one of the inputs).

Usage:
    python3 verify_besttrack_rmax.py [path/to/ibtracs.csv]

Downloads the NCEI IBTrACS "last 3 years" WMO CSV to a cache file if no
path is given and none is cached yet (~10 MB,
https://www.ncei.noaa.gov/data/international-best-track-archive-for-
climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.last3years.list.v04r01.csv).
"""
import csv
import math
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                 "GFE", "procedures"))
import TCWind_JTWC as tc

IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-"
               "archive-for-climate-stewardship-ibtracs/v04r01/access/csv/"
               "ibtracs.last3years.list.v04r01.csv")
CACHE = "/tmp/claude-0/-home-user-awips-tools/738f763c-b8e3-58a4-9745-13d9f53ffc1b/scratchpad/ibtracs_last3.csv"

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


def build_record(row):
    if row["BASIN"] != "WP" or row["USA_AGENCY"].strip() != "jtwc_wp":
        return None
    vmax = to_float(row["USA_WIND"])
    rmw = to_float(row["USA_RMW"])
    lat = to_float(row["USA_LAT"]) or to_float(row["LAT"])
    lon = to_float(row["USA_LON"]) or to_float(row["LON"])
    if vmax is None or rmw is None or rmw <= 0 or lat is None or lon is None:
        return None

    radii = {}
    for thresh in (64, 50, 34):
        vals = {}
        any_present = False
        for q in QUADS:
            v = to_float(row["USA_R%d_%s" % (thresh, q)])
            if v is not None:
                any_present = True
                vals[q] = v
            else:
                vals[q] = 0.0
        if any_present:
            radii[thresh] = vals

    return {
        "sid": row["SID"], "name": row["NAME"], "season": row["SEASON"],
        "iso_time": row["ISO_TIME"], "lat": lat, "lon": lon,
        "vmax": vmax, "rmw": rmw, "radii": radii,
    }


def stats(pairs):
    """pairs: list of (estimate, truth). Returns bias, MAE, RMSE, r."""
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
        print("  %-28s (no records)" % label)
        return
    print("  %-28s n=%-5d bias=%+6.1f nm  MAE=%5.1f nm  RMSE=%5.1f nm  r=%.2f"
          % (label, s["n"], s["bias"], s["mae"], s["rmse"], s["r"]))


def category(vmax):
    if vmax < 34:
        return "TD (<34kt)"
    if vmax < 64:
        return "TS (34-63kt)"
    return "TY+ (64kt+)"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE
    records = [rec for row in load_rows(path)
               if (rec := build_record(row)) is not None]
    print("%d usable JTWC best-track records (WP basin, RMW present)\n"
          % len(records))

    willoughby_only = []
    clamped = []
    by_cat_clamped = {}
    clamp_bound = []
    clamp_not_bound = []

    for rec in records:
        snap = tc.Snapshot()
        snap.lat, snap.lon, snap.vmax = rec["lat"], rec["lon"], rec["vmax"]
        snap.radii = rec["radii"]

        w = tc.willoughbyRmax(snap.vmax, snap.lat)
        c = tc.resolveRmax(snap, 0.0)

        willoughby_only.append((w, rec["rmw"]))
        clamped.append((c, rec["rmw"]))
        by_cat_clamped.setdefault(category(rec["vmax"]), []).append((c, rec["rmw"]))
        if c < w - 1e-6:
            clamp_bound.append((c, rec["rmw"]))
        else:
            clamp_not_bound.append((c, rec["rmw"]))

    print("Willoughby (2006) regression alone, vs JTWC best-track RMW:")
    fmt("all records", stats(willoughby_only))

    print("\nTool's actual resolveRmax() (regression, clamped by radii "
          "when reported), vs JTWC best-track RMW:")
    fmt("all records", stats(clamped))
    print()
    for cat in ("TD (<34kt)", "TS (34-63kt)", "TY+ (64kt+)"):
        fmt(cat, stats(by_cat_clamped.get(cat, [])))

    print("\nSplit by whether the radii clamp actually changed the estimate:")
    fmt("clamp bound (radii used)", stats(clamp_bound))
    fmt("clamp not bound (regression won)", stats(clamp_not_bound))

    print("\n%d of %d records (%.0f%%) had the clamp bind - i.e. the radii "
          "in the bulletin, not the Atlantic-tuned regression, actually "
          "determined the tool's Rmax most of the time this data is used."
          % (len(clamp_bound), len(records),
             100.0 * len(clamp_bound) / len(records) if records else 0))


if __name__ == "__main__":
    main()
