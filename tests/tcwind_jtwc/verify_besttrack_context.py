#!/usr/bin/env python3
"""SUPERSEDED for the Findings pipeline - kept as a standalone, CSV-driven
check, not deleted, but tests/tcwind_jtwc/data/gtcm_findings.json's byNature
/byLand blocks come from verify_stratified.py now, not from this script.
Three differences, all fixed in the successor: verify_stratified.py covers
all three archive basins (this script is WP-only), scores BOTH vortex
constructions (this script only ever called resolveRmax() - the LEGACY
"perquad" Rmax source, not read at all under the shipped VORTEX_METHOD=
"gtcm" default; see verify_holdout.py's header for the _buildVortexGTCM
dead-parameter detail), and is wired into gtcm_findings.json/Findings.html
(this script's output never reached either). This script still runs and its
resolveRmax()-vs-RMW-by-nature/land numbers are still real - useful for
auditing that one legacy code path specifically - just read them as
describing "perquad"'s Rmax source, not the shipped default.

--- original header follows -------------------------------------------------

Does the tool's accuracy hold up in the situations that matter most
operationally - near land, and during extratropical transition - or does
it quietly get worse exactly when a real forecaster would need it most?

Every other script in this suite (verify_besttrack_rmax.py,
verify_besttrack_roci.py, verify_besttrack_holland.py) reports one
aggregate number across the whole WestPac archive. That can hide a real
problem: a bias that looks fine on average could be masking "great over
open water, bad near the coast" or "great for a purely tropical system,
bad once it starts transitioning" - and those are exactly the situations
where a bad wind grid does the most damage (watches/warnings are
concentrated near land) or where this tool's own architecture is most
likely to struggle (the CONSON case earlier in this project's history -
a fast-moving, transitioning storm - is what originally surfaced the
motion-asymmetry double-counting bug).

Both slices below come straight from IBTrACS' own fields - no new data,
no external literature, nothing this tool's model has any part in
producing, so there is no risk of a circular check:

  - NATURE: IBTrACS' own storm-type flag per record ("TS" tropical,
    "ET" extratropical transition, "SS" subtropical, "MX" mixture, "DS"
    disturbance, "NR" not reported).
  - DIST2LAND: IBTrACS' own distance to the nearest coastline, km.

Usage:
    python3 verify_besttrack_context.py [path/to/ibtracs.csv]
"""
import os
import sys

from besttrack_common import CACHE, iter_storms, build_storm_records, stats, fmt
import TCWind_JTWC as tc


LAND_BUCKETS = [
    ("over/at coast (<=25km)", lambda d: d <= 25),
    ("near land (25-100km)", lambda d: 25 < d <= 100),
    ("coastal waters (100-300km)", lambda d: 100 < d <= 300),
    ("open ocean (>300km)", lambda d: d > 300),
]

NATURE_LABEL = {
    "TS": "TS (purely tropical)",
    "ET": "ET (extratropical transition)",
    "SS": "SS (subtropical)",
    "MX": "MX (mixture)",
    "DS": "DS (disturbance)",
    "NR": "NR (not reported)",
}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else CACHE

    rmax_by_nature = {}
    rmax_by_land = {}
    n_seen = 0
    n_used = 0

    for sid, name, season, rows in iter_storms(path):
        for rec in build_storm_records(rows):
            n_seen += 1
            # Same scope as the live tool since the depression skip: no
            # organized wind field/radii to speak of below TS strength,
            # so no point checking Rmax accuracy there either.
            if rec["vmax"] < 34:
                continue
            if not rec["rmw"] or rec["rmw"] <= 0:
                continue
            n_used += 1

            snap = tc.Snapshot()
            snap.lat, snap.lon, snap.vmax = rec["lat"], rec["lon"], rec["vmax"]
            snap.radii = rec["radii"]
            pred = tc.resolveRmax(snap, 0.0)
            pair = (pred, rec["rmw"])

            nat = NATURE_LABEL.get(rec["nature"], rec["nature"] or "(blank)")
            rmax_by_nature.setdefault(nat, []).append(pair)

            d = rec["dist2land"]
            if d is not None and d >= 0:
                for label, test in LAND_BUCKETS:
                    if test(d):
                        rmax_by_land.setdefault(label, []).append(pair)
                        break

    print("%d records seen, %d usable (TS-strength+, RMW present)\n"
          % (n_seen, n_used))

    print("Tool's Rmax vs actual RMW, by IBTrACS storm-nature flag:")
    for nat in sorted(rmax_by_nature, key=lambda k: -len(rmax_by_nature[k])):
        fmt(nat, stats(rmax_by_nature[nat]))

    print("\nTool's Rmax vs actual RMW, by distance to nearest land:")
    for label, _test in LAND_BUCKETS:
        fmt(label, stats(rmax_by_land.get(label, [])))


if __name__ == "__main__":
    main()
