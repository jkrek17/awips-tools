#!/usr/bin/env python3
"""Compare the two vortex constructions in TCWind_JTWC.py.

    "perquad"  per-quadrant radial fit, tangentially interpolated.  Reproduces
               every reported radius exactly, by construction.  NHC's legacy
               TCMWindTool worked this way.

    "wtcm"     one symmetric modified-Rankine vortex plus a single wavenumber-1
               motion term (Schwerdt 1979), fit by least squares against all
               reported radii together.  This is the construction NHC's Gridded
               TCM uses, so it is what the Atlantic/EastPac grids OPC already
               ingests look like.

Two questions, answered separately:

  1. RING REPRODUCTION - how far does each construction land from the radii the
     bulletin actually reported?  This is the tool's contract, so "perquad" is
     exact by definition and the only interesting number is what "wtcm" costs.

  2. FIELD DIFFERENCE - how different are the two wind fields a forecaster would
     actually see, in kt and in the 34/50/64 kt areas that drive warnings?  A
     large ring error that moves no isotach area matters less than a small one
     that does.

Runs hermetically against the committed best-track sample; no network, no
IBTrACS CSV.

    python3 compare_vortex_methods.py [--cases N] [--json OUT.json]
"""

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "GFE", "procedures"))
import TCWind_JTWC as T  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "data", "besttrack_sample.json")

# Radial resolution for locating a threshold crossing.  0.05 nm is far finer
# than any GFE grid and finer than the 5 nm the radii are reported at, so it
# contributes nothing measurable to the numbers below.
R_MAX_NM = 600.0
R_STEPS = 12000


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


