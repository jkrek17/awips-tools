#!/usr/bin/env python3
"""Build the two best-track datasets shipped inside the Apps Script web
app for the "Best-track QC" panel:

  - a random sample of 100 storms, each with its full track (position,
    Vmax, reported wind radii, and observed RMW where available), for
    the storm browser - lets you flip through a real storm and see its
    actual reported radii/RMW next to the tool's own modeled output.
  - every usable record in the whole WP best-track archive (~16k),
    compacted to just what the verification scatter needs, for the
    aggregate predicted-vs-actual Rmax chart.

Both are written as ready-to-push Apps Script source
(web/TCWind_JTWC/BestTrackData.gs, `var BEST_TRACK_SAMPLE = [...]` /
`var BEST_TRACK_SCATTER = [...]`) plus the same data as plain JSON
under tests/tcwind_jtwc/data/ for reference/diffing.

Usage:
    python3 prep_besttrack_data.py [path/to/ibtracs_WP.csv]
"""
import calendar
import csv
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                 "GFE", "procedures"))
import TCWind_JTWC as tc
from verify_besttrack_rmax import load_rows, CACHE, to_float, QUADS

SEED = 20260902
N_SAMPLE_STORMS = 100
MIN_RECORDS = 6
# JTWC's WestPac wind-radii reporting only becomes reliably present from
# here on (checked: <50% of jtwc_wp records have USA_RMW before 2001) - a
# pre-2001 storm has essentially no radii/RMW to show, which would make the
# storm browser look like the tool is failing when really there's just
# nothing to compare against.
MIN_SEASON = 2001

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
GS_OUT = os.path.join(HERE, "..", "..", "web", "TCWind_JTWC", "BestTrackData.gs")


def quad_radii(row, thresh):
    vals = {}
    any_present = False
    for q in QUADS:
        v = to_float(row["USA_R%d_%s" % (thresh, q)])
        if v is not None:
            any_present = True
        vals[q] = v or 0.0
    return vals if any_present else None


def build_storm_records(rows):
    """rows: one storm's IBTrACS rows, in file order (already time-sorted).
    Returns a list of record dicts with motion filled in from consecutive
    positions, same convention parseJTWC() uses (last point inherits the
    previous motion)."""
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
            "radii": radii,
        })

    for i, rec in enumerate(recs):
        if i + 1 < len(recs):
            brg, spd = tc._bearing_speed(_pt(rec), _pt(recs[i + 1]))
            rec["motionDir"], rec["motionSpd"] = brg, spd
        elif i > 0:
            rec["motionDir"] = recs[i - 1]["motionDir"]
            rec["motionSpd"] = recs[i - 1]["motionSpd"]
        else:
            rec["motionDir"], rec["motionSpd"] = 0.0, 0.0
    return recs


class _pt(object):
    """Minimal duck-typed stand-in for a Tau, for tc._bearing_speed()."""
    def __init__(self, rec):
        self.lat = rec["lat"]
        self.lon = rec["lon"]
        self.epoch = rec["epoch"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE
    from collections import defaultdict, OrderedDict
    by_sid = defaultdict(list)
    names = {}
    seasons = {}
    for row in load_rows(path):
        if row["USA_AGENCY"].strip() != "jtwc_wp":
            continue
        by_sid[row["SID"]].append(row)
        names[row["SID"]] = row["NAME"]
        seasons[row["SID"]] = row["SEASON"]

    # --- sample-100 storm browser dataset -----------------------------
    eligible = [sid for sid, rows in by_sid.items()
                if int(seasons[sid]) >= MIN_SEASON
                and sum(1 for r in rows if to_float(r["USA_WIND"])
                        and to_float(r["USA_LAT"])) >= MIN_RECORDS]
    rnd = random.Random(SEED)
    sample_sids = rnd.sample(eligible, min(N_SAMPLE_STORMS, len(eligible)))

    sample = []
    for sid in sorted(sample_sids, key=lambda s: (seasons[s], s)):
        recs = build_storm_records(by_sid[sid])
        if len(recs) < MIN_RECORDS:
            continue
        sample.append({
            "sid": sid, "name": names[sid], "season": seasons[sid],
            "records": recs,
        })
    print("Storm browser: %d storms, %d total records"
          % (len(sample), sum(len(s["records"]) for s in sample)))

    # --- full-archive scatter dataset ----------------------------------
    # Compact positional rows: [vmax, lat, rmw, r64min, r50min, r34min].
    # r*min is the smallest nonzero quadrant at that threshold (0 if the
    # threshold wasn't reported) - all resolveRmax()'s clamp needs is
    # Math.min() across quadrants, so shipping just that lets the client
    # reuse the real resolveRmax()/willoughbyRmax() unmodified rather than
    # duplicating the clamp formula here.
    scatter = []
    for rows in by_sid.values():
        for row in rows:
            lat = to_float(row["USA_LAT"]) or to_float(row["LAT"])
            vmax = to_float(row["USA_WIND"])
            rmw = to_float(row["USA_RMW"])
            if lat is None or vmax is None or rmw is None or rmw <= 0:
                continue
            mins = []
            for thresh in (64, 50, 34):
                q = quad_radii(row, thresh)
                nz = [v for v in (q or {}).values() if v > 0]
                mins.append(round(min(nz), 1) if nz else 0)
            scatter.append([round(vmax, 1), round(lat, 2), round(rmw, 1)] + mins)
    print("Scatter: %d records" % len(scatter))

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "besttrack_sample.json"), "w") as f:
        json.dump(sample, f, indent=1)
    with open(os.path.join(DATA_DIR, "besttrack_scatter.json"), "w") as f:
        json.dump(scatter, f)

    with open(GS_OUT, "w") as f:
        f.write("/**\n")
        f.write(" * Best-track QC datasets. Generated by\n")
        f.write(" * tests/tcwind_jtwc/prep_besttrack_data.py - do not hand-edit.\n")
        f.write(" * See tests/tcwind_jtwc/data/*.json for the same data, and\n")
        f.write(" * tests/tcwind_jtwc/README.md for what this is for.\n")
        f.write(" *\n")
        f.write(" * BEST_TRACK_SAMPLE: %d storms for the storm browser, full\n"
                % len(sample))
        f.write(" *   per-record radii/RMW where reported.\n")
        f.write(" * BEST_TRACK_SCATTER: %d records for the verification\n"
                % len(scatter))
        f.write(" *   scatter, as [vmax, lat, rmw, r64min, r50min, r34min].\n")
        f.write(" */\n")
        f.write("var BEST_TRACK_SAMPLE = ")
        json.dump(sample, f, separators=(",", ":"))
        f.write(";\n\n")
        f.write("var BEST_TRACK_SCATTER = ")
        json.dump(scatter, f, separators=(",", ":"))
        f.write(";\n")

    gs_size = os.path.getsize(GS_OUT)
    print("Wrote %s (%.1f MB)" % (GS_OUT, gs_size / 1e6))


if __name__ == "__main__":
    main()
