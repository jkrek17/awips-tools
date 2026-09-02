#!/usr/bin/env python3
"""Build the datasets shipped inside the Apps Script web app for the
"Best-track QC" panel:

  - a random sample of 100 storms, each with its full track (position,
    Vmax, reported wind radii, RMW, and ROCI where available), for the
    storm browser - lets you flip through a real storm and see its
    actual reported radii/RMW/ROCI next to the tool's own modeled
    output on the map.
  - every usable record in the whole WP best-track archive (~16k),
    compacted to just what the verification scatter needs, for the
    aggregate predicted-vs-actual Rmax chart.
  - a small summary of how far the tool's own profile and an
    independent Holland (1980) profile diverge, by zone (Rmax-R64,
    R64-R50, R50-R34, beyond R34) - see verify_besttrack_holland.py,
    which this reuses.

All three are written as ready-to-push Apps Script source
(web/TCWind_JTWC/BestTrackData.gs, fetched by the client via
Code.gs's getBestTrackSample()/getBestTrackScatter()/
getHollandZoneSummary(), same as live bulletins) plus plain JSON under
tests/tcwind_jtwc/data/ for reference/diffing.

Usage:
    python3 prep_besttrack_data.py [path/to/ibtracs_WP.csv]
"""
import json
import os
import random
import sys

from besttrack_common import CACHE, iter_storms, build_storm_records, quad_radii, to_float
from verify_besttrack_holland import (
    solve_holland_B, holland_v_at, dest_grid,
)
import TCWind_JTWC as tc
import numpy as np

SEED = 20260902
N_SAMPLE_STORMS = 100
MIN_RECORDS = 6
# iter_storms() below already defaults to besttrack_common.MIN_SEASON
# (2005) - not 2001, since RMW/some radii is one thing, but reliable
# R50/R64 reporting specifically only starts around 2005 (see that
# constant's own comment). all_storms is already restricted by the time
# it reaches build_sample() below, so no separate cutoff is needed here.

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
GS_OUT = os.path.join(HERE, "..", "..", "web", "TCWind_JTWC", "BestTrackData.gs")


def build_sample(all_storms):
    eligible = [(sid, name, season, rows) for sid, name, season, rows in all_storms
                if sum(1 for r in rows if r["USA_WIND"].strip()
                        and r["USA_LAT"].strip()) >= MIN_RECORDS]
    rnd = random.Random(SEED)
    picked = rnd.sample(eligible, min(N_SAMPLE_STORMS, len(eligible)))
    picked.sort(key=lambda t: (t[2], t[0]))  # season, sid

    sample = []
    for sid, name, season, rows in picked:
        recs = build_storm_records(rows)
        if len(recs) < MIN_RECORDS:
            continue
        sample.append({"sid": sid, "name": name, "season": season, "records": recs})
    return sample


def build_scatter(all_storms):
    # Compact positional rows: [vmax, lat, rmw, r64min, r50min, r34min].
    # r*min is the smallest nonzero quadrant at that threshold (0 if the
    # threshold wasn't reported) - all resolveRmax()'s clamp needs is
    # Math.min() across quadrants, so shipping just that lets the client
    # reuse the real resolveRmax()/willoughbyRmax() unmodified rather than
    # duplicating the clamp formula here.
    scatter = []
    for sid, name, season, rows in all_storms:
        for row in rows:
            lat = to_float(row["USA_LAT"]) or to_float(row["LAT"])
            vmax = to_float(row["USA_WIND"])
            rmw = to_float(row["USA_RMW"])
            if lat is None or vmax is None or rmw is None or rmw <= 0:
                continue
            # buildFor() in TCWind_JTWC.py now skips any storm-time below
            # tropical storm strength outright, so this chart (which uses
            # the real resolveRmax()) shouldn't score the tool against
            # something it no longer even attempts.
            if vmax < 34:
                continue
            mins = []
            for thresh in (64, 50, 34):
                q = quad_radii(row, thresh)
                nz = [v for v in (q or {}).values() if v > 0]
                mins.append(round(min(nz), 1) if nz else 0)
            scatter.append([round(vmax, 1), round(lat, 2), round(rmw, 1)] + mins)
    return scatter


