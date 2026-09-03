#!/usr/bin/env python3
"""Held-out-radius skill check for TCWind_JTWC's GTCM fit.

Productionized from a review prototype (leave_one_ring_out.py) that asked one
question no other script in this suite asks: does GTCM predict anything it
was not fit to?

Every OTHER check in this suite is one of:

  - Self-consistency (compare_vortex_methods.ringFit / ringFitVsTarget) -
    scores the field AT the radii it was fit to. Not a skill score; the
    module docstring says so.
  - Smoothness/coherence (verify_gtcm.py's `coherence` block) - explicitly
    framed as *not* accuracy: the office moved to GTCM for PHYSICAL
    PLAUSIBILITY, not for accuracy against the reported radii.
  - A different model's skill (verify_besttrack_holland.py) - fits Holland
    (1980), not GTCM, and checks Holland's R50/R64 prediction.
  - RMW checked against resolveRmax()/willoughbyRmax() (verify_besttrack_
    rmax.py, fit_westpac_rmax.py) - the LEGACY "perquad" path's Rmax source.
    Under the shipped VORTEX_METHOD="gtcm" default, resolveRmax() is
    computed and then never read (_buildVortexGTCM's rmax_nm parameter is
    accepted and ignored) - so none of those checks say anything about the
    parameter the shipped default actually uses, fitGTCM()'s own `rm`.

Nothing fit GTCM's OWN fitGTCM() to a subset of the reported radii and
checked its prediction of the withheld ones, until this script.

METHOD
------
Population: every record, from ANY basin in the committed archive, with
Vmax > 64 kt and all three thresholds (R64/R50/R34) reported (at least one
nonzero quadrant each) - the richest-observed slice of the archive, and the
only one where there is anything to hold out.

Two held-out experiments, both scored for BOTH vortex constructions:

  r34Only   Fit using ONLY the R34 quadrant radii (R50/R64 dropped from the
            snapshot before fitting/building). Predict R50 and R64 per
            quadrant; compare to the record's real, never-fit values. This
            is exactly the "34 kt-only" case fitGTCM() pins rm to
            willoughbyRmax() climatology for (see its docstring), so the
            gtcm column here always exercises that pinned-rm path.
  r34R50    Fit using R34 AND R50 (R64 dropped). Predict R64 per quadrant.
            Closer to a real operational bulletin than r34Only (see caveat).

  gtcm      T.fitGTCM() on the restricted snapshot, then T._gtcmProfile()/
            T._gtcmUV() along each quadrant bearing (QUAD_AZ) - the exact
            functions the shipped field uses - to find the outermost radius
            crossing the target threshold.
  perquad   The retired construction, via T.buildVortex(method='perquad') on
            the SAME restricted snapshot, fed T.resolveRmax() for its Rmax,
            using compare_vortex_methods.ray_grid()/_crossing() so the
            geodesy matches what that script already uses.

Scored: bias, MAE, RMSE, r, and "never reached" fraction (the modelled field
never crosses the target threshold at all - excluded from bias/MAE/RMSE/r,
which have no signed error to average for those; counted and reported
separately, same convention compare_vortex_methods.py uses), per quadrant
and pooled ("all"), per basin and pooled across basins.

Context, not held-out (both computed from the FULL reported radii, i.e. NOT
an extrapolation test): fitGTCM()'s `rm` vs the record's actual RMW, and
resolveRmax()/willoughbyRmax() vs the same RMW - so a reader can see how the
live default's own internal size parameter compares to the legacy fallback
it replaced, on the same population, when both get to see everything.
Restricted to the sub-population that also has RMW reported.

CAVEAT - read before quoting a number out of this
---------------------------------------------------
r34Only is a deliberately HARDER, SYNTHETIC task than the tool's real
situation: a real JTWC bulletin that reports R34 quadrants on a Vmax>64kt
system routinely also reports R50 (and usually R64) - that is why the
Vmax>64-and-all-three-reported population exists to draw this test from in
the first place - so "given only R34, predict R50 and R64" throws away
information the tool would actually have. r34R50 -> R64 is closer to a real
forecasting scenario (only the strongest, innermost ring withheld) and
should be read as the more representative of the two.

Records are NOT independent by storm (besttrack_common's usual caveat): the
same storm contributes many 6-hourly records with similar Vmax/radii/motion.
Every stat below reports both n (records) and nStorms (distinct storms) for
exactly this reason - n alone overstates the independent evidence behind it.

Hermetic: reads the same committed archive compare_vortex_methods.py does
(besttrack_sample.json for WP, archive_index.json/archive_storms.json for
NA/EP, via compare_vortex_methods.load_storms()) - the same storms the rest
of the Findings pipeline scores, so this and verify_gtcm.py's other blocks
are never describing different samples. No network, no IBTrACS CSV.

Usage:
    python3 verify_holdout.py [--basins WP,NA,EP] [--out PATH]

Importable: compute() returns the JSON-shaped dict verify_gtcm.py embeds
verbatim as the top-level "holdout" block:

    {
      "caveat": str, "definitions": {...}, "runtimeSec": float,
      "byBasin": {"<WP|NA|EP>": {
          "n": int, "nStorms": int,
          "r34Only": {"<gtcm|perquad>": {"R50": EXP, "R64": EXP}},
          "r34R50":  {"<gtcm|perquad>": {"R64": EXP}},
          "rmwContext": {"gtcmRmAllRadii": STATS, "resolveRmaxAllRadii": STATS},
      }, ...},
      "pooled": { same shape as one byBasin entry, plus "n"/"nStorms" },
    }

  EXP    = {"byQuad": {"<NE|SE|SW|NW|all>": STATS}, "neverReached": NEVER}
  STATS  = {"n": int, "nStorms": int, "bias": float, "mae": float,
            "rmse": float, "r": float}   (nm; r may be NaN if degenerate)
  NEVER  = {"count": int, "total": int, "pct": float, "nStormsMissed": int}
"""
import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "GFE", "procedures"))

