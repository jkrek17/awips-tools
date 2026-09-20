#!/usr/bin/env python3
"""Cross-check the shape of the tool's radial wind profile against an
independent published model - Holland (1980).

STILL A LIVE CHECK, unlike its sibling verify_besttrack_* scripts.  It is not
scoring the tool against nature: it anchors a second, independently designed
parametric profile at the SAME points the tool has (Vmax/Rmax and one reported
radius) and asks where the two shapes disagree.  Two models disagreeing is
evidence about structural uncertainty, which is a claim the tool can actually
support, and the region where they disagree most - just outside the core - is
the region where being wrong matters most operationally.

Reframed for GTCM.  When this was written, VORTEX_METHOD was "perquad", so
"the tool's curve" below is the per-quadrant construction, and its exactly-
correct-by-construction R50/R64 is what made the Holland comparison
interesting.  The default is now "gtcm", which does not pass through the
reported radii at all, so re-running this against the current default would
answer a different (and still useful) question: how far one fitted symmetric
Rankine vortex sits from one fitted Holland profile.  The numbers recorded in
tests/tcwind_jtwc/README.md are the perquad ones.  This has NOT been re-run
under GTCM here - it needs the WestPac IBTrACS CSV, which is not in this
environment - so treat the recorded zone-divergence numbers as describing the
superseded construction until someone with the CSV re-runs it.

Note also that its Rmax anchor is best-track RMW, which the real-time tool
never has; that makes it a controlled shape comparison, not a check of
anything the tool does operationally.

--- original description follows -------------------------------------------


The tool's own R34/R50/R64 are not a fair thing to re-check against best
track: the model is built to pass through those exact points, so it
always "wins" there by construction (that's what the live tool's "fit
check" already shows, near-zero error). What's actually uncertain is the
SHAPE between and beyond those points - and that's exactly where a
different, independently-designed model can serve as a second opinion.

Two things, using the dimensionless (pressure-free) form of Holland's
profile, V(r) = Vmax * sqrt((Rmax/r)^B * exp(1 - (Rmax/r)^B)):

1. Solve Holland's B from Vmax, Rmax=(best-track RMW), and the storm's
   OWN reported (quadrant-mean) R34 - i.e. anchor Holland the same two
   ways the tool is anchored (core Vmax/Rmax, and one real radius). Then
   ask Holland to PREDICT R50 and R64, which it was never fit to, and
   compare those predictions to the real reported R50/R64. This is a
   genuine out-of-sample check - unlike the tool, Holland's R50/R64
   aren't guaranteed to be anywhere close.
2. With that same B, evaluate Holland's full profile at a grid of radii
   and compare it directly to the tool's own profile (built from the
   real reported radii, as the live tool does) - both anchored the same
   way, so the divergence between them isolates the two models'
   different shape assumptions, broken out by zone (inside Rmax, between
   Rmax-R64, R64-R50, R50-R34, beyond R34).

Usage:
    python3 verify_besttrack_holland.py [path/to/ibtracs.csv]
"""
import math
import os
import sys

import numpy as np

from besttrack_common import (
    CACHE, iter_storms, build_storm_records, snapshot_from_record,
    quad_mean, stats, fmt, category,
)
import TCWind_JTWC as tc

EARTH_R_NM = 3440.065


def holland_g(x):
    return x * math.exp(1.0 - x)


def solve_x_for_g(y, lo=1e-6, hi=1.0, iters=60):
    """g(x) = x*exp(1-x) is monotonic increasing on (0, 1] from 0 to 1,
    which is the branch we're always on (r >= Rmax => x = (Rmax/r)^B <= 1).
    Bisect for g(x) = y."""
    y = min(max(y, holland_g(lo)), holland_g(hi))
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if holland_g(mid) < y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def solve_holland_B(vmax, rmax_nm, r34_nm):
    """B such that Holland's V(r34_nm) = 34 kt, given Vmax/Rmax."""
    y = (34.0 / vmax) ** 2
    x = solve_x_for_g(y)
    ratio = rmax_nm / r34_nm  # < 1
    return math.log(x) / math.log(ratio)


def holland_radius_at(vmax, rmax_nm, B, target_kt):
    """r where Holland's V(r) = target_kt, for r >= rmax_nm."""
    y = (target_kt / vmax) ** 2
    x = solve_x_for_g(y)
    return rmax_nm / (x ** (1.0 / B))


def holland_v_at(vmax, rmax_nm, B, r_nm):
    x = (rmax_nm / r_nm) ** B
    return vmax * math.sqrt(max(holland_g(x), 0.0))


