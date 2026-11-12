"""Remote Sensing Systems (RSS) ASCAT daily 0.25 degree maps of Metop-B and Metop-C: full swaths over the open
ocean (NOAA STAR's ASCAT is a coastal product). Files are posted about 2 days after the day ends (lately
about 5), 1-3 MB gzipped each.

    day(sat, date, lat_range=(15, 70)) -> dict of cell arrays, or None when the file is not posted (404)
        lat, lon (-180..180)   cell centres: lat -89.875 + 0.25 i, lon 0.125 + 0.25 j (x.125 degrees)
        spd_kt                 wind speed, knots (RSS's equivalent-neutral 10 m wind, as served)
        dir_deg                meteorological direction, the wind blows FROM (RSS serves the direction toward)
        t_min                  minutes after 00 UTC of the day (RSS serves 6-minute steps)
        rain                   uint8, the scatterometer rain bit (1 = flagged)
        node                   uint8, 0 ascending pass, 1 descending pass
    sat is "b" or "c" (also "metopb", "Metop-C").

Each file is uint8 [2 passes, 5 variables, 720, 1440]: time (x 6 min), wind (x 0.2 m/s), direction (x 1.5 deg,
toward), rain (bit 0 scatterometer flag, bits 2-7 radiometer), sos (x 0.02); 255 = no data. Ported from
jkrek17/marine-research rk/truth.py (_ascat_get, _ascat_cells)."""
from __future__ import annotations

import datetime as dt
import gzip
import re

import numpy as np

from .http import get

URL = "https://data.remss.com/ascat/metop{s}/bmaps_v02.1/y{y}/m{m}/ascat{s}_{d}_v02.1.gz"
KT = 1.943844                  # m/s to knots
LAT = -89.875 + 0.25 * np.arange(720)
LON = 0.125 + 0.25 * np.arange(1440)
_MISSING = 250                 # wind bytes above this and time bytes above 240 are no data


def sat_letter(sat):
    m = re.fullmatch(r"(?:metop)?-?([bc])", str(sat).strip().lower())
    if not m:
        raise ValueError("sat must be b or c, got %r" % (sat,))
    return m.group(1)


def url(sat, date):
    d = date.strftime("%Y%m%d")
    return URL.format(s=sat_letter(sat), y=d[:4], m=d[4:6], d=d)


def decode(blob):
    """The gzipped file bytes -> uint8 [2, 5, 720, 1440]."""
    return np.frombuffer(gzip.decompress(blob), np.uint8).reshape(2, 5, 720, 1440)


def cells(a, lat_range=(15.0, 70.0)):
    """uint8 [2, 5, 720, 1440] -> the valid cells of both passes inside lat_range (see module doc)."""
    rows = np.nonzero((LAT >= lat_range[0]) & (LAT <= lat_range[1]))[0]
    parts = []
    for p in range(2):
        t, w, d, rn, _ = (a[p, i][rows] for i in range(5))
        iy, ix = np.nonzero((w <= _MISSING) & (t <= 240))
        parts.append(dict(
            lat=LAT[rows][iy].astype(np.float32),
            lon=(((LON[ix] + 180) % 360) - 180).astype(np.float32),
            spd_kt=(w[iy, ix] * 0.2 * KT).astype(np.float32),
            dir_deg=((d[iy, ix] * 1.5 + 180.0) % 360).astype(np.float32),
            t_min=(t[iy, ix].astype(np.int16) * 6),
            rain=(rn[iy, ix] & 1).astype(np.uint8),
            node=np.full(iy.size, p, np.uint8)))
    return {k: np.concatenate([q[k] for q in parts]) for k in parts[0]}


def day(sat, date, lat_range=(15.0, 70.0)):
    """One satellite's valid cells for a UTC day (date or datetime) -> dict (module doc); None when not posted."""
    r = get(url(sat, date))
    return None if r is None else cells(decode(r.content), lat_range)
