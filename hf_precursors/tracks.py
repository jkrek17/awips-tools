"""One detector, one measurement, every low in the basin.

WHY THE DESIGN CHANGED. The matched case-control pass built its two arms by
different processes: a case started from a hand-analysed archive position and
was walked backwards through a tracker, a control was detected in ERA5 and
described where it stood. Everything that made those two procedures differ --
above all a tracker that only one arm went through -- landed entirely on the
cases, and no amount of matching can repair a difference in how the two arms
were MEASURED.

So nothing here starts from the archive. Every low in the North Pacific is
detected by the same detector, at every synoptic time, and described by the
same code. Tracks are linked afterwards, and the archive enters only at the
end, as a LABEL: did this track produce hurricane-force winds. That is what
the archive is good at -- it is ground truth about wind, not about position.

THE OTHER CHANGE: A MEASURED OUTCOME. The archive records hurricane force
where an analyst saw it, so a compact wind core in a scatterometer gap is a
missing label rather than a missing event, and a study predicting that label
is partly predicting the observing system. ERA5's own 10 m wind and gust
fields are measured the same way for every low in the record. They
under-represent peak winds -- they are a smoothed analysis -- but they are
uniformly smoothed, so as a relative measure across storms they are far
cleaner than the label, and they turn a binary outcome into a continuous one
with much more power behind it.

Both are kept. Agreement between them is itself a result: it says how much
of the archive's label is wind and how much is coverage.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import era5  # noqa: E402
from controls import LAT_RANGE, LON_RANGE, find_lows  # noqa: E402
from pressure_field import Field, great_circle_km  # noqa: E402

MS_TO_KT = 1.943844
WIND_RADIUS_KM = 500.0      # where a low's own wind maximum is looked for
SYNOPTIC_HOURS = (0, 6, 12, 18)
SEASON_START = (10, 1)      # 1 October
SEASON_END = (4, 30)        # 30 April -- 94% of Pacific onsets fall inside

FIELDS = ["when", "lat", "lon", "p_centre", "p_env", "depth", "fit_depth",
          "scale_km", "fit_rms", "grad_hpa_per_100km", "vg_kt", "vgeo_kt",
          "wind_kt", "gust_kt", "wind_lat", "wind_lon", "wind_dist_km"]


def season_times(season):
    """Every synoptic time from 1 Oct of `season` to 30 Apr following."""
    t = datetime(season, *SEASON_START, tzinfo=timezone.utc)
    end = datetime(season + 1, *SEASON_END, 18, tzinfo=timezone.utc)
    out = []
    while t <= end:
        if t.hour in SYNOPTIC_HOURS:
            out.append(t)
        t += timedelta(hours=6)
    return out


def surface_wind(when):
    """(speed_kt, gust_kt) grids, and the shared axes."""
    ds = era5.dataset()
    stamp = era5._stamp(when)
    u = ds["10m_u_component_of_wind"].sel(time=stamp, method="nearest").values
    v = ds["10m_v_component_of_wind"].sel(time=stamp, method="nearest").values
    g = ds["instantaneous_10m_wind_gust"].sel(time=stamp, method="nearest").values
    return np.hypot(u, v) * MS_TO_KT, g * MS_TO_KT


def peak_near(grid, lats, lons, clat, clon, radius_km=WIND_RADIUS_KM):
    """(value, lat, lon, distance) of the grid's maximum within `radius_km`.

    Returned with its position because where the maximum sits relative to the
    centre is itself a diagnostic -- a wind maximum 400 km from the low is a
    different structure from one at 150 km.
    """
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(np.cos(np.radians(clat)), 0.15))
    rows = np.where((lats >= clat - dlat) & (lats <= clat + dlat))[0]
    step = float(abs(lons[1] - lons[0]))
    c0 = int(round(((clon % 360.0) - lons[0] % 360.0) / step))
    half = int(np.ceil(dlon / step))
    cols = (np.arange(c0 - half, c0 + half + 1)) % grid.shape[1]
    sub = grid[np.ix_(rows, cols)]
    la = lats[rows][:, None] * np.ones((1, len(cols)))
    lo = lons[cols][None, :] * np.ones((len(rows), 1))
    dist = great_circle_km(clat, clon, la, lo)
    inside = dist <= radius_km
    if not inside.any():
        return np.nan, np.nan, np.nan, np.nan
    masked = np.where(inside, sub, -np.inf)
    k = np.unravel_index(np.argmax(masked), masked.shape)
    return float(sub[k]), float(la[k]), float(lo[k]), float(dist[k])


def scan_season(season, out_path):
    times = season_times(season)
    lats, lons = era5.axes()
    rows, t0 = [], time.time()
    for n, when in enumerate(times, 1):
        try:
            mslp = era5.mslp(when)
            wind, gust = surface_wind(when)
        except Exception as exc:                        # noqa: BLE001
            print(f"  {when} read failed: {exc}", flush=True)
            continue
        for d in find_lows(mslp):
            w, wla, wlo, wd = peak_near(wind, lats, lons, d["lat"], d["lon"])
            g, _, _, _ = peak_near(gust, lats, lons, d["lat"], d["lon"])
            rows.append({
                "when": when.strftime("%Y-%m-%d %H"),
                "lat": round(d["lat"], 2), "lon": round(d["lon"], 2),
                "p_centre": round(d["p_centre"], 1), "p_env": round(d["p_env"], 1),
                "depth": round(d["depth"], 1), "fit_depth": round(d["fit_depth"], 1),
                "scale_km": round(d["scale_km"], 0), "fit_rms": round(d["fit_rms"], 2),
                "grad_hpa_per_100km": round(d["grad_hpa_per_100km"], 3),
                "vg_kt": round(d["vg_kt"], 1), "vgeo_kt": round(d["vgeo_kt"], 1),
                "wind_kt": round(w, 1), "gust_kt": round(g, 1),
                "wind_lat": round(wla, 2), "wind_lon": round(wlo, 2),
                "wind_dist_km": round(wd, 0),
            })
        if n % 100 == 0:
            rate = (time.time() - t0) / n
            print(f"  {season}: {n}/{len(times)}  {len(rows)} lows  "
                  f"eta {rate * (len(times) - n):.0f}s", flush=True)
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{season}: wrote {len(rows)} low-instances over {len(times)} times",
          flush=True)


if __name__ == "__main__":
    season = int(sys.argv[1])
    out = HERE / "data" / f"scan_{season}.csv"
    scan_season(season, out)
