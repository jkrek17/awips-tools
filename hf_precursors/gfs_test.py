"""Does the phase space still add once the model's own forecast is in hand?

THE COMPARISON THAT MATTERS. A forecaster is not choosing between these
predictors and nothing. They are looking at the model's 24 h forecast of
10 m wind. So the baseline here is not persistence of an analysis -- it is

    pointwise depth + wind now + GFS's own f024 forecast wind

and the question is whether HVTL and HVTU add anything on top of that. If
they do not, the panels restate what the model already says and should not
be built.

HOW THE FORECAST IS SAMPLED. Each low sits at a time t and is labelled by
whether hurricane force followed within 24 h. The forecast a forecaster
would have is the run initialised at t, at f024, valid at t+24. Its wind is
taken as the maximum within 500 km of where the low ACTUALLY WAS at t+24,
read off the ERA5 track. That hands GFS a perfect track, which is generous
to the competitor on purpose: if the phase space still adds when the model
is given the storm's future position for free, the gain is not a tracking
artefact.
"""
from __future__ import annotations

import csv
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gfs  # noqa: E402
from pressure_field import great_circle_km  # noqa: E402

CONFIRM = (2021, 2023, 2025)
RADIUS_KM = 500.0
LEAD_H = 24


def season_of(d):
    return d.year if d.month >= 7 else d.year - 1


def load():
    with open(HERE / "data" / "precursors_pointwise.csv") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        d = datetime.strptime(r["when"], "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        if season_of(d) not in CONFIRM:
            continue
        r["dt"] = d
        out.append(r)

    with open(HERE / "data" / "instances_d5.csv") as fh:
        pos = defaultdict(dict)
        for i in csv.DictReader(fh):
            t = datetime.strptime(i["when"], "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
            pos[i["track"]][t] = (float(i["lat"]), float(i["lon"]))
    return out, pos


def peak_within(grid, lats, lons, clat, clon, radius_km=RADIUS_KM):
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(np.cos(np.radians(clat)), 0.15))
    rows = np.where((lats >= clat - dlat) & (lats <= clat + dlat))[0]
    step = float(abs(lons[1] - lons[0]))
    c0 = int(round(((clon % 360.0) - lons[0] % 360.0) / step))
    half = int(np.ceil(dlon / step))
    cols = np.arange(c0 - half, c0 + half + 1) % grid.shape[1]
    sub = grid[np.ix_(rows, cols)]
    la = lats[rows][:, None] * np.ones((1, len(cols)))
    lo = lons[cols][None, :] * np.ones((len(rows), 1))
    inside = great_circle_km(clat, clon, la, lo) <= radius_km
    return float(np.nanmax(np.where(inside, sub, -np.inf))) if inside.any() else np.nan


def main():
    chunk, nchunks = int(sys.argv[1]), int(sys.argv[2])
    rows, pos = load()

    todo = []
    for r in rows:
        later = pos.get(r["track"], {}).get(r["dt"] + timedelta(hours=LEAD_H))
        if later is None:
            continue
        todo.append((r, later))
    by_init = defaultdict(list)
    for r, later in todo:
        by_init[r["dt"]].append((r, later))
    inits = sorted(by_init)[chunk::nchunks]
    if chunk == 0:
        print(f"{len(rows)} confirmation-season lows, {len(todo)} with a known "
              f"position 24 h later, {len(by_init)} GFS cycles", flush=True)

    out, t0, miss = [], time.time(), 0
    for n, init in enumerate(inits, 1):
        got = gfs.fetch(init, LEAD_H)
        if got is None:
            miss += len(by_init[init])
            continue
        fields, lats, lons = got
        spd, _ = gfs.wind_kt(fields)
        for r, (la, lo) in by_init[init]:
            w = peak_within(spd, lats, lons, la, lo % 360.0)
            out.append(dict(r, gfs_f024_kt=round(w, 1) if np.isfinite(w) else "",
                            dt=r["dt"].strftime("%Y-%m-%d %H")))
        if n % 20 == 0:
            rate = (time.time() - t0) / n
            print(f"  chunk {chunk}: {n}/{len(inits)} cycles, {len(out)} lows, "
                  f"{miss} unavailable, eta {rate * (len(inits) - n):.0f}s",
                  flush=True)

    dst = HERE / "data" / f"gfs_{chunk}.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"chunk {chunk}: {len(out)} lows, {miss} cycles unavailable -> {dst.name}",
          flush=True)


if __name__ == "__main__":
    main()