def build_holland_zone_summary(all_storms):
    """Mirrors verify_besttrack_holland.py's zone-divergence computation,
    condensed to {zone: {n, mean, p90}} for the bar chart."""
    zone_diffs = {}
    for sid, name, season, rows in all_storms:
        for rec in build_storm_records(rows):
            rmw = rec["rmw"]
            # build_storm_records() already gives us the full radii dict
            # per record, so compute the mean directly from it.
            r34_vals = [v for v in rec["radii"].get(34, {}).values() if v > 0]
            r34 = sum(r34_vals) / len(r34_vals) if r34_vals else None
            if not rmw or not r34 or rec["vmax"] <= 34 or r34 <= rmw:
                continue
            try:
                B = solve_holland_B(rec["vmax"], rmw, r34)
            except (ValueError, ZeroDivisionError):
                continue
            if not (0.3 <= B <= 3.0):
                continue

            snap = tc.Snapshot()
            snap.lat, snap.lon, snap.vmax = rec["lat"], rec["lon"], rec["vmax"]
            snap.radii = rec["radii"]
            tool_rmax = tc.resolveRmax(snap, 0.0)

            edge_pts = [("Rmax", tool_rmax)]
            for thresh, label in ((64, "R64"), (50, "R50")):
                vals = [v for v in rec["radii"].get(thresh, {}).values() if v > 0]
                if vals:
                    edge_pts.append((label, sum(vals) / len(vals)))
            edge_pts.append(("R34", r34))
            edge_pts.append(("2xR34", r34 * 2.0))
            edge_pts.sort(key=lambda p: p[1])

            for (name_lo, lo), (name_hi, hi) in zip(edge_pts, edge_pts[1:]):
                if hi <= lo:
                    continue
                mid = (lo + hi) / 2.0
                lat, lon = dest_grid(rec["lat"], rec["lon"], 45.0, np.array([mid]))
                tool_mag, _d, _r, _r34 = tc.buildVortex(
                    lat, lon, snap, tool_rmax, normalizePeak=False)
                holland_mag = holland_v_at(rec["vmax"], rmw, B, mid)
                label = name_lo + "-" + name_hi
                zone_diffs.setdefault(label, []).append(
                    abs(float(tool_mag[0]) - holland_mag))

    out = {}
    for label, vals in zone_diffs.items():
        vals_sorted = sorted(vals)
        p90 = vals_sorted[int(0.9 * (len(vals_sorted) - 1))]
        out[label] = {"n": len(vals), "mean": round(sum(vals) / len(vals), 2),
                       "p90": round(p90, 2)}
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE
    all_storms = list(iter_storms(path))
    print("%d storms (jtwc_wp) loaded" % len(all_storms))

    sample = build_sample(all_storms)
    print("Storm browser: %d storms, %d total records"
          % (len(sample), sum(len(s["records"]) for s in sample)))

    scatter = build_scatter(all_storms)
    print("Scatter: %d records" % len(scatter))

    zone_summary = build_holland_zone_summary(all_storms)
    print("Holland zone summary: %s" % {k: v["n"] for k, v in zone_summary.items()})

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "besttrack_sample.json"), "w") as f:
        json.dump(sample, f, indent=1)
    with open(os.path.join(DATA_DIR, "besttrack_scatter.json"), "w") as f:
        json.dump(scatter, f)
    with open(os.path.join(DATA_DIR, "holland_zone_summary.json"), "w") as f:
        json.dump(zone_summary, f, indent=1)

    with open(GS_OUT, "w") as f:
        f.write("/**\n")
        f.write(" * Best-track QC datasets. Generated by\n")
        f.write(" * tests/tcwind_jtwc/prep_besttrack_data.py - do not hand-edit.\n")
        f.write(" * See tests/tcwind_jtwc/data/*.json for the same data, and\n")
        f.write(" * tests/tcwind_jtwc/README.md for what this is for.\n")
        f.write(" *\n")
        f.write(" * BEST_TRACK_SAMPLE: %d storms for the storm browser, full\n"
                % len(sample))
        f.write(" *   per-record radii/RMW/ROCI where reported.\n")
        f.write(" * BEST_TRACK_SCATTER: %d records for the verification\n"
                % len(scatter))
        f.write(" *   scatter, as [vmax, lat, rmw, r64min, r50min, r34min].\n")
        f.write(" * HOLLAND_ZONE_SUMMARY: mean/p90 |tool-Holland| divergence\n")
        f.write(" *   by radial zone, from verify_besttrack_holland.py.\n")
        f.write(" */\n")
        f.write("var BEST_TRACK_SAMPLE = ")
        json.dump(sample, f, separators=(",", ":"))
        f.write(";\n\n")
        f.write("var BEST_TRACK_SCATTER = ")
        json.dump(scatter, f, separators=(",", ":"))
        f.write(";\n\n")
        f.write("var HOLLAND_ZONE_SUMMARY = ")
        json.dump(zone_summary, f, separators=(",", ":"))
        f.write(";\n")

    gs_size = os.path.getsize(GS_OUT)
    print("Wrote %s (%.1f MB)" % (GS_OUT, gs_size / 1e6))


if __name__ == "__main__":
    main()
