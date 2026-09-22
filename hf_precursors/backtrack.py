"""Walk back from hurricane-force onset and see how far the low can be followed.

THE ANCHOR IS THE EVENT. The earlier lead-time study anchored on each track's
own pressure minimum, which the tracker has to find, and then concluded that
at 96 h "the low does not exist". That conclusion was contaminated twice
over: a track only entered the database once it was 15 hPa deep, and the
anchor was a derived quantity rather than the thing being forecast.

The archive gives the anchor directly -- the hour hurricane force was first
analysed -- for every case. So: start at that position and time, walk
backwards through ERA5 at 6 h steps out to 96 h, and record what is there at
each step. No depth floor is applied on the way back. A low that is 4 hPa
deep is still a low, and whether it is findable at T-96 is the question
rather than an entry requirement.

WHAT IS RECORDED. At each step: the pressure minimum the tracker landed on,
its depth against the environment, scale, gradient, and the ERA5 gust nearby,
plus the distance it moved from the previous step. A step much larger than a
storm can travel is the signature of the tracker leaving the storm, and it is
kept rather than smoothed so the point at which the trail goes cold can be
read off instead of guessed.

A low is called IDENTIFIABLE at a step when its depth is at least
MIN_IDENTIFIABLE_HPA and the step that reached it is plausible. The fraction
of cases still identifiable at each lead is the answer to how far back these
storms can be seen at all.
"""
from __future__ import annotations

import csv
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import era5  # noqa: E402
from archive_cases import build_cases  # noqa: E402
from pressure_field import describe_low, great_circle_km  # noqa: E402
from tracks import peak_near, surface_wind  # noqa: E402

STEP_H = 6
MAX_LEAD_H = 96
FIRST_RADIUS_KM = 350.0
GUESS_RADIUS_KM = 300.0
MIN_IDENTIFIABLE_HPA = 3.0
MAX_PLAUSIBLE_STEP_KM = 500.0

COLS = ["id", "season", "onset", "lead_h", "when", "lat", "lon", "p_centre",
        "depth", "scale_km", "grad_hpa_per_100km", "vg_kt", "gust_kt",
        "step_km", "identifiable"]


def _guess(prev, cur):
    if prev is None:
        return cur["lat"], cur["lon"], FIRST_RADIUS_KM
    dlat = cur["lat"] - prev["lat"]
    dlon = ((cur["lon"] - prev["lon"] + 180.0) % 360.0) - 180.0
    return cur["lat"] + dlat, (cur["lon"] + dlon) % 360.0, GUESS_RADIUS_KM


def walk(case):
    """Every 6 h step back from onset, out to MAX_LEAD_H."""
    lats, lons = era5.axes()
    cur = dict(lat=float(case.lat), lon=float(case.lon) % 360.0)
    prev = None
    rows = []
    for k in range(0, MAX_LEAD_H // STEP_H + 1):
        lead = k * STEP_H
        when = case.onset - timedelta(hours=lead)
        glat, glon, radius = _guess(prev, cur)
        try:
            field = era5.mslp(when)
            d = describe_low(field, glat, glon, refine_km=radius)
            _, gust = surface_wind(when)
            g, _, _, _ = peak_near(gust, lats, lons, d["lat"], d["lon"])
        except Exception as exc:                        # noqa: BLE001
            print(f"  {case.id} lead {lead}: {exc}", flush=True)
            break
        step = 0.0 if k == 0 else great_circle_km(
            cur["lat"], cur["lon"], d["lat"], d["lon"])
        ident = int(d["depth"] >= MIN_IDENTIFIABLE_HPA
                    and step <= MAX_PLAUSIBLE_STEP_KM)
        rows.append({
            "id": case.id, "season": case.season,
            "onset": case.onset.strftime("%Y-%m-%d %H"),
            "lead_h": lead, "when": when.strftime("%Y-%m-%d %H"),
            "lat": round(d["lat"], 2), "lon": round(d["lon"], 2),
            "p_centre": round(d["p_centre"], 1),
            "depth": round(d["depth"], 1),
            "scale_km": round(d["scale_km"], 0) if np.isfinite(d["scale_km"]) else "",
            "grad_hpa_per_100km": round(d["grad_hpa_per_100km"], 3)
            if np.isfinite(d["grad_hpa_per_100km"]) else "",
            "vg_kt": round(d["vg_kt"], 1) if np.isfinite(d["vg_kt"]) else "",
            "gust_kt": round(g, 1) if np.isfinite(g) else "",
            "step_km": round(step, 0), "identifiable": ident,
        })
        prev, cur = cur, d
    return rows


def main():
    chunk, nchunks = int(sys.argv[1]), int(sys.argv[2])
    cases = [c for c in build_cases() if c.basin == "pac" and c.season >= 2020]
    mine = cases[chunk::nchunks]
    out = []
    for n, c in enumerate(mine, 1):
        out.extend(walk(c))
        if n % 10 == 0:
            print(f"  chunk {chunk}: {n}/{len(mine)}", flush=True)
    dst = HERE / "data" / f"backtrack_{chunk}.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    print(f"chunk {chunk}: {len(mine)} cases, {len(out)} rows -> {dst.name}",
          flush=True)


if __name__ == "__main__":
    main()
