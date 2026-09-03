#!/usr/bin/env python3
"""Compare the two vortex constructions in TCWind_JTWC.py.

    "perquad"  per-quadrant radial fit, tangentially interpolated.  Reproduces
               every reported radius exactly, by construction.  NHC's legacy
               TCMWindTool worked this way.

    "gtcm"     NHC's Gridded TCM / WTCM, implemented from the Gridded TCM Users
               Guide v1.9.1: one symmetric modified Rankine vortex with two size
               parameters (eq. 3) plus a wavenumber-1 asymmetry, fit by weighted
               least squares on WIND error (eq. 7).  This is what builds the
               Atlantic/EastPac grids OPC already ingests.

Two questions, answered separately:

  1. RING REPRODUCTION - how far does each construction land from the radii the
     bulletin reported?  Read this one carefully.  GTCM fits to the quadrant
     AVERAGE wind, converting the reported quadrant MAXIMUM with a 0.85 factor
     (guide step 2c), so its rings are expected to sit ~15% inside the reported
     value.  That is the model working as specified, not an error.  Both
     framings are reported below: against the reported radius, and against the
     0.85-scaled radius GTCM actually fits to.

     Neither framing is a skill score.  The tool's job is not to reproduce the
     reported radii - GTCM deliberately does not - it is to render a physically
     plausible field consistent with the bulletin.  How plausible, i.e. how
     free of the kinks and steps the per-quadrant construction has by
     construction, is measured separately in verify_gtcm.py ("coherence").

  2. FIELD DIFFERENCE - how different are the two wind fields a forecaster would
     actually see, in kt and in the 34/50/64 kt areas that drive warnings?  A
     large ring error that moves no isotach area matters less than a small one
     that does.

Runs hermetically against the committed best-track data in ./data; no network,
no IBTrACS CSV.  WestPac comes from besttrack_sample.json (JTWC, 2005-2024),
North Atlantic and East Pacific from archive_storms.json (NHC, 2004-2024).

    python3 compare_vortex_methods.py [--basin WP|NA|EP|all] [--cases N]
                                      [--json OUT.json]

Importable as a library: load_cases(), evaluate() and stats() are what
verify_gtcm.py uses to build tests/tcwind_jtwc/data/gtcm_findings.json, so
there is one implementation of the ring and field numbers, not two.
"""

import argparse
import json
import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "GFE", "procedures"))
import TCWind_JTWC as T  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SAMPLE = os.path.join(DATA, "besttrack_sample.json")
ARCHIVE_INDEX = os.path.join(DATA, "archive_index.json")
ARCHIVE_STORMS = os.path.join(DATA, "archive_storms.json")

BASINS = ("WP", "NA", "EP")
METHODS = ("perquad", "gtcm")
THRESHOLDS = (64, 50, 34)
DEFAULT_SEED = 42

# ---------------------------------------------------------------------------
# T.fitGTCM() is memoised here, keyed on the snapshot's own content.
#
# _buildVortexGTCM() re-fits from scratch on EVERY call - it has no notion
# that ring_errors() below asks it to build the same storm-time's field
# along four different quadrant rays (and field_difference() a fifth time,
# on a full polar grid), and the fit depends only on the snapshot, never on
# the grid it is asked to evaluate on. Measured effect: a 60-case WP
# `evaluate()` run went from ~2.05 s/case to well under 1 s/case with this
# on (see the runtime numbers in tests/tcwind_jtwc/README.md and the
# verify_gtcm.py --out JSON's own generation note). This changes no
# GFE/procedures/TCWind_JTWC.py source - it wraps the function this module
# already imports, so every caller that goes through `T.fitGTCM` (including
# TCWind_JTWC.py's own `_buildVortexGTCM`, which looks the name up in the
# same module namespace this patches) benefits, with no behavior change:
# same inputs, same fit, just not recomputed three or four times over.
_FIT_CACHE = {}
_ORIG_FIT_GTCM = T.fitGTCM


