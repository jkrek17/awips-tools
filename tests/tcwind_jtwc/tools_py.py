#!/usr/bin/env python3
"""CLI wrapper around TCWind_JTWC.py's parser and vortex math, for the
regression/cross-check scripts in this directory. Prints JSON to stdout so
it can be driven from another Python process or diffed against the JS side.

    tools_py.py parse <bulletin.txt>
    tools_py.py vortex <snapshot.json> <points.json>
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                 "GFE", "procedures"))
import numpy as np
import TCWind_JTWC as tc


def tau_to_dict(t):
    return {
        "tau": t.tau, "epoch": t.epoch, "lat": t.lat, "lon": t.lon,
        "vmax": t.vmax, "gust": t.gust,
        "radii": {str(k): v for k, v in sorted(t.radii.items())},
        "motionDir": t.motionDir, "motionSpd": t.motionSpd, "conf": t.conf,
    }


def cmd_parse(path):
    with open(path) as f:
        text = f.read()
    taus, header = tc.parseJTWC(text)
    out = {"header": header, "taus": [tau_to_dict(t) for t in taus]}
    print(json.dumps(out, sort_keys=True))


def cmd_vortex(snapshot_path, points_path):
    with open(snapshot_path) as f:
        snap_in = json.load(f)
    with open(points_path) as f:
        points = json.load(f)  # list of [lat, lon]

    snap = tc.Snapshot()
    snap.lat = snap_in["lat"]
    snap.lon = snap_in["lon"]
    snap.vmax = snap_in["vmax"]
    snap.radii = {int(k): v for k, v in snap_in["radii"].items()}
    snap.motionDir = snap_in.get("motionDir", 0.0)
    snap.motionSpd = snap_in.get("motionSpd", 0.0)

    rmax = tc.resolveRmax(snap, snap_in.get("rmaxOverride", 0.0))
    latGrid = np.array([p[0] for p in points], dtype=np.float64)
    lonGrid = np.array([p[1] for p in points], dtype=np.float64)
    # normalizePeak=False: peak-core normalization is applied by structurally
    # different code on each side (buildVortex() bakes it in per-call, using
    # whichever points happen to be passed to THAT call, as its own sample
    # of "the strongest cell"; Index.html's drawField() applies the same idea
    # separately, over its own NX*NY raster). Both are correct for their own
    # grid, but a normalized comparison here would just be comparing two
    # different grid resolutions' correction factors against each other, not
    # actually checking whether the two ports agree. Compare the raw,
    # pre-normalization field instead - that's the part that must match.
    mag, direc, r, r34 = tc.buildVortex(latGrid, lonGrid, snap, rmax,
                                         normalizePeak=False)

    out = {
        "rmax": rmax,
        "points": [
            {"lat": points[i][0], "lon": points[i][1],
             "mag": float(mag[i]), "dir": float(direc[i]),
             "r": float(r[i]), "r34": float(r34[i])}
            for i in range(len(points))
        ],
    }
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("parse")
    p1.add_argument("file")
    p2 = sub.add_parser("vortex")
    p2.add_argument("snapshot")
    p2.add_argument("points")
    args = ap.parse_args()

    if args.cmd == "parse":
        cmd_parse(args.file)
    elif args.cmd == "vortex":
        cmd_vortex(args.snapshot, args.points)
