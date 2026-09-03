"""Shared IBTrACS loading/record-building for the tcwind_jtwc
verification and data-prep scripts (verify_besttrack_rmax.py,
verify_besttrack_roci.py, verify_besttrack_holland.py,
prep_besttrack_data.py, fit_westpac_rmax.py).
See README.md for what each of those actually checks.

Originally WestPac-only (JTWC, agency ``jtwc_wp``). It now also handles the
two NHC basins in the same code path, because IBTrACS stores NHC's own
analysis in the very same ``USA_*`` columns that hold JTWC's for WestPac:

    basin  agency        source                     archive window
    -----  ------------  -------------------------  --------------
    WP     jtwc_wp       JTWC best track            2005-2024
    NA     hurdat_atl    NHC HURDAT2 North Atlantic 2004-2024
    EP     hurdat_epa    NHC HURDAT2 East Pacific   2004-2024

The window differs by basin on purpose and the difference is real, not a
rounding of convenience: JTWC R50/R64 reporting only becomes reliable in
2005 (see MIN_SEASON below), whereas NHC R64 reporting is *zero* before
2004 and substantial from 2004 on. Each basin starts at its own first
fully-radii-capable season.
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

_IBTRACS_BASE = ("https://www.ncei.noaa.gov/data/international-best-track-"
                 "archive-for-climate-stewardship-ibtracs/v04r01/access/csv/")


def ibtracs_url(basin):
    return "%sibtracs.%s.list.v04r01.csv" % (_IBTRACS_BASE, basin.upper())


IBTRACS_URL = ibtracs_url("WP")   # kept: WestPac callers import this by name

QUADS = ["NE", "SE", "SW", "NW"]

# ---------------------------------------------------------------------------
# Basin registry
#
# BASIN_AGENCY / AGENCY_BASIN map between the IBTrACS two-letter basin code
# and the USA_AGENCY string whose rows carry that basin's operational
# analysis in the USA_* columns.
BASIN_AGENCY = {"WP": "jtwc_wp", "NA": "hurdat_atl", "EP": "hurdat_epa"}
AGENCY_BASIN = dict((v, k) for k, v in BASIN_AGENCY.items())

# NHC hands storms between its two basins mid-track (and IBTrACS keeps one
# SID across the handoff), so when loading either NHC file we accept rows
# from both NHC agencies and decide the storm's home basin from its own
# BASIN column. Loading strictly by agency would silently truncate the
# handful of crossers.
BASIN_ROW_AGENCIES = {"WP": ("jtwc_wp",),
                      "NA": ("hurdat_atl", "hurdat_epa"),
                      "EP": ("hurdat_epa", "hurdat_atl")}


# ---------------------------------------------------------------------------
# Where the CSVs live.
#
# This used to be a hardcoded absolute path into one particular scratch
# directory, which died the moment that directory did. It is now resolved,
# in order:
#   1. env IBTRACS_<BASIN>   - an explicit full path to one basin's CSV
#   2. env IBTRACS_DIR       - a directory holding ibtracs.<BASIN>.csv
#   3. tests/tcwind_jtwc/data/ibtracs/ibtracs.<BASIN>.csv  (repo-local)
# and every caller can still override it with argv[1] as before.
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IBTRACS_DIR = os.path.join(_HERE, "data", "ibtracs")


def cache_path(basin="WP"):
    """Best guess at the local IBTrACS CSV for one basin. Existence is not
    checked here - load_rows() reports a missing file, with the URL."""
    basin = basin.upper()
    env = os.environ.get("IBTRACS_%s" % basin)
    if env:
        return env
    root = os.environ.get("IBTRACS_DIR") or DEFAULT_IBTRACS_DIR
    return os.path.join(root, "ibtracs.%s.csv" % basin)


# Backwards compatibility: the WestPac scripts import CACHE directly and
# pass it straight to iter_storms(). It is now a live, overridable path
# rather than a dead one, but it is still just a string.
CACHE = cache_path("WP")

# RMW/wind-radii presence before 2001 is essentially zero (checked
# directly: 0 usable RMW records pre-2001 in this agency's data), so that
# part of the old "2001-2024" coverage claim held on its own. But 2001-2004
# specifically has unreliable R50/R64 reporting (25.7% of typhoon-strength
# records had an R64 radius at all, vs. 86-94% from 2005 onward - see
# verify_besttrack_context.py's header) - 15% of the dataset had far less
# for the tool to work with than the rest. Every script here now starts
# at 2005 by default, so "the archive" means the same, fully-radii-capable
# window everywhere: the storm browser sample, the verification stats, and
# the Findings page numbers all agree.
MIN_SEASON = 2005

# Per-basin first season, keyed by basin code. WestPac keeps 2005 (above);
# the NHC basins start at 2004 because NHC's R64 reporting is zero before
# 2004 in both NA and EP and substantial from 2004 onward. Callers that do
# not name a basin still get MIN_SEASON, so nothing WestPac-facing moves.
BASIN_MIN_SEASON = {"WP": MIN_SEASON, "NA": 2004, "EP": 2004}
MAX_SEASON = 2024   # 2025 is still open in IBTrACS v04r01; the archive ends 2024


def load_rows(path, url=IBTRACS_URL, allow_download=True):
    """Stream the data rows of an IBTrACS CSV (the units row is skipped).

    If the file is missing and downloading is permitted, fetch it from
    ``url`` first. Pass allow_download=False to fail loudly instead - which
    is what the data-prep script does, since re-pulling 50 MB from NCEI on a
    typo is worse than an error message."""
    if not os.path.exists(path):
        if not allow_download:
            raise IOError(
                "IBTrACS CSV not found: %s\n"
                "  Point IBTRACS_DIR (or IBTRACS_<BASIN>) at a directory "
                "holding it, or pass the path explicitly.\n"
                "  Source: %s" % (path, url or "(no URL known)"))
        if not url:
            raise IOError("IBTrACS CSV not found and no URL known: %s" % path)
        print("Downloading %s ..." % url, file=sys.stderr)
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        urllib.request.urlretrieve(url, path)
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


def storm_basin(rows):
    """The IBTrACS BASIN of a storm's first row - i.e. where it was born.
    Used instead of adding a 5th element to iter_storms()'s tuple, which
    every existing WestPac caller unpacks by position."""
    for row in rows:
        b = (row.get("BASIN") or "").strip()
        if b:
            return b
    return ""


def storm_agency(rows):
    """The USA_AGENCY that contributed the most rows to this storm."""
    counts = {}
    for row in rows:
        a = (row.get("USA_AGENCY") or "").strip()
        if a:
            counts[a] = counts.get(a, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def iter_storms(path, agency="jtwc_wp", min_season=MIN_SEASON,
                max_season=None, basin=None, allow_download=True):
    """Yields (sid, name, season, rows) - rows grouped by SID, storms in
    file order (which is already time order within IBTrACS).

    agency      a USA_AGENCY string, or any iterable of them. Accepting
                several matters for the NHC files: NHC hands a storm from
                hurdat_atl to hurdat_epa (or back) mid-track under one SID,
                so filtering on a single agency chops the crossers in half.
    min_season  inclusive; defaults to MIN_SEASON (2005). Pass None for the
                full uncapped archive (back to 1945 for jtwc_wp).
    max_season  inclusive; None means no upper bound.
    basin       optional IBTrACS BASIN code ("NA"/"EP"/"WP"). Applied to the
                storm's *first* row, so a storm that crosses out of the
                basin is still yielded whole rather than truncated.

    The season filter is applied per row, but every row of one storm carries
    the same SEASON in IBTrACS, so it is effectively per storm."""
    from collections import OrderedDict
    if isinstance(agency, str):
        agencies = {agency}
    elif agency is None:
        agencies = None
    else:
        agencies = set(agency)

    url = None
    if basin:
        url = ibtracs_url(basin)
    elif agencies and len(agencies) == 1:
        only = list(agencies)[0]
        if only in AGENCY_BASIN:
            url = ibtracs_url(AGENCY_BASIN[only])

    by_sid = OrderedDict()
    names, seasons = {}, {}
    for row in load_rows(path, url=url or IBTRACS_URL,
                         allow_download=allow_download):
        if agencies is not None and row["USA_AGENCY"].strip() not in agencies:
            continue
        season = int(row["SEASON"])
        if min_season and season < min_season:
            continue
        if max_season and season > max_season:
            continue
        sid = row["SID"]
        by_sid.setdefault(sid, []).append(row)
        names.setdefault(sid, row["NAME"])
        seasons.setdefault(sid, row["SEASON"])
    for sid, rows in by_sid.items():
        if basin and storm_basin(rows) != basin:
            continue
        yield sid, names[sid], seasons[sid], rows


def iter_basin_storms(basin, path=None, min_season=None, max_season=MAX_SEASON,
                      allow_download=False):
    """iter_storms() wired up for one named basin: the right agency set, the
    right first season, and the CSV wherever cache_path() finds it.
    Yields (sid, name, season, rows) exactly as iter_storms() does."""
    basin = basin.upper()
    if basin not in BASIN_AGENCY:
        raise ValueError("unknown basin %r (know %s)"
                         % (basin, ", ".join(sorted(BASIN_AGENCY))))
    if path is None:
        path = cache_path(basin)
    if min_season is None:
        min_season = BASIN_MIN_SEASON[basin]
    return iter_storms(path, agency=BASIN_ROW_AGENCIES[basin],
                       min_season=min_season, max_season=max_season,
                       basin=basin, allow_download=allow_download)


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