import TCWind_JTWC as T                # noqa: E402
import compare_vortex_methods as C     # noqa: E402

OUT = os.path.join(HERE, "data", "holdout_findings.json")

QUADS = ["NE", "SE", "SW", "NW"]
R_GRID = np.linspace(0.05, C.R_MAX_NM, C.R_STEPS)
BASINS = ("WP", "NA", "EP")

EXPERIMENTS = (("r34Only", (34,), (50, 64)), ("r34R50", (34, 50), (64,)))

CAVEAT = (
    "r34Only fits GTCM/perquad to R34 alone and predicts R50/R64 - a "
    "deliberately HARDER, synthetic task than the tool's real situation, "
    "since a real bulletin reporting R34 on a Vmax>64kt system usually also "
    "reports R50 (and often R64), so this throws away information the tool "
    "would actually have. r34R50 (fit R34+R50, predict R64 only) withholds "
    "just the innermost ring and is the more representative of the two. "
    "Records are not independent by storm - see nStorms next to every n.")

DEFINITIONS = {
    "r34Only": "Fit GTCM/perquad using ONLY the reported R34 quadrant "
        "radii (R50/R64 removed from the snapshot before fitting); predict "
        "R50 and R64 per quadrant and score against the record's real, "
        "never-fit values. See the caveat: this is a harder task than the "
        "tool usually faces. Since fitGTCM() pins rm to willoughbyRmax() "
        "climatology whenever no 50/64 kt target is present - which every "
        "record in this experiment's restricted snapshot satisfies by "
        "construction - GTCM's r34Only column always exercises that pinned-"
        "rm, exponent-only path, not the free-rm search r34R50 and the "
        "tool's real Vmax>64kt bulletins use.",
    "r34R50": "Fit GTCM/perquad using R34 AND R50 (R64 removed); predict "
        "R64 per quadrant and score against the real value. Closer to a "
        "real bulletin than r34Only.",
    "neverReached": "Fraction of targets the modelled field never crosses "
        "at any radius along that quadrant bearing. Excluded from bias/"
        "MAE/RMSE/r (no signed error to average); perquad is near 0 by "
        "construction (a Rankine tail decays slowly), GTCM's failures here "
        "are storms whose withheld structure one symmetric vortex, fit to "
        "less than it is being asked to predict, cannot reach.",
    "rmwContext": "NOT a held-out test - both fitGTCM's rm and "
        "resolveRmax()/willoughbyRmax() computed from the FULL reported "
        "radii (nothing withheld), against the record's actual RMW. "
        "Context for how the live default's own internal size parameter "
        "compares to the legacy fallback it replaced, when both get to "
        "see everything.",
    "stats": "bias/mae/rmse/r in nm, n = record count, nStorms = distinct "
        "storm count behind those records (see the module-level caveat: "
        "records are not independent by storm).",
}