def ring_errors(snap, method):
    """Signed error, in nm, for every reported ring along its quadrant bearing."""
    rmax = T.resolveRmax(snap, 0.0)
    radii = np.linspace(0.05, R_MAX_NM, R_STEPS)
    out = []
    for q, az in T.QUAD_AZ.items():
        lat, lon = _ray(snap.lat, snap.lon, az, radii)
        mag, _dir, _r, _r34 = T.buildVortex(lat, lon, snap, rmax, method=method)
        mag = np.asarray(mag, dtype=float)
        for threshold in (64, 50, 34):
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
    is wtcm area / perquad area for that isotach.
    """
    rmax = T.resolveRmax(snap, 0.0)
    rr = np.linspace(2.0, 400.0, 200)
    az = np.arange(0.0, 360.0, 5.0)
    R, A = np.meshgrid(rr, az)
    lat, lon = _ray(snap.lat, snap.lon, 0.0, [1.0])  # placeholder, replaced below

    # Build lat/lon for every (radius, azimuth) cell.
    lats = np.empty(R.shape)
    lons = np.empty(R.shape)
    for i, a in enumerate(az):
        la, lo = _ray(snap.lat, snap.lon, float(a), rr)
        lats[i, :] = la
        lons[i, :] = lo

    fields = {}
    for method in ("perquad", "wtcm"):
        mag, _d, _r, _r34 = T.buildVortex(lats, lons, snap, rmax, method=method)
        fields[method] = np.asarray(mag, dtype=float)

    diff = np.abs(fields["wtcm"] - fields["perquad"])
    # Area weight for a polar cell is r*dr*dtheta; constant factors cancel in a
    # ratio, so r alone is enough.
    weight = R
    areas = {}
    for threshold in (34, 50, 64):
        a_pq = float(np.sum(weight * (fields["perquad"] >= threshold)))
        a_wt = float(np.sum(weight * (fields["wtcm"] >= threshold)))
        areas[threshold] = (a_wt / a_pq) if a_pq > 0 else float("nan")
    return float(diff.mean()), float(np.percentile(diff, 95)), areas


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=int, default=200,
                    help="storm-times to evaluate (default 200)")
    ap.add_argument("--json", help="also write the summary to this path")
    args = ap.parse_args()

    with open(SAMPLE) as fh:
        storms = json.load(fh)

    per_thr = {"perquad": {34: [], 50: [], 64: []},
               "wtcm": {34: [], 50: [], 64: []}}
    # A reported ring the field never reaches at all is a worse failure than a
    # displaced one, and averaging only the hits would hide it entirely.
    missed = {"perquad": {34: 0, 50: 0, 64: 0},
              "wtcm": {34: 0, 50: 0, 64: 0}}
    diffs, p95s = [], []
    area_ratios = {34: [], 50: [], 64: []}
    n = 0

    for storm in storms:
        for rec in storm["records"]:
            if rec["vmax"] < 34 or not (rec.get("radii") or {}):
                continue
            snap = _snapshot(rec)
            if not snap.radii:
                continue
            for method in ("perquad", "wtcm"):
                for threshold, rep, got in ring_errors(snap, method):
                    if got is None:
                        missed[method][threshold] += 1
                    else:
                        per_thr[method][threshold].append(got - rep)
            m, p, areas = field_difference(snap)
            diffs.append(m)
            p95s.append(p)
            for threshold, ratio in areas.items():
                if np.isfinite(ratio):
                    area_ratios[threshold].append(ratio)
            n += 1
            if n >= args.cases:
                break
        if n >= args.cases:
            break

    def stats(vals):
        v = np.asarray(vals, dtype=float)
        if not len(v):
            return None
        return dict(n=int(len(v)), bias=float(v.mean()),
                    mae=float(np.abs(v).mean()),
                    rmse=float(math.sqrt(float((v ** 2).mean()))),
                    p90=float(np.percentile(np.abs(v), 90)))

    print("Vortex method comparison - %d storm-times from the committed "
          "best-track sample\n" % n)
    print("1. RING REPRODUCTION (the tool's contract)")
    print("   %-9s %-6s %7s %9s %9s %9s %9s"
          % ("method", "ring", "n", "bias", "MAE", "RMSE", "p90|err|"))
    print("   " + "-" * 62)
    summary = {"cases": n, "rings": {}, "field": {}}
    for method in ("perquad", "wtcm"):
        for threshold in (64, 50, 34):
            st = stats(per_thr[method][threshold])
            if not st:
                continue
            summary["rings"].setdefault(method, {})[threshold] = st
            print("   %-9s R%-5d %7d %+9.2f %9.2f %9.2f %9.2f"
                  % (method, threshold, st["n"], st["bias"], st["mae"],
                     st["rmse"], st["p90"]))
        allv = sum(per_thr[method].values(), [])
        st = stats(allv)
        if st:
            summary["rings"].setdefault(method, {})["all"] = st
            print("   %-9s %-6s %7d %+9.2f %9.2f %9.2f %9.2f"
                  % (method, "ALL", st["n"], st["bias"], st["mae"],
                     st["rmse"], st["p90"]))
        gone = sum(missed[method].values())
        total = gone + len(allv)
        summary["rings"].setdefault(method, {})["never_reached"] = gone
        print("   %-9s reported rings the field NEVER reaches: %d of %d (%.1f%%)"
              % (method, gone, total, 100.0 * gone / total if total else 0.0))
        if gone:
            print("   %-9s   by ring: %s" % ("", ", ".join(
                "R%d %d" % (t, missed[method][t]) for t in (64, 50, 34)
                if missed[method][t])))
        print("   " + "-" * 62)

    print("\n2. FIELD DIFFERENCE (what a forecaster would see change)")
    print("   mean |wtcm - perquad| over the field : %6.2f kt" % np.mean(diffs))
    print("   p95 of that difference, per case     : %6.2f kt" % np.mean(p95s))
    for threshold in (34, 50, 64):
        vals = area_ratios[threshold]
        if vals:
            print("   %d kt area, wtcm / perquad          : %6.3f  "
                  "(median %.3f)" % (threshold, float(np.mean(vals)),
                                     float(np.median(vals))))
            summary["field"]["area_ratio_%d" % threshold] = float(np.mean(vals))
    summary["field"]["mean_abs_kt"] = float(np.mean(diffs))
    summary["field"]["p95_abs_kt"] = float(np.mean(p95s))

    print("\nCaveat: the \"wtcm\" branch is reconstructed from the description in")
    print("TCWind_JTWC.py plus published forms, NOT from NHC's Users Guide. The")
    print("radial-exponent treatment in particular (see WTCM_X_* in that file) is")
    print("unverified, and is the most likely reason a real WTCM would score")
    print("better than this. Treat these numbers as an upper bound on the cost of")
    print("switching, not as a measurement of NHC's own tool.")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        print("\nwrote %s" % args.json)


if __name__ == "__main__":
    main()
