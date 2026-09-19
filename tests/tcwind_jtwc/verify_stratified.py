#!/usr/bin/env python3
"""Does the tool's accuracy hold up in the situations that matter most
operationally - near land, and during extratropical/subtropical transition -
or does it quietly get worse exactly when a forecaster would need it most?

Folds verify_besttrack_context.py's question into the archive-based
pipeline (see that script's own header for why it is being superseded here
rather than edited in place): that script checked only resolveRmax() - the
LEGACY "perquad" Rmax source, not read at all under the shipped
VORTEX_METHOD="gtcm" default (see verify_holdout.py's header) - on WP alone,
and its result never reached compare_vortex_methods.py, verify_gtcm.py, or
gtcm_findings.json. This script:

  - covers all three archive basins (WP/NA/EP), not WP only, using the same
    committed storms compare_vortex_methods.py and verify_holdout.py score
    (compare_vortex_methods.load_storms(), hermetic, no CSV);
  - scores BOTH vortex constructions (gtcm and perquad), not just the
    superseded Rmax path;
  - reports the SAME two kinds of statistic the rest of this suite already
    defines, split by stratum, rather than a third bespoke metric:
      ringFit  - compare_vortex_methods.ring_errors()/stats() pooled over
                 all thresholds and quadrants ("all"), against the reported
                 radius. Self-consistency, not a skill score - see that
                 module's docstring. Population: every usable() record
                 (Vmax>=34, any radii reported).
      holdout  - verify_holdout.py's r34Only/r34R50 held-out-radius
                 experiments, pooled over quadrants ("all" only - splitting
                 further by quadrant AND stratum fragments already-thin
                 strata into single digits). Population: verify_holdout.
                 eligible() (Vmax>64, R34/R50/R64 all reported) - a strict
                 subset of the ringFit population, so a stratum can appear
                 in one block and not the other if it has no Vmax>64 cases.

Both strata come straight from IBTrACS' own fields, already carried on every
archive record (besttrack_common.build_storm_records()) - no new data, no
external literature, nothing this tool's model has any part in producing:

  NATURE     IBTrACS' own storm-type flag per record: "TS" tropical, "ET"
             extratropical transition, "SS" subtropical, "MX" mixture; every
             other value (DS disturbance, NR not reported, blank) pools into
             "other" rather than fragmenting into single-digit buckets.
  DIST2LAND  IBTrACS' own distance to the nearest coastline, km, bucketed
             <=25 / 25-100 / 100-300 / >300 (watches/warnings concentrate
             near land, so accuracy right at the coast is operationally the
             highest-stakes bucket here, not an afterthought).

CAVEAT: same as verify_holdout.py's - records are not independent by storm
(n and nStorms are both reported for every stratum), and r34Only in
particular is a harder synthetic task than the tool's real situation. ET/SS
in particular are rare in this archive; read their n and nStorms before
trusting their numbers, and treat a stratum with nStorms in the single
digits as suggestive, not conclusive.

Usage:
    python3 verify_stratified.py [--basins WP,NA,EP] [--out PATH]

Importable: compute() returns {"byNature": {...}, "byLand": {...}}, the two
top-level blocks verify_gtcm.py embeds verbatim. Shape, per group:

    {"n": int, "nStorms": int,
     "ringFit": {"<gtcm|perquad>": STATS},
     "holdout": {"r34Only": {"<gtcm|perquad>": {"R50": EXP, "R64": EXP}},
                 "r34R50":  {"<gtcm|perquad>": {"R64": EXP}}}}

STATS/EXP/etc. are the same shapes compare_vortex_methods.py and
verify_holdout.py already define (see their docstrings).
"""
import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "GFE", "procedures"))

import compare_vortex_methods as C     # noqa: E402
import verify_holdout as H             # noqa: E402

OUT = os.path.join(HERE, "data", "stratified_findings.json")
BASINS = ("WP", "NA", "EP")

NATURE_LABEL = {"TS": "TS (purely tropical)",
                "ET": "ET (extratropical transition)",
                "SS": "SS (subtropical)", "MX": "MX (mixture)"}
NATURE_GROUPS = ("TS (purely tropical)", "ET (extratropical transition)",
                 "SS (subtropical)", "MX (mixture)", "other")

LAND_BUCKETS = [("<=25 km", lambda d: d <= 25),
                ("25-100 km", lambda d: 25 < d <= 100),
                ("100-300 km", lambda d: 100 < d <= 300),
                (">300 km", lambda d: d > 300)]
LAND_GROUPS = tuple(label for label, _test in LAND_BUCKETS)