def _snapshot_key(snap):
    radii = tuple(sorted(
        (t, tuple(sorted(v.items()))) for t, v in (snap.radii or {}).items()))
    return (round(float(snap.vmax), 6), round(float(snap.lat), 6),
            round(float(snap.lon), 6), round(float(snap.motionDir or 0.0), 6),
            round(float(snap.motionSpd or 0.0), 6), radii)


def _cached_fit_gtcm(snap):
    key = _snapshot_key(snap)
    fit = _FIT_CACHE.get(key)
    if fit is None:
        fit = _ORIG_FIT_GTCM(snap)
        _FIT_CACHE[key] = fit
    return fit


T.fitGTCM = _cached_fit_gtcm


def clear_fit_cache():
    """Drop every cached fit.

    The cache key is the snapshot's content only - it does not know which
    implementation of T._gtcmProfile is active. verify_gtcm.py's continuity
    diagnostic (coherence_with_continuous_ri()) temporarily swaps that
    function out from under fitGTCM to answer "how much of GTCM's measured
    incoherence is the one eq.(3) line"; without clearing the cache around
    that swap, a snapshot already fit under the normal profile would keep
    returning its stale (wrong-profile) cached fit instead of being re-fit
    under the patched one. Call this immediately before AND after any such
    swap.
    """
    _FIT_CACHE.clear()

# Radial resolution for locating a threshold crossing.  0.2 nm (600/3000) is
# still far finer than any GFE grid and finer than the 5 nm the radii are
# reported at, so it contributes nothing measurable to the numbers below -
# confirmed directly: dropping from 12000 to 3000 steps moves a measured
# crossing radius by <0.01 nm on a sample case, for a ~28x wall-clock win.
# That win matters here specifically because _buildVortexGTCM() re-derives
# its per-azimuth outer-taper radius (a 900-point radial probe) for EVERY
# point of whatever grid it is handed, including a ray built only to locate
# one crossing - so this grid's point count, not fitGTCM's own cost, is what
# dominates a ring_errors() call. Not this module's bug to fix (it is in
# GFE/procedures/TCWind_JTWC.py, which this test suite does not own), so the
# fix here is to stop asking for more radial resolution than the crossing
# search needs.
R_MAX_NM = 600.0
R_STEPS = 3000


def _ray(clat, clon, brg_deg, dists_nm):
    """Great-circle points outward from a centre along one bearing."""
    lat1 = math.radians(clat)
    lon1 = math.radians(clon)
    brg = math.radians(brg_deg)
    d = np.asarray(dists_nm, dtype=float) / T.EARTH_R_NM
    lat2 = np.arcsin(np.sin(lat1) * np.cos(d)
                     + np.cos(lat1) * np.sin(d) * math.cos(brg))
    lon2 = lon1 + np.arctan2(math.sin(brg) * np.sin(d) * np.cos(lat1),
                             np.cos(d) - np.sin(lat1) * np.sin(lat2))
    return np.degrees(lat2), np.degrees(lon2)


def ray_grid(clat, clon, bearings, dists_nm):
    """(nbearing, ndist) lat/lon grids - one great-circle ray per bearing."""
    dists_nm = np.asarray(dists_nm, dtype=float)
    lats = np.empty((len(bearings), len(dists_nm)))
    lons = np.empty_like(lats)
    for i, b in enumerate(bearings):
        la, lo = _ray(clat, clon, float(b), dists_nm)
        lats[i, :] = la
        lons[i, :] = lo
    return lats, lons


def _crossing(radii, mag, threshold):
    """Outermost radius where the profile falls through `threshold`."""
    above = mag[:-1] >= threshold
    below = mag[1:] < threshold
    idx = np.where(above & below)[0]
    if not len(idx):
        return None
    i = idx[-1]
    span = mag[i] - mag[i + 1]
    f = (mag[i] - threshold) / span if span else 0.0
    return float(radii[i] + f * (radii[i + 1] - radii[i]))


