"""NDFD oceanic wind (the desk's issued grids) from the AWS mirror noaa-ndfd-pds.

Files are WMO-headed GRIB2 snapshots of the whole sector, rewritten every 3 h whether or
not the desk has sent new grids: wmo/wspd/YYYY/MM/DD/<PRODUCT>_KWBN_YYYYMMDDHHMM.
YCYZ98 = oceanic days 1-3 (one message per 3 h step, forecastTime 2, 5, ... h after the
snapshot hour), YCYZ97 = days 4-7. Grid: Mercator 2517 x 1793, 10 km, m/s; land and
water outside the desk's area are missing. Rows are stored boustrophedonic (every second
row reversed), which eccodes does not undo; wind_on_grid flips them.

    keys = ndfd.snapshots(dt.date(2026, 10, 16))              # [(snapshot time, key), ...]
    key = ndfd.covering([t0, t48])                            # newest YCYZ98 holding both
    key = ndfd.issued_after(dt.datetime(2026, 10, 16, 12, 30))   # first snapshot posted from then, within 3 h
    grids = ndfd.wind_on_grid(key, [t0, t12], lats, lons)     # {valid: kt grid, NaN = no data}
"""
from __future__ import annotations

import datetime as dt
import re

import numpy as np

from .http import get

BUCKET = "https://noaa-ndfd-pds.s3.amazonaws.com"
KT = 1.943844


def snapshots(day, product="YCYZ98", element="wspd"):
    """[(snapshot datetime, key)] posted on one day, oldest first."""
    prefix = "wmo/%s/%s/%s" % (element, day.strftime("%Y/%m/%d"), product)
    r = get("%s/?list-type=2&prefix=%s" % (BUCKET, prefix))
    if r is None:
        return []
    keys = re.findall(r"<Key>([^<]+)</Key>", r.text)
    out = []
    for k in keys:
        m = re.search(r"_KWBN_(\d{12})$", k)
        if m:
            out.append((dt.datetime.strptime(m.group(1), "%Y%m%d%H%M"), k))
    return sorted(out)


def covering(valid, product="YCYZ98", first_step=2, last_step=71, now=None):
    """Key of the newest snapshot whose steps span every time in `valid` (naive UTC), or
    None. A snapshot at hour H holds valid times H+first_step .. H+last_step."""
    lo, hi = min(valid), max(valid)
    end = (now or dt.datetime.utcnow()).date()
    for d in (end, end - dt.timedelta(days=1), end - dt.timedelta(days=2)):
        for t, k in reversed(snapshots(d, product)):
            h = t.replace(minute=0)
            if h + dt.timedelta(hours=first_step) <= lo and hi <= h + dt.timedelta(hours=last_step):
                return k
    return None


def issued_after(t, product="YCYZ98", within_h=3):
    """Key of the first snapshot posted at or after t (naive UTC) and before t + within_h hours, or
    None (looks at t's date and the next one)."""
    end = t + dt.timedelta(hours=within_h)
    for d in (t.date(), t.date() + dt.timedelta(days=1)):
        for s, k in snapshots(d, product):
            if t <= s < end:
                return k
    return None


def _valid(h, eccodes):
    d, t = str(eccodes.codes_get(h, "dataDate")), eccodes.codes_get(h, "dataTime")
    base = dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(hours=t // 100, minutes=t % 100)
    return base + dt.timedelta(hours=eccodes.codes_get(h, "forecastTime"))


def wind_on_grid(key, valid, lats, lons):
    """{valid time: wind kt on the regular grid (lats, lons: cell centres, any order and
    longitude convention)}: the mean of the NDFD cells whose centres fall in each cell,
    NaN where none has data. Times the file lacks are left out."""
    import eccodes
    r = get("%s/%s" % (BUCKET, key))
    if r is None:
        return {}
    blob, want, out, cells = r.content, set(valid), {}, None
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    dy, dx = lats[1] - lats[0], lons[1] - lons[0]
    pos = 0
    while pos < len(blob):
        start = blob.find(b"GRIB", pos)
        if start < 0:
            break
        size = int.from_bytes(blob[start + 8:start + 16], "big")   # GRIB2 total length
        h = eccodes.codes_new_from_message(blob[start:start + size])
        pos = start + size
        try:
            t = _valid(h, eccodes)
            if t not in want:
                continue
            v = eccodes.codes_get_values(h)
            miss = eccodes.codes_get(h, "missingValue")
            if eccodes.codes_get(h, "alternativeRowScanning"):
                # rows alternate direction (boustrophedonic) and eccodes hands them back as
                # stored: flip every second row so values line up with latitudes/longitudes
                ni = eccodes.codes_get(h, "Ni")
                v = v.reshape(-1, ni).copy()
                v[1::2] = v[1::2, ::-1]
                v = v.ravel()
            if cells is None:   # cell -> grid box mapping, once per file
                la = eccodes.codes_get_array(h, "latitudes")
                lo = eccodes.codes_get_array(h, "longitudes")
                iy = np.floor((la - lats[0]) / dy + 0.5).astype(int)
                ix = np.floor(((lo - lons[0]) % 360) / dx + 0.5).astype(int)
                inside = (iy >= 0) & (iy < lats.size) & (ix >= 0) & (ix < lons.size)
                cells = (inside, iy[inside] * lons.size + ix[inside])
        finally:
            eccodes.codes_release(h)
        inside, flat = cells
        vals = v[inside]
        ok = (vals != miss) & np.isfinite(vals) & (vals < 1000)
        n = np.bincount(flat[ok], minlength=lats.size * lons.size)
        s = np.bincount(flat[ok], weights=vals[ok], minlength=lats.size * lons.size)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[t] = (s / n * KT).reshape(lats.size, lons.size).astype(np.float32)
    return out
