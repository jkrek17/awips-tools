#!/usr/bin/env python3
"""Build the ocean surface current background layer for the globe view.

Why this exists: the archive's fix-density maxima sit over the Gulf Stream
and the Kuroshio - the sharp SST gradient across those western boundary
currents supplies the low-level baroclinicity and surface heat flux that
feeds explosive cyclogenesis. This script gives the globe a current field so
that relationship is visible, not just asserted in prose.

Source: OSCAR (Ocean Surface Current Analysis Real-time) sea surface
velocity, dataset id jplOscar, served by NOAA CoastWatch ERDDAP. NASA/JPL
product; U.S. Government work, public domain.
    https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplOscar

The native grid is 1/3 degree - time[117] depth[1] latitude[481]
longitude[1201], u/v in m/s, latitude 80 to -80, longitude 20 to 420 (the
extra 40 degrees past 360 is a duplicate wraparound pad, not new data - see
strip_lon_pad()). The newest time step on this ERDDAP mirror is 2014-09-26,
so this is a *historical mean*, not current conditions; main() prints the
real span it found and that exact string is what gets written into the
output payload, so the page can never describe it as more current than it
is.

The mean is a **vector mean**: u and v are averaged separately over time,
then speed/direction are derived from the averages, not averaged as scalar
speeds. That matters for what the layer is *for* - a persistent, coherently-
directed flow like the Gulf Stream keeps a strong vector mean, while a patch
of open ocean dominated by transient eddies (large instantaneous speeds,
inconsistent direction) averages down toward zero. Averaging scalar speeds
instead would do the opposite: eddies never cancel, so noisy open ocean would
look just as "fast" as the boundary currents the layer exists to show.

Downsampling happens server-side, via ERDDAP's own hyperslab stride syntax
(the same [start:stride:stop] indexing the recipe this was built from uses) -
there is no client-side interpolation, just asking the server for every Nth
native grid point.

Fetches are chunked by time (a handful of steps per request) and retried
with backoff: a single request for all 117 steps at once is tens of MB and
one flaky connection would lose the whole build, whereas a failed chunk here
just retries on its own.

Writes:
    docs/data/currents.js   window.HF_CURRENTS = {...}   (works from file://)

Usage:
    python3 tools/build_currents.py                  # fetch, build, write
    python3 tools/build_currents.py --check           # build, but write nothing
    python3 tools/build_currents.py --resolution 2.5  # coarser/finer output grid
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplOscar"

# Native OSCAR grid. Latitude has no wraparound issue (it just runs pole to
# pole); longitude is padded 40 degrees past a full circle (see
# strip_lon_pad) so the *unique* span is 360 degrees, not 400.
NATIVE_STEP_DEG = 1.0 / 3.0
NATIVE_LAT_N = 481          # latitude[481]: 80 .. -80
NATIVE_LON_N = 1201         # longitude[1201]: 20 .. 420 (last 121 duplicate the first)
NATIVE_LON0 = 20.0
NATIVE_UNIQUE_LON_SPAN = 360.0

DEFAULT_RESOLUTION_DEG = 2.0   # "something around 2 degrees" per spec
TIME_CHUNK = 12                # time steps per request (~12 MB each, ~1.5 s)

ROUND_DIGITS = 2               # m/s - plenty for a background layer, not a forecast product

FETCH_RETRIES = 5
FETCH_TIMEOUT_S = 90


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def http_get(url: str) -> str:
    """GET with retry/backoff. ERDDAP is generally solid but a chunked build
    makes dozens of requests, and one dropped connection should not sink the
    whole run - retry a few times with growing backoff before giving up."""
    ctx = ssl.create_default_context()
    last_err = None
    for attempt in range(FETCH_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "awips-tools/build_currents"})
            with urllib.request.urlopen(req, context=ctx, timeout=FETCH_TIMEOUT_S) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
            last_err = err
            if attempt == FETCH_RETRIES - 1:
                break
            wait = 2 ** attempt
            print(f"  fetch failed ({err}) - retrying in {wait}s "
                  f"(attempt {attempt + 2}/{FETCH_RETRIES})...", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last_err}")


def fetch_time_axis():
    """The list of ISO timestamps ERDDAP actually holds for this dataset,
    read live rather than assumed - the archive is static but there is no
    reason to hardcode a count this one request confirms for free."""
    text = http_get(f"{BASE_URL}.csv?time")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # lines[0] is "time", lines[1] is the "UTC" units row.
    return lines[2:]


def stride_for_resolution(resolution_deg: float) -> int:
    """Nearest native-grid stride for a requested output resolution. Rounds
    rather than floors/ceils so e.g. 2.0 deg lands exactly on stride 6
    (2.0 / (1/3) == 6.0) instead of drifting off by one."""
    stride = max(1, round(resolution_deg / NATIVE_STEP_DEG))
    return stride


def fetch_uv_chunk(t0: int, t1: int, lat_stride: int, lon_stride: int) -> str:
    """One ERDDAP griddap request for both u and v, a slice of time steps,
    at the given lat/lon stride. u and v share one request (same subset
    spec) since ERDDAP griddap allows comma-separated variables - halves the
    request count versus fetching them separately."""
    spec = f"[{t0}:{t1}][0][0:{lat_stride}:{NATIVE_LAT_N - 1}][0:{lon_stride}:{NATIVE_LON_N - 1}]"
    url = f"{BASE_URL}.csv?u{spec},v{spec}"
    return http_get(url)


# ---------------------------------------------------------------------------
# Parse + accumulate
# ---------------------------------------------------------------------------

def parse_uv_rows(text: str):
    """Yield (u, v) floats (None for NaN) for every data row of a griddap
    CSV, in the server's own iteration order: time outermost, then latitude,
    then longitude fastest. That fixed order - not the lat/lon text in each
    row - is what lets the caller reshape the stream into a grid; parsing it
    out again would just risk float round-trip mismatches for no benefit."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    next(reader)  # units row
    try:
        u_col = header.index("u")
        v_col = header.index("v")
    except ValueError as err:
        raise RuntimeError(f"unexpected CSV header {header!r}") from err

    def one(raw):
        return None if raw == "NaN" else float(raw)

    n = 0
    for row in reader:
        if not row:
            continue
        yield one(row[u_col]), one(row[v_col])
        n += 1
    return n