def _snapshot(rec):
    s = T.Snapshot()
    s.lat = rec["lat"]
    s.lon = rec["lon"]
    s.vmax = rec["vmax"]
    s.radii = dict((int(k), dict(v)) for k, v in (rec.get("radii") or {}).items())
    s.motionDir = rec.get("motionDir") or 0.0
    s.motionSpd = rec.get("motionSpd") or 0.0
    s.conf = T.CONF_TROPICAL
    s.epoch = rec.get("epoch") or 0
    return s


snapshot = _snapshot          # public alias; _snapshot kept for old callers


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------

def usable(rec):
    """A storm-time this comparison can say anything about.

    Below 34 kt there is no ring to reproduce and no isotach to compare, and
    with no reported radii at all both constructions fall back to the same
    climatological guess, so such records carry no information here.
    """
    return rec.get("vmax", 0) >= 34 and bool(rec.get("radii") or {})


def _load_wp():
    """WestPac storms, from the committed JTWC sample."""
    with open(SAMPLE) as fh:
        storms = json.load(fh)
    return [(s["sid"], s["season"], s["records"]) for s in storms]


def _load_archive(basin):
    """NA/EP storms, from the generated archive files."""
    if not (os.path.exists(ARCHIVE_INDEX) and os.path.exists(ARCHIVE_STORMS)):
        return []
    with open(ARCHIVE_INDEX) as fh:
        index = json.load(fh)
    with open(ARCHIVE_STORMS) as fh:
        storms = json.load(fh)
    out = []
    for e in sorted(index, key=lambda e: e["sid"]):
        if e.get("basin") != basin or e["sid"] not in storms:
            continue
        out.append((e["sid"], e.get("season"), storms[e["sid"]]))
    return out


def load_storms(basin):
    """[(sid, season, [record, ...]), ...] for one basin, or [] if absent.

    WestPac deliberately reads besttrack_sample.json rather than the archive:
    that file is the frozen input the previously published comparison numbers
    were computed from, so this stays reproducible against them.
    """
    if basin == "WP":
        return _load_wp()
    return _load_archive(basin)


def load_cases(basin, limit=None, seed=DEFAULT_SEED):
    """Usable storm-times for one basin, sampled ACROSS storms.

    Seeded round-robin, not file order: storms are shuffled once (seeded, so
    re-running gives the same cases), then cases are drawn one at a time from
    each storm in that shuffled order - every storm's earliest usable record
    first, then every storm's second, and so on - before truncating at
    `limit`. This is deliberately the fix for the failure mode a small
    `--cases` used to have: the old version walked storms in file order and
    simply truncated, so `--cases 24` on WP landed on 2 storms (the first two
    in file order) contributing every one of their usable records before a
    third storm was ever touched, and the equivalent NA/EP runs did the same.
    A caller asking for N cases now gets cases spread across up to N distinct
    storms (fewer only if the basin itself has fewer usable storms than N).

    Still deterministic and still a prefix property: the full round-robin
    order is built once and then sliced, so a larger `limit` is a superset of
    a smaller one, and `seed=None` falls back to storms in load_storms()'s
    own (sid/file) order - the old behavior - for a caller that wants it.
    """
    pools = []
    for sid, _season, recs in load_storms(basin):
        u = [r for r in recs if usable(r)]
        if u:
            pools.append((sid, u))
    order = list(range(len(pools)))
    if seed is not None:
        random.Random(seed).shuffle(order)

    cases = []
    round_idx = 0
    while limit is None or len(cases) < limit:
        added = False
        for oi in order:
            sid, recs = pools[oi]
            if round_idx < len(recs):
                cases.append((sid, recs[round_idx]))
                added = True
                if limit and len(cases) >= limit:
                    break
        if not added:
            break
        round_idx += 1
    return cases


def case_storms(cases):
    """Distinct storm SIDs among a list of (sid, record) cases."""
    return set(sid for sid, _rec in cases)