def dest_grid(clat, clon, az_deg, r_nm):
    d2r = np.pi / 180.0
    d = r_nm / EARTH_R_NM
    b = az_deg * d2r
    l1, o1 = clat * d2r, clon * d2r
    l2 = np.arcsin(np.sin(l1) * np.cos(d) + np.cos(l1) * np.sin(d) * np.cos(b))
    o2 = o1 + np.arctan2(np.sin(b) * np.sin(d) * np.cos(l1),
                          np.cos(d) - np.sin(l1) * np.sin(l2))
    return l2 / d2r, o2 / d2r


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE

    r50_pairs, r64_pairs = [], []
    zone_diffs = {}
    n_seen = n_fit = 0

    for sid, name, season, rows in iter_storms(path):
        for row in rows:
            n_seen += 1
        for rec in build_storm_records(rows):
            rmw = rec["rmw"]
            r34 = None
            if 34 in rec["radii"]:
                nz = [v for v in rec["radii"][34].values() if v > 0]
                r34 = sum(nz) / len(nz) if nz else None
            if not rmw or not r34 or rec["vmax"] <= 34 or r34 <= rmw:
                continue

            B = solve_holland_B(rec["vmax"], rmw, r34)
            if not (0.3 <= B <= 3.0):  # degenerate fits, skip
                continue
            n_fit += 1

            if rec["vmax"] > 50:
                nz = [v for v in rec["radii"].get(50, {}).values() if v > 0]
                if nz:
                    r50_actual = sum(nz) / len(nz)
                    r50_pred = holland_radius_at(rec["vmax"], rmw, B, 50.0)
                    r50_pairs.append((r50_pred, r50_actual))
            if rec["vmax"] > 64:
                nz = [v for v in rec["radii"].get(64, {}).values() if v > 0]
                if nz:
                    r64_actual = sum(nz) / len(nz)
                    r64_pred = holland_radius_at(rec["vmax"], rmw, B, 64.0)
                    r64_pairs.append((r64_pred, r64_actual))

            # Tool's own profile vs Holland's, same anchors (rmw as Rmax,
            # matching what the tool would compute from these radii too).
            # Sample the midpoint of each zone actually present for this
            # storm (a storm without a reported R64/R50 just has fewer
            # zones) and compare the two models' wind speed there.
            snap = snapshot_from_record(rec)
            tool_rmax = tc.resolveRmax(snap, 0.0)
            edge_pts = [("Rmax", tool_rmax)]
            if 64 in rec["radii"]:
                v = quad_mean_val(rec, 64)
                if v:
                    edge_pts.append(("R64", v))
            if 50 in rec["radii"]:
                v = quad_mean_val(rec, 50)
                if v:
                    edge_pts.append(("R50", v))
            edge_pts.append(("R34", r34))
            edge_pts.append(("2xR34", r34 * 2.0))
            edge_pts.sort(key=lambda p: p[1])
            for (name_lo, lo), (name_hi, hi) in zip(edge_pts, edge_pts[1:]):
                if hi <= lo:
                    continue
                mid = (lo + hi) / 2.0
                lat, lon = dest_grid(rec["lat"], rec["lon"], 45.0,
                                     np.array([mid]))
                tool_mag, _d, _r, _r34a = tc.buildVortex(
                    lat, lon, snap, tool_rmax, normalizePeak=False)
                holland_mag = holland_v_at(rec["vmax"], rmw, B, mid)
                label = name_lo + "-" + name_hi
                zone_diffs.setdefault(label, []).append(
                    abs(float(tool_mag[0]) - holland_mag))

    print("%d records seen, %d with a valid Holland fit (RMW + R34 both "
          "reported, Vmax > 34 kt)\n" % (n_seen, n_fit))

    print("Holland's predicted R50/R64 (fit only to R34) vs actual "
          "reported R50/R64:")
    fmt("R50", stats(r50_pairs))
    fmt("R64", stats(r64_pairs))

    print("\nTool's profile vs Holland's profile, |difference| in kt, by "
          "zone (both anchored to the same Vmax/Rmax/R34 - a storm without "
          "a reported R64/R50 just contributes fewer, wider zones):")
    zone_order = ["Rmax-R64", "R64-R50", "Rmax-R50", "R50-R34", "Rmax-R34",
                  "R34-2xR34"]
    for label in sorted(zone_diffs, key=lambda l: zone_order.index(l)
                        if l in zone_order else 99):
        vals = zone_diffs[label]
        print("  %-14s n=%-5d mean |diff|=%5.1f kt  max |diff|=%5.1f kt"
              % (label, len(vals), sum(vals) / len(vals), max(vals)))


def quad_mean_val(rec, thresh):
    nz = [v for v in rec["radii"].get(thresh, {}).values() if v > 0]
    return sum(nz) / len(nz) if nz else None


if __name__ == "__main__":
    main()