DEFINITIONS = {
    "nature": "IBTrACS' own per-record storm-type flag. TS/ET/SS/MX kept "
        "separate; DS (disturbance)/NR (not reported)/blank pool into "
        "'other' rather than fragmenting further.",
    "land": "IBTrACS' own DIST2LAND (km to nearest coastline), bucketed "
        "<=25 / 25-100 / 100-300 / >300. Records with no DIST2LAND value "
        "are excluded from this block only.",
    "ringFit": "compare_vortex_methods.ring_errors()/stats(), pooled over "
        "all thresholds and quadrants, against the REPORTED radius. "
        "Self-consistency (see that module's docstring), not a skill "
        "score. Population: usable() records (Vmax>=34, any radii "
        "reported) - see the top-level ringFit/ringFitVsTarget blocks for "
        "the unstratified version of this same statistic.",
    "holdout": "verify_holdout.py's r34Only/r34R50 experiments, pooled "
        "over quadrants only (not split further by quadrant here). "
        "Population: verify_holdout.eligible() (Vmax>64, R34/R50/R64 all "
        "reported) - a strict subset of the ringFit population, so a "
        "stratum can be present in ringFit and absent from holdout. See "
        "the top-level holdout block's caveat before reading r34Only.",
    "stats": "Every leaf is n (record count) and nStorms (distinct storm "
        "count) alongside bias/mae/rmse/(r where applicable) - records "
        "are not independent by storm.",
}


# ---------------------------------------------------------------------------
# stratum assignment
# ---------------------------------------------------------------------------

def nature_group(rec):
    return NATURE_LABEL.get((rec.get("nature") or "").strip(), "other")


def land_group(rec):
    d = rec.get("dist2land")
    if d is None or d < 0:
        return None
    for label, test in LAND_BUCKETS:
        if test(d):
            return label
    return None


# ---------------------------------------------------------------------------
# ringFit, pooled by stratum
# ---------------------------------------------------------------------------

def _reduce_ring_buckets(buckets, counted, groups):
    out = {}
    for g in groups:
        entry = {"nStorms": len(counted[g])}
        methods_out = {}
        for m in C.METHODS:
            st = C.stats(buckets[g][m])
            if st:
                methods_out[m] = st
        entry["ringFit"] = methods_out
        entry["n"] = max((st["n"] for st in methods_out.values()), default=0)
        out[g] = entry
    return out


def ring_fit_combined(basins, progress=None):
    """One pass over every usable() record computing ring_errors() once and
    filing the errors into BOTH the nature and the land bucket it belongs
    to - half the cost of two independent passes. Returns
    (by_nature, by_land), each {group: {n, nStorms, ringFit}}."""
    nat_buckets = dict((g, dict((m, []) for m in C.METHODS))
                       for g in NATURE_GROUPS)
    nat_storms = dict((g, set()) for g in NATURE_GROUPS)
    land_buckets = dict((g, dict((m, []) for m in C.METHODS))
                        for g in LAND_GROUPS)
    land_storms = dict((g, set()) for g in LAND_GROUPS)
    n = 0
    for basin in basins:
        for sid, _season, recs in C.load_storms(basin):
            for rec in recs:
                if not C.usable(rec):
                    continue
                ng = nature_group(rec)
                lg = land_group(rec)
                snap = C._snapshot(rec)
                errs = dict((m, []) for m in C.METHODS)
                for method in C.METHODS:
                    for _threshold, rep, got in C.ring_errors(snap, method):
                        if got is not None:
                            errs[method].append((got - rep, sid))
                for method in C.METHODS:
                    nat_buckets[ng][method].extend(errs[method])
                    if lg is not None:
                        land_buckets[lg][method].extend(errs[method])
                nat_storms[ng].add(sid)
                if lg is not None:
                    land_storms[lg].add(sid)
                n += 1
                if progress and n % progress == 0:
                    sys.stderr.write("      ringFit %d records\n" % n)
                    sys.stderr.flush()
    return (_reduce_ring_buckets(nat_buckets, nat_storms, NATURE_GROUPS),
            _reduce_ring_buckets(land_buckets, land_storms, LAND_GROUPS))


# ---------------------------------------------------------------------------
# holdout, pooled by stratum
# ---------------------------------------------------------------------------

def _reduce_holdout_buckets(accs, storms, groups):
    out = {}
    for g in groups:
        entry = {"nStorms": len(storms[g])}
        blocks = {}
        total_n = 0
        for name, _fit_t, targets in H.EXPERIMENTS:
            red = H.reduce_experiment(accs[g][name], targets)
            has_any = any(red[m].get("R%d" % t, {}).get("byQuad", {}).get("all")
                         for m in C.METHODS for t in targets)
            if has_any:
                blocks[name] = red
                for m in C.METHODS:
                    for t in targets:
                        st = red[m]["R%d" % t]["byQuad"].get("all")
                        if st:
                            total_n = max(total_n, st["n"])
        entry["n"] = total_n
        if blocks:
            entry.update(blocks)
        out[g] = entry
    return out