def basin_scope(basin):
    """{'seasons', 'storms', 'records', 'usableRecords'} for one basin."""
    storms = load_storms(basin)
    if not storms:
        return None
    seasons = sorted(int(s) for _sid, s, _r in storms if s)
    nrec = sum(len(r) for _sid, _s, r in storms)
    nuse = sum(1 for _sid, _s, recs in storms for rec in recs if usable(rec))
    return {"seasons": ("%d-%d" % (seasons[0], seasons[-1])) if seasons else "",
            "storms": len(storms), "records": nrec, "usableRecords": nuse}


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

def ring_errors(snap, method):
    """Signed error, in nm, for every reported ring along its quadrant bearing."""
    rmax = T.resolveRmax(snap, 0.0)
    radii = np.linspace(0.05, R_MAX_NM, R_STEPS)
    out = []
    for q, az in T.QUAD_AZ.items():
        lat, lon = _ray(snap.lat, snap.lon, az, radii)
        mag, _dir, _r, _r34 = T.buildVortex(lat, lon, snap, rmax, method=method)
        mag = np.asarray(mag, dtype=float)
        for threshold in THRESHOLDS:
            quad = snap.radii.get(threshold)
            if not quad or snap.vmax < threshold:
                continue
            rep = quad.get(q, 0.0)
            if not rep or rep <= 0:
                continue
            out.append((threshold, float(rep), _crossing(radii, mag, threshold)))
    return out


def field_difference(snap):
    """Compare the two fields on a common polar grid around the storm.

    Returns (mean_abs_kt, p95_abs_kt, {threshold: area_ratio}) where the ratio
    is gtcm area / perquad area for that isotach.
    """
    rmax = T.resolveRmax(snap, 0.0)
    rr = np.linspace(2.0, 400.0, 200)
    az = np.arange(0.0, 360.0, 5.0)
    R, _A = np.meshgrid(rr, az)
    lats, lons = ray_grid(snap.lat, snap.lon, az, rr)

    fields = {}
    for method in METHODS:
        mag, _d, _r, _r34 = T.buildVortex(lats, lons, snap, rmax, method=method)
        fields[method] = np.asarray(mag, dtype=float)

    diff = np.abs(fields["gtcm"] - fields["perquad"])
    # Area weight for a polar cell is r*dr*dtheta; constant factors cancel in a
    # ratio, so r alone is enough.
    weight = R
    areas = {}
    for threshold in (34, 50, 64):
        a_pq = float(np.sum(weight * (fields["perquad"] >= threshold)))
        a_wt = float(np.sum(weight * (fields["gtcm"] >= threshold)))
        areas[threshold] = (a_wt / a_pq) if a_pq > 0 else float("nan")
    return float(diff.mean()), float(np.percentile(diff, 95)), areas


def stats(pairs):
    """(value, sid) pairs -> n / nStorms / bias / MAE / RMSE / p90|err|.

    n is the record/observation count (a ring-quadrant, a case, ...);
    nStorms is the count of DISTINCT storms behind those n observations -
    consecutive records of one storm are highly autocorrelated (same
    Vmax+-5kt, same radii +- one report, same motion), so n alone
    overstates how much independent evidence a stat rests on. A bare list
    of values (no sid) is also accepted for backward compatibility, in
    which case nStorms falls back to n (each value assumed independent).
    """
    if not pairs:
        return None
    if pairs and not isinstance(pairs[0], (tuple, list)):
        pairs = [(v, i) for i, v in enumerate(pairs)]
    v = np.asarray([p[0] for p in pairs], dtype=float)
    storms = set(p[1] for p in pairs)
    return dict(n=int(len(v)), nStorms=len(storms), bias=float(v.mean()),
                mae=float(np.abs(v).mean()),
                rmse=float(math.sqrt(float((v ** 2).mean()))),
                p90=float(np.percentile(np.abs(v), 90)))


