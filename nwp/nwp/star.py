"""NOAA STAR scatterometer passes (OSCAT-3 and the coastal ultra-high-resolution ASCAT of Metop-B and
Metop-C), read from the STAR ocean surface wind viewer's JSON files (manati.star.nesdis.noaa.gov).

    passes(day)  -> [(prefix, url, start)] STAR lists under a UTC day (date or datetime), sorted by (prefix, start)
    points(url)  -> dict(lat, lon (-180..180), u, v, spd (knots), q (uint8, 1 = flagged, likely rain))
    start_time(name) -> naive UTC datetime parsed from a pass file name

Files are 5-13 MB, about 50 a day, posted 3-4 h after the pass; the server keeps about a month. A point's
time is only bracketed, [file start, start of the next file of the same prefix]. Winds are the 10 m wind as
served (equivalent-neutral not confirmed). Ported from jkrek17/marine-research rk/truth.py."""
from __future__ import annotations

import datetime as dt
import json
import re

import numpy as np

from .http import get

URL = "https://manati.star.nesdis.noaa.gov"
PREFIXES = ("oscat3_AS", "oscat3_DS", "UHR_METOP-B_AS", "UHR_METOP-B_DS", "UHR_METOP-C_AS", "UHR_METOP-C_DS")
_LIST = URL + "/product_src/info/oswtviewer/map_layers.php?date={ymd}&prefix={prefix}"
_RE_DOY = re.compile(r"(\d{4})-(\d{3})T(\d{2})-(\d{2})-(\d{2})")
_RE_YMD = re.compile(r"_(\d{8})T(\d{6})_")


def start_time(name):
    """Pass start (naive UTC datetime) from a STAR pass file name: '..._2026-301T02-32-14_lite5.json' (year,
    day of year, time; OSCAT-3) or '..._20261028T003525_73213_rev1of1_ec.json' (UHR ASCAT). ValueError if neither."""
    m = _RE_DOY.search(name)
    if m:
        y, doy, h, mi, sec = (int(g) for g in m.groups())
        return dt.datetime(y, 1, 1) + dt.timedelta(days=doy - 1, hours=h, minutes=mi, seconds=sec)
    m = _RE_YMD.search(name)
    if m:
        return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    raise ValueError("no pass start time in %r" % name)


def passes(day, prefixes=PREFIXES):
    """Passes STAR lists for a UTC day -> [(prefix, url, start datetime)] sorted by (prefix, start); a prefix
    with nothing posted (or no listing) adds nothing."""
    out = []
    for prefix in prefixes:
        r = get(_LIST.format(ymd=day.strftime("%Y%m%d"), prefix=prefix))
        if r is None:
            continue
        for u in json.loads(r.content).get("json_urls") or []:
            out.append((prefix, URL + u if u.startswith("/") else u, start_time(u)))
    return sorted(out, key=lambda x: (x[0], x[2]))


def _grid(recs):
    """UHR ASCAT layout, leaflet-velocity grids [{header: {parameterNumber 2 (u) | 3 (v) | other (q), lo1, la1,
    dx, dy, nx, ny}, data: [row-major from la1 southward, None = no wind]}] -> (lat, lon, u, v, q) arrays."""
    by = {}
    for r in recs:
        h = r["header"]
        by[{2: "u", 3: "v"}.get(h.get("parameterNumber"), "q")] = r
    h = by["u"]["header"]
    nx, ny = int(h["nx"]), int(h["ny"])

    def arr(k):
        if k not in by:
            return np.zeros(nx * ny, np.float32)
        return np.array([np.nan if x is None else x for x in by[k]["data"]], np.float32)
    u, v, q = arr("u"), arr("v"), arr("q")
    ok = np.isfinite(u) & np.isfinite(v)
    iy, ix = np.divmod(np.nonzero(ok)[0], nx)
    return ((h["la1"] - iy * h["dy"]).astype(np.float32), (h["lo1"] + ix * h["dx"]).astype(np.float32),
            u[ok], v[ok], np.nan_to_num(q[ok]).astype(np.uint8))


def parse(recs):
    """Pass records (parsed JSON) -> points dict (see module doc). OSCAT-3 files are point records
    [{la, lo, u, v, q}]; UHR ASCAT files are regular grids."""
    if recs and "header" in recs[0]:
        la, lo, u, v, q = _grid(recs)
    elif recs:
        la = np.array([r["la"] for r in recs], np.float32)
        lo = np.array([r["lo"] for r in recs], np.float32)
        u = np.array([r["u"] for r in recs], np.float32)
        v = np.array([r["v"] for r in recs], np.float32)
        q = np.array([r.get("q", 0) or 0 for r in recs]).astype(np.uint8)
    else:
        z = np.zeros(0, np.float32)
        return dict(lat=z, lon=z, u=z, v=z, spd=z, q=np.zeros(0, np.uint8))
    ok = np.isfinite(la) & np.isfinite(lo) & np.isfinite(u) & np.isfinite(v)
    la, lo, u, v, q = la[ok], lo[ok], u[ok], v[ok], q[ok]
    lon = ((lo + 180) % 360 - 180).astype(np.float32)
    return dict(lat=la, lon=lon, u=u, v=v, spd=np.hypot(u, v).astype(np.float32), q=q)


def points(url):
    """Download one pass file -> points dict (knots); None when the file is gone (404)."""
    r = get(url)
    return None if r is None else parse(json.loads(r.content))