def holdout_combined(basins, progress=None):
    """One pass over every verify_holdout.eligible() record, running each
    held-out-radius experiment ONCE and filing it into both the nature and
    the land bucket it belongs to. Returns (by_nature, by_land)."""
    nat_accs = dict((g, dict((name, dict((m, H._empty_acc(targets))
                                        for m in C.METHODS))
                            for name, _t, targets in H.EXPERIMENTS))
                   for g in NATURE_GROUPS)
    nat_storms = dict((g, set()) for g in NATURE_GROUPS)
    land_accs = dict((g, dict((name, dict((m, H._empty_acc(targets))
                                         for m in C.METHODS))
                             for name, _t, targets in H.EXPERIMENTS))
                    for g in LAND_GROUPS)
    land_storms = dict((g, set()) for g in LAND_GROUPS)
    n = 0
    for basin in basins:
        for sid, _season, recs in C.load_storms(basin):
            for rec in recs:
                if not H.eligible(rec):
                    continue
                ng = nature_group(rec)
                lg = land_group(rec)
                for name, fit_t, targets in H.EXPERIMENTS:
                    acc = H.collect_experiment([(sid, rec)], fit_t, targets,
                                               progress=None)
                    H.merge_experiment(nat_accs[ng][name], acc, targets)
                    if lg is not None:
                        H.merge_experiment(land_accs[lg][name], acc, targets)
                nat_storms[ng].add(sid)
                if lg is not None:
                    land_storms[lg].add(sid)
                n += 1
                if progress and n % progress == 0:
                    sys.stderr.write("      holdout %d records\n" % n)
                    sys.stderr.flush()
    return (_reduce_holdout_buckets(nat_accs, nat_storms, NATURE_GROUPS),
            _reduce_holdout_buckets(land_accs, land_storms, LAND_GROUPS))


# ---------------------------------------------------------------------------
# top level
# ---------------------------------------------------------------------------

def compute(basins=BASINS, progress=None):
    t0 = time.time()
    nature_ring, land_ring = ring_fit_combined(basins, progress=progress)
    nature_hold, land_hold = holdout_combined(basins, progress=progress)

    def merge(ring, hold, groups):
        out = {}
        for g in groups:
            r, h = ring.get(g, {}), hold.get(g, {})
            entry = {"n": r.get("n", 0), "nStorms": r.get("nStorms", 0)}
            if "ringFit" in r:
                entry["ringFit"] = r["ringFit"]
            for name, _fit_t, _targets in H.EXPERIMENTS:
                if name in h:
                    entry.setdefault("holdout", {})[name] = h[name]
            if "holdout" in entry:
                entry["holdoutN"] = h.get("n", 0)
                entry["holdoutNStorms"] = h.get("nStorms", 0)
            out[g] = entry
        return out

    return {
        "generated": datetime.date.today().isoformat(),
        "definitions": DEFINITIONS,
        "byNature": merge(nature_ring, nature_hold, NATURE_GROUPS),
        "byLand": merge(land_ring, land_hold, LAND_GROUPS),
        "runtimeSec": round(time.time() - t0, 1),
    }


def _print_group(label, g, entry):
    print("  %-32s n=%-5d nStorms=%-4d" % (label, entry.get("n", 0),
                                           entry.get("nStorms", 0)))
    rf = entry.get("ringFit") or {}
    for m in C.METHODS:
        st = rf.get(m)
        if st:
            print("      ringFit %-9s bias=%+7.2f MAE=%6.2f RMSE=%6.2f "
                  "n=%d nStorms=%d" % (m, st["bias"], st["mae"], st["rmse"],
                                       st["n"], st["nStorms"]))
    hd = entry.get("holdout") or {}
    for name in ("r34Only", "r34R50"):
        blk = hd.get(name)
        if not blk:
            continue
        for method in C.METHODS:
            for t, exp in blk.get(method, {}).items():
                st = exp["byQuad"].get("all")
                if st:
                    print("      holdout.%-8s %-9s %-4s bias=%+7.2f "
                          "MAE=%6.2f n=%d nStorms=%d"
                          % (name, method, t, st["bias"], st["mae"],
                             st["n"], st["nStorms"]))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basins", default="WP,NA,EP")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--progress", type=int, default=500)
    args = ap.parse_args()
    basins = tuple(b.strip().upper() for b in args.basins.split(",") if b.strip())

    findings = compute(basins, progress=args.progress)
    with open(args.out, "w") as fh:
        json.dump(findings, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote %s (%.1fs)" % (args.out, findings["runtimeSec"]))

    print("\n=== byNature ===")
    for g in NATURE_GROUPS:
        _print_group(g, g, findings["byNature"][g])
    print("\n=== byLand ===")
    for g in LAND_GROUPS:
        _print_group(g, g, findings["byLand"][g])


if __name__ == "__main__":
    main()
