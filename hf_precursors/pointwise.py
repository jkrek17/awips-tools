"""Does the gain survive the translation to a pointwise D2D field?

THE PROBLEM. The screen that found HVTL and HVTU worth +0.047 AUC used a
depth from a Gaussian fit to the azimuthal-mean pressure profile around a
DETECTED CENTRE. A D2D derived parameter has no centre: it computes one
number per grid point from windowed operations on the fields. So the depth
that a panel could actually show is not the depth the model was fitted on,
and a gain measured with one is not evidence for the other.

THE POINTWISE ANALOGUE. `cps_HartCPS` already builds the quantity: the
maximum of a field over a 500 km window minus its value at the point. On
MSLP that is "how much higher the pressure gets within 500 km of here",
which is a depth wherever a low sits and is defined everywhere. It is what
the package's own machinery would compute, so it is the honest stand-in.

If the gain holds with pointwise depth in place of the fitted depth, a panel
is worth building. If it does not, the finding belongs in a case-study note
and not on a screen.
"""
from __future__ import annotations

import csv
import glob
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import era5  # noqa: E402
from pressure_field import great_circle_km, offset_point  # noqa: E402

WINDOW_KM = 500.0      # Hart's own analysis radius, as the package uses it
RING_BEARINGS = np.arange(0.0, 360.0, 15.0)
RING_RADII = np.arange(100.0, WINDOW_KM + 1, 100.0)


def window_depth(mslp, clat, clon):
    """Max MSLP within WINDOW_KM of the point, minus the value at it.

    Sampled on a polar ring rather than a grid box because the package's
    window is a distance, and a box at high latitude reaches much further
    east-west than north-south.
    """
    p_here = float(mslp.sample(clat, clon))
    hi = p_here
    for b in RING_BEARINGS:
        for r in RING_RADII:
            la, lo = offset_point(clat, clon, b, r)
            v = float(mslp.sample(la, lo))
            if v > hi:
                hi = v
    return hi - p_here


def main():
    rows = []
    for p in sorted(glob.glob(str(HERE / "data" / "precursors_*.csv"))):
        with open(p) as fh:
            rows += list(csv.DictReader(fh))
    by_time = defaultdict(list)
    for r in rows:
        by_time[datetime.strptime(r["when"], "%Y-%m-%d %H").replace(
            tzinfo=timezone.utc)].append(r)
    times = sorted(by_time)
    print(f"{len(rows)} lows over {len(times)} times", flush=True)

    t0 = time.time()
    for n, when in enumerate(times, 1):
        try:
            mslp = era5.mslp(when)
        except Exception as exc:                        # noqa: BLE001
            print(f"  {when}: {exc}", flush=True)
            continue
        for r in by_time[when]:
            r["depth_pw"] = round(
                window_depth(mslp, float(r["lat"]), float(r["lon"])), 2)
        if n % 200 == 0:
            rate = (time.time() - t0) / n
            print(f"  {n}/{len(times)}  eta {rate * (len(times) - n):.0f}s",
                  flush=True)

    dst = HERE / "data" / "precursors_pointwise.csv"
    keep = [r for r in rows if "depth_pw" in r]
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(keep[0].keys()))
        w.writeheader()
        w.writerows(keep)
    print(f"wrote {dst.name}: {len(keep)} rows", flush=True)


if __name__ == "__main__":
    main()