# ---------------------------------------------------------------------------
# population
# ---------------------------------------------------------------------------

def _nonzero_quads(d):
    return dict((q, v) for q, v in (d or {}).items() if v and v > 0)


def eligible(rec):
    """Vmax > 64 and all three thresholds reported (>=1 nonzero quadrant
    each) - the population this whole script draws from.

    Record radii dicts come straight out of JSON, so their threshold keys
    are strings ("64"/"50"/"34"), unlike compare_vortex_methods.Snapshot's
    (int-keyed, via besttrack_common.build_storm_records()/_snapshot()'s own
    int(k) conversion) - this module works on the raw record dicts, so every
    radii lookup here uses str(threshold)."""
    if rec.get("vmax", 0) <= 64:
        return False
    radii = rec.get("radii") or {}
    return all(str(t) in radii and _nonzero_quads(radii[str(t)])
              for t in (64, 50, 34))


def load_population(basins=BASINS):
    """{basin: [(sid, rec), ...]} of eligible records, via the SAME storms
    compare_vortex_methods.py (and so verify_gtcm.py) already scores."""
    out = {}
    for basin in basins:
        cases = []
        for sid, _season, recs in C.load_storms(basin):
            for rec in recs:
                if eligible(rec):
                    cases.append((sid, rec))
        out[basin] = cases
    return out


def _restricted(rec, thresholds):
    r = dict(rec)
    r["radii"] = dict((str(t), dict(rec["radii"][str(t)])) for t in thresholds)
    return r


def _snapshot(rec):
    return C._snapshot(rec)


# ---------------------------------------------------------------------------
# prediction
# ---------------------------------------------------------------------------

def gtcm_predict(snap_restricted, targets):
    """fit (dict) and {quad: {target: radius_or_None}} via the shipped
    fitGTCM()/_gtcmProfile()/_gtcmUV() directly - no lat/lon geodesy needed,
    the profile is a function of (r, azimuth) alone."""
    fit = T.fitGTCM(snap_restricted)
    out = {}
    for q in QUADS:
        az = T.QUAD_AZ[q]
        V = T._gtcmProfile(R_GRID, snap_restricted.vmax, fit["a"], fit["rm"],
                            fit["ri"], fit["x1"], fit["x2"])
        u, v = T._gtcmUV(V, np.full_like(R_GRID, az), fit["ax"], fit["ay"],
                          snap_restricted.lat)
        mag = np.sqrt(u * u + v * v)
        out[q] = dict((t, C._crossing(R_GRID, mag, float(t)))
                      for t in targets)
    return fit, out


def perquad_predict(snap_restricted, rec, targets):
    """Same held-out-radius test for the retired construction, via the real
    buildVortex(method='perquad') on an actual lat/lon ray grid."""
    rmax = T.resolveRmax(snap_restricted, 0.0)
    out = {}
    for q in QUADS:
        az = T.QUAD_AZ[q]
        lat, lon = C._ray(rec["lat"], rec["lon"], az, R_GRID)
        mag, _d, _r, _r34 = T.buildVortex(lat, lon, snap_restricted, rmax,
                                          method="perquad")
        mag = np.asarray(mag, dtype=float)
        out[q] = dict((t, C._crossing(R_GRID, mag, float(t)))
                      for t in targets)
    return rmax, out


# ---------------------------------------------------------------------------
# scoring - collect raw (pred, actual, sid) triples once, reduce to stats,
# merge accumulators across basins. Kept as three separate steps so the
# same raw pairs feed both the per-basin blocks and the cross-basin pool,
# rather than re-running the (fit, predict) pass a second time for pooling.
# ---------------------------------------------------------------------------

