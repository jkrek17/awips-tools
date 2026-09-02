#!/usr/bin/env python3
"""Verify the tool's wind-field SIZE (not just its core Rmax) against real
best-track data, using ROCI - radius of the outermost closed isobar.

Every check up to now (verify_besttrack_rmax.py, and the fit check the
web app itself reports) is either checking Rmax against best-track RMW,
or checking the field AT the reported wind radii - and the field is
*constructed* to pass through those radii exactly, so that's closer to a
self-consistency check than independent verification. ROCI is neither:
it's a pressure-based size measure, never fed into the vortex model at
all (the model only ever sees Vmax and wind radii), so comparing it to
where the tool's own wind field decays away is a genuinely independent
check of whether the field's overall size/decay is realistic.

Caveat, stated plainly: ROCI (radius of outermost closed *isobar*) and
"radius where the modeled *wind* falls below some threshold" are related
but not identically defined quantities - a storm's pressure field and
wind field don't share one boundary. Chavas & Emanuel (2010) found ROCI
correlates reasonably well with the theoretical radius of vanishing wind
(R0), which is the closest wind-based analogue, so this is treated as a
same-order-of-magnitude plausibility/bias check, not a precise physical
equivalence - hence checking three different low-wind thresholds rather
than picking one and treating it as exact.

Method: for each record, build the tool's actual radial wind profile
(buildVortex(), including motion asymmetry from consecutive best-track
positions, same as the live tool) along 8 azimuths out to 600 nm, find
where it crosses each threshold, average across azimuths, and compare
that to the record's ROCI.

Usage:
    python3 verify_besttrack_roci.py [path/to/ibtracs.csv]
"""
import os
import sys

import numpy as np

from besttrack_common import (
    CACHE, iter_storms, build_storm_records, snapshot_from_record,
    stats, fmt, category,
)
import TCWind_JTWC as tc

THRESHOLDS_KT = (10.0, 15.0, 20.0)
N_AZ = 8
N_R = 120
MAX_R_NM = 600.0
EARTH_R_NM = 3440.065


def dest_grid(clat, clon, az_deg, r_nm):
    """Great-circle destination points: one azimuth, an array of radii."""
    d2r = np.pi / 180.0
    d = r_nm / EARTH_R_NM
    b = az_deg * d2r
    l1, o1 = clat * d2r, clon * d2r
    l2 = np.arcsin(np.sin(l1) * np.cos(d) + np.cos(l1) * np.sin(d) * np.cos(b))
    o2 = o1 + np.arctan2(np.sin(b) * np.sin(d) * np.cos(l1),
                          np.cos(d) - np.sin(l1) * np.sin(l2))
    return l2 / d2r, o2 / d2r


def edge_radii(rec, rmax):
    """Tool's own radial wind profile at N_AZ azimuths, out to MAX_R_NM,
    then the (interpolated) radius at each of THRESHOLDS_KT, averaged
    across azimuths. Returns a dict {threshold: mean_radius_nm}."""
    snap = snapshot_from_record(rec)
    r_samples = np.linspace(max(rmax, 1.0), MAX_R_NM, N_R)

    crossings = {t: [] for t in THRESHOLDS_KT}
    for az in np.linspace(0, 360, N_AZ, endpoint=False):
        lat, lon = dest_grid(rec["lat"], rec["lon"], az, r_samples)
        mag, _direc, _r, _r34 = tc.buildVortex(lat, lon, snap, rmax,
                                               normalizePeak=False)
        mag = np.asarray(mag)
        for t in THRESHOLDS_KT:
            below = np.where(mag < t)[0]
            if below.size == 0:
                crossings[t].append(MAX_R_NM)  # never decays that far in range
                continue
            i = below[0]
            if i == 0:
                crossings[t].append(float(r_samples[0]))
                continue
            r0, r1 = r_samples[i - 1], r_samples[i]
            v0, v1 = mag[i - 1], mag[i]
            f = (v0 - t) / (v0 - v1) if v0 != v1 else 0.0
            crossings[t].append(float(r0 + f * (r1 - r0)))

    return {t: sum(vs) / len(vs) for t, vs in crossings.items()}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE
    pairs = {t: [] for t in THRESHOLDS_KT}
    by_cat = {t: {} for t in THRESHOLDS_KT}
    n_seen = 0
    n_used = 0

    for sid, name, season, rows in iter_storms(path):
        for rec in build_storm_records(rows):
            n_seen += 1
            if not rec["roci"] or rec["roci"] <= 0:
                continue
            n_used += 1
            snap = snapshot_from_record(rec)
            rmax = tc.resolveRmax(snap, 0.0)
            edges = edge_radii(rec, rmax)
            cat = category(rec["vmax"])
            for t in THRESHOLDS_KT:
                pairs[t].append((edges[t], rec["roci"]))
                by_cat[t].setdefault(cat, []).append((edges[t], rec["roci"]))

    print("%d records seen, %d with usable ROCI\n" % (n_seen, n_used))
    for t in THRESHOLDS_KT:
        print("Tool's radius where modeled wind falls below %.0f kt, "
              "vs best-track ROCI:" % t)
        fmt("all records", stats(pairs[t]))
        for cat in ("TD (<34kt)", "TS (34-63kt)", "TY+ (64kt+)"):
            fmt("  " + cat, stats(by_cat[t].get(cat, [])))
        print()


if __name__ == "__main__":
    main()
