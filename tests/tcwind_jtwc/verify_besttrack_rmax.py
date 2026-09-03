#!/usr/bin/env python3
"""SUPERSEDED CONFIGURATION - kept for provenance, not as a current check.

    Nothing in this script describes the wind field TCWind_JTWC.py builds
    today.  Read the next four paragraphs before quoting a number out of it.

VORTEX_METHOD is now "gtcm".  On that path the radius of maximum wind is not
an input at all: fitGTCM() FITS it (the `rm` it returns) by weighted least
squares on wind error, from a climatological first guess given by Gridded TCM
Users Guide eq. (5), rmw = exp(3.7450 - 0.01338*Vmax + 0.01908*|lat|).
willoughbyRmax() and resolveRmax() play no part in it - _buildVortexGTCM()
takes an `rmax_nm` argument and never reads it.  They still drive the legacy
"perquad" construction, which is still selectable and still exercised by
compare_vortex_methods.py, so they are not dead code; they are just not what
the shipped default uses.

The framing is also wrong, not only the configuration.  This script scores the
tool's Rmax against JTWC's post-season best-track RMW as though the tool were
a forecast competing with nature.  It is not.  Its job is to render a
physically plausible wind field consistent with what one bulletin says, and
under GTCM the internal Rmax is a fitted parameter of that rendering - a
quantity that has no obligation to match a post-season analysis, and is not
independently observable in real time either way.

Kept rather than deleted for one concrete reason: willoughbyRmax()'s docstring
in GFE/procedures/TCWind_JTWC.py cites this file BY NAME as the validation
behind the three regression coefficients still compiled into that function,
and so does web/TCWind_JTWC/Index.html.  Deleting it would leave the shipped
source citing a file that does not exist and those coefficients unauditable.

It also cannot be re-run here: it needs the WestPac IBTrACS CSV, which is not
in this environment.  The numbers it printed are in git history and in
tests/tcwind_jtwc/README.md.

What replaced it: tests/tcwind_jtwc/verify_gtcm.py, which measures ring fit,
field difference, GTCM fit quality and - the point of the switch - the
COHERENCE of the field, and writes tests/tcwind_jtwc/data/gtcm_findings.json.

--- original header follows ------------------------------------------------

Verify the tool's Rmax estimate against real JTWC best-track data.

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

Downloads NCEI IBTrACS' WestPac-basin CSV to a cache file if no path is
given and none is cached yet (~115 MB - it's basin-filtered, not
date-filtered, so the raw file actually goes back to 1945; build_record()
below applies besttrack_common.MIN_SEASON, currently 2005, since that's
where jtwc_wp's R50/R64 reporting - not just RMW - becomes reliable,
https://www.ncei.noaa.gov/data/international-best-track-archive-
for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.WP.list.v04r01.csv).
"""
import csv
import math
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                 "GFE", "procedures"))
import TCWind_JTWC as tc
from besttrack_common import MIN_SEASON

IBTRACS_URL = ("https://www.ncei.noaa.gov/data/international-best-track-"
               "archive-for-climate-stewardship-ibtracs/v04r01/access/csv/"
               "ibtracs.WP.list.v04r01.csv")
CACHE = "/tmp/claude-0/-home-user-awips-tools/738f763c-b8e3-58a4-9745-13d9f53ffc1b/scratchpad/ibtracs_wp_full.csv"

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
    if int(row["SEASON"]) < MIN_SEASON:
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


# The original Atlantic-tuned Willoughby (2006) coefficients, hardcoded here
# (independent of whatever tc.willoughbyRmax() currently uses) so this
# report always shows the "before" picture, even after willoughbyRmax()
# itself gets refit - see fit_westpac_rmax.py.
def atlantic_willoughby_rmax(vmax_kt, lat_deg):
    v_ms = vmax_kt * tc.KT2MS
    return 46.4 * math.exp(-0.0155 * v_ms + 0.0169 * abs(lat_deg)) * tc.KM2NM


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE
    # >= 34kt only: buildFor() in TCWind_JTWC.py now skips any storm-time
    # below tropical storm strength outright (no organized 34kt-or-greater
    # wind field to speak of, essentially never any radii either) rather
    # than build a vortex for it - so scoring the tool against depression-
    # strength records would be scoring it on something it no longer even
    # attempts. See the "TD (<34kt)" row this used to print here.
    records = [rec for row in load_rows(path)
               if (rec := build_record(row)) is not None and rec["vmax"] >= 34]
    print("%d usable JTWC best-track records (WP basin, RMW present, "
          "TS-strength or greater - depressions excluded, the tool no "
          "longer runs on them)\n" % len(records))

    atlantic_only = []
    current_only = []
    current_clamped = []
    by_cat_clamped = {}
    clamp_bound = []
    clamp_not_bound = []

    for rec in records:
        snap = tc.Snapshot()
        snap.lat, snap.lon, snap.vmax = rec["lat"], rec["lon"], rec["vmax"]
        snap.radii = rec["radii"]

        a = atlantic_willoughby_rmax(snap.vmax, snap.lat)
        w = tc.willoughbyRmax(snap.vmax, snap.lat)
        c = tc.resolveRmax(snap, 0.0)

        atlantic_only.append((a, rec["rmw"]))
        current_only.append((w, rec["rmw"]))
        current_clamped.append((c, rec["rmw"]))
        by_cat_clamped.setdefault(category(rec["vmax"]), []).append((c, rec["rmw"]))
        if c < w - 1e-6:
            clamp_bound.append((c, rec["rmw"]))
        else:
            clamp_not_bound.append((c, rec["rmw"]))

    print("Regression alone (no radii clamp), vs JTWC best-track RMW:")
    fmt("original Willoughby (2006)", stats(atlantic_only))
    fmt("currently live in the tool", stats(current_only))

    print("\nTool's actual resolveRmax() (regression, clamped by radii "
          "when reported), vs JTWC best-track RMW:")
    fmt("all records", stats(current_clamped))
    print()
    for cat in ("TS (34-63kt)", "TY+ (64kt+)"):
        fmt(cat, stats(by_cat_clamped.get(cat, [])))

    print("\nSplit by whether the radii clamp actually changed the estimate:")
    fmt("clamp bound (radii used)", stats(clamp_bound))
    fmt("clamp not bound (regression won)", stats(clamp_not_bound))

    print("\n%d of %d records (%.0f%%) had the clamp bind - i.e. the radii "
          "in the bulletin, not the regression, actually determined the "
          "tool's Rmax most of the time this data is used."
          % (len(clamp_bound), len(records),
             100.0 * len(clamp_bound) / len(records) if records else 0))


if __name__ == "__main__":
    main()