def evaluate(cases, progress=None):
    """Ring and field numbers for a list of (sid, record) storm-times.

    Returns the ringFit / ringFitVsTarget / neverReached / fieldDiff blocks
    for one basin, in exactly the shape gtcm_findings.json wants.

    ringFitVsTarget scores BOTH methods against the same target - the reported
    radius scaled by GTCM_QUAD_AVG_FACTOR, i.e. the quadrant AVERAGE radius the
    GTCM fit is actually aimed at.  Scoring each method against its own
    goalposts would make the comparison meaningless; perquad's large positive
    bias in that block is the correct reading that it reproduces the quadrant
    MAXIMUM and therefore overshoots the quadrant average.
    """
    per_thr = dict((m, dict((t, []) for t in THRESHOLDS)) for m in METHODS)
    per_thr_fit = dict((m, dict((t, []) for t in THRESHOLDS)) for m in METHODS)
    # A reported ring the field never reaches at all is a worse failure than a
    # displaced one, and averaging only the hits would hide it entirely.
    missed = dict((m, dict((t, 0) for t in THRESHOLDS)) for m in METHODS)
    missed_storms = dict((m, dict((t, set()) for t in THRESHOLDS))
                         for m in METHODS)
    diffs, p95s = [], []
    diff_sids = []
    area_ratios = {34: [], 50: [], 64: []}
    eval_storms = set()
    n = 0

    for sid, rec in cases:
        snap = _snapshot(rec)
        if not snap.radii:
            continue
        eval_storms.add(sid)
        for method in METHODS:
            for threshold, rep, got in ring_errors(snap, method):
                if got is None:
                    missed[method][threshold] += 1
                    missed_storms[method][threshold].add(sid)
                else:
                    per_thr[method][threshold].append((got - rep, sid))
                    per_thr_fit[method][threshold].append(
                        (got - rep * T.GTCM_QUAD_AVG_FACTOR, sid))
        m, p, areas = field_difference(snap)
        diffs.append(m)
        p95s.append(p)
        diff_sids.append(sid)
        for threshold, ratio in areas.items():
            if np.isfinite(ratio):
                area_ratios[threshold].append(ratio)
        n += 1
        if progress and n % progress == 0:
            sys.stderr.write("      %d cases (%s)\n" % (n, sid))
            sys.stderr.flush()

    def block(store):
        out = {}
        for method in METHODS:
            out[method] = {}
            for threshold in THRESHOLDS:
                st = stats(store[method][threshold])
                if st:
                    out[method][str(threshold)] = st
            st = stats(sum(store[method].values(), []))
            if st:
                out[method]["all"] = st
        return out

    never = {}
    for method in METHODS:
        gone = sum(missed[method].values())
        hit = sum(len(v) for v in per_thr[method].values())
        total = gone + hit
        gone_storms = set()
        hit_storms = set()
        for t in THRESHOLDS:
            gone_storms |= missed_storms[method][t]
            hit_storms |= set(sid for _v, sid in per_thr[method][t])
        never[method] = {"count": gone, "total": total,
                         "pct": (100.0 * gone / total) if total else 0.0,
                         "nStorms": len(gone_storms | hit_storms),
                         "countStorms": len(gone_storms),
                         "byRing": dict((str(t), missed[method][t])
                                        for t in THRESHOLDS)}

    field = {"meanAbsKt": float(np.mean(diffs)) if diffs else float("nan"),
             "p95AbsKt": float(np.mean(p95s)) if p95s else float("nan"),
             "n": len(diffs), "nStorms": len(set(diff_sids))}
    for threshold in (34, 50, 64):
        vals = area_ratios[threshold]
        # Median, not mean: the ratio is unbounded above and a single case
        # where perquad's isotach area collapses to almost nothing sends the
        # mean to 3.1 while the median sits at 0.68.  The mean is kept
        # alongside so the skew is visible rather than hidden.
        field["areaRatio%d" % threshold] = (float(np.median(vals)) if vals
                                            else float("nan"))
        field["areaRatio%dMean" % threshold] = (float(np.mean(vals)) if vals
                                                else float("nan"))
        field["areaRatio%dN" % threshold] = len(vals)
    return {"cases": n, "storms": len(eval_storms),
            "ringFit": block(per_thr), "ringFitVsTarget": block(per_thr_fit),
            "neverReached": never, "fieldDiff": field}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_basin(basin, res):
    print("Vortex method comparison - %s, %d storm-times, %d distinct storms\n"
          % (basin, res["cases"], res["storms"]))
    print("1. RING REPRODUCTION (not a skill score - see the module docstring)")
    print("   %-9s %-6s %7s %9s %9s %9s %9s"
          % ("method", "ring", "n", "bias", "MAE", "RMSE", "p90|err|"))
    print("   " + "-" * 62)
    for method in METHODS:
        for key in ("64", "50", "34", "all"):
            st = res["ringFit"][method].get(key)
            if not st:
                continue
            label = "ALL" if key == "all" else "R" + key
            print("   %-9s %-6s %7d %+9.2f %9.2f %9.2f %9.2f"
                  % (method, label, st["n"], st["bias"], st["mae"],
                     st["rmse"], st["p90"]))
        nr = res["neverReached"][method]
        print("   %-9s reported rings the field NEVER reaches: %d of %d (%.1f%%)"
              % (method, nr["count"], nr["total"], nr["pct"]))
        if nr["count"]:
            print("   %-9s   by ring: %s" % ("", ", ".join(
                "R%s %d" % (t, nr["byRing"][t]) for t in ("64", "50", "34")
                if nr["byRing"].get(t))))
        print("   " + "-" * 62)

    print("\n   Same rings against the quadrant-AVERAGE target GTCM fits to")
    print("   (0.85 x the reported quadrant maximum), both methods:")
    for method in METHODS:
        st = res["ringFitVsTarget"][method].get("all")
        if st:
            print("   %-9s %-6s %7d %+9.2f %9.2f %9.2f %9.2f"
                  % (method, "ALL", st["n"], st["bias"], st["mae"],
                     st["rmse"], st["p90"]))

    f = res["fieldDiff"]
    print("\n2. FIELD DIFFERENCE (what a forecaster would see change)")
    print("   mean |gtcm - perquad| over the field : %6.2f kt" % f["meanAbsKt"])
    print("   p95 of that difference, per case     : %6.2f kt" % f["p95AbsKt"])
    for threshold in (34, 50, 64):
        print("   %d kt area, gtcm / perquad          : %6.3f median, "
              "%6.3f mean, n=%d" % (threshold, f["areaRatio%d" % threshold],
                                    f["areaRatio%dMean" % threshold],
                                    f["areaRatio%dN" % threshold]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basin", default="WP",
                    help="WP, NA, EP or all (default WP)")
    ap.add_argument("--cases", type=int, default=200,
                    help="storm-times per basin (default 200), sampled by "
                         "seeded round-robin across storms, not truncated "
                         "in file order; 0 or negative means the whole "
                         "basin's usable population")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="storm-shuffle seed for --cases sampling "
                         "(default %d)" % DEFAULT_SEED)
    ap.add_argument("--json", help="also write the summary to this path")
    args = ap.parse_args()

    basins = BASINS if args.basin.lower() == "all" else (args.basin.upper(),)
    limit = args.cases if args.cases and args.cases > 0 else None
    summary = {}
    for basin in basins:
        cases = load_cases(basin, limit, seed=args.seed)
        if not cases:
            print("%s: no data (archive files not generated?)\n" % basin)
            continue
        res = evaluate(cases)
        summary[basin] = res
        _print_basin(basin, res)
        print("")

    print("The GTCM branch follows the Users Guide v1.9.1. Two documented")
    print("departures: the profile is tapered beyond the modelled 34 kt radius so")
    print("the insert terminates (NHC leaves its grids missing out there and lets")
    print("the receiving office blend), and step 4's land-roughness reduction is")
    print("not implemented, so the field is marine-exposure everywhere.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        print("\nwrote %s" % args.json)


if __name__ == "__main__":
    main()