def _empty_acc(targets):
    return (dict((t, dict((q, []) for q in QUADS + ["all"])) for t in targets),
            dict((t, 0) for t in targets),
            dict((t, set()) for t in targets))


def collect_experiment(cases, fit_thresholds, targets, progress=None):
    """{method: (pairs, miss_n, miss_storms)} raw accumulators, one
    (fit, predict) pass over `cases`."""
    acc = dict((m, _empty_acc(targets)) for m in C.METHODS)
    n = 0
    for sid, rec in cases:
        restricted = _restricted(rec, fit_thresholds)
        snap_r = _snapshot(restricted)
        gfit, gpred = gtcm_predict(snap_r, targets)
        _rmax, ppred = perquad_predict(snap_r, rec, targets)
        preds = {"gtcm": gpred, "perquad": ppred}

        for method in C.METHODS:
            pairs, miss_n, miss_storms = acc[method]
            for t in targets:
                actual_q = _nonzero_quads(rec["radii"].get(str(t), {}))
                for q, actual in actual_q.items():
                    got = preds[method][q][t]
                    if got is None:
                        miss_n[t] += 1
                        miss_storms[t].add(sid)
                        continue
                    pairs[t][q].append((got, actual, sid))
                    pairs[t]["all"].append((got, actual, sid))
        n += 1
        if progress and n % progress == 0:
            sys.stderr.write("      holdout %d/%d cases (%s)\n"
                             % (n, len(cases), sid))
            sys.stderr.flush()
    return acc


def merge_experiment(dst, src, targets):
    for method in C.METHODS:
        dpairs, dmiss_n, dmiss_s = dst[method]
        spairs, smiss_n, smiss_s = src[method]
        for t in targets:
            for q in QUADS + ["all"]:
                dpairs[t][q].extend(spairs[t][q])
            dmiss_n[t] += smiss_n[t]
            dmiss_s[t] |= smiss_s[t]
    return dst


def _pair_stats(triples):
    """[(pred, actual, sid), ...] -> bias/mae/rmse/r/n/nStorms, or None."""
    if not triples:
        return None
    pred = np.array([t[0] for t in triples], dtype=float)
    act = np.array([t[1] for t in triples], dtype=float)
    sids = set(t[2] for t in triples)
    err = pred - act
    n = len(err)
    out = dict(n=n, nStorms=len(sids), bias=float(err.mean()),
              mae=float(np.abs(err).mean()),
              rmse=float(math.sqrt(float((err ** 2).mean()))))
    if n >= 2 and float(np.std(pred)) > 0 and float(np.std(act)) > 0:
        out["r"] = float(np.corrcoef(pred, act)[0, 1])
    else:
        out["r"] = float("nan")
    return out


def reduce_experiment(acc, targets):
    out = {}
    for method in C.METHODS:
        pairs, miss_n, miss_storms = acc[method]
        out[method] = {}
        for t in targets:
            byQuad = {}
            for q in QUADS + ["all"]:
                st = _pair_stats(pairs[t][q])
                if st:
                    byQuad[q] = st
            hits = len(pairs[t]["all"])
            total = hits + miss_n[t]
            out[method]["R%d" % t] = {
                "byQuad": byQuad,
                "neverReached": {
                    "count": miss_n[t], "total": total,
                    "pct": (100.0 * miss_n[t] / total) if total else 0.0,
                    "nStormsMissed": len(miss_storms[t]),
                },
            }
    return out


def rmw_context(cases, progress=None):
    """[(pred, actual, sid), ...] pairs for fitGTCM().rm and resolveRmax(),
    both from the FULL reported radii, vs actual RMW - restricted to the
    sub-population of `cases` that also has RMW reported."""
    gtcm_pairs, legacy_pairs = [], []
    n = 0
    for sid, rec in cases:
        if not rec.get("rmw") or rec["rmw"] <= 0:
            continue
        snap = _snapshot(rec)
        fit = T.fitGTCM(snap)
        legacy = T.resolveRmax(snap, 0.0)
        gtcm_pairs.append((fit["rm"], rec["rmw"], sid))
        legacy_pairs.append((legacy, rec["rmw"], sid))
        n += 1
        if progress and n % progress == 0:
            sys.stderr.write("      rmwContext %d cases (%s)\n" % (n, sid))
            sys.stderr.flush()
    return gtcm_pairs, legacy_pairs


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------

