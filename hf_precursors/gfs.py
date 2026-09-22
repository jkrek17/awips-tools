"""GFS forecast fields, fetched by byte range from the AWS open-data archive.

WHY THIS EXISTS. Everything measured so far is perfect prog: predictors from
an analysis, scored against what happened. That sets an upper bound on skill
and says nothing about whether a forecaster gains anything, because the
forecaster is not choosing between our predictors and nothing -- they are
looking at the model's own forecast of the wind. The only honest test is
whether the phase space adds to THAT.

THE FETCH. A GFS cycle's pgrb2.0p25 file is about 500 MB, and the three
fields wanted are about 2.5 MB of it. Each cycle publishes an `.idx` giving
every record's byte offset, so the ranges for just those records can be
requested directly. Nothing is kept: each forecast is streamed to a scratch
file, read, and deleted, because the container's disk is a fixed allowance
and there are hundreds of them.

The grid is 721x1440 at 0.25 degrees -- the same grid ERA5 uses -- so every
routine in this package applies to a GFS field unchanged.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np

BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
MS_TO_KT = 1.943844

# 10 m wind only. The surface gust record did not come back through the
# same filter, and it is not needed: the competitor being tested is the
# field a forecaster actually has on screen, which is the model's 10 m wind.
WANTED = [("UGRD", "10 m above ground"),
          ("VGRD", "10 m above ground")]


def _url(init, fhour):
    return (f"{BASE}/gfs.{init:%Y%m%d}/{init:%H}/atmos/"
            f"gfs.t{init:%H}z.pgrb2.0p25.f{fhour:03d}")


def _idx(url, timeout=60):
    r = subprocess.run(["curl", "-s", "--max-time", str(timeout), url + ".idx"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return r.stdout.decode("utf-8", "replace").splitlines()


def _ranges(lines, wanted):
    """Byte ranges for the wanted (parameter, level) records."""
    recs = []
    for i, line in enumerate(lines):
        p = line.split(":")
        if len(p) < 5:
            continue
        start = int(p[1])
        end = None
        if i + 1 < len(lines):
            nxt = lines[i + 1].split(":")
            if len(nxt) > 1:
                end = int(nxt[1]) - 1
        recs.append((p[3], p[4], start, end))
    out = []
    for name, level in wanted:
        for pname, plevel, start, end in recs:
            if pname == name and plevel == level:
                out.append((name, start, end))
                break
    return out


def fetch(init, fhour, wanted=None, timeout=180):
    """(name -> 2D array, lats, lons) for one forecast, or None.

    Records are fetched in one multi-range request rather than one per
    field: a single connection for three records instead of three.
    """
    wanted = wanted or WANTED
    url = _url(init, fhour)
    lines = _idx(url)
    if not lines:
        return None
    rngs = _ranges(lines, wanted)
    if len(rngs) != len(wanted):
        return None
    spec = ",".join(f"{s}-{e}" for _, s, e in rngs if e is not None)
    fd, path = tempfile.mkstemp(suffix=".grb")
    os.close(fd)
    try:
        r = subprocess.run(["curl", "-s", "--max-time", str(timeout),
                            "-r", spec, url, "-o", path], capture_output=True)
        if r.returncode != 0 or os.path.getsize(path) == 0:
            return None
        import xarray as xr
        out, lats, lons = {}, None, None
        # A multi-range body concatenates the GRIB messages, which cfgrib
        # reads as one file; the 10 m winds and the gust sit on different
        # level types, so they come back as separate datasets.
        for filt in ({"typeOfLevel": "heightAboveGround", "level": 10},):
            try:
                ds = xr.open_dataset(path, engine="cfgrib", decode_timedelta=True,
                                     backend_kwargs={"filter_by_keys": filt,
                                                     "indexpath": ""})
            except Exception:                          # noqa: BLE001
                continue
            for v in ds.data_vars:
                out[v] = ds[v].values
                lats = ds.latitude.values
                lons = ds.longitude.values
            ds.close()
        if not out or lats is None:
            return None
        return out, lats, lons
    finally:
        for p in (path, path + ".923a8.idx"):
            try:
                os.remove(p)
            except OSError:
                pass


def wind_kt(fields):
    """(10 m speed, gust) in knots from a fetched forecast."""
    u = fields.get("u10")
    v = fields.get("v10")
    g = fields.get("gust")
    spd = np.hypot(u, v) * MS_TO_KT if u is not None and v is not None else None
    return spd, (g * MS_TO_KT if g is not None else None)