def build(resolution_deg: float, time_chunk: int = TIME_CHUNK):
    lat_stride = stride_for_resolution(resolution_deg)
    lon_stride = lat_stride  # same physical spacing on both axes

    times = fetch_time_axis()
    n_time = len(times)
    print(f"time axis: {n_time} steps, {times[0]} to {times[-1]}")

    nlat = (NATIVE_LAT_N - 1) // lat_stride + 1
    nlon_raw = (NATIVE_LON_N - 1) // lon_stride + 1   # includes the wraparound pad
    lat0 = 80.0
    lat_step = -lat_stride * NATIVE_STEP_DEG           # negative: index runs 80 -> -80
    lon_step = lon_stride * NATIVE_STEP_DEG

    # Drop the padded columns once we know how many are real: the unique
    # longitude span is exactly 360 degrees, so any column at or past that
    # offset from NATIVE_LON0 repeats an earlier one and would double-draw a
    # meridian's worth of cells.
    nlon = int(round(NATIVE_UNIQUE_LON_SPAN / lon_step))
    if nlon > nlon_raw:
        nlon = nlon_raw

    print(f"output grid: {nlat} x {nlon} cells at {lat_stride * NATIVE_STEP_DEG:.3f} deg "
          f"(requested {resolution_deg} deg)")

    sum_u = [[0.0] * nlon for _ in range(nlat)]
    sum_v = [[0.0] * nlon for _ in range(nlat)]
    count = [[0] * nlon for _ in range(nlat)]

    rows_expected_per_step = nlat * nlon_raw
    chunks_done = 0
    t0 = 0
    while t0 < n_time:
        t1 = min(t0 + time_chunk - 1, n_time - 1)
        n_steps = t1 - t0 + 1
        print(f"  fetching steps {t0}..{t1} of {n_time - 1}...", file=sys.stderr)
        text = fetch_uv_chunk(t0, t1, lat_stride, lon_stride)

        row_iter = parse_uv_rows(text)
        rows_seen = 0
        for step in range(n_steps):
            for ilat in range(nlat):
                for ilon_raw in range(nlon_raw):
                    u, v = next(row_iter)
                    rows_seen += 1
                    if ilon_raw >= nlon:
                        continue  # padded wraparound column - not new information
                    if u is None or v is None:
                        continue  # land, or genuinely missing - never coerced to 0
                    sum_u[ilat][ilon_raw] += u
                    sum_v[ilat][ilon_raw] += v
                    count[ilat][ilon_raw] += 1
        expected = n_steps * rows_expected_per_step
        if rows_seen != expected:
            raise RuntimeError(f"chunk {t0}..{t1}: expected {expected} rows, parsed {rows_seen} "
                                f"- server response did not match the requested shape")
        chunks_done += 1
        t0 = t1 + 1

    print(f"fetched {chunks_done} chunk(s) covering {n_time} time steps")

    # Vector mean per cell, then derive speed/direction from the averaged
    # components (see module docstring for why this is a vector mean and not
    # an average of instantaneous speeds).
    u_grid = [[None] * nlon for _ in range(nlat)]
    v_grid = [[None] * nlon for _ in range(nlat)]
    speeds = []
    n_ocean = 0
    for ilat in range(nlat):
        for ilon in range(nlon):
            n = count[ilat][ilon]
            if n == 0:
                continue
            mu = sum_u[ilat][ilon] / n
            mv = sum_v[ilat][ilon] / n
            u_grid[ilat][ilon] = round(mu, ROUND_DIGITS)
            v_grid[ilat][ilon] = round(mv, ROUND_DIGITS)
            speeds.append(math.hypot(mu, mv))
            n_ocean += 1

    speeds.sort()
    def pct(p):
        if not speeds:
            return 0.0
        idx = min(len(speeds) - 1, int(round(p * (len(speeds) - 1))))
        return round(speeds[idx], 3)

    stats = {
        "meanSpeed": round(sum(speeds) / len(speeds), 3) if speeds else 0.0,
        "p90Speed": pct(0.90),
        "p99Speed": pct(0.99),
        "maxSpeed": round(speeds[-1], 3) if speeds else 0.0,
    }

    payload = {
        "source": "OSCAR sea surface velocity, NASA/JPL, via NOAA CoastWatch ERDDAP (dataset jplOscar)",
        "license": "U.S. Government work; public domain",
        "period": {"start": times[0][:10], "end": times[-1][:10], "nTimeSteps": n_time},
        "note": ("Mean of all " + str(n_time) + " available OSCAR fields over the stated period "
                 "(vector mean of u/v, not an average of instantaneous speeds) - a historical "
                 "mean, not current conditions."),
        "units": "m/s",
        # lat0/lon0 + lat/lon step describe the grid; lon0 is in OSCAR's own
        # 20..380 frame (not normalized to -180..180) - the globe's density
        # layer already draws cells in that same shifted frame (see
        # DENSITY_LON_ORIGIN in globe.js) since the projection's trig is
        # 360-periodic and does not care, so currents.js reuses it rather
        # than introducing a second longitude convention.
        "grid": {
            "nlat": nlat, "nlon": nlon,
            "lat0": lat0, "latStep": round(lat_step, 6),
            "lon0": NATIVE_LON0, "lonStep": round(lon_step, 6),
        },
        "stats": stats,
        "u": u_grid,
        "v": v_grid,
    }

    return payload, n_ocean, nlat * nlon


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build but write nothing")
    ap.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION_DEG,
                    help=f"output grid spacing in degrees (default {DEFAULT_RESOLUTION_DEG})")
    ap.add_argument("--time-chunk", type=int, default=TIME_CHUNK,
                    help=f"time steps per HTTP request (default {TIME_CHUNK})")
    args = ap.parse_args()

    payload, n_ocean, n_total = build(args.resolution, args.time_chunk)
    s = payload["stats"]
    print(f"cells: {n_ocean}/{n_total} have data  "
          f"mean speed {s['meanSpeed']} m/s  p90 {s['p90Speed']}  p99 {s['p99Speed']}  max {s['maxSpeed']} m/s")
    print(f"period: {payload['period']['start']} to {payload['period']['end']} "
          f"({payload['period']['nTimeSteps']} time steps)")

    if args.check:
        return

    data_dir = os.path.join(ROOT, "docs", "data")
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "currents.js")

    compact = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("/* generated by tools/build_currents.py - do not edit */\n")
        fh.write("/* OSCAR sea surface velocity, NASA/JPL via NOAA CoastWatch ERDDAP. "
                  "US Government work, public domain. */\n")
        fh.write("window.HF_CURRENTS = " + compact + ";\n")

    size = os.path.getsize(out_path)
    print(f"wrote docs/data/currents.js ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