def compute(basins=BASINS, progress=None):
    t0 = time.time()
    population = load_population(basins)

    pooled_acc = dict((name, dict((m, _empty_acc(targets)) for m in C.METHODS))
                      for name, _fit_t, targets in EXPERIMENTS)
    pooled_rmw_g, pooled_rmw_l = [], []

    byBasin = {}
    for basin in basins:
        cases = population.get(basin) or []
        sys.stderr.write("%s: %d eligible records (Vmax>64, R34/R50/R64 "
                         "all reported), %d distinct storms\n"
                         % (basin, len(cases), len(C.case_storms(cases))))
        entry = {"n": len(cases), "nStorms": len(C.case_storms(cases))}
        if cases:
            for name, fit_t, targets in EXPERIMENTS:
                acc = collect_experiment(cases, fit_t, targets,
                                        progress=progress)
                entry[name] = reduce_experiment(acc, targets)
                merge_experiment(pooled_acc[name], acc, targets)

            g_pairs, l_pairs = rmw_context(cases, progress=progress)
            entry["rmwContext"] = {
                "gtcmRmAllRadii": _pair_stats(g_pairs),
                "resolveRmaxAllRadii": _pair_stats(l_pairs),
            }
            pooled_rmw_g.extend(g_pairs)
            pooled_rmw_l.extend(l_pairs)
        byBasin[basin] = entry

    pooled = {}
    for name, _fit_t, targets in EXPERIMENTS:
        pooled[name] = reduce_experiment(pooled_acc[name], targets)
    pooled["rmwContext"] = {
        "gtcmRmAllRadii": _pair_stats(pooled_rmw_g),
        "resolveRmaxAllRadii": _pair_stats(pooled_rmw_l),
    }
    all_cases = []
    for b in basins:
        all_cases.extend(population.get(b) or [])
    pooled["n"] = len(all_cases)
    pooled["nStorms"] = len(C.case_storms(all_cases))

    return {
        "generated": datetime.date.today().isoformat(),
        "caveat": CAVEAT,
        "definitions": DEFINITIONS,
        "byBasin": byBasin,
        "pooled": pooled,
        "runtimeSec": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basins", default="WP,NA,EP")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--progress", type=int, default=100)
    args = ap.parse_args()
    basins = tuple(b.strip().upper() for b in args.basins.split(",") if b.strip())

    findings = compute(basins, progress=args.progress)

    with open(args.out, "w") as fh:
        json.dump(findings, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote %s (%.1fs)" % (args.out, findings["runtimeSec"]))

    p = findings["pooled"]
    print("\nPooled across %s, n=%d records, %d distinct storms\n"
          % (", ".join(basins), p["n"], p["nStorms"]))
    for name, _fit_t, targets in EXPERIMENTS:
        print("=== %s ===" % name)
        for t in targets:
            print("  R%d:" % t)
            for method in C.METHODS:
                blk = p[name][method]["R%d" % t]
                st = blk["byQuad"].get("all")
                nr = blk["neverReached"]
                if st:
                    print("    %-9s all-quad bias=%+7.2f MAE=%6.2f "
                          "RMSE=%6.2f r=%.2f  n=%d nStorms=%d  "
                          "neverReached=%d/%d (%.1f%%)"
                          % (method, st["bias"], st["mae"], st["rmse"],
                             st["r"], st["n"], st["nStorms"], nr["count"],
                             nr["total"], nr["pct"]))
    rc = p["rmwContext"]
    print("\n=== rmwContext (full radii, vs actual RMW) ===")
    for key in ("gtcmRmAllRadii", "resolveRmaxAllRadii"):
        st = rc.get(key)
        if st:
            print("  %-22s bias=%+7.2f MAE=%6.2f RMSE=%6.2f r=%.2f  "
                  "n=%d nStorms=%d" % (key, st["bias"], st["mae"],
                                       st["rmse"], st["r"], st["n"],
                                       st["nStorms"]))


if __name__ == "__main__":
    main()
